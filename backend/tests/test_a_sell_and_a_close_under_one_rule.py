"""A sell's and a close's result under one rule (brief AV, part 2).

Measured on the demo with an invented fund (2026-10-14): a photographed row
with no recorded cost, sold whole, realized +130.00 and was taxed on it; the
same row closed for the same proceeds realized 0.00. And the close of a
photographed row was never walked: with a cost recorded and 300.00 bought
since, the close realized +530.00 where the sale realized +230.00; a dividend
before it left the totals; a buy after it reached no row.

The rule the reader chose, (c): what a disposal realizes on the units PAID for
is a gain or a loss (`realized_pl`, the tax's base); what it realizes on a
situation's value with no purchase price on record is movement
(`realized_movement`), said beside it and never taxed. Their sum is the whole
result at average cost. Every name and figure here is invented.
"""

from __future__ import annotations

import pytest

from app import advisor, analytics, crud
from app.database import SessionLocal

SITUATION = "2026-01-01"


def _made(response) -> int:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _photo(client, **holding) -> int:
    bank = _made(client.post("/api/institutions", json={"name": "Banca Alfa"}))
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Alfa", "asset_class": "fund_etf", "symbol": "ALFA.MI",
        "quantity": 10, "unit_price": 100, "currency": "EUR", **holding}))
    return bank


def _entry(client, bank: int, kind: str, date: str, **figures) -> None:
    body = {"kind": kind, "date": date, "institution_id": bank, "asset_name": "Fondo Alfa",
            "symbol": "ALFA.MI", "currency": "EUR", **figures}
    if kind != "close":
        body["price_currency"] = "EUR"
    _made(client.post("/api/transactions", json=body))


def _buys(client, bank: int, price: float = 100) -> None:
    for day in ("2026-02-02", "2026-03-02", "2026-04-01"):
        _entry(client, bank, "buy", day, quantity=1, unit_price=price)


def _portfolio(client) -> dict:
    return client.get("/api/dashboard/portfolio").json()


def _row(client, symbol: str = "ALFA.MI") -> dict:
    return next(r for r in _portfolio(client)["rows"] if r["symbol"] == symbol)


# --- The close is walked ---------------------------------------------------------------


def test_a_close_measures_against_everything_bought_since_the_photograph(client):
    bank = _photo(client, cost_basis=900)
    _buys(client, bank)
    _entry(client, bank, "close", "2026-05-04", amount=1430)
    row = _row(client)
    assert (row["realized_pl"], row["realized_movement"]) == (230.0, 0.0), (
        "1,430 against the 900 recorded and the 300 paid since; it said +530.00"
    )
    assert (row["quantity"], row["book_value"], row["closed_on"]) == (0.0, 0.0, "2026-05-04")


def test_a_close_that_names_the_row_without_its_ticker_is_walked_too(client):
    """A close may carry no ticker; it settles the row it names. Matched by
    name as before, and now walked with the buys before it."""
    bank = _photo(client, cost_basis=900)
    _buys(client, bank)
    _made(client.post("/api/transactions", json={
        "kind": "close", "date": "2026-05-04", "institution_id": bank,
        "asset_name": "Fondo Alfa", "amount": 1430, "currency": "EUR"}))
    row = _row(client)
    assert (row["realized_pl"], row["quantity"], row["closed_on"]) == (230.0, 0.0, "2026-05-04")


def test_a_dividend_before_the_close_stays_in_the_totals(client):
    bank = _photo(client, cost_basis=900)
    _entry(client, bank, "dividend", "2026-03-16", quantity=10, unit_price=2)
    _entry(client, bank, "close", "2026-05-04", amount=1100)
    body = _portfolio(client)
    assert body["total_dividends"] == 20.0, "it fell to 0.00 once the row was closed"
    assert body["rows"][0]["dividends"] == 20.0


def test_a_buy_after_the_close_is_held_and_the_row_reads_open(client):
    bank = _photo(client)
    _entry(client, bank, "close", "2026-05-04", amount=1100)
    _entry(client, bank, "buy", "2026-06-01", quantity=2, unit_price=110)
    row = _row(client)
    assert (row["quantity"], row["book_value"]) == (2.0, 220.0), "it reached no row"
    assert row["closed_on"] is None, "units are held again: not 'disposed of'"
    assert row["realized_movement"] == 100.0
    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 220.0


