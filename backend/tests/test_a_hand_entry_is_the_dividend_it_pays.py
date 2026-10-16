"""A dividend the reader entered by hand is recognised as the one the catch-up
was about to record, and anything less than certain is asked.

Brief AZ (2026-10-16). The reader types a dividend from the statement, dated
the day the broker credited it, days or weeks after its ex-date. Typed before
the catch-up reached that ex-date (a rate not published yet, Yahoo not
answering that day, the app not opened), it was stored beside the row the
catch-up recorded next, and everything counted both: measured at `eaa89fc` on
an invented household, 3.70 typed on the payment date, then 5.00 recorded on
the ex-date, the cash at 5,008.70 where 5,003.70 is right, the dividends
collected 8.70, a withholding of 1.30 estimated on a credit already net.

Now an entry dated in a dividend's window (`dividend_pairs.windows`) is that
dividend when the pairing is unique both ways; it takes the ex-date and the
dividend is not recorded, and the banner says so. Two entries for one
dividend, one entry two dividends could be, and an entry beside the app's own
estimate of the same dividend (the double the defects left on record, the
reviewer's note 1) are asked, and nothing is written until the reader
answers. Every answer is a row or a remembered "not this one".

Yahoo is faked where the app meets it, `prices._fetch_dividends`; the reader's
day with `dated.today`. Every name and figure is invented.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import dated, models, pac, prices
from app.database import SessionLocal
from app.main import app

TICKER = "XDIV.MI"
EX = "2026-09-22"
PAID = "2026-09-29"


class Yahoo:
    """The dividends Yahoo lists for the invented share: (ex-date, per share)."""

    def __init__(self) -> None:
        self.listed = [(EX, 0.25)]

    def fetch(self, symbol: str, period: str = "max"):
        events = [{"date": day, "dps": dps} for day, dps in self.listed] if symbol == TICKER else []
        return prices.DividendWindow(answered=True, dividends=events)


@pytest.fixture()
def yahoo(monkeypatch) -> Yahoo:
    fake = Yahoo()
    monkeypatch.setattr(prices, "_fetch_dividends", lambda symbol, period="max": fake.fetch(symbol, period))
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    return fake


@pytest.fixture()
def on(monkeypatch):
    def today_is(day: str) -> None:
        monkeypatch.setattr(dated, "today", lambda: day)

    today_is("2026-10-05")
    return today_is


def _household(client, situation: str = "2026-09-01") -> int:
    r = client.put("/api/settings/tax",
                   json={"country": None, "capital_gains_rate": 26, "dividend_withholding_rate": 26})
    assert r.status_code == 200, r.text
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": situation}).json()["id"]
    r = client.post(f"/api/snapshots/{sid}/holdings",
                    json={"asset_name": "Example Dividend Share", "asset_class": "equity", "symbol": TICKER,
                          "quantity": 20, "unit_price": 50, "currency": "EUR", "distribution_policy": "dist"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/institutions/{iid}/cash-anchors",
                    json={"date": situation, "amount": 5000.0, "currency": "EUR"})
    assert r.status_code == 201, r.text
    return iid


def _typed(client, iid: int, day: str, per_share: float = 0.185) -> int:
    """A dividend entered on the ledger form: the units, the net per share,
    the amount left to be worked out."""
    r = client.post("/api/transactions", json={
        "kind": "dividend", "date": day, "institution_id": iid, "asset_name": "Example Dividend Share",
        "symbol": TICKER, "asset_class": "equity", "quantity": 20, "unit_price": per_share, "fees": 0,
        "amount": None, "currency": "EUR", "price_currency": "EUR",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _catch_up(client) -> dict:
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    return r.json()


def _created(result: dict) -> list[tuple]:
    return [(t["date"], t["amount"]) for t in result["created"]]


def _dividends(client) -> list[tuple]:
    return sorted(
        (t["date"], t["amount"], t.get("ex_date"), t["estimated"])
        for t in client.get("/api/transactions").json()
        if t["kind"] == "dividend"
    )


def _figures(client, iid: int) -> dict:
    (cash,) = [c for c in client.get("/api/cash/positions").json() if c["institution_id"] == iid]
    portfolio = client.get("/api/dashboard/portfolio").json()
    return {
        "cash": round(cash["projected"], 2),
        "dividends": round(portfolio["total_dividends"], 2),
        "estimated": round(portfolio["total_dividends_estimated"], 2),
        "withholding": round(portfolio["tax_estimate"]["dividend_withholding"] or 0.0, 4),
    }


def _answer(client, iid: int, **body) -> dict:
    r = client.post("/api/transactions/dividend-answer", json={"institution_id": iid, "symbol": TICKER, **body})
    assert r.status_code == 200, r.text
    return r.json()


# --- The window and the pairing, on their own --------------------------------------------------


def test_a_window_reaches_the_next_ex_date_or_70_days_whichever_is_later():
    from app.dividend_pairs import windows

    # Quarterly: the period to the next ex-date; the latest, its usual spacing.
    assert windows(["2026-03-20", "2026-06-19", "2026-09-18"]) == {
        "2026-03-20": ("2026-03-20", "2026-06-19"),
        "2026-06-19": ("2026-06-19", "2026-09-18"),
        "2026-09-18": ("2026-09-18", "2026-12-18"),
    }
    # Monthly: 70 days each, overlapping.
    assert windows(["2026-07-02", "2026-08-04"]) == {
        "2026-07-02": ("2026-07-02", "2026-09-10"),
        "2026-08-04": ("2026-08-04", "2026-10-13"),
    }
    # One dividend listed: a year.
    assert windows(["2026-05-06"]) == {"2026-05-06": ("2026-05-06", "2027-05-06")}


def test_a_pairing_is_made_only_when_unique_both_ways():
    from app.dividend_pairs import Dividend, pair

    spans = {"2026-07-02": ("2026-07-02", "2026-09-10"), "2026-08-04": ("2026-08-04", "2026-10-13")}
    july, august = Dividend("2026-07-02"), Dividend("2026-08-04")
    one = pair([july], [(1, "2026-07-20")], spans)
    assert (one.recognised, one.held) == ([(1, "2026-07-02")], {"2026-07-02"})
    both = pair([july, august], [(1, "2026-08-16")], spans)
    assert (both.recognised, both.by_entry, both.by_dividend) == ([], [(1, ["2026-07-02", "2026-08-04"])], [])
    assert both.held == {"2026-07-02", "2026-08-04"}
    two = pair([july], [(1, "2026-07-20"), (2, "2026-07-25")], spans)
    assert (two.recognised, two.by_dividend) == ([], [("2026-07-02", [1, 2])])
    said_apart = pair([july, august], [(1, "2026-08-16")], spans, apart=[(1, "2026-07-02")])
    assert said_apart.recognised == [(1, "2026-08-04")]
    estimate = pair([Dividend("2026-07-02", estimate_id=9)], [(1, "2026-07-20")], spans)
    assert (estimate.recognised, estimate.doubles) == ([], [(1, "2026-07-02")])
    outside = pair([july], [(1, "2026-07-01"), (2, "2026-09-10")], spans)
    assert (outside.recognised, outside.held) == ([], set())


# --- The first defect ------------------------------------------------------------------------


def test_a_dividend_typed_at_its_payment_date_before_the_catch_up_is_counted_once(client, yahoo, on):
    """As measured: 3.70 typed on the payment date, then the catch-up."""
    iid = _household(client)
    tx_id = _typed(client, iid, PAID)
    result = _catch_up(client)

    assert _created(result) == []
    right = {"cash": 5003.7, "dividends": 3.7, "estimated": 0.0, "withholding": 0.0}
    assert _figures(client, iid) == right
    assert result.get("recognised") == [{
        "institution_id": iid, "institution_name": "Broker A", "symbol": TICKER, "ex_date": EX,
        "entry": {"id": tx_id, "date": PAID, "amount": 3.7, "currency": "EUR", "estimated": False},
    }]
    assert result["questions"] == []
    assert _dividends(client) == [(PAID, 3.7, EX, False)]

    assert _created(_catch_up(client)) == []
    on("2026-10-06")
    again = _catch_up(client)
    assert (_created(again), again["recognised"], again["questions"]) == ([], [], [])
    assert _figures(client, iid) == right


def test_an_entry_dated_on_the_ex_date_is_recognised_and_said(client, yahoo, on):
    """It settled the ex-date silently before; now it is the dividend's, and
    the banner says so. And it is the pairing that gives it the ex-date, not
    the adoption, which is for the catch-up's own rows: adopted, it would be
    in no banner."""
    iid = _household(client)
    tx_id = _typed(client, iid, EX)
    result = _catch_up(client)
    assert _created(result) == []
    assert [r["entry"]["id"] for r in result["recognised"]] == [tx_id]
    assert _dividends(client) == [(EX, 3.7, EX, False)]


# --- Inside and outside the window -----------------------------------------------------------


def test_an_entry_dated_before_the_ex_date_is_another_dividend(client, yahoo, on):
    """No dividend is paid before its ex-date: an entry dated 21 September is
    not the dividend of the 22nd, which is recorded beside it, as before."""
    iid = _household(client)
    _typed(client, iid, "2026-09-21")
    result = _catch_up(client)
    assert _created(result) == [(EX, 5.0)]
    assert (result["recognised"], result["questions"]) == ([], [])
    assert _dividends(client) == [("2026-09-21", 3.7, None, False), (EX, 5.0, EX, True)]


def test_an_entry_after_the_window_is_another_dividend(client, yahoo, on):
    """Two quarterly dividends: the window of 22 June ends on 22 September,
    the next ex-date, being more than 70 days on. An entry of 29 September
    is the September dividend's, and June's is recorded."""
    yahoo.listed = [("2026-06-22", 0.25), (EX, 0.25)]
    iid = _household(client, situation="2026-06-01")
    tx_id = _typed(client, iid, PAID)
    result = _catch_up(client)
    assert _created(result) == [("2026-06-22", 5.0)]
    assert [(r["ex_date"], r["entry"]["id"]) for r in result["recognised"]] == [(EX, tx_id)]
    assert _dividends(client) == [("2026-06-22", 5.0, "2026-06-22", True), (PAID, 3.7, EX, False)]


def test_a_payment_after_the_next_ex_date_is_still_in_its_window(client, yahoo, on):
    """A monthly ADR's shape, measured on 2026-10-16: paid 57 to 68 days after
    its ex-date, its ex-dates about 30 days apart. Each window reaches 70
    days, so an entry of 16 August, 45 days after the first ex-date and 12
    after the second, falls in both: which one it is, is asked."""
    yahoo.listed = [("2026-07-02", 0.003), ("2026-08-04", 0.003)]
    iid = _household(client, situation="2026-06-01")
    tx_id = _typed(client, iid, "2026-08-16", per_share=0.002)
    result = _catch_up(client)
    assert _created(result) == []
    (asked,) = result["questions"]
    assert asked["kind"] == "which_dividend"
    assert [d["ex_date"] for d in asked["dividends"]] == ["2026-07-02", "2026-08-04"]
    assert [e["id"] for e in asked["entries"]] == [tx_id]


# --- Asked, never guessed --------------------------------------------------------------------


def test_two_entries_for_one_dividend_are_asked_about_and_nothing_is_recorded(client, yahoo, on):
    iid = _household(client)
    first = _typed(client, iid, PAID)
    second = _typed(client, iid, "2026-10-02", per_share=0.06)
    result = _catch_up(client)
    assert (_created(result), result["recognised"]) == ([], [])
    (asked,) = result["questions"]
    assert asked == {
        "kind": "which_entry", "institution_id": iid, "institution_name": "Broker A", "symbol": TICKER,
        "asset_name": "Example Dividend Share",
        "dividends": [{"ex_date": EX, "dps": 0.25, "currency": "EUR", "units": 20.0, "estimate": None}],
        "entries": [
            {"id": first, "date": PAID, "amount": 3.7, "currency": "EUR", "estimated": False},
            {"id": second, "date": "2026-10-02", "amount": 1.2, "currency": "EUR", "estimated": False},
        ],
    }
    # Asked again at the next start, nothing written meanwhile.
    on("2026-10-06")
    again = _catch_up(client)
    assert (_created(again), len(again["questions"])) == ([], 1)

    answered = _answer(client, iid, answer="link", transaction_id=first, ex_date=EX)
    assert (_created(answered), answered["questions"]) == ([], [])
    assert _dividends(client) == [(PAID, 3.7, EX, False), ("2026-10-02", 1.2, None, False)]
    assert _figures(client, iid)["cash"] == 5004.9


def test_neither_entry_records_the_dividend_and_is_never_asked_again(client, yahoo, on):
    iid = _household(client)
    first = _typed(client, iid, PAID)
    second = _typed(client, iid, "2026-10-02", per_share=0.06)
    _catch_up(client)
    answered = _answer(client, iid, answer="apart",
                       pairs=[{"transaction_id": first, "ex_date": EX}, {"transaction_id": second, "ex_date": EX}])
    assert _created(answered) == [(EX, 5.0)]
    assert answered["questions"] == []
    on("2026-10-06")
    assert _catch_up(client)["questions"] == []
    assert _dividends(client) == [
        (EX, 5.0, EX, True), (PAID, 3.7, None, False), ("2026-10-02", 1.2, None, False),
    ]


def test_an_entry_two_dividends_could_be_takes_the_one_the_reader_names(client, yahoo, on):
    yahoo.listed = [("2026-07-02", 0.003), ("2026-08-04", 0.003)]
    iid = _household(client, situation="2026-06-01")
    tx_id = _typed(client, iid, "2026-08-16", per_share=0.002)
    _catch_up(client)
    answered = _answer(client, iid, answer="link", transaction_id=tx_id, ex_date="2026-07-02")
    # The July dividend is the entry; August's has no entry left, so it is
    # recorded at its estimate.
    assert _created(answered) == [("2026-08-04", 0.06)]
    assert answered["questions"] == []
    assert _dividends(client) == [("2026-08-04", 0.06, "2026-08-04", True), ("2026-08-16", 0.04, "2026-07-02", False)]


def test_an_entry_that_is_neither_dividend_leaves_both_recorded(client, yahoo, on):
    yahoo.listed = [("2026-07-02", 0.003), ("2026-08-04", 0.003)]
    iid = _household(client, situation="2026-06-01")
    tx_id = _typed(client, iid, "2026-08-16", per_share=0.002)
    _catch_up(client)
    answered = _answer(client, iid, answer="apart", pairs=[
        {"transaction_id": tx_id, "ex_date": "2026-07-02"}, {"transaction_id": tx_id, "ex_date": "2026-08-04"},
    ])
    assert _created(answered) == [("2026-07-02", 0.06), ("2026-08-04", 0.06)]
    assert answered["questions"] == []


# --- The doubles already on record (the reviewer's note 1) ------------------------------------


def _estimate_then_typed(client, iid: int) -> int:
    """The catch-up records the estimate first, then the reader types the
    credit as a new row, passing by the form's offer to correct it: the
    first defect's other order, two rows for one dividend."""
    assert _created(_catch_up(client)) == [(EX, 5.0)]
    return _typed(client, iid, PAID)


