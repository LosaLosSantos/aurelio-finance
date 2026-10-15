"""What the ledger paid before the latest situation, proposed and written on
the reader's press (brief AW, part 2).

The reader chose (2026-10-15) a one-time recovery shown before anything is
written: the Portfolio carries the walk's proposals (`paid_recovery`) and the
purchases a disagreeing situation left unread (`paid_unread`); a row's
proposal is written as its cost only when the reader accepts it, and once
declined it is never proposed again (a row of `settings`, deleted with its
row). Every name and figure here is invented.
"""

from __future__ import annotations

import pytest

from app import crud, dated, fx, prices
from app.database import SessionLocal

FIRST, SECOND, THIRD = "2026-03-02", "2026-05-04", "2026-07-01"
FUND = {"asset_name": "Fondo Gamma", "asset_class": "fund_etf", "symbol": "GAMMA.MI"}
OTHER = {"asset_name": "Fondo Delta", "asset_class": "fund_etf", "symbol": "DELTA.MI"}


def _made(response) -> dict:
    assert response.status_code in (200, 201, 204), response.text
    return response.json() if response.status_code != 204 else {}


@pytest.fixture
def the_day(monkeypatch):
    monkeypatch.setattr(dated, "today", lambda: "2026-10-15")


def _account(client, name: str = "Banca Gamma") -> int:
    return _made(client.post("/api/institutions", json={"name": name}))["id"]


def _situation(client, bank: int, date: str, *rows: dict) -> tuple[int, list[int]]:
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": date}))["id"]
    return sid, [
        _made(client.post(f"/api/snapshots/{sid}/holdings", json={"currency": "EUR", **row}))["id"]
        for row in rows
    ]


def _buy(client, bank: int, date: str, quantity: float, unit_price: float, fund=FUND) -> None:
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": date, "institution_id": bank, **fund, "quantity": quantity,
        "unit_price": unit_price, "currency": "EUR", "price_currency": "EUR"}))


def _carried_before_av(client, fund=FUND, name: str = "Banca Gamma") -> tuple[int, int]:
    """10 photographed at 100 with no cost, three buys of 100, then the row as
    the code before brief AV carried it: 13 x 110, no cost."""
    bank = _account(client, name)
    _situation(client, bank, FIRST, {**fund, "quantity": 10, "unit_price": 100})
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _buy(client, bank, date, 1, 100, fund)
    _, (latest,) = _situation(client, bank, SECOND, {**fund, "quantity": 13, "unit_price": 110})
    return bank, latest


def _portfolio(client) -> dict:
    return _made(client.get("/api/dashboard/portfolio"))


def _cache(symbol: str, price: float, currency: str = "EUR") -> None:
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {symbol: {"price": price, "as_of": "2026-10-14",
                                               "currency": currency}})


def test_the_portfolio_carries_the_proposal(client, the_day):
    _, latest = _carried_before_av(client)
    p = _portfolio(client)
    (item,) = p["paid_recovery"]
    assert (item["holding_id"], item["institution"], item["asset_name"], item["symbol"]) == (
        latest, "Banca Gamma", "Fondo Gamma", "GAMMA.MI")
    assert (item["paid"], item["units"], item["quantity"], item["since"]) == (300.0, 3.0, 13.0, FIRST)
    assert (item["situation_date"], item["row_paid"], item["row_units"]) == (SECOND, 0.0, 0.0)
    assert [(e["date"], e["kind"], e["amount"]) for e in item["entries"]] == [
        ("2026-03-16", "buy", 100.0), ("2026-04-01", "buy", 100.0), ("2026-04-15", "buy", 100.0)]
    assert p["paid_unread"] == []


def test_a_proposal_accepted_is_read_back_by_the_projection(client, the_day):
    _, latest = _carried_before_av(client)
    _cache("GAMMA.MI", 110.0)
    before = next(r for r in _portfolio(client)["rows"] if r["symbol"] == "GAMMA.MI")
    assert (before["book_paid"], before["delta"]) == (0.0, 0.0), "the 300.00 was in the value"

    row = _made(client.post(f"/api/holdings/{latest}/paid-recovery", json={"paid": 300.0, "units": 3.0}))
    assert (row["cost_basis"], row["cost_quantity"], row["cost_estimated"]) == (300.0, 3.0, False)
    p = _portfolio(client)
    after = next(r for r in p["rows"] if r["symbol"] == "GAMMA.MI")
    assert (after["book_value"], after["book_paid"], after["units_paid"]) == (1400.0, 300.0, 3.0)
    assert (after["delta"], after["delta_paid"]) == (30.0, 30.0), "the gain on the part paid"
    assert p["paid_recovery"] == [], "accepted: nothing left to propose"


