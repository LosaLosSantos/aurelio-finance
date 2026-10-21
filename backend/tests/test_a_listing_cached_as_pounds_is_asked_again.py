"""A listing the price cache learnt as pounds is asked about once more.

Brief AK, 2026-10-08: `prices._fetch_currency` upper-cased the currency Yahoo
names, so a London listing quoted in pence ("GBp") was learnt as pounds
("GBP"), and a position priced from it is valued a hundredfold. `2fb9f7b`
keeps Yahoo's spelling from then on, but a listing's currency is learnt once:
measured at `c61e5bc` (brief BE), a row cached as GBP stayed GBP through a
catch-up and a Portfolio load, and Yahoo was asked the currency of nothing.
Now the day's refresh asks once more about each symbol cached as GBP, and the
answer's spelling wins. Every ticker here is invented.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app import crud, dated, models, prices
from app.database import SessionLocal

PENCE, POUNDS = "ZZPEN.L", "ZZPND.L"
YAHOO_SAYS = {PENCE: "GBp", POUNDS: "GBP"}


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


@pytest.fixture()
def asked(client, monkeypatch) -> list[str]:
    """Both listings held, cached as GBP yesterday; Yahoo prices both and,
    asked, names each one's currency."""
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {s: {"price": 250.0, "as_of": "2026-10-20", "currency": "GBP"}
                                      for s in (PENCE, POUNDS)})
        db.execute(text("UPDATE price_cache SET fetched_at = '2026-10-20T12:00:00+00:00'"))
        db.commit()
    bank = _made(client.post("/api/institutions", json={"name": "Broker Zeta"}))["id"]
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": "2026-10-01"}))["id"]
    for symbol in (PENCE, POUNDS):
        _made(client.post(f"/api/snapshots/{sid}/holdings", json={
            "asset_name": f"Azione {symbol}", "asset_class": "equity", "symbol": symbol,
            "quantity": 10, "unit_price": 248, "currency": "GBP"}))
    seen: list[str] = []

    def currency(symbol):
        seen.append(symbol)
        return YAHOO_SAYS.get(symbol)

    monkeypatch.setattr(prices, "_fetch_currency", currency)
    monkeypatch.setattr(prices, "_fetch_recent_closes",
                        lambda symbols: {s: (251.0, dated.today()) for s in symbols})
    monkeypatch.setattr(dated, "today", lambda: "2026-10-21")
    return seen


def _cached(symbol: str) -> str | None:
    with SessionLocal() as db:
        return db.get(models.PriceCache, symbol).currency


def test_a_pence_listing_cached_as_pounds_learns_its_pence(client, asked):
    _made(client.post("/api/transactions/catch-up"))

    assert _cached(PENCE) == "GBp"
    assert _cached(POUNDS) == "GBP", "a listing quoted in pounds stays in pounds"
    assert sorted(asked) == [PENCE, POUNDS]


def test_each_is_asked_once_and_not_on_the_days_after(client, monkeypatch, asked):
    _made(client.post("/api/transactions/catch-up"))
    _made(client.post("/api/transactions/catch-up"))
    monkeypatch.setattr(dated, "today", lambda: "2026-10-22")
    with SessionLocal() as db:
        db.execute(text("UPDATE price_cache SET fetched_at = '2026-10-21T12:00:00+00:00'"))
        db.commit()

    _made(client.post("/api/transactions/catch-up"))

    assert sorted(asked) == [PENCE, POUNDS]


def test_a_listing_yahoo_does_not_name_is_asked_at_its_next_refresh(client, monkeypatch, asked):
    monkeypatch.setitem(YAHOO_SAYS, PENCE, None)
    _made(client.post("/api/transactions/catch-up"))
    assert _cached(PENCE) == "GBP", "nothing learnt, nothing replaced"
    monkeypatch.setitem(YAHOO_SAYS, PENCE, "GBp")
    monkeypatch.setattr(dated, "today", lambda: "2026-10-22")
    with SessionLocal() as db:
        db.execute(text("UPDATE price_cache SET fetched_at = '2026-10-21T12:00:00+00:00'"))
        db.commit()

    _made(client.post("/api/transactions/catch-up"))

    assert _cached(PENCE) == "GBp"
    assert asked.count(PENCE) == 2