def test_an_entry_beside_the_app_s_estimate_is_asked_about(client, yahoo, on):
    iid = _household(client)
    tx_id = _estimate_then_typed(client, iid)
    assert _figures(client, iid)["cash"] == 5008.7
    result = _catch_up(client)
    (asked,) = result["questions"]
    estimate = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend" and t["estimated"]][0]
    assert asked["kind"] == "same_dividend"
    assert asked["dividends"] == [{
        "ex_date": EX, "dps": 0.25, "currency": "EUR", "units": 20.0,
        "estimate": {"id": estimate["id"], "date": EX, "amount": 5.0, "currency": "EUR", "estimated": True},
    }]
    assert [e["id"] for e in asked["entries"]] == [tx_id]
    # Asked, never resolved alone.
    assert _dividends(client) == [(EX, 5.0, EX, True), (PAID, 3.7, None, False)]


def test_keeping_the_reader_s_entry_removes_the_estimate_and_remembers_it(client, yahoo, on):
    iid = _household(client)
    tx_id = _estimate_then_typed(client, iid)
    _catch_up(client)
    answered = _answer(client, iid, answer="link", transaction_id=tx_id, ex_date=EX)
    assert (_created(answered), answered["questions"]) == ([], [])
    assert _dividends(client) == [(PAID, 3.7, EX, False)]
    assert _figures(client, iid) == {"cash": 5003.7, "dividends": 3.7, "estimated": 0.0, "withholding": 0.0}
    on("2026-10-06")
    assert _created(_catch_up(client)) == []