def test_every_unit_paid_is_written_as_a_cost_for_all_of_them(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, {**FUND, "quantity": 10, "unit_price": 100, "cost_basis": 900})
    _buy(client, bank, "2026-04-01", 2, 100)
    _, (latest,) = _situation(client, bank, SECOND, {**FUND, "quantity": 12, "unit_price": 105})
    (item,) = _portfolio(client)["paid_recovery"]
    assert (item["paid"], item["units"], item["opening_paid"], item["opening_units"]) == (
        1100.0, 12.0, 900.0, 10.0)
    row = _made(client.post(f"/api/holdings/{latest}/paid-recovery",
                            json={"paid": item["paid"], "units": item["units"]}))
    assert (row["cost_basis"], row["cost_quantity"]) == (1100.0, None)


def test_accept_all_writes_every_row_or_none(client, the_day):
    _, gamma = _carried_before_av(client, FUND, "Banca Gamma")
    _, delta = _carried_before_av(client, OTHER, "Banca Delta")
    shown = {i["holding_id"]: i for i in _portfolio(client)["paid_recovery"]}
    assert set(shown) == {gamma, delta}

    stale = [{"holding_id": gamma, "paid": 300.0, "units": 3.0},
             {"holding_id": delta, "paid": 290.0, "units": 3.0}]
    refused = client.post("/api/paid-recovery", json={"rows": stale})
    assert refused.status_code == 409
    assert "Fondo Delta" in refused.json()["detail"] and "Reload the Portfolio" in refused.json()["detail"]
    with SessionLocal() as db:
        from app import models
        assert db.get(models.Holding, gamma).cost_basis is None, "one refused, none written"

    rows = _made(client.post("/api/paid-recovery", json={"rows": [
        {"holding_id": h, "paid": i["paid"], "units": i["units"]} for h, i in shown.items()]}))
    assert sorted((r["id"], r["cost_basis"], r["cost_quantity"]) for r in rows) == sorted(
        [(gamma, 300.0, 3.0), (delta, 300.0, 3.0)])
    assert _portfolio(client)["paid_recovery"] == []


def test_a_proposal_that_changed_is_refused_in_words(client, the_day):
    bank, latest = _carried_before_av(client)
    (item,) = _portfolio(client)["paid_recovery"]
    first = min((t for t in _made(client.get("/api/transactions")) if t["kind"] == "buy"),
                key=lambda t: t["date"])
    _made(client.put(f"/api/transactions/{first['id']}", json={
        "kind": "buy", "date": first["date"], "institution_id": bank, **FUND, "quantity": 1,
        "unit_price": 95, "amount": None, "currency": "EUR", "price_currency": "EUR"}))
    refused = client.post(f"/api/holdings/{latest}/paid-recovery",
                          json={"paid": item["paid"], "units": item["units"]})
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "What the ledger paid for Fondo Gamma changed since the page was loaded. Reload the "
        "Portfolio to see the figures before you accept them.")


def test_a_row_with_nothing_proposed_is_refused(client, the_day):
    bank = _account(client)
    _, (only,) = _situation(client, bank, FIRST, {**FUND, "quantity": 10, "unit_price": 100})
    for path in (f"/api/holdings/{only}/paid-recovery", f"/api/holdings/{only}/paid-recovery/decline"):
        refused = client.post(path, json={"paid": 1.0, "units": 1.0})
        assert refused.status_code == 409, path
        assert refused.json()["detail"].startswith("Nothing is proposed for Fondo Gamma any more")


def test_a_declined_row_is_not_proposed_again(client, the_day, monkeypatch):
    bank, latest = _carried_before_av(client)
    _made(client.post(f"/api/holdings/{latest}/paid-recovery/decline"))
    assert _portfolio(client)["paid_recovery"] == []
    with SessionLocal() as db:
        assert crud.declined_paid(db) == {latest}

    # A new situation started from the last one: nothing bought since the
    # declined one, and the declined purchases are not proposed on it either.
    monkeypatch.setattr(prices, "get_quotes", lambda symbols: {
        s: {"symbol": s, "price": 115.0, "as_of": THIRD} for s in symbols})
    _made(client.post(f"/api/institutions/{bank}/snapshots/prefilled", json={"date": THIRD}))
    assert _portfolio(client)["paid_recovery"] == []


@pytest.mark.parametrize("deleted", ["holding", "situation", "institution"])
def test_a_decline_goes_with_its_row(client, the_day, deleted):
    bank, latest = _carried_before_av(client)
    _made(client.post(f"/api/holdings/{latest}/paid-recovery/decline"))
    with SessionLocal() as db:
        from app import models
        situation = db.get(models.Holding, latest).snapshot_id
    path = {"holding": f"/api/holdings/{latest}", "situation": f"/api/snapshots/{situation}",
            "institution": f"/api/institutions/{bank}"}[deleted]
    assert client.delete(path).status_code == 204
    with SessionLocal() as db:
        assert crud.declined_paid(db) == set(), f"the key outlived its {deleted}"


