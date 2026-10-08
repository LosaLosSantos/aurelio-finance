"""One event, one row: two catch-ups at once record nothing twice.

The app posts one catch-up per page load, so two tabs opened together run two
at once, and so does React's StrictMode on the development server. Each
catch-up asked "already recorded?" and then wrote, holding nothing in between,
and in between sits the network: Yahoo's close for a PAC occurrence, and for a
dividend paid in another currency Frankfurter's rate, asked by the write
itself. Measured on 2026-09-30 on the suite's database, both catch-ups held at
the faked fetch, 10 trials each:

- a PAC occurrence that buys was bought twice, 10 of 10, and its cash taken
  twice;
- one too small to buy was recorded unfilled once, because that table has a
  unique constraint, and the second catch-up answered 500, 10 of 10;
- with two occurrences, the second catch-up reading the carry the first had
  left: both bought twice, or one occurrence both bought AND recorded
  unfilled, with the carry at 102 where the plan alone leaves 2;
- a dividend was recorded twice, 10 of 10.

A unique index on the buys was prototyped and does not close it. Refused on one
occurrence, the second catch-up went on with the carry the first had left after
the NEXT one, found it too little for a unit and recorded that next occurrence
unfilled, in a table no index on the buys can see; a month later the plan
bought a unit with money it had never been given. So an occurrence is settled
in one step: SQLite's write lock is taken, the catch-up asks again whether the
occurrence is still unsettled and the carry still the one it worked from, and
only then writes (`database.sole_writer`). A dividend is asked again the same
way. The network is asked before the lock, never under it.

Every race here is forced, not hoped for: the faked fetch, or the check itself,
holds both callers until both are inside the window. The lock is checked from
outside, by a second plain connection to the same file asking for it without
waiting, which is how another process would find it.
"""

from __future__ import annotations

import sqlite3
import threading

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import crud, database, dated, fx, models, prices
from app.database import SessionLocal, unit_of_work
from app.main import app

FEB, MAR, APR = "2026-02-10", "2026-03-10", "2026-04-10"
TODAY = "2026-03-15"
EX = "2026-03-20"


# --- Helpers -----------------------------------------------------------------


