"""A dividend keeps its ex-date, whatever day its row is dated.

Brief AZ (2026-10-16). The catch-up records a dividend on its ex-date at the
market's gross figure, to be corrected with what the broker credited, and
until this brief that day was also the only key it found the dividend by
(`crud.get_dividend_dates_settled`). The broker credits the money on the
PAYMENT date, days or weeks later, so a reader correcting the row with the
statement moves it there, and the next page load, the same day, found the
ex-date empty and recorded the dividend again: measured at `eaa89fc` on an
invented household, 5.00 gross recorded again beside the 3.70 the reader had
corrected, the cash at 5,008.70 where 5,003.70 is right and a withholding of
1.30 estimated on money already taxed.

So the ex-date has a column of its own (`transactions.ex_date`, a migration
that fills it on the catch-up's untouched rows), written on every dividend the
catch-up records, adopted onto one of its older rows still on its ex-date, and
kept by every edit, since no form sends it. A deletion is remembered by it.

Yahoo is faked where the app meets it, `prices._fetch_dividends`, the reader's
day with `dated.today`, and every name and figure is invented.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import advisor, database, dated, models, prices
from app.database import SessionLocal
from app.main import app

TICKER = "XDIV.MI"
EX = "2026-09-22"
PAID = "2026-09-29"


@pytest.fixture()
def yahoo(monkeypatch):
    """One dividend, 0.25 EUR a share on 22 September, on a listing in euros,
    so no exchange rate is asked for. Every ask is counted."""
    asked: list[str] = []

    def fetch(symbol: str, period: str = "max"):
        asked.append(symbol)
        listed = [{"date": EX, "dps": 0.25}] if symbol == TICKER else []
        return prices.DividendWindow(answered=True, dividends=listed)

    monkeypatch.setattr(prices, "_fetch_dividends", fetch)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    return asked


@pytest.fixture()
def on(monkeypatch):
    def today_is(day: str) -> None:
        monkeypatch.setattr(dated, "today", lambda: day)

    today_is("2026-10-05")
    return today_is


def _household(client) -> int:
    """Broker A: a situation and a balance of 5,000.00 on 1 September, 20
    units of a distributing share, and tax rates of 26%."""
    r = client.put("/api/settings/tax",
                   json={"country": None, "capital_gains_rate": 26, "dividend_withholding_rate": 26})
    assert r.status_code == 200, r.text
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-09-01"}).json()["id"]
    r = client.post(f"/api/snapshots/{sid}/holdings",
                    json={"asset_name": "Example Dividend Share", "asset_class": "equity", "symbol": TICKER,
                          "quantity": 20, "unit_price": 50, "currency": "EUR", "distribution_policy": "dist"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/institutions/{iid}/cash-anchors",
                    json={"date": "2026-09-01", "amount": 5000.0, "currency": "EUR"})
    assert r.status_code == 201, r.text
    return iid


def _catch_up(client) -> list[tuple]:
    """What a catch-up recorded: (day, amount) of each new row."""
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    return [(t["date"], t["amount"]) for t in r.json()["created"]]


def _dividends(client) -> list[tuple]:
    """Every dividend on the ledger: day, amount, ex-date, estimated. Read
    with `get`, so on the code before this brief a test reaches the figures
    it is about and fails there, not on a missing field."""
    return sorted(
        (t["date"], t["amount"], t.get("ex_date"), t["estimated"])
        for t in client.get("/api/transactions").json()
        if t["kind"] == "dividend"
    )


def _moved_and_corrected(client, day: str = PAID) -> dict:
    """The ledger form's PUT on the app's row: every box as the row fills it,
    the day the money arrived, the net per share typed, the amount left to be
    worked out (null), as `Portfolio.tsx` sends it."""
    (tx,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    r = client.put(f"/api/transactions/{tx['id']}", json={
        "kind": "dividend", "date": day, "institution_id": tx["institution_id"],
        "asset_name": tx["asset_name"], "symbol": tx["symbol"], "quantity": tx["quantity"],
        "unit_price": 0.185, "fees": 0, "amount": None, "currency": "EUR", "price_currency": "EUR",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _figures(client, iid: int) -> dict:
    (cash,) = [c for c in client.get("/api/cash/positions").json() if c["institution_id"] == iid]
    portfolio = client.get("/api/dashboard/portfolio").json()
    tax = portfolio["tax_estimate"]
    return {
        "cash": round(cash["projected"], 2),
        "dividends": round(portfolio["total_dividends"], 2),
        "estimated": round(portfolio["total_dividends_estimated"], 2),
        "withholding": round(tax["dividend_withholding"] or 0.0, 4),
    }


# --- The row moved to the day its money arrived --------------------------------------------


def test_a_dividend_moved_to_its_payment_date_is_not_recorded_again(client, yahoo, on):
    """The second defect, as measured: corrected to 3.70 and moved to the
    payment date, then caught up again the same day and the next."""
    iid = _household(client)
    assert _catch_up(client) == [(EX, 5.0)]
    _moved_and_corrected(client)
    right = {"cash": 5003.7, "dividends": 3.7, "estimated": 0.0, "withholding": 0.0}
    assert _figures(client, iid) == right

    assert _catch_up(client) == []
    on("2026-10-06")
    assert _catch_up(client) == []
    assert _figures(client, iid) == right
    assert _dividends(client) == [(PAID, 3.7, EX, False)]


def test_the_ledger_says_each_dividend_s_ex_date(client, yahoo, on):
    _household(client)
    _catch_up(client)
    assert _dividends(client) == [(EX, 5.0, EX, True)]
    _moved_and_corrected(client)
    assert _dividends(client) == [(PAID, 3.7, EX, False)]


def test_no_request_sets_or_clears_an_ex_date(client, yahoo, on):
    """No form has a box for it, and a body that carries one anyway leaves
    the stored one as it was: only the catch-up and the reader's answer to
    its question write it."""
    _household(client)
    _catch_up(client)
    (tx,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    for sent in ("2026-01-01", None):
        r = client.put(f"/api/transactions/{tx['id']}", json={
            "kind": "dividend", "date": PAID, "institution_id": tx["institution_id"],
            "asset_name": tx["asset_name"], "symbol": tx["symbol"], "quantity": 20,
            "unit_price": 0.185, "amount": None, "currency": "EUR", "price_currency": "EUR",
            "ex_date": sent,
        })
        assert r.status_code == 200, r.text
        assert r.json().get("ex_date") == EX
    r = client.post("/api/transactions", json={
        "kind": "dividend", "date": PAID, "institution_id": tx["institution_id"],
        "asset_name": tx["asset_name"], "symbol": TICKER, "quantity": 20, "unit_price": 0.1,
        "currency": "EUR", "price_currency": "EUR", "ex_date": EX,
    })
    assert r.status_code == 201, r.text
    assert r.json()["ex_date"] is None


def test_a_dividend_moved_then_deleted_stays_deleted(client, yahoo, on):
    """Brief AO remembers a deletion by its day; a moved dividend's day is its
    payment date, and the catch-up would have recorded it again on its
    ex-date. The deletion is remembered by the ex-date the row keeps."""
    _household(client)
    _catch_up(client)
    moved = _moved_and_corrected(client)
    assert client.delete(f"/api/transactions/{moved['id']}").status_code == 204
    assert _catch_up(client) == []
    on("2026-10-06")
    assert _catch_up(client) == []
    assert _dividends(client) == []
    with SessionLocal() as db:
        keys = [k for k in db.scalars(select(models.Setting.key)) if k.startswith("dividend_deleted:")]
    assert keys == [f"dividend_deleted:{moved['institution_id']}:{TICKER}:{EX}"]


# --- One of the catch-up's rows the migration left without its ex-date ----------------------


def _corrected_before_this_brief(client) -> int:
    """The app's row corrected by the reader on its ex-date, as one corrected
    before the migration is: no longer estimated, so the migration gave it no
    ex-date, and its date its only key."""
    _catch_up(client)
    (tx,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    r = client.put(f"/api/transactions/{tx['id']}", json={
        "kind": "dividend", "date": EX, "institution_id": tx["institution_id"],
        "asset_name": tx["asset_name"], "symbol": tx["symbol"], "quantity": 20,
        "unit_price": 0.185, "amount": None, "currency": "EUR", "price_currency": "EUR",
    })
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        db.get(models.Transaction, tx["id"]).ex_date = None
        db.commit()
    return tx["id"]


def test_the_catch_up_gives_its_own_corrected_row_its_ex_date(client, yahoo, on):
    """The reviewer's note 2: adopted at the next catch-up, since the row is
    the catch-up's (its note) and sits on a day Yahoo lists as an ex-date; then
    it can be moved like any other, and is not recorded again, the same day or
    the next."""
    iid = _household(client)
    tx_id = _corrected_before_this_brief(client)
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    # Silently: the row is the catch-up's own, and no figure moves.
    assert (r.json()["created"], r.json().get("recognised", [])) == ([], [])
    with SessionLocal() as db:
        assert db.get(models.Transaction, tx_id).ex_date == EX

    _moved_and_corrected(client)
    assert _catch_up(client) == []
    on("2026-10-06")
    assert _catch_up(client) == []
    assert _figures(client, iid)["cash"] == 5003.7
    assert _dividends(client) == [(PAID, 3.7, EX, False)]


def test_two_catch_ups_at_once_adopt_once_and_record_nothing(client, yahoo, monkeypatch, on):
    """Brief Y's shape, two tabs held at the fetch: both find the row without
    its ex-date before either writes. The second asks again under the write
    lock and finds nothing left to give."""
    iid = _household(client)
    tx_id = _corrected_before_this_brief(client)
    on("2026-10-06")  # yesterday's answer is not used today, so both ask
    everyone_in = threading.Barrier(2, timeout=10)

    def held(symbol: str, period: str = "max"):
        everyone_in.wait()
        return prices.DividendWindow(answered=True, dividends=[{"date": EX, "dps": 0.25}])

    monkeypatch.setattr(prices, "_fetch_dividends", held)
    tab = TestClient(app, raise_server_exceptions=False)
    outcomes: list = []
    lock = threading.Lock()

    def run() -> None:
        r = tab.post("/api/transactions/catch-up")
        with lock:
            outcomes.append((r.status_code, r.json()["created"] if r.status_code == 200 else r.text))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a catch-up never came back"
    assert outcomes == [(200, []), (200, [])]
    with SessionLocal() as db:
        assert db.get(models.Transaction, tx_id).ex_date == EX
    assert _dividends(client) == [(EX, 3.7, EX, False)]
    assert _figures(client, iid)["cash"] == 5003.7


# --- What the chat reads ---------------------------------------------------------------------


def test_the_chat_s_ledger_line_says_a_moved_dividend_s_ex_date(client, yahoo, on):
    _household(client)
    _catch_up(client)
    with SessionLocal() as db:
        before = advisor.build_context(db)
    assert f"- {EX} dividend 20 x {TICKER} @ 0.25 EUR = 5.00 EUR (estimated)" in before
    assert "with ex-date" not in before
    _moved_and_corrected(client)
    with SessionLocal() as db:
        after = advisor.build_context(db)
    assert f"- {PAID} dividend 20 x {TICKER} @ 0.18 EUR = 3.70 EUR, the dividend with ex-date {EX}" in after


# --- The migration ---------------------------------------------------------------------------


@pytest.fixture
def before_the_ex_date(tmp_path, start_on):
    """A file the real chain built up to `31668ac923e3`, the revision before
    this one, with four ledger rows: the catch-up's dividend nobody touched,
    one of its dividends the reader corrected, the reader's own dividend, and
    a plan's buy, estimated like the first."""
    path = tmp_path / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, "31668ac923e3")
    rows = [
        ("dividend", "2026-03-20", 1, "Auto-recorded from market data: a dividend of 0.25 EUR per share"),
        ("dividend", "2026-06-25", 0, "Auto-recorded from market data: a dividend of 0.25 EUR per share"),
        ("dividend", "2026-09-29", 0, None),
        ("buy", "2026-09-15", 1, None),
    ]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO institutions (name, created_at) VALUES ('Broker A', '2026-01-01')")
        for kind, day, estimated, note in rows:
            conn.execute(
                "INSERT INTO transactions (kind, date, institution_id, asset_name, symbol, quantity,"
                " unit_price, fees, amount, currency, price_currency, estimated, note, created_at)"
                " VALUES (?, ?, 1, 'Example Dividend Share', 'XDIV.MI', 20, 0.25, 0, 5.0, 'EUR', 'EUR',"
                " ?, ?, '2026-10-01T10:00:00')",
                (kind, day, estimated, note),
            )
    start_on(path)
    return path


def test_the_migration_gives_the_ex_date_only_to_the_catch_up_s_untouched_dividends(before_the_ex_date):
    path = before_the_ex_date
    then = "SELECT id, kind, date, amount, estimated, note FROM transactions ORDER BY id"
    with closing(sqlite3.connect(path)) as conn:
        before = conn.execute(then).fetchall()

    database.init_db()

    assert len(list(path.parent.glob("data.db.bak-*-before-migration-31668ac923e3-to-*"))) == 1, (
        "the app copied the file before migrating it"
    )
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute(then).fetchall() == before
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(transactions)")}
        assert columns["ex_date"][3] == 0, "nullable"
        assert conn.execute("SELECT kind, date, ex_date FROM transactions ORDER BY id").fetchall() == [
            ("dividend", "2026-03-20", "2026-03-20"),
            ("dividend", "2026-06-25", None),
            ("dividend", "2026-09-29", None),
            ("buy", "2026-09-15", None),
        ]

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    command.downgrade(cfg, "31668ac923e3")
    with closing(sqlite3.connect(path)) as conn, conn:
        assert "ex_date" not in [row[1] for row in conn.execute("PRAGMA table_info(transactions)")]
        assert conn.execute(then).fetchall() == before