def test_a_row_listed_in_another_currency_is_written_in_it(client, the_day, monkeypatch):
    """Stored in the currency the row is read in, as "Start from the last one"
    stores it, and read back as the same money."""
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {
        "2026-10-15": {"USD": 1.25}})
    usd = {**FUND, "symbol": "GAMMA.US", "currency": "USD"}
    _cache("GAMMA.US", 140.0, "USD")
    bank = _account(client)
    _situation(client, bank, FIRST, {**usd, "quantity": 10, "unit_price": 125})
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _made(client.post("/api/transactions", json={
            "kind": "buy", "date": date, "institution_id": bank, **usd, "quantity": 1,
            "unit_price": 100, "currency": "EUR", "price_currency": "EUR"}))
    _, (latest,) = _situation(client, bank, SECOND, {**usd, "quantity": 13, "unit_price": 140})
    (item,) = _portfolio(client)["paid_recovery"]
    assert (item["paid"], item["units"]) == (300.0, 3.0), "in the base"
    row = _made(client.post(f"/api/holdings/{latest}/paid-recovery",
                            json={"paid": 300.0, "units": 3.0}))
    assert (row["cost_basis"], row["cost_quantity"]) == (375.0, 3.0), "300.00 in dollars at 1.25"
    after = next(r for r in _portfolio(client)["rows"] if r["symbol"] == "GAMMA.US")
    assert after["book_paid"] == pytest.approx(300.0)


def test_no_rate_for_the_row_s_currency_is_refused_in_words(client, the_day, monkeypatch):
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {})
    chf = {**FUND, "symbol": "GAMMA.SW", "currency": "CHF"}
    _cache("GAMMA.SW", 140.0, "CHF")
    bank = _account(client)
    _situation(client, bank, FIRST, {**chf, "quantity": 10, "unit_price": 125})
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _made(client.post("/api/transactions", json={
            "kind": "buy", "date": date, "institution_id": bank, **chf, "quantity": 1,
            "unit_price": 100, "currency": "EUR", "price_currency": "EUR"}))
    _, (latest,) = _situation(client, bank, SECOND, {**chf, "quantity": 13, "unit_price": 140})
    (item,) = _portfolio(client)["paid_recovery"]
    refused = client.post(f"/api/holdings/{latest}/paid-recovery",
                          json={"paid": item["paid"], "units": item["units"]})
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("No exchange rate for CHF is known today")


def test_purchases_left_unread_reach_the_portfolio(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, {**FUND, "quantity": 10, "unit_price": 100})
    _buy(client, bank, "2026-04-01", 2, 100)
    _, (latest,) = _situation(client, bank, SECOND, {**FUND, "quantity": 13, "unit_price": 105})
    p = _portfolio(client)
    assert p["paid_recovery"] == []
    (left,) = p["paid_unread"]
    assert (left["holding_id"], left["institution"], left["situation_date"]) == (
        latest, "Banca Gamma", SECOND)
    assert (left["stated_units"], left["walked_units"], left["paid"], left["units"]) == (
        13.0, 12.0, 200.0, 2.0)
    assert (left["since"], left["purchases"], left["opening_paid"]) == (FIRST, 1, None)


def test_an_accepted_cost_for_every_unit_then_reads_as_typed(client, the_day):
    """Said in the plan: written for every unit and not estimated, it is the
    shape of a cost the reader typed, so a buy corrected behind it later is
    not proposed again."""
    bank = _account(client)
    _situation(client, bank, FIRST, {**FUND, "quantity": 10, "unit_price": 100, "cost_basis": 900})
    _buy(client, bank, "2026-04-01", 2, 100)
    _, (latest,) = _situation(client, bank, SECOND, {**FUND, "quantity": 12, "unit_price": 105})
    (item,) = _portfolio(client)["paid_recovery"]
    _made(client.post(f"/api/holdings/{latest}/paid-recovery",
                      json={"paid": item["paid"], "units": item["units"]}))
    buy = next(t for t in _made(client.get("/api/transactions")) if t["kind"] == "buy")
    _made(client.put(f"/api/transactions/{buy['id']}", json={
        "kind": "buy", "date": buy["date"], "institution_id": bank, **FUND, "quantity": 2,
        "unit_price": 98, "amount": None, "currency": "EUR", "price_currency": "EUR"}))
    assert _portfolio(client)["paid_recovery"] == []