def test_keeping_both_is_remembered_and_not_asked_again(client, yahoo, on):
    iid = _household(client)
    tx_id = _estimate_then_typed(client, iid)
    _catch_up(client)
    answered = _answer(client, iid, answer="apart", pairs=[{"transaction_id": tx_id, "ex_date": EX}])
    assert (_created(answered), answered["questions"]) == ([], [])
    on("2026-10-06")
    assert _catch_up(client)["questions"] == []
    assert _dividends(client) == [(EX, 5.0, EX, True), (PAID, 3.7, None, False)]


def test_the_second_defect_s_leftover_is_asked_about_too(client, yahoo, on):
    """Before this brief: the app's row corrected and moved to the payment
    date, then recorded again on its ex-date by the next start. The moved row
    keeps no ex-date (the migration gave it none), the new estimate does."""
    iid = _household(client)
    _catch_up(client)
    (tx,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    with SessionLocal() as db:
        row = db.get(models.Transaction, tx["id"])
        row.date, row.ex_date, row.estimated, row.unit_price, row.amount = PAID, None, False, 0.185, 3.7
        db.add(models.Transaction(
            kind="dividend", date=EX, ex_date=EX, institution_id=iid, asset_name="Example Dividend Share",
            symbol=TICKER, quantity=20, unit_price=0.25, fees=0, amount=5.0, currency="EUR",
            price_currency="EUR", estimated=True, note="Auto-recorded from market data: a dividend of 0.25 EUR per share",
        ))
        db.commit()
    (asked,) = _catch_up(client)["questions"]
    assert (asked["kind"], [e["id"] for e in asked["entries"]]) == ("same_dividend", [tx["id"]])
    _answer(client, iid, answer="link", transaction_id=tx["id"], ex_date=EX)
    assert _dividends(client) == [(PAID, 3.7, EX, False)]


def test_the_app_s_corrected_row_beside_an_entry_is_asked_about_not_adopted(client, yahoo, on):
    """The catch-up gives its own row its ex-date in silence only when no
    other row in the dividend's window keeps none. Beside an entry of the
    reader's the two may be one dividend counted twice: both are named and the
    reader says which is the dividend."""
    iid = _household(client)
    assert _created(_catch_up(client)) == [(EX, 5.0)]
    (row,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    with SessionLocal() as db:
        auto = db.get(models.Transaction, row["id"])
        auto.ex_date, auto.estimated, auto.unit_price, auto.amount = None, False, 0.185, 3.7
        db.commit()
    typed = _typed(client, iid, PAID)
    on("2026-10-06")
    result = _catch_up(client)
    (asked,) = result["questions"]
    assert (asked["kind"], [e["id"] for e in asked["entries"]]) == ("which_entry", [row["id"], typed])
    assert (_created(result), result["recognised"]) == ([], [])
    _answer(client, iid, answer="link", transaction_id=row["id"], ex_date=EX)
    assert _dividends(client) == [(EX, 3.7, EX, False), (PAID, 3.7, None, False)]


# --- Two catch-ups at once, and answers that no longer stand ---------------------------------


def test_two_catch_ups_at_once_recognise_an_entry_once(client, yahoo, monkeypatch, on):
    iid = _household(client)
    tx_id = _typed(client, iid, PAID)
    everyone_in = threading.Barrier(2, timeout=10)

    def held(symbol: str, period: str = "max"):
        everyone_in.wait()
        return prices.DividendWindow(answered=True, dividends=[{"date": EX, "dps": 0.25}])

    monkeypatch.setattr(prices, "_fetch_dividends", held)
    tab = TestClient(app, raise_server_exceptions=False)
    results: list = []
    lock = threading.Lock()

    def run() -> None:
        r = tab.post("/api/transactions/catch-up")
        with lock:
            results.append(r.json() if r.status_code == 200 else r.text)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a catch-up never came back"
    assert all(isinstance(r, dict) for r in results), results
    assert sum(len(r["recognised"]) for r in results) == 1
    assert sum(len(r["created"]) for r in results) == 0
    assert _dividends(client) == [(PAID, 3.7, EX, False)]
    with SessionLocal() as db:
        assert db.get(models.Transaction, tx_id).ex_date == EX


def test_two_catch_ups_held_between_the_pairing_and_the_write_recognise_once(client, yahoo, monkeypatch, on):
    """Brief Y's harder shape: both tabs have read the entry without its
    ex-date before either writes, and the second asks again under the lock.
    Its answer must come from the database, not from the copy it read first,
    or both report the entry recognised (found while building)."""
    iid = _household(client)
    tx_id = _typed(client, iid, PAID)
    everyone_in = threading.Barrier(2, timeout=10)
    real = pac._recognise

    def held(*args, **kwargs):
        everyone_in.wait()
        return real(*args, **kwargs)

    monkeypatch.setattr(pac, "_recognise", held)
    tab = TestClient(app, raise_server_exceptions=False)
    results: list = []
    lock = threading.Lock()

    def run() -> None:
        r = tab.post("/api/transactions/catch-up")
        with lock:
            results.append(r.json() if r.status_code == 200 else r.text)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a catch-up never came back"
    assert all(isinstance(r, dict) for r in results), results
    assert sum(len(r["recognised"]) for r in results) == 1
    assert sum(len(r["created"]) for r in results) == 0
    with SessionLocal() as db:
        assert db.get(models.Transaction, tx_id).ex_date == EX


def test_an_entry_typed_while_the_dividend_is_being_written_stops_the_write(client, yahoo, monkeypatch, on):
    """The catch-up read no entry in the window, worked the dividend out, and
    meanwhile the reader saved their own: asked again under the write lock,
    the window holds it, and nothing is written. The next catch-up pairs it."""
    iid = _household(client)
    real = pac._record_dividend
    typed: list[int] = []

    def meanwhile(*args, **kwargs):
        typed.append(_typed(client, iid, PAID))
        return real(*args, **kwargs)

    monkeypatch.setattr(pac, "_record_dividend", meanwhile)
    assert _created(_catch_up(client)) == []
    monkeypatch.setattr(pac, "_record_dividend", real)
    result = _catch_up(client)
    assert (_created(result), [r["entry"]["id"] for r in result["recognised"]]) == ([], typed)
    assert _dividends(client) == [(PAID, 3.7, EX, False)]


def test_an_answer_that_no_longer_stands_is_refused_in_words(client, yahoo, on):
    iid = _household(client)
    first = _typed(client, iid, PAID)
    second = _typed(client, iid, "2026-10-02", per_share=0.06)
    _catch_up(client)
    _answer(client, iid, answer="link", transaction_id=first, ex_date=EX)

    def refused(**body) -> str:
        r = client.post("/api/transactions/dividend-answer", json={"institution_id": iid, "symbol": TICKER, **body})
        assert r.status_code == 409, r.text
        return r.json()["detail"]

    assert refused(answer="link", transaction_id=first, ex_date=EX) == (
        f"That entry of {TICKER} at Broker A is no longer one the question was about: reload the "
        "page to see what is asked now."
    )
    assert refused(answer="link", transaction_id=second, ex_date=EX) == (
        f"The dividend of {TICKER} with ex-date {EX} already has an entry of yours."
    )
    assert refused(answer="link", transaction_id=second, ex_date="2026-08-01") == (
        f"Yahoo no longer lists a dividend of {TICKER} with ex-date 2026-08-01."
    )
    r = client.post("/api/transactions/dividend-answer",
                    json={"institution_id": iid, "symbol": TICKER, "answer": "link", "transaction_id": second})
    assert r.status_code == 422
    assert _dividends(client) == [(PAID, 3.7, EX, False), ("2026-10-02", 1.2, None, False)]


def test_an_entry_deleted_takes_what_the_reader_said_of_it_along(client, yahoo, on):
    iid = _household(client)
    tx_id = _estimate_then_typed(client, iid)
    _catch_up(client)
    _answer(client, iid, answer="apart", pairs=[{"transaction_id": tx_id, "ex_date": EX}])
    with SessionLocal() as db:
        before = [k for k in db.scalars(select(models.Setting.key)) if k.startswith("dividend_apart:")]
    assert before == [f"dividend_apart:{iid}:{TICKER}:{EX}:{tx_id}"]
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 204
    with SessionLocal() as db:
        after = [k for k in db.scalars(select(models.Setting.key)) if k.startswith("dividend_apart:")]
    assert after == []
