"""Prices module + endpoints. The network is monkeypatched — tests never call
Yahoo or OpenFIGI (so they're fast and CI-safe)."""

from __future__ import annotations

import datetime

import pytest

from app import models, prices
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()


def test_get_quote_shapes_and_rounds(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_recent_close", lambda s: (162.33949, "EUR", "2026-06-12"))
    monkeypatch.setattr(prices, "_fetch_name", lambda s: "Vanguard FTSE All-World")
    assert prices.get_quote("VWCE.MI", "EUR") == {
        "symbol": "VWCE.MI",
        "name": "Vanguard FTSE All-World",
        "price": 162.3395,
        "currency": "EUR",
        "as_of": "2026-06-12",
    }


def test_get_quote_empty_symbol_raises():
    with pytest.raises(prices.PriceError):
        prices.get_quote("   ", "EUR")


def test_resolve_isin_dedupes_and_maps(monkeypatch):
    monkeypatch.setattr(
        prices,
        "_fetch_openfigi",
        lambda isin: [
            {"ticker": "VWRA", "exchCode": "LN", "name": "VANG FTSE AW", "securityType": "ETP"},
            {"ticker": "VWRA", "exchCode": "LN", "name": "VANG FTSE AW", "securityType": "ETP"},
            {"ticker": "VWCE", "exchCode": "GY", "name": "VANG FTSE AW", "securityType": "ETP"},
        ],
    )
    out = prices.resolve_isin("IE00BK5BQT80")
    assert [s["ticker"] for s in out] == ["VWRA", "VWCE"]
    assert out[0]["exchange"] == "LN"


def test_quote_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        prices,
        "get_quote",
        lambda s, base: {"symbol": s, "price": 100.0, "currency": "EUR", "as_of": "2026-06-12"},
    )
    r = client.get("/api/prices/quote", params={"symbol": "AAPL"})
    assert r.status_code == 200 and r.json()["price"] == 100.0


def test_quote_endpoint_propagates_price_error_as_502(client, monkeypatch):
    def boom(_s, _base):
        raise prices.PriceError("no data")

    monkeypatch.setattr(prices, "get_quote", boom)
    assert client.get("/api/prices/quote", params={"symbol": "NOPE"}).status_code == 502


def _qty_holding(client, **extra) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    payload = {"currency": "EUR", 
        "asset_name": "iShares World",
        "asset_class": "equity",
        "symbol": "VWCE.MI",
        "quantity": 10,
        "unit_price": 100,
        **extra,
    }
    return client.post(f"/api/snapshots/{sid}/holdings", json=payload).json()["id"]


def test_refresh_price_updates_price_but_never_the_recorded_value(client, monkeypatch):
    """Refreshing a price must leave the snapshot's recorded value alone: the
    snapshot is a dated photograph, and rewriting it with today's market price
    silently re-dates the record (and collapses P/L vs recorded to zero)."""
    hid = _qty_holding(client, distribution_policy="acc")
    monkeypatch.setattr(
        prices,
        "get_quote",
        lambda s, base: {"symbol": s, "price": 120.0, "currency": "EUR", "as_of": "2026-06-12"},
    )
    body = client.post(f"/api/holdings/{hid}/refresh-price").json()
    assert body["unit_price"] == 120.0
    assert body["value"] == 1000.0  # unchanged: 10 units at the recorded 100
    assert body["distribution_policy"] == "acc"  # round-trips through the API