def _account(client, name: str = "Broker A") -> int:
    """An account with 5,000 EUR of cash from 2026-01-01."""
    iid = client.post("/api/institutions", json={"name": name, "type": "broker"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": "2026-01-01", "amount": 5000, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    return iid


def _plan(client, iid: int, *, start: str, frequency: str = "monthly", symbol: str = "VWCE.MI") -> int:
    """100 EUR per occurrence from `iid`, bought in whole units at `iid`."""
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "PAC World",
            "amount": 100,
            "currency": "EUR",
            "frequency": frequency,
            "execution": "whole_units",
            "start_date": start,
            "source_institution_id": iid,
            "targets": [{"symbol": symbol, "asset_name": "World", "institution_id": iid}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _distributing(client, iid: int, symbol: str = "VWRL.MI", currency: str = "EUR") -> None:
    """A situation on 2026-01-01 holding 10 units of a distributing fund."""
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-01"}).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": f"{symbol}, distributing",
            "asset_class": "fund_etf",
            "symbol": symbol,
            "quantity": 10,
            "unit_price": 100,
            "distribution_policy": "dist",
            "currency": currency,
        },
    )
    assert r.status_code == 201, r.text


def _today(monkeypatch, day: str) -> None:
    monkeypatch.setattr(dated, "today", lambda: day)


def _close(symbol: str, day: str, price: float) -> dict:
    return {"symbol": symbol, "price": price, "as_of": day}


def _two_tabs(on_finish=None) -> list[int]:
    """Two catch-ups at once through the route, as two tabs post them. The
    statuses are what each tab got: a server error is a 500 here, as in the
    browser, not an exception re-raised in the test."""
    tab = TestClient(app, raise_server_exceptions=False)
    statuses: list[int] = []
    lock = threading.Lock()

    def run() -> None:
        response = tab.post("/api/transactions/catch-up")
        with lock:
            statuses.append(response.status_code)
        if on_finish is not None:
            on_finish()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a catch-up never came back"
    return sorted(statuses)


def _settled(plan_id: int) -> tuple[list[tuple], list[str], float]:
    """What the plan's occurrences left: the buys (occurrence, units, price),
    the occurrences recorded unfilled, and the carry."""
    with SessionLocal() as db:
        buys = [
            (t.plan_occurrence, t.quantity, t.unit_price)
            for t in db.scalars(
                select(models.Transaction)
                .where(models.Transaction.plan_id == plan_id)
                .order_by(models.Transaction.plan_occurrence, models.Transaction.id)
            )
        ]
        unfilled = sorted(
            db.scalars(
                select(models.PlanUnfilledOccurrence.occurrence).where(
                    models.PlanUnfilledOccurrence.plan_id == plan_id
                )
            )
        )
        return buys, unfilled, db.get(models.AccumulationPlan, plan_id).carried_remainder


def _cash(client) -> float:
    return client.get("/api/dashboard/summary").json()["cash_total"]


def _write_lock_is_free() -> bool:
    """Whether another connection to the database file could start writing
    right now, asked without waiting: what a second process would find."""
    other = sqlite3.connect(database.engine.url.database, timeout=0)
    try:
        other.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return False
    else:
        other.rollback()
        return True
    finally:
        other.close()


# --- The PAC -------------------------------------------------------------------


def _yahoo_holds_the_first_two(monkeypatch, closes: dict[str, float]) -> list[str]:
    """Yahoo's close for each day in `closes`; the first two asks wait until
    both are inside, which is after "already settled?" and before the write."""
    everyone_in = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    asked: list[str] = []

    def get_price_on(symbol, on):
        with lock:
            asked.append(on.isoformat())
            held = len(asked) <= 2
        if held:
            everyone_in.wait()
        return _close(symbol, on.isoformat(), closes[on.isoformat()])

    monkeypatch.setattr(prices, "get_price_on", get_price_on)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    return asked


def test_two_catch_ups_buy_an_occurrence_once(client, monkeypatch):
    """100 EUR at 50: two units, once. Before: four units and the cash taken
    twice, both tabs answered 200."""
    iid = _account(client)
    plan_id = _plan(client, iid, start=MAR, frequency="annual")
    asked = _yahoo_holds_the_first_two(monkeypatch, {MAR: 50.0})
    _today(monkeypatch, TODAY)

    assert _two_tabs() == [200, 200]
    assert len(asked) == 2, "the catch-ups did not overlap, so nothing was tested"
    assert _settled(plan_id) == ([(MAR, 2.0, 50.0)], [], 0.0)
    assert _cash(client) == 4900.0


def test_two_catch_ups_record_an_unfilled_occurrence_once_and_both_answer(client, monkeypatch):
    """100 EUR against a unit of 150: nothing bought, the occurrence recorded
    unfilled and its 100 carried. The unique constraint on that table already
    kept it to one row; what it did not do was let the second catch-up end
    cleanly, which answered 500 on the constraint. Now it asks again under
    the lock, finds the row, and writes nothing."""
    iid = _account(client)
    plan_id = _plan(client, iid, start=MAR, frequency="annual")
    asked = _yahoo_holds_the_first_two(monkeypatch, {MAR: 150.0})
    _today(monkeypatch, TODAY)

    assert _two_tabs() == [200, 200]
    assert len(asked) == 2, "the catch-ups did not overlap, so nothing was tested"
    assert _settled(plan_id) == ([], [MAR], 100.0)


def test_one_catch_up_buying_while_the_other_finds_too_little(client, monkeypatch):
    """The shape that made the brief's index insufficient. 100 EUR a month:
    the February close is 90 (one unit, 10 carried), the March close 108 (the
    110 available buys one, 2 carried). Both catch-ups price February at once;
    at March, whichever arrives second waits until the first has finished, then
    reads the carry it left, 2, finds 102 too little for 108 and would record
    March unfilled, which no index on the buys can see. It asks again under
    the lock, finds March bought, and writes nothing.

    A month later one plain catch-up must leave exactly what the plan run alone
    leaves: April unfilled, 102 carried. After the prototyped index it bought a
    unit at 108 with 94 left over: money the plan had never been given."""
    iid = _account(client)
    plan_id = _plan(client, iid, start=FEB)
    closes = {FEB: 90.0, MAR: 108.0, APR: 108.0}
    february_in = threading.Barrier(2, timeout=10)
    first_done = threading.Event()
    lock = threading.Lock()
    arrivals: dict[str, int] = {}

    def get_price_on(symbol, on):
        day = on.isoformat()
        with lock:
            arrivals[day] = arrivals.get(day, 0) + 1
            second = arrivals[day] == 2
        if day == FEB:
            february_in.wait()
        elif second:
            assert first_done.wait(timeout=10)
        return _close(symbol, day, closes[day])

    monkeypatch.setattr(prices, "get_price_on", get_price_on)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    _today(monkeypatch, TODAY)

    assert _two_tabs(on_finish=first_done.set) == [200, 200]
    assert arrivals == {FEB: 2, MAR: 2}, "the catch-ups did not overlap, so nothing was tested"
    assert _settled(plan_id) == ([(FEB, 1.0, 90.0), (MAR, 1.0, 108.0)], [], 2.0)
    assert _cash(client) == 5000.0 - 90.0 - 108.0

    _today(monkeypatch, "2026-04-15")
    assert client.post("/api/transactions/catch-up").status_code == 200
    assert _settled(plan_id) == ([(FEB, 1.0, 90.0), (MAR, 1.0, 108.0)], [APR], 102.0)


def test_a_catch_up_never_settles_from_a_carry_that_moved(client, monkeypatch):
    """Asking again whether the occurrence is settled is not enough on its own:
    what an occurrence buys depends on the carry, and the other catch-up can
    move the carry by settling an EARLIER occurrence. Here Yahoo does not
    answer one of the two identical February asks. The catch-up that got its
    close buys February and carries 10; the other skips February and goes on
    to March with the carry it loaded at its start, 0, so it reads 100 against
    108 and would record March unfilled, carrying 100. It gets the lock first,
    finds March still unsettled but the carry no longer the 0 it worked from,
    and writes nothing; the first then buys March with its 110.

    Before, March came out unfilled AND bought, carrying 92."""
    iid = _account(client)
    plan_id = _plan(client, iid, start=FEB)
    february_in = threading.Barrier(2, timeout=10)
    february_bought = threading.Event()
    other_done = threading.Event()
    lock = threading.Lock()
    roles: dict[int, str] = {}

    def get_price_on(symbol, on):
        day, me = on.isoformat(), threading.get_ident()
        if day == FEB:
            february_in.wait()
            with lock:
                roles[me] = "missed" if "buys" in roles.values() else "buys"
            if roles[me] == "missed":
                raise prices.PriceError("no answer this time")
            return _close(symbol, day, 90.0)
        if roles[me] == "buys":
            february_bought.set()  # it reaches March only once February is committed
            assert other_done.wait(timeout=10)
        else:
            assert february_bought.wait(timeout=10)
        return _close(symbol, day, 108.0)

    monkeypatch.setattr(prices, "get_price_on", get_price_on)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    _today(monkeypatch, TODAY)

    # The one that missed February finishes first: the other waits for it.
    assert _two_tabs(on_finish=other_done.set) == [200, 200]
    assert sorted(roles.values()) == ["buys", "missed"], "the catch-ups did not overlap"
    assert _settled(plan_id) == ([(FEB, 1.0, 90.0), (MAR, 1.0, 108.0)], [], 2.0)


# --- The dividend ----------------------------------------------------------------


def test_two_catch_ups_record_a_dividend_once(client, monkeypatch):
    """Brief X's measurement, made a test: both catch-ups held between "already
    recorded?" and the write. Before: two rows of 5.00, both tabs 200."""
    iid = _account(client)
    _distributing(client, iid)
    monkeypatch.setattr(
        prices,
        "_fetch_dividends",
        lambda symbol, period="max": prices.DividendWindow(answered=True, dividends=[{"date": EX, "dps": 0.5}]),
    )
    _today(monkeypatch, "2026-04-01")
    everyone_in = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    checks: list[str] = []
    real = crud.get_dividend_dates_recorded

    def held(db, institution_id, symbol):
        recorded = real(db, institution_id, symbol)
        with lock:
            checks.append(symbol)
            first_two = len(checks) <= 2
        if first_two:
            everyone_in.wait()
        return recorded

    monkeypatch.setattr(crud, "get_dividend_dates_recorded", held)

    assert _two_tabs() == [200, 200]
    assert len(checks) >= 2, "the catch-ups did not overlap, so nothing was tested"
    with SessionLocal() as db:
        rows = [
            (t.date, t.quantity, t.unit_price, t.amount, t.estimated)
            for t in db.scalars(select(models.Transaction).where(models.Transaction.kind == "dividend"))
        ]
    assert rows == [(EX, 10.0, 0.5, 5.0, True)]


# --- The lock: held for every re-check, for no fetch ----------------------------


def test_the_write_lock_is_held_to_ask_again_and_never_while_the_network_is_asked(client, monkeypatch):
    """Two halves of one rule, read from outside by a second connection.

    Every question that decides a write is asked again with the lock held, or
    it can be answered for two catch-ups at once. And nothing that reaches the
    network runs with it held: while it is, every other write in the app waits,
    and Yahoo or Frankfurter can take seconds. Both cross a currency here, so
    Frankfurter is asked twice: once for the PAC's close day, and once while
    the dividend's own credit is worked out, the call that used to sit inside
    the dividend's window (measured 2026-09-30)."""
    iid = _account(client, "IBKR")
    _plan(client, iid, start=MAR, frequency="annual", symbol="VTI")  # listed in USD
    _distributing(client, iid, symbol="VT", currency="USD")
    feb_20 = "2026-02-20"  # before the PAC's day, so its rate is not stored yet
    seen: list[tuple[str, bool]] = []

    def at(name, answer):
        def call(*args, **kwargs):
            seen.append((name, _write_lock_is_free()))
            return answer(*args, **kwargs)

        return call

    monkeypatch.setattr(prices, "get_price_on", at("yahoo close", lambda s, on: _close(s, on.isoformat(), 50.0)))
    monkeypatch.setattr(prices, "_fetch_currency", at("yahoo currency", lambda s: "USD"))
    monkeypatch.setattr(
        prices,
        "_fetch_dividends",
        at(
            "yahoo dividends",
            lambda s, period="max": prices.DividendWindow(answered=True, dividends=[{"date": feb_20, "dps": 0.5}]),
        ),
    )
    monkeypatch.setattr(fx, "_fetch_rates", at("frankfurter", lambda base, start, end=None: {start: {"USD": 1.08}}))
    monkeypatch.setattr(crud, "get_plan_occurrences_settled", at("settled?", crud.get_plan_occurrences_settled))
    monkeypatch.setattr(crud, "get_dividend_dates_recorded", at("recorded?", crud.get_dividend_dates_recorded))
    _today(monkeypatch, "2026-04-01")

    out = client.post("/api/transactions/catch-up")
    assert out.status_code == 200, out.text
    assert sorted(t["kind"] for t in out.json()["created"]) == ["buy", "dividend"]

    fetches = [(name, free) for name, free in seen if not name.endswith("?")]
    assert [name for name, _ in fetches].count("frankfurter") == 2
    assert all(free for _, free in fetches), fetches
    # First asked with nothing held, to see whether there is anything to do;
    # then asked again with the lock held, immediately before the write.
    assert [(n, f) for n, f in seen if n == "settled?"] == [("settled?", True), ("settled?", False)]
    assert [(n, f) for n, f in seen if n == "recorded?"] == [("recorded?", True), ("recorded?", False)]
    assert _write_lock_is_free()


# --- The helper itself ----------------------------------------------------------


def test_a_sole_writer_lets_go_even_when_it_writes_nothing():
    """The catch-up that finds its occurrence already settled writes nothing,
    and the lock must still be released when it leaves: a lock kept would stop
    every other write until the session is closed."""
    with SessionLocal() as db:
        with database.sole_writer(db):
            assert not _write_lock_is_free()
        assert _write_lock_is_free()


def test_a_sole_writer_refuses_to_open_inside_a_unit_of_work():
    """Opened inside another unit, it would hold the lock for whatever that unit
    does next, which may be a network call."""
    with SessionLocal() as db:
        with unit_of_work(db):
            try:
                with database.sole_writer(db):
                    raise AssertionError("it opened inside a unit of work")
            except RuntimeError as exc:
                assert "unit of work" in str(exc)
        assert _write_lock_is_free()
