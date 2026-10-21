"""A new situation started from the last keeps what was paid (brief AV, part 3).

Measured on the demo with an invented fund (2026-10-14): photographed at 10 x
100 with no cost, then three plan buys of 100, "Start from the last one" wrote
the new row 13 x 110 = 1,430.00 with no cost. The 300.00 paid was folded into
the situation's value: after one more buy, the projection could see 110.00 of
purchases where the ledger held 410.00.

The new row now keeps the part paid as its cost, with the units it paid for
(`holdings.cost_quantity`, a migration); the other units are the situation's
value. The units the cost covers open at it, the others at the row's own
price. Every name and figure here is invented.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app import crud, database, pac, prices, schemas, screen
from app.database import SessionLocal

SITUATION = "2026-01-01"
NEW_SITUATION = "2026-05-01"


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


def _photo(client, **holding) -> tuple[int, int]:
    bank = _made(client.post("/api/institutions", json={"name": "Banca Alfa"}))["id"]
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))["id"]
    hid = _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Alfa", "asset_class": "fund_etf", "symbol": "ALFA.MI",
        "quantity": 10, "unit_price": 100, "currency": "EUR", **holding}))["id"]
    return bank, hid


def _buy(client, bank: int, date: str, quantity: float, unit_price: float, **more) -> None:
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": date, "institution_id": bank, "asset_name": "Fondo Alfa",
        "symbol": "ALFA.MI", "quantity": quantity, "unit_price": unit_price, "currency": "EUR",
        "price_currency": "EUR", **more}))


def _market(monkeypatch, price: float | None) -> None:
    """The quote the new situation is priced with, and the same close cached
    for the Portfolio. None: nothing answers."""
    monkeypatch.setattr(prices, "get_quotes", lambda symbols: (
        {} if price is None else
        {s: {"symbol": s, "price": price, "as_of": NEW_SITUATION} for s in symbols}))
    if price is not None:
        with SessionLocal() as db:
            crud.upsert_price_caches(db, {"ALFA.MI": {"price": price, "as_of": NEW_SITUATION,
                                                      "currency": "EUR"}})


def _new_situation(client, bank: int) -> tuple[dict, dict]:
    snap = _made(client.post(f"/api/institutions/{bank}/snapshots/prefilled",
                             json={"date": NEW_SITUATION}))
    (row,) = _made(client.get(f"/api/snapshots/{snap['id']}/holdings"))
    return snap, row


def _position(client) -> dict:
    rows = _made(client.get("/api/dashboard/portfolio"))["rows"]
    return next(r for r in rows if r["symbol"] == "ALFA.MI")


# --- The carry ---------------------------------------------------------------------------


def test_the_new_situation_keeps_what_the_buys_paid_and_for_how_many_units(client, monkeypatch):
    bank, _ = _photo(client)
    for date in ("2026-02-02", "2026-03-02", "2026-04-01"):
        _buy(client, bank, date, 1, 100)
    _market(monkeypatch, 110.0)
    _, row = _new_situation(client, bank)
    assert (row["quantity"], row["unit_price"], row["value"]) == (13.0, 110.0, 1430.0)
    assert (row["cost_basis"], row["cost_quantity"]) == (300.0, 3.0), "it carried no cost"
    assert row["cost_estimated"] is False, "the reader's own buys"

    p = _position(client)
    assert (p["book_value"], p["book_paid"], p["units_paid"]) == (1400.0, 300.0, 3.0)
    assert p["cost_known"] is False
    assert p["delta"] == 30.0 and p["delta_paid"] == 30.0, (
        "the gain on the part paid survives the new situation; the rest starts again"
    )

    _buy(client, bank, "2026-05-04", 1, 110)
    p = _position(client)
    assert (p["book_paid"], p["units_paid"]) == (410.0, 4.0), "it could see only the 110.00"


def test_the_units_carried_are_the_ones_bought(client, monkeypatch):
    """6 photographed at 195, 4 bought for 766.00: the new row's cost is
    766.00 for 4 units, not for an average share of the 10."""
    bank, _ = _photo(client, quantity=6, unit_price=195)
    _buy(client, bank, "2026-02-02", 4, 191, fees=2)
    _market(monkeypatch, 200.0)
    _, row = _new_situation(client, bank)
    assert (row["cost_basis"], row["cost_quantity"]) == (766.0, 4.0)
    p = _position(client)
    assert (p["book_value"], p["delta"], p["delta_paid"]) == (1966.0, 34.0, 34.0)


def test_a_plan_s_buys_carried_stay_estimated(client, monkeypatch):
    monkeypatch.setattr(
        prices, "get_price_on",
        lambda symbol, on, today=None: {"symbol": symbol, "price": 100.0, "as_of": on.isoformat()},
    )
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    bank, _ = _photo(client)
    _made(client.post("/api/accumulation-plans", json={
        "name": "Piano Alfa", "amount": 100, "currency": "EUR", "frequency": "monthly",
        "execution": "fractional", "start_date": "2026-02-02", "source_institution_id": bank,
        "targets": [{"symbol": "ALFA.MI", "asset_name": "Fondo Alfa", "institution_id": bank}],
    }))
    import datetime

    with SessionLocal() as db:
        assert len(pac.execute_due(db, as_of=datetime.date(2026, 4, 10))["created"]) == 3
    _market(monkeypatch, 110.0)
    _, row = _new_situation(client, bank)
    assert (row["cost_basis"], row["cost_quantity"], row["cost_estimated"]) == (300.0, 3.0, True)
    assert _position(client)["cost_estimated"] is True


def test_a_row_nothing_could_price_carries_no_cost_as_before(client, monkeypatch):
    """Written at the projection's average of photograph and purchases, one
    price for both: splitting it would move money between them (a book of
    1,666.67 beside a value of 1,600.00 on this row). It stays a row needing
    the reader, with no cost, and the answer says what was paid on it and is
    not kept, so the page can say so."""
    bank, _ = _photo(client)
    _buy(client, bank, "2026-02-02", 5, 120)
    _market(monkeypatch, None)
    snap, row = _new_situation(client, bank)
    assert (row["value"], row["cost_basis"], row["cost_quantity"]) == (1600.0, None, None)
    assert snap["needs_attention"] == ["Fondo Alfa"]
    assert snap["paid_not_kept"] == [{"asset_name": "Fondo Alfa", "units_paid": 5.0}]
    p = _position(client)
    assert (p["book_value"], p["observed_value"]) == (1600.0, 1600.0)


def test_only_a_part_paid_and_lost_is_said(client, monkeypatch):
    """A row re-priced keeps its part paid; a row with nothing paid has none
    to lose, priced or not: neither is named."""
    bank, _ = _photo(client)
    _buy(client, bank, "2026-02-02", 3, 100)
    _market(monkeypatch, 110.0)
    snap, _ = _new_situation(client, bank)
    assert snap["paid_not_kept"] == []

    other = _made(client.post("/api/institutions", json={"name": "Banca Gamma"}))["id"]
    sid = _made(client.post(f"/api/institutions/{other}/snapshots", json={"date": SITUATION}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Gamma", "asset_class": "fund_etf", "symbol": "GAMMA.MI",
        "quantity": 10, "unit_price": 100, "currency": "EUR"}))
    _made(client.post("/api/transactions", json={
        "kind": "sell", "date": "2026-02-02", "institution_id": other, "asset_name": "Fondo Gamma",
        "symbol": "GAMMA.MI", "quantity": 4, "unit_price": 100, "currency": "EUR",
        "price_currency": "EUR"}))
    _market(monkeypatch, None)
    snap = _made(client.post(f"/api/institutions/{other}/snapshots/prefilled",
                             json={"date": NEW_SITUATION}))
    assert (snap["needs_attention"], snap["paid_not_kept"]) == (["Fondo Gamma"], [])


def test_a_cost_recorded_for_every_unit_is_carried_whole(client, monkeypatch):
    bank, _ = _photo(client, cost_basis=900)
    _buy(client, bank, "2026-02-02", 3, 100)
    _market(monkeypatch, 110.0)
    _, row = _new_situation(client, bank)
    assert (row["cost_basis"], row["cost_quantity"]) == (1200.0, None)
    assert _position(client)["cost_known"] is True


def test_units_with_no_value_and_no_cost_are_carried_as_head_carried_them(client, monkeypatch):
    """Filed under STILL OPEN: such units count as costing nothing, so with a
    buy the row reads all paid and the new row's cost covers every unit. The
    API refuses such a row since brief BE; one written before is read so."""
    bank, hid = _photo(client)
    with SessionLocal() as db:
        db.execute(text("UPDATE holdings SET unit_price = NULL, value = NULL WHERE id = :id"), {"id": hid})
        db.commit()
    _buy(client, bank, "2026-02-02", 5, 100)
    _market(monkeypatch, None)
    _, row = _new_situation(client, bank)
    assert (row["cost_basis"], row["cost_quantity"]) == (500.0, None)


# --- A cost that pays for some of the units ------------------------------------------------


def test_a_cost_typed_for_some_of_the_units_opens_them_at_it(client):
    _, _ = _photo(client, quantity=13, unit_price=110, cost_basis=300, cost_quantity=3)
    p = _position(client)
    assert (p["book_value"], p["book_paid"], p["units_paid"]) == (1400.0, 300.0, 3.0)
    assert p["cost_known"] is False


def _body(row: dict, **over) -> dict:
    keys = ("asset_name", "asset_class", "symbol", "isin", "quantity", "unit_price", "value",
            "cost_basis", "currency", "distribution_policy")
    return {**{k: row[k] for k in keys}, **over}


def test_an_edit_that_leaves_the_cost_keeps_what_it_paid_for(client, monkeypatch):
    """The form sends the cost it loaded and leaves the rest out: a price
    corrected on a carried row keeps 300.00 for 3 units, and its estimate."""
    bank, hid = _photo(client, quantity=13, unit_price=110, cost_basis=300, cost_quantity=3,
                       cost_estimated=True)
    row = _made(client.get(f"/api/holdings/{hid}"))
    after = _made(client.put(f"/api/holdings/{hid}", json=_body(row, unit_price=112)))
    assert (after["cost_quantity"], after["cost_estimated"]) == (3.0, True)


@pytest.mark.parametrize("over,sentence", [
    ({"quantity": 2}, "This cost paid for 3 units, more than the 2 typed here. "
                      "Type what the units you hold cost, or keep at least 3."),
    ({"quantity": None, "unit_price": None, "value": 1430},
     "This cost paid for 3 units, and a row entered as a total has none. "
     "Type what the whole position cost, or keep it in units and a price."),
])
def test_units_below_what_the_cost_paid_for_are_refused_in_words(client, over, sentence):
    _, hid = _photo(client, quantity=13, unit_price=110, cost_basis=300, cost_quantity=3)
    row = _made(client.get(f"/api/holdings/{hid}"))
    r = client.put(f"/api/holdings/{hid}", json=_body(row, **over))
    assert r.status_code == 422
    assert r.json()["detail"] == sentence


def test_a_count_of_units_needs_a_cost_and_no_more_units_than_held(client):
    bank = _made(client.post("/api/institutions", json={"name": "Banca Beta"}))["id"]
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))["id"]
    base = {"asset_name": "Fondo Beta", "symbol": "BETA.MI", "quantity": 5, "unit_price": 10,
            "currency": "EUR"}
    no_cost = client.post(f"/api/snapshots/{sid}/holdings", json={**base, "cost_quantity": 2})
    above = client.post(f"/api/snapshots/{sid}/holdings",
                        json={**base, "cost_basis": 20, "cost_quantity": 6})
    assert no_cost.status_code == 422 and "needs the cost it goes with" in no_cost.json()["detail"]
    assert above.status_code == 422 and "more than the 5 typed here" in above.json()["detail"]
    assert client.post(f"/api/snapshots/{sid}/holdings",
                       json={**base, "cost_basis": 20, "cost_quantity": 5}).status_code == 201


def test_a_cost_typed_by_the_reader_covers_every_unit(client):
    _, hid = _photo(client, quantity=13, unit_price=110, cost_basis=300, cost_quantity=3)
    row = _made(client.get(f"/api/holdings/{hid}"))
    after = _made(client.put(f"/api/holdings/{hid}",
                             json=_body(row, cost_basis=1250, cost_quantity=None)))
    assert (after["cost_basis"], after["cost_quantity"]) == (1250.0, None)
    assert _position(client)["cost_known"] is True


# --- What the chat reads on the situation's page --------------------------------------------


def test_the_situation_s_page_says_what_the_cost_paid_for(client):
    bank, hid = _photo(client, quantity=13, unit_price=110, cost_basis=300, cost_quantity=3)
    sid = _made(client.get(f"/api/holdings/{hid}"))["snapshot_id"]
    with SessionLocal() as db:
        note = screen.resolve(db, schemas.ChatPageSituation(
            kind="situation", institution_id=bank, snapshot_id=sid)).note
    assert (
        "- Fondo Alfa [fund_etf] ALFA.MI: qty 13 x 110.00 = 1430.00 EUR; cost 300.00 EUR for 3 "
        "of the 13 units (the others are this situation's value, no cost recorded)"
    ) in note


# --- The migration ---------------------------------------------------------------------------


@pytest.fixture
def before_the_count(tmp_path, start_on):
    """A file the real chain built up to `491fe57d31db`, the revision before
    this one, with a holding in it."""
    path = tmp_path / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, "491fe57d31db")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO institutions (name, created_at) VALUES ('Banca Alfa', '2026-01-01')")
        conn.execute("INSERT INTO snapshots (institution_id, date, created_at) VALUES (1, ?, ?)",
                     (SITUATION, "2026-01-01T10:00:00"))
        conn.execute(
            "INSERT INTO holdings (snapshot_id, asset_name, asset_class, symbol, quantity,"
            " unit_price, value, cost_basis, cost_estimated, currency)"
            " VALUES (1, 'Fondo Alfa', 'fund_etf', 'ALFA.MI', 10, 100, 1000, 900, 0, 'EUR')"
        )
    start_on(path)
    return path


def test_the_migration_adds_the_count_and_keeps_every_row_as_it_was(before_the_count):
    path = before_the_count
    then = ("SELECT id, snapshot_id, asset_name, symbol, quantity, unit_price, value, cost_basis,"
            " cost_estimated, currency FROM holdings")
    with closing(sqlite3.connect(path)) as conn:
        before = conn.execute(then).fetchall()

    database.init_db()

    assert len(list(path.parent.glob("data.db.bak-*-before-migration-491fe57d31db-to-*"))) == 1, (
        "the app copied the file before migrating it"
    )
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute(then).fetchall() == before
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(holdings)")}
        assert columns["cost_quantity"][3] == 0, "nullable"
        assert conn.execute("SELECT cost_quantity FROM holdings").fetchall() == [(None,)]

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    command.downgrade(cfg, "491fe57d31db")
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(holdings)")]
        assert "cost_quantity" not in columns
        assert conn.execute(then).fetchall() == before