def test_refresh_price_without_symbol_is_400(client):
    iid = client.post("/api/institutions", json={"name": "X"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    hid = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Misc", "asset_class": "other", "value": 500, "currency": "EUR"},
    ).json()["id"]
    assert client.post(f"/api/holdings/{hid}/refresh-price").status_code == 400


def test_refresh_price_missing_holding_is_404(client):
    assert client.post("/api/holdings/999/refresh-price").status_code == 404


def test_quote_carries_the_instrument_name(client, monkeypatch):
    """The name is what catches a ticker pointing at the wrong fund: a wrong
    ticker still returns a believable price, so the price alone proves nothing."""
    monkeypatch.setattr(prices, "_fetch_recent_close", lambda s: (101.25, "EUR", "2026-08-22"))
    monkeypatch.setattr(
        prices, "_fetch_name", lambda s: "iShares Core MSCI World UCITS ETF USD (Acc)"
    )
    body = client.get("/api/prices/quote", params={"symbol": "EUNL.DE"}).json()
    assert body["name"] == "iShares Core MSCI World UCITS ETF USD (Acc)"
    assert body["price"] == 101.25


def test_a_missing_name_never_withholds_the_price(client, monkeypatch):
    monkeypatch.setattr(prices, "_fetch_recent_close", lambda s: (101.25, "EUR", "2026-08-22"))

    def boom(_s):
        raise RuntimeError("name lookup down")

    monkeypatch.setattr(prices, "_fetch_name", boom)
    body = client.get("/api/prices/quote", params={"symbol": "EUNL.DE"}).json()
    assert body["price"] == 101.25 and body["name"] is None


def test_a_coin_name_resolves_to_a_pair():
    """A coin has no price until you say "priced in what", so 'Bitcoin' is not
    a symbol. Typing the name people actually know must still work."""
    assert prices.resolve_symbol("Bitcoin", "EUR") == "BTC-EUR"
    assert prices.resolve_symbol("BTC", "EUR") == "BTC-EUR"
    assert prices.resolve_symbol("  ethereum ", "EUR") == "ETH-EUR"
    assert prices.resolve_symbol("Bitcoin", "USD") == "BTC-USD"


def test_resolution_never_hijacks_a_real_ticker():
    """The failure mode to avoid: an alias quietly stealing an equity's ticker
    and pricing a different instrument. Anything already shaped like a symbol
    passes through untouched."""
    for sym in ["VWCE.MI", "KO", "BTC-USD", "OR.PA", "LINK", "DOT", "ADA"]:
        assert prices.resolve_symbol(sym, "EUR") == sym


def test_quote_reports_the_symbol_it_resolved_to(client, monkeypatch):
    """The stored symbol must become the canonical pair, so the position still
    prices next time without the name lookup."""
    monkeypatch.setattr(prices, "_fetch_recent_close", lambda s: (65750.0, "EUR", "2026-08-22"))
    monkeypatch.setattr(prices, "_fetch_name", lambda s: "Bitcoin EUR")
    body = client.get("/api/prices/quote", params={"symbol": "Bitcoin"}).json()
    assert body["symbol"] == "BTC-EUR"


def test_a_coin_with_no_base_pair_falls_back_to_dollars(monkeypatch):
    """Yahoo does not quote every coin in EUR. A position priced in dollars and
    converted by the FX layer beats an unpriced one."""
    seen = []

    def fetch(symbol):
        seen.append(symbol)
        if symbol.endswith("-EUR"):
            raise prices.PriceError("no EUR pair")
        return (1.23, "USD", "2026-08-22")

    monkeypatch.setattr(prices, "_fetch_recent_close", fetch)
    monkeypatch.setattr(prices, "_fetch_name", lambda s: "Stellar USD")
    q = prices.get_quote("stellar", "EUR")
    assert seen == ["XLM-EUR", "XLM-USD"]
    assert q["symbol"] == "XLM-USD" and q["currency"] == "USD"


# --- Telling "your ticker is wrong" from "nobody answered" -------------------


def _empty(_symbol, *a, **k):
    """What yfinance returns for a bad ticker AND for a dead network alike."""
    raise prices.PriceError("unused")


def test_an_outage_does_not_blame_the_symbol(monkeypatch):
    """The whole point. Offline, VWCE.MI is still correct, and telling someone
    to add an exchange suffix it already has sends them to change something
    that was right."""
    prices._reset_reachability()
    monkeypatch.setattr(prices, "_fetch_probe", lambda s: False)  # nothing answers
    err = prices._no_data("VWCE.MI")
    assert isinstance(err, prices.MarketUnreachable)
    assert "may well be correct" in str(err)
    assert "check the ticker" not in str(err)


def test_a_reachable_market_does_blame_the_symbol(monkeypatch):
    """If another lamp lights, the bulb is dead: the market answered, so the
    symbol really is the problem."""
    prices._reset_reachability()
    monkeypatch.setattr(prices, "_fetch_probe", lambda s: True)
    err = prices._no_data("28IT.MI")
    assert not isinstance(err, prices.MarketUnreachable)
    assert "check the ticker" in str(err)


def test_the_probe_cost_does_not_grow_with_the_portfolio(monkeypatch):
    """The verdict is cached, so a portfolio-wide outage costs one round of
    canaries — not one probe per position. Twenty-five failing symbols and
    three failing symbols must cost the same."""
    calls = []
    monkeypatch.setattr(prices, "_fetch_probe", lambda s: calls.append(s) or False)

    prices._reset_reachability()
    for symbol in ("VWCE.MI", "EUNL.DE", "SIE.DE"):
        prices._no_data(symbol)
    few = len(calls)

    calls.clear()
    prices._reset_reachability()
    for n in range(25):
        prices._no_data(f"SYM{n}.MI")
    assert len(calls) == few <= len(prices._CANARIES)
    # and it asks about the canaries, never about the symbol that failed
    assert set(calls) <= set(prices._CANARIES)


def test_unreachable_is_still_a_price_error(monkeypatch):
    """It is a subclass on purpose: every existing `except PriceError` keeps
    working, and only the callers that care ask for the difference."""
    prices._reset_reachability()
    monkeypatch.setattr(prices, "_fetch_probe", lambda s: False)
    assert isinstance(prices._no_data("X"), prices.PriceError)


def test_the_endpoint_answers_503_for_an_outage_and_502_for_a_bad_ticker(
    client, monkeypatch
):
    """A client that cannot tell them apart will show the wrong advice, which
    is exactly what the frontend used to do for both."""
    prices._reset_reachability()
    monkeypatch.setattr(prices, "_fetch_recent_close", _empty)

    monkeypatch.setattr(prices, "_fetch_probe", lambda s: False)
    prices._reset_reachability()
    monkeypatch.setattr(
        prices, "get_quote", lambda s, base: (_ for _ in ()).throw(prices.MarketUnreachable("down"))
    )
    assert client.get("/api/prices/quote", params={"symbol": "VWCE.MI"}).status_code == 503

    monkeypatch.setattr(
        prices, "get_quote", lambda s, base: (_ for _ in ()).throw(prices.PriceError("nope"))
    )
    assert client.get("/api/prices/quote", params={"symbol": "NOPE"}).status_code == 502


def test_an_outage_skips_the_pointless_second_crypto_attempt(monkeypatch):
    """With nothing answering, trying the dollar pair as well just fails twice
    and reports the second failure."""
    prices._reset_reachability()
    tried = []

    def fetch(symbol):
        tried.append(symbol)
        raise prices.MarketUnreachable("nothing answered")

    monkeypatch.setattr(prices, "_fetch_recent_close", fetch)
    with pytest.raises(prices.MarketUnreachable):
        prices.get_quote("bitcoin", "EUR")
    assert tried == ["BTC-EUR"], "it also tried the USD pair with the network down"


def test_a_close_on_a_date_comes_with_the_currency_the_listing_is_known_to_trade_in(
    client, monkeypatch
):
    """A ledger entry has to state what its price is in, and the market's
    dated close does not say. A listing's currency does not change, so once
    anything has priced the symbol the cache knows it and the dated quote
    carries it; a symbol nothing has priced comes back with none rather than a
    guess."""
    from app import models, prices
    from app.database import SessionLocal

    monkeypatch.setattr(
        prices, "_fetch_close_window", lambda symbol, start, end: [("2026-06-13", 180.25)]
    )
    with SessionLocal() as db:
        db.merge(models.PriceCache(symbol="AAPL", price=200.0, currency="USD", as_of=TODAY))
        db.commit()

    known = client.get("/api/prices/quote", params={"symbol": "AAPL", "on": "2026-06-13"}).json()
    unknown = client.get("/api/prices/quote", params={"symbol": "MSFT", "on": "2026-06-13"}).json()

    assert (known["price"], known["as_of"], known["currency"]) == (180.25, "2026-06-13", "USD")
    assert unknown["currency"] is None


def test_the_known_listing_currencies_come_from_the_cache_alone(client):
    """What the ledger form proposes as the currency of a price. A listing the
    cache has not learned the currency of is absent, not guessed — and the
    market is not asked: every network helper refuses in these tests, so a call
    would have turned this read into an error."""
    with SessionLocal() as db:
        db.add_all(
            [
                models.PriceCache(symbol="VTI", price=372.84, currency="USD", as_of=TODAY),
                models.PriceCache(symbol="VWCE.MI", price=165.7, currency="EUR", as_of=TODAY),
                models.PriceCache(symbol="NEW.MI", price=10.0, currency=None, as_of=TODAY),
            ]
        )
        db.commit()

    r = client.get("/api/prices/listing-currencies")

    assert r.status_code == 200, r.text
    assert r.json() == {"VTI": "USD", "VWCE.MI": "EUR"}
