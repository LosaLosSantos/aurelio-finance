"""The realized result, the dividends collected and the tax estimate span every
situation of an account (brief AW, part 4).

Measured at `8325ebd` (2026-10-15) on an invented household: a situation on
2026-03-02, then a buy, a sell, a share sold whole and a dividend of 12.00.
Read on 2026-06-15: realized +208.33, dividends 12.00, tax 54.17. After a
situation of 2026-07-01, started from the last one or typed by hand: all three
0.00, while the tax caveat still said "the whole recorded ledger". The totals
summed `positions.project`, which reads each account's ledger only after its
latest situation.

Each stretch between two situations is now read by `project` itself, as of the
date of the situation that ends it, from the one before it as stored, and
added to the totals; the rows keep their own window. What is dated on or
before an account's first situation is in that photograph and is not read.
Every name and figure here is invented.
"""

from __future__ import annotations

import pytest

from app import advisor, analytics, dated, prices
from app.database import SessionLocal

FUND = {"asset_name": "Fondo Epsilon", "symbol": "EPS.MI", "asset_class": "fund_etf"}
SHARE = {"asset_name": "Azione Epsilon", "symbol": "EPSA.MI", "asset_class": "equity"}
GOLD = {"asset_name": "Lingotto Epsilon", "asset_class": "commodity"}
BOND = {"asset_name": "Obbligazioni Epsilon", "symbol": "EPSB.MI", "asset_class": "bond"}
LATER = "2026-07-01"


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


def _entry(client, bank: int, kind: str, date: str, asset: dict, **figures) -> None:
    more = {} if kind == "close" else {"price_currency": "EUR"}
    _made(client.post("/api/transactions", json={
        "kind": kind, "date": date, "institution_id": bank, **asset, "currency": "EUR",
        **more, **figures}))


def _household(client, monkeypatch) -> int:
    monkeypatch.setattr(dated, "today", lambda: "2026-06-15")
    bank = _made(client.post("/api/institutions", json={"name": "Banca Epsilon"}))["id"]
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": "2026-03-02"}))["id"]
    for row in ({**FUND, "quantity": 20, "unit_price": 50, "cost_basis": 900},
                {**SHARE, "quantity": 10, "unit_price": 30, "cost_basis": 250}):
        _made(client.post(f"/api/snapshots/{sid}/holdings", json={**row, "currency": "EUR"}))
    _entry(client, bank, "buy", "2026-04-01", FUND, quantity=10, unit_price=55)
    _entry(client, bank, "sell", "2026-05-04", FUND, quantity=5, unit_price=60)
    _entry(client, bank, "sell", "2026-05-10", SHARE, quantity=10, unit_price=40)
    _entry(client, bank, "dividend", "2026-06-01", FUND, quantity=25, unit_price=0.48)
    _made(client.put("/api/settings/tax", json={
        "country": None, "capital_gains_rate": 26, "dividend_withholding_rate": 26}))
    return bank


def _totals() -> dict:
    with SessionLocal() as db:
        p = analytics.compute_portfolio(db)
    t = p["tax_estimate"]
    return {"realized": round(p["total_realized"], 2), "dividends": round(p["total_dividends"], 2),
            "tax": None if t["total"] is None else round(t["total"], 2)}


def _later_situation(client, monkeypatch, bank: int, how: str) -> None:
    monkeypatch.setattr(dated, "today", lambda: LATER)
    if how == "started from the last one":
        monkeypatch.setattr(prices, "get_quotes", lambda symbols: {
            s: {"symbol": s, "price": 58.0, "as_of": "2026-06-30"} for s in symbols})
        _made(client.post(f"/api/institutions/{bank}/snapshots/prefilled", json={"date": LATER}))
    else:
        sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": LATER}))["id"]
        _made(client.post(f"/api/snapshots/{sid}/holdings", json={
            **FUND, "quantity": 25, "unit_price": 58, "currency": "EUR"}))
    monkeypatch.setattr(dated, "today", lambda: "2026-07-15")


@pytest.mark.parametrize("how", ["started from the last one", "typed by hand"])
def test_a_later_situation_keeps_what_was_realized_and_collected(client, monkeypatch, how):
    bank = _household(client, monkeypatch)
    before = _totals()
    assert before == {"realized": 208.33, "dividends": 12.0, "tax": 54.17}
    _later_situation(client, monkeypatch, bank, how)
    assert _totals() == before, "a new situation took all three to 0.00"