def test_a_position_born_in_the_ledger_reads_open_once_bought_again(client):
    bank = _made(client.post("/api/institutions", json={"name": "Banca Beta"}))
    _entry(client, bank, "buy", "2026-02-02", quantity=3, unit_price=100)
    _entry(client, bank, "close", "2026-03-02", amount=330)
    assert _row(client)["closed_on"] == "2026-03-02"
    _entry(client, bank, "buy", "2026-04-01", quantity=2, unit_price=110)
    row = _row(client)
    assert (row["quantity"], row["closed_on"]) == (2.0, None), (
        "it read 'disposed of' with 2 units held"
    )
    assert row["realized_pl"] == 30.0


# --- The rule: a gain on the units paid for, movement on the rest -------------------------


@pytest.mark.parametrize("kind,figures", [
    ("sell", {"quantity": 13, "unit_price": 110}),
    ("close", {"amount": 1430}),
])
def test_a_blend_sold_or_closed_gives_the_same_answer(client, kind, figures):
    """10 photographed at 100 with no cost and 3 bought at 100: 1,430 for the
    13 is +130.00 at average cost, +30.00 of it on the 3 paid for."""
    bank = _photo(client)
    _buys(client, bank)
    _entry(client, bank, kind, "2026-05-04", **figures)
    row = _row(client)
    assert row["realized_pl"] == pytest.approx(30.0, abs=1e-9)
    assert row["realized_movement"] == pytest.approx(100.0, abs=1e-9)


def test_the_gain_is_the_bought_units_own(client):
    """6 at 195 photographed with no cost, 4 bought for 766.00, all 10 sold at
    200: +34.00 on the 4, +30.00 movement on the 6."""
    bank = _photo(client, quantity=6, unit_price=195)
    _entry(client, bank, "buy", "2026-02-02", quantity=4, unit_price=191, fees=2)
    _entry(client, bank, "sell", "2026-05-04", quantity=10, unit_price=200)
    row = _row(client)
    assert row["realized_pl"] == pytest.approx(34.0, abs=1e-9)
    assert row["realized_movement"] == pytest.approx(30.0, abs=1e-9)


def test_units_bought_above_today_price_are_a_loss_whatever_the_photograph_did(client):
    bank = _photo(client)
    _entry(client, bank, "buy", "2026-02-02", quantity=3, unit_price=120)
    _entry(client, bank, "sell", "2026-05-04", quantity=13, unit_price=110)
    row = _row(client)
    assert row["realized_pl"] == pytest.approx(-30.0, abs=1e-9)
    assert row["realized_movement"] == pytest.approx(100.0, abs=1e-9)


def test_a_photograph_with_no_cost_realizes_only_movement(client):
    bank = _photo(client)
    _entry(client, bank, "sell", "2026-05-04", quantity=4, unit_price=130)
    row = _row(client)
    assert (row["realized_pl"], row["realized_movement"]) == (0.0, 120.0)


def test_a_cost_recorded_realizes_only_a_gain(client):
    bank = _photo(client, cost_basis=800)
    _entry(client, bank, "sell", "2026-05-04", quantity=4, unit_price=130)
    row = _row(client)
    assert (row["realized_pl"], row["realized_movement"]) == (200.0, 0.0)


def test_a_sale_of_more_units_than_held_splits_its_proceeds_by_the_pools(client):
    """Clamped as before: 15 sold from 13 held. Their 1,650 is split by the
    units' shares, 3 of 13 paid for."""
    bank = _photo(client)
    _buys(client, bank)
    _entry(client, bank, "sell", "2026-05-04", quantity=15, unit_price=110)
    row = _row(client)
    assert row["realized_pl"] == pytest.approx(1650 * 3 / 13 - 300, abs=1e-9)
    assert row["realized_pl"] + row["realized_movement"] == pytest.approx(350.0, abs=1e-9)


def test_a_disposal_with_no_unit_left_follows_what_the_position_was(client):
    bank = _photo(client)
    _entry(client, bank, "sell", "2026-05-04", quantity=10, unit_price=110)
    _entry(client, bank, "sell", "2026-05-05", quantity=1, unit_price=110)
    row = _row(client)
    assert (row["realized_pl"], row["realized_movement"]) == (0.0, 210.0), (
        "nothing of it was paid, so the stray proceeds are movement too"
    )


def test_units_with_no_value_and_no_cost_read_as_they_did(client):
    """Filed under STILL OPEN: such units count as costing nothing. The rule
    keeps that reading: their sale is a gain, as it was."""
    bank = _photo(client, unit_price=None)
    _entry(client, bank, "buy", "2026-02-02", quantity=5, unit_price=100)
    _entry(client, bank, "sell", "2026-05-04", quantity=15, unit_price=110)
    row = _row(client)
    assert (row["realized_pl"], row["realized_movement"]) == (1150.0, 0.0)


