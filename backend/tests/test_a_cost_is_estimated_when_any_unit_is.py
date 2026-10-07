"""A position's cost is estimated when any unit behind it is.

A plan's buy is priced at the market close of its day and stored `estimated`,
not read off a broker's contract note. Until brief AI (2026-10-07) a position
born from such buys said its cost was not estimated ("every unit came from a
recorded fill"), and a photographed cost with plan buys on top said the same
of the whole blend: the figure was right, its provenance was not. Measured by
brief R on a test database, 2026-09-17: a position a monthly plan had built,
declared not estimated, every buy behind it estimated.

The rule: estimated while any unit held came from a buy still marked
estimated, or from a photographed cost that was itself derived; correcting the
buys clears it, and so does a walk that empties the position. Every name and
amount here is invented.
"""

from __future__ import annotations

import datetime

import pytest

from app import advisor, pac, prices
from app.database import SessionLocal

SITUATION = "2026-01-01"
FIRST_BUY = "2026-01-05"
CAUGHT_UP_TO = datetime.date(2026, 3, 10)  # three buys: 5 January, February, March


def _made(response) -> int:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.fixture
def market(monkeypatch):
    """Every close at 100.00 EUR, so a 300 EUR plan buys 3 units a month."""
    monkeypatch.setattr(
        prices, "get_price_on",
        lambda symbol, on: {"symbol": symbol, "price": 100.0, "as_of": on.isoformat()},
    )
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")


def _bank(client) -> int:
    return _made(client.post("/api/institutions", json={"name": "Banca Alfa"}))


def _photo(client, bank: int, **holding) -> None:
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Alfa", "asset_class": "fund_etf", "symbol": "ALFA.MI",
        "quantity": 10, "unit_price": 90, "currency": "EUR", **holding}))


def _plan_buys(client, bank: int) -> list[dict]:
    _made(client.post("/api/accumulation-plans", json={
        "name": "Piano Alfa", "amount": 300, "currency": "EUR", "frequency": "monthly",
        "start_date": FIRST_BUY, "source_institution_id": bank,
        "targets": [{"symbol": "ALFA.MI", "asset_name": "Fondo Alfa", "institution_id": bank}],
    }))
    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=CAUGHT_UP_TO)
    assert len(out["created"]) == 3, out["skipped"]
    buys = [t for t in client.get("/api/transactions").json() if t["kind"] == "buy"]
    assert all(t["estimated"] for t in buys)
    return buys


def _row(client) -> dict:
    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    return next(r for r in rows if r["symbol"] == "ALFA.MI")


def _correct(client, buy: dict) -> None:
    """The reader's gesture on an estimated row: the pencil, then Save. Any
    edit clears `estimated`."""
    body = {k: buy[k] for k in ("kind", "date", "institution_id", "asset_name", "symbol",
                                "asset_class", "quantity", "unit_price", "fees", "currency",
                                "price_currency")}
    r = client.put(f"/api/transactions/{buy['id']}", json={**body, "amount": buy["amount"]})
    assert r.status_code == 200, r.text
    assert r.json()["estimated"] is False


# --- Born from plan buys -------------------------------------------------------------


def test_a_position_born_from_plan_buys_says_its_cost_is_estimated(client, market):
    _plan_buys(client, _bank(client))
    row = _row(client)
    assert (row["quantity"], row["avg_cost"]) == (9.0, 100.0)
    assert row["cost_known"] is True
    assert row["cost_estimated"] is True


def test_correcting_every_plan_buy_clears_the_estimate_and_not_before(client, market):
    buys = _plan_buys(client, _bank(client))
    for buy in buys[:-1]:
        _correct(client, buy)
    assert _row(client)["cost_estimated"] is True, "one estimated buy is still behind the units"
    _correct(client, buys[-1])
    assert _row(client)["cost_estimated"] is False


def test_a_position_emptied_and_bought_again_by_hand_is_a_price_paid(client, market):
    bank = _bank(client)
    _plan_buys(client, bank)
    entry = {"institution_id": bank, "asset_name": "Fondo Alfa", "symbol": "ALFA.MI",
             "currency": "EUR", "price_currency": "EUR"}
    _made(client.post("/api/transactions", json={
        **entry, "kind": "sell", "date": "2026-04-01", "quantity": 9, "unit_price": 110}))
    _made(client.post("/api/transactions", json={
        **entry, "kind": "buy", "date": "2026-05-01", "quantity": 2, "unit_price": 120}))
    row = _row(client)
    assert (row["quantity"], row["avg_cost"]) == (2.0, 120.0)
    assert row["cost_estimated"] is False, "no unit bought by the plan is held any more"


# --- A photograph with plan buys on top -----------------------------------------------


def test_a_recorded_cost_with_plan_buys_on_top_is_estimated(client, market):
    bank = _bank(client)
    _photo(client, bank, cost_basis=850)
    _plan_buys(client, bank)
    row = _row(client)
    assert (row["quantity"], row["book_value"]) == (19.0, 1750.0)
    assert row["cost_known"] is True
    assert row["cost_estimated"] is True


def test_a_recorded_cost_with_a_real_buy_on_top_stays_a_price_paid(client):
    bank = _bank(client)
    _photo(client, bank, cost_basis=850)
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-02-01", "institution_id": bank, "asset_name": "Fondo Alfa",
        "symbol": "ALFA.MI", "quantity": 5, "unit_price": 95, "currency": "EUR",
        "price_currency": "EUR"}))
    row = _row(client)
    assert (row["cost_known"], row["cost_estimated"]) == (True, False)


def test_a_derived_photographed_cost_stays_estimated_under_real_buys(client):
    bank = _bank(client)
    _photo(client, bank, cost_basis=850, cost_estimated=True)
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-02-01", "institution_id": bank, "asset_name": "Fondo Alfa",
        "symbol": "ALFA.MI", "quantity": 5, "unit_price": 95, "currency": "EUR",
        "price_currency": "EUR"}))
    assert _row(client)["cost_estimated"] is True


def test_a_situation_started_from_the_last_one_keeps_the_estimate(client, market, monkeypatch):
    """"Start from the last one" copies the projected cost into the new
    photograph, and with it whether that cost is estimated: it copied "not
    estimated" for a blend of plan buys, and the provenance was gone for good."""
    bank = _bank(client)
    _photo(client, bank, cost_basis=850)
    _plan_buys(client, bank)
    monkeypatch.setattr(prices, "get_quotes", lambda symbols: {})
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots/prefilled",
                            json={"date": "2026-04-01"}))
    holding = next(h for h in client.get(f"/api/snapshots/{sid}/holdings").json()
                   if h["symbol"] == "ALFA.MI")
    assert (holding["quantity"], holding["cost_basis"]) == (19.0, 1750.0)
    assert holding["cost_estimated"] is True


# --- What the analyst and the chat are told -------------------------------------------


def test_the_chat_and_the_analyst_are_told_where_an_estimated_cost_came_from(client, market):
    _plan_buys(client, _bank(client))
    with SessionLocal() as db:
        chat, analyst = advisor.build_context(db), advisor.build_portfolio_context(db)
    said = (
        "cost ESTIMATED: some or all of it is a plan's buy priced at a market close, or a "
        "cost derived from a reported % return, not read off a contract note"
    )
    for context in (chat, analyst):
        line = next(x for x in context.splitlines() if "ALFA.MI" in x and "avg cost" in x)
        assert line.endswith(said), line
