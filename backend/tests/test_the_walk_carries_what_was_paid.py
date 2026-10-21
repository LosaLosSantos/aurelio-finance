"""How much of a position's cost was paid, carried by the walk (brief AV, part 1).

A position's cost was known or unknown, one yes or no, and a row that mixed a
situation's value (no cost recorded) with later purchases said "cost unknown"
for all of it. Measured on the demo with an invented fund photographed at 10
x 100 and three plan buys of 100 after it (2026-10-14): 300.00 of a 1,300.00
book was paid, and the row knew none of it.

The walk now carries a PAID POOL: the money paid and the units it paid for. A
buy adds its cash and its units; a sell takes the same share of the pool's
units and money as of the book's; a close empties it; a photograph's value
with no cost adds nothing to it. Every name and figure here is invented.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import anyio
import pytest
from mcp.client import Client
from sqlalchemy import text

from app import crud, pac, positions, prices
from app.database import SessionLocal, engine
from app.mcp_server import build_server

SITUATION = "2026-01-01"
FIRST_BUY = "2026-01-05"
CAUGHT_UP_TO = datetime.date(2026, 3, 10)  # three buys: 5 January, February, March


def _entry(n: int, kind: str, quantity: float = 0.0, amount: float = 0.0,
           estimated: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=n, date=f"2026-02-{n:02d}", kind=kind, quantity=quantity,
                           amount=amount, estimated=estimated)


# --- The walk -------------------------------------------------------------------------


def test_a_buy_adds_its_cash_and_its_units_to_what_was_paid():
    s = positions.replay(
        [_entry(1, "buy", 1, 100), _entry(2, "buy", 1, 100), _entry(3, "buy", 1, 100)],
        start_qty=10, start_book=1000, start_paid=0.0, start_paid_units=0.0,
    )
    assert (s.quantity, s.book, s.paid, s.paid_units) == (13.0, 1300.0, 300.0, 3.0)


def test_a_sell_takes_the_paid_pool_in_proportion_and_leaves_the_share_as_it_was():
    s = positions.replay(
        [_entry(1, "buy", 3, 300), _entry(2, "sell", 6.5, 715)],
        start_qty=10, start_book=1000, start_paid=0.0, start_paid_units=0.0,
    )
    assert (s.quantity, s.book, s.paid, s.paid_units) == (6.5, 650.0, 150.0, 1.5)
    assert s.paid / s.book == 300 / 1300, "the share of the book paid is unchanged"


def test_each_pool_keeps_its_own_average_price_through_a_sell():
    """6 photographed at 195 with no cost, then 4 bought for 766.00 (191 each
    and 2.00 of fees): the paid units average 191.50, the others 195.00, and
    selling half of the position changes neither."""
    s = positions.replay(
        [_entry(1, "buy", 4, 766), _entry(2, "sell", 5, 1000)],
        start_qty=6, start_book=1170, start_paid=0.0, start_paid_units=0.0,
    )
    assert s.paid / s.paid_units == pytest.approx(191.5, abs=1e-12)
    assert (s.book - s.paid) / (s.quantity - s.paid_units) == pytest.approx(195.0, abs=1e-12)
    assert s.book == pytest.approx(968.0, abs=1e-9), "the book is average cost: 1,936 / 2"


def test_a_close_empties_what_was_paid():
    s = positions.replay(
        [_entry(1, "buy", 3, 300), _entry(2, "close", 0, 1430)],
        start_qty=10, start_book=1000, start_paid=0.0, start_paid_units=0.0,
    )
    assert (s.quantity, s.book, s.paid, s.paid_units) == (0.0, 0.0, 0.0, 0.0)


def test_left_out_the_opening_is_taken_as_paid_and_a_sell_keeps_it_all_paid():
    s = positions.replay(
        [_entry(1, "buy", 3, 300), _entry(2, "sell", 4.5, 520), _entry(3, "sell", 1.1, 130)],
        start_qty=10, start_book=900,
    )
    assert s.paid == s.book and s.paid_units == s.quantity, "the same arithmetic, to the bit"


def test_an_estimated_buy_marks_the_paid_part_estimated():
    s = positions.replay(
        [_entry(1, "buy", 1, 100, estimated=True)],
        start_qty=10, start_book=1000, start_paid=0.0, start_paid_units=0.0,
    )
    assert s.cost_estimated is True and s.paid == 100.0


# --- What the Portfolio's row says --------------------------------------------------------


def _made(response) -> int:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.fixture
def market(monkeypatch):
    """Every close at 100.00 EUR, so a plan of 100 EUR a month buys 1 unit."""
    monkeypatch.setattr(
        prices, "get_price_on",
        lambda symbol, on, today=None: {"symbol": symbol, "price": 100.0, "as_of": on.isoformat()},
    )
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")


def _photo(client, **holding) -> int:
    bank = _made(client.post("/api/institutions", json={"name": "Banca Alfa"}))
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Alfa", "asset_class": "fund_etf", "symbol": "ALFA.MI",
        "quantity": 10, "unit_price": 100, "currency": "EUR", **holding}))
    return bank


def _plan_buys(client, bank: int) -> None:
    _made(client.post("/api/accumulation-plans", json={
        "name": "Piano Alfa", "amount": 100, "currency": "EUR", "frequency": "monthly",
        "execution": "fractional", "start_date": FIRST_BUY, "source_institution_id": bank,
        "targets": [{"symbol": "ALFA.MI", "asset_name": "Fondo Alfa", "institution_id": bank}],
    }))
    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=CAUGHT_UP_TO)
    assert len(out["created"]) == 3, out["skipped"]


def _priced(symbol: str, price: float) -> None:
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {symbol: {"price": price, "as_of": "2026-03-09",
                                               "currency": "EUR"}})


def _row(client) -> dict:
    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    return next(r for r in rows if r["symbol"] == "ALFA.MI")


def test_a_blend_says_how_much_of_it_was_paid(client, market):
    """The measured case: 300.00 of 1,300.00 paid, for 3 of the 13 units; at a
    price of 110 the P/L is +130.00, of which +30.00 on the units bought."""
    _plan_buys(client, _photo(client))
    _priced("ALFA.MI", 110.0)
    row = _row(client)
    assert (row["quantity"], row["book_value"]) == (13.0, 1300.0)
    assert (row["book_paid"], row["units_paid"]) == (300.0, 3.0)
    assert row["cost_known"] is False, "not all of it was paid"
    assert row["cost_estimated"] is True, "the part paid is the plan's buys at the close"
    assert row["delta"] == 130.0 and row["delta_paid"] == pytest.approx(30.0, abs=1e-9)


def test_the_gain_on_the_part_paid_is_on_the_units_actually_bought(client):
    """6 photographed at 195 with no cost, 4 bought for 766.00 (191 each and
    2.00 of fees), the price at 200: +64.00 in all, +34.00 of it on the 4."""
    bank = _photo(client, quantity=6, unit_price=195)
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-02-02", "institution_id": bank, "asset_name": "Fondo Alfa",
        "symbol": "ALFA.MI", "quantity": 4, "unit_price": 191, "fees": 2, "currency": "EUR",
        "price_currency": "EUR"}))
    _priced("ALFA.MI", 200.0)
    row = _row(client)
    assert (row["book_value"], row["book_paid"], row["units_paid"]) == (1936.0, 766.0, 4.0)
    assert row["delta"] == pytest.approx(64.0, abs=1e-9)
    assert row["delta_paid"] == pytest.approx(34.0, abs=1e-9)
    assert row["cost_estimated"] is False, "a buy of the reader's own"


def test_a_recorded_cost_is_all_paid(client, market):
    _plan_buys(client, _photo(client, cost_basis=900))
    _priced("ALFA.MI", 110.0)
    row = _row(client)
    assert row["cost_known"] is True
    assert (row["book_paid"], row["units_paid"]) == (row["book_value"], row["quantity"])
    assert row["delta_paid"] == row["delta"]


def test_a_photograph_with_no_cost_and_nothing_bought_has_nothing_paid(client):
    _photo(client)
    _priced("ALFA.MI", 110.0)
    row = _row(client)
    assert (row["book_paid"], row["units_paid"], row["delta_paid"]) == (0.0, 0.0, 0.0)
    assert row["delta"] == 100.0


def test_a_row_with_no_units_says_no_units_paid(client):
    bank = _made(client.post("/api/institutions", json={"name": "Banca Beta"}))
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Lingotto", "asset_class": "commodity", "value": 500,
        "cost_basis": 400, "currency": "EUR"}))
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert (row["book_paid"], row["units_paid"], row["cost_known"]) == (400.0, None, True)


def test_units_photographed_with_no_value_and_no_cost_read_as_they_did(client):
    """Filed under STILL OPEN by brief AV: such units count as costing nothing,
    and the row says its cost is known once a buy joins them. The paid pool
    keeps that reading rather than changing it in passing. The API refuses
    such a row since brief BE; one written before is read so."""
    bank = _photo(client)
    with SessionLocal() as db:
        db.execute(text("UPDATE holdings SET unit_price = NULL, value = NULL"))
        db.commit()
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-02-02", "institution_id": bank, "asset_name": "Fondo Alfa",
        "symbol": "ALFA.MI", "quantity": 5, "unit_price": 100, "currency": "EUR",
        "price_currency": "EUR"}))
    row = _row(client)
    assert (row["book_value"], row["cost_known"]) == (500.0, True)
    assert (row["book_paid"], row["units_paid"]) == (500.0, 15.0)


def test_the_totals_say_how_much_of_the_book_was_paid(client, market):
    _plan_buys(client, _photo(client))
    body = client.get("/api/dashboard/portfolio").json()
    assert (body["total_book"], body["total_book_paid"]) == (1300.0, 300.0)


def test_an_outside_assistant_reads_the_part_paid(client, market):
    _plan_buys(client, _photo(client))
    server = build_server(engine.url.database)

    async def drive():
        async with Client(server, raise_exceptions=True) as c:
            return await c.call_tool("get_positions", {})

    body = anyio.run(drive).structured_content
    (row,) = body["positions"]
    assert (row["book_value"], row["book_paid"], row["units_paid"]) == (1300.0, 300.0, 3.0)
    assert "book_paid" in body["reading"]