@pytest.mark.parametrize("holding,proceeds,expected", [
    ({"value": 400, "cost_basis": 350}, 430, (80.0, 0.0)),
    ({"value": 400}, 430, (0.0, 30.0)),
    ({"value": 400, "cost_basis": 0}, 50, (50.0, 0.0)),
    ({"value": 0}, 50, (0.0, 50.0)),
])
def test_a_row_with_no_units_is_paid_all_or_nothing(client, holding, proceeds, expected):
    bank = _made(client.post("/api/institutions", json={"name": "Banca Gamma"}))
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Lingotto", "asset_class": "commodity", "currency": "EUR", **holding}))
    _made(client.post("/api/transactions", json={
        "kind": "close", "date": "2026-05-04", "institution_id": bank,
        "asset_name": "Lingotto", "amount": proceeds, "currency": "EUR"}))
    row = _portfolio(client)["rows"][0]
    assert (row["realized_pl"], row["realized_movement"]) == expected
    assert row["closed_on"] == "2026-05-04"


# --- The tax follows ----------------------------------------------------------------------


def _rates(client) -> None:
    r = client.put("/api/settings/tax", json={
        "country": None, "capital_gains_rate": 26, "dividend_withholding_rate": 26})
    assert r.status_code == 200, r.text


def test_the_tax_is_estimated_on_the_gain_and_names_the_movement(client):
    _rates(client)
    bank = _photo(client)
    _buys(client, bank)
    _entry(client, bank, "close", "2026-05-04", amount=1430)
    body = _portfolio(client)
    assert body["total_realized"] == pytest.approx(30.0, abs=1e-9)
    assert body["total_realized_movement"] == pytest.approx(100.0, abs=1e-9)
    est = body["tax_estimate"]
    assert est["taxable_gain"] == pytest.approx(30.0, abs=1e-9)
    assert est["capital_gains_tax"] == pytest.approx(7.8, abs=1e-9)
    assert est["realized_movement"] == pytest.approx(100.0, abs=1e-9)
    assert est["total"] == pytest.approx(7.8, abs=1e-9), "kept, with the movement said beside it"
    assert any("no rate is applied to it" in c for c in est["caveats"])


def test_the_chat_never_reads_the_total_without_the_movement(client):
    _rates(client)
    bank = _photo(client)
    _buys(client, bank)
    _entry(client, bank, "close", "2026-05-04", amount=1430)
    with SessionLocal() as db:
        lines = advisor._render_tax(analytics.compute_portfolio(db)["tax_estimate"])
    total = next(line for line in lines if "estimated total" in line)
    assert total == (
        "  - estimated total: 7.80 (it leaves out any tax on the movement of +100.00 above, "
        "which no rate can be applied to)"
    )
    assert (
        "  - realized movement +100.00 on situations' values with no purchase price on "
        "record: NOT a gain, and no rate is applied to it"
    ) in lines


def test_with_no_rate_the_chat_reads_the_movement_apart(client):
    bank = _photo(client)
    _buys(client, bank)
    _entry(client, bank, "close", "2026-05-04", amount=1430)
    with SessionLocal() as db:
        (line,) = advisor._render_tax(analytics.compute_portfolio(db)["tax_estimate"])
    assert "The realized result is +30.00 on the units paid for" in line
    assert "A further +100.00 realized on situations' values" in line


def test_the_row_and_the_totals_read_by_the_chat_say_the_movement(client):
    bank = _photo(client)
    _buys(client, bank)
    _entry(client, bank, "sell", "2026-05-04", quantity=6.5, unit_price=110)
    with SessionLocal() as db:
        ctx = advisor.build_context(db)
    assert (
        "realized P/L +15.00 on the units paid for, and movement +50.00 on a situation's "
        "value with no purchase price on record (NOT profit)"
    ) in ctx
    assert (
        "- TOTAL realized P/L (since each account's first situation; each row's own figure "
        "since its situation): +15.00 on the units paid for; realized movement +50.00"
    ) in ctx


def test_a_position_all_paid_keeps_its_result_to_the_bit(client):
    """All of it paid, as every position was read before brief AV: the gain is
    the whole result, computed as `replay` always did (proceeds less the units
    sold at the average), and the movement is exactly zero."""
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {"ALFA.MI": {"price": 130.0, "as_of": "2026-05-04",
                                                  "currency": "EUR"}})
    bank = _photo(client, cost_basis=900)
    _entry(client, bank, "sell", "2026-05-04", quantity=3.3, unit_price=127.31)
    (sell,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "sell"]
    row = _row(client)
    assert row["realized_movement"] == 0.0
    assert row["realized_pl"] == sell["amount"] - 3.3 * (900.0 / 10)
