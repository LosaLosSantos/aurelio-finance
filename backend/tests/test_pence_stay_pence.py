"""A London price in pence stays in pence when the app learns its currency.

`prices._fetch_currency` upper-cased the code Yahoo names. London quotes some
listings in pence, "GBp", and others in pounds, "GBP", and the case of one
letter is a hundredfold (`fx._MINOR_EXACT`). Measured 2026-10-08 on two public
London listings quoted in pence, VOD.L and ISF.L: Yahoo names "GBp", and the
app learnt "GBP". This is how the price cache learns what a listing trades in:
through the "Refresh market prices" button, a plan's targets, and since brief
AJ the daily refresh of any held symbol the cache never priced.

Yahoo is faked under the real yfinance (`tests/yahoo_chart.py`), so the code is
read off yfinance's own `fast_info`, as the app reads it. Every symbol here is
invented.
"""

from __future__ import annotations

import pytest

from app import dated, models, prices
from app.database import SessionLocal
from tests.yahoo_chart import Listing, install

REAL_FETCH_CURRENCY = prices._fetch_currency
TODAY = "2026-10-08"


@pytest.fixture()
def yahoo_chart(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "_fetch_currency", REAL_FETCH_CURRENCY)
    return install(monkeypatch, tmp_path)


@pytest.mark.parametrize("named", ["GBp", "GBP", "USD", "ZAc"])
def test_a_listings_currency_is_kept_as_yahoo_spells_it(yahoo_chart, named):
    """Pence and South African cents keep their small letter; pounds and
    dollars were never touched."""
    yahoo_chart.listings["XLST.L"] = Listing(
        closes={"2026-10-07": 250.0}, currency=named, timezone="Europe/London"
    )

    assert prices._fetch_currency("XLST.L") == named


@pytest.mark.parametrize("named", ["", "N/A"])
def test_what_is_no_currency_code_is_no_currency(yahoo_chart, named):
    """Nothing, or anything that is not three letters, is not learnt as a
    currency: the listing stays one whose currency is not known."""
    yahoo_chart.listings["XLST.L"] = Listing(
        closes={"2026-10-07": 250.0}, currency=named, timezone="Europe/London"
    )

    assert prices._fetch_currency("XLST.L") is None


def test_the_daily_refresh_keeps_a_pence_listing_in_pence(client, yahoo_chart, monkeypatch):
    """A London fund quoted in pence, held and never priced: the catch-up's
    daily refresh prices it in the batch and learns its currency once. Before:
    it learnt GBP, and the position would have been converted as pounds."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    yahoo_chart.listings["XPEN.L"] = Listing(
        closes={"2026-10-07": 250.0}, currency="GBp", timezone="Europe/London"
    )
    monkeypatch.setattr(prices, "_fetch_recent_closes", lambda symbols: {"XPEN.L": (250.0, "2026-10-07")})
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-10-01"}).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Example London fund", "asset_class": "fund_etf", "symbol": "XPEN.L",
            "quantity": 10, "unit_price": 250, "currency": "GBp", "distribution_policy": "acc",
        },
    )
    assert r.status_code == 201, r.text

    assert client.post("/api/transactions/catch-up").status_code == 200

    with SessionLocal() as db:
        row = db.get(models.PriceCache, "XPEN.L")
        assert (row.price, row.as_of, row.currency) == (250.0, "2026-10-07", "GBp")