def test_a_close_by_name_and_a_position_born_between_situations_stay(client, monkeypatch):
    bank = _household(client, monkeypatch)
    sid = _made(client.get(f"/api/institutions/{bank}/snapshots"))[0]["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        **GOLD, "value": 400, "cost_basis": 350, "currency": "EUR"}))
    _entry(client, bank, "close", "2026-05-20", GOLD, amount=430)
    _entry(client, bank, "buy", "2026-04-10", BOND, quantity=2, unit_price=100)
    _entry(client, bank, "sell", "2026-06-10", BOND, quantity=2, unit_price=120)
    assert _totals()["realized"] == 328.33, "+80.00 the gold, +40.00 the bonds"
    _later_situation(client, monkeypatch, bank, "started from the last one")
    assert _totals()["realized"] == 328.33


def test_a_dividend_before_an_account_s_first_situation_is_not_read(client, monkeypatch):
    bank = _household(client, monkeypatch)
    _entry(client, bank, "dividend", "2026-02-15", FUND, quantity=20, unit_price=0.25)
    _later_situation(client, monkeypatch, bank, "started from the last one")
    assert _totals()["dividends"] == 12.0, "the 5.00 is in the first situation's photograph"
    with SessionLocal() as db:
        caveats = analytics.compute_portfolio(db)["tax_estimate"]["caveats"]
    assert (
        "It covers the ledger from each account's first situation on, not a tax year: what is "
        "dated on or before an account's first situation is in that situation and is not "
        "read. Nothing here carries losses forward or offsets them against gains across years."
    ) in caveats
    assert not any("whole recorded ledger" in c for c in caveats)


def test_an_entry_on_a_situation_s_date_is_counted_once(client, monkeypatch):
    """In the stretch that ends on its date, as `events_after`'s (anchor, day]
    implies, and not again after it."""
    bank = _household(client, monkeypatch)
    _entry(client, bank, "sell", LATER, FUND, quantity=1, unit_price=59)
    monkeypatch.setattr(dated, "today", lambda: LATER)
    assert _totals()["realized"] == 219.0, "+10.67 on the day, before any later situation"
    _later_situation(client, monkeypatch, bank, "started from the last one")
    assert _totals()["realized"] == 219.0


def test_an_account_with_no_situation_is_counted_once(client, monkeypatch):
    _household(client, monkeypatch)
    other = _made(client.post("/api/institutions", json={"name": "Banca Zeta"}))["id"]
    _entry(client, other, "buy", "2026-04-01", BOND, quantity=2, unit_price=100)
    _entry(client, other, "sell", "2026-05-01", BOND, quantity=2, unit_price=110)
    assert _totals()["realized"] == 228.33


def test_no_total_moves_on_a_proposal(client, monkeypatch):
    """Each earlier stretch opens at its situation as stored, never at the
    walk's carried pool: a total must not move on a proposal the reader has not
    accepted, nor on one accepted on the latest row."""
    monkeypatch.setattr(dated, "today", lambda: "2026-10-14")
    bank = _made(client.post("/api/institutions", json={"name": "Banca Epsilon"}))["id"]

    def situation(date: str, quantity: float, price: float) -> int:
        sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": date}))["id"]
        return _made(client.post(f"/api/snapshots/{sid}/holdings", json={
            **FUND, "quantity": quantity, "unit_price": price, "currency": "EUR"}))["id"]

    situation("2026-05-04", 10, 100)
    for date in ("2026-06-01", "2026-07-01", "2026-08-03"):
        _entry(client, bank, "buy", date, FUND, quantity=1, unit_price=100)
    situation("2026-08-20", 13, 110)  # as the code before brief AV carried it
    _entry(client, bank, "sell", "2026-09-01", FUND, quantity=2, unit_price=120)
    latest = situation("2026-10-10", 11, 115)

    with SessionLocal() as db:
        p = analytics.compute_portfolio(db)
    pending = (round(p["total_realized"], 2), round(p["total_realized_movement"], 2))
    assert pending == (0.0, 20.0), "the sell read against the situation as stored"
    (item,) = p["paid_recovery"]
    _made(client.post(f"/api/holdings/{latest}/paid-recovery",
                      json={"paid": item["paid"], "units": item["units"]}))
    with SessionLocal() as db:
        p = analytics.compute_portfolio(db)
    assert (round(p["total_realized"], 2), round(p["total_realized_movement"], 2)) == pending


def test_the_chat_s_total_lines_say_both_windows(client, monkeypatch):
    bank = _household(client, monkeypatch)
    _later_situation(client, monkeypatch, bank, "started from the last one")
    with SessionLocal() as db:
        ctx = advisor.build_context(db)
    window = "since each account's first situation; each row's own figure since its situation"
    assert f"- TOTAL realized P/L ({window}): +208.33" in ctx
    assert f"- TOTAL dividends collected ({window}): 12.00" in ctx
