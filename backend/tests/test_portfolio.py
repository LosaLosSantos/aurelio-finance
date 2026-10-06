"""Portfolio view: book values from the DB; market values + P/L from a single
batch price fetch (live) or from the price cache (non-live). Every price
carries its `as_of` close date."""

from __future__ import annotations

import datetime

from app import prices

TODAY = datetime.date.today().isoformat()


def _one_position(client, **extra) -> tuple[int, int]:
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
    client.post(f"/api/snapshots/{sid}/holdings", json=payload)
    return iid, sid


def test_portfolio_book_only_no_network(client):
    _, sid = _one_position(client)
    # cash holdings must be excluded from the portfolio (they live in the register)
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Cash", "asset_class": "cash", "value": 5000, "currency": "EUR"},
    )

    p = client.get("/api/dashboard/portfolio").json()  # live=false, empty cache
    assert p["priced"] is False and p["prices_as_of"] is None
    assert len(p["rows"]) == 1  # cash excluded
    row = p["rows"][0]
    assert row["book_value"] == 1000 and row["live_price"] is None and row["market_value"] is None
    assert p["total_book"] == 1000 and p["total_market"] is None


def test_portfolio_live_computes_pl_and_as_of(client, monkeypatch):
    _one_position(client)
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 120.0, "as_of": "2026-08-08"} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    p = client.get("/api/dashboard/portfolio", params={"live": "true"}).json()
    row = p["rows"][0]
    assert row["live_price"] == 120.0
    assert row["as_of"] == "2026-08-08"
    assert row["market_value"] == 1200.0      # 10 * 120
    assert row["delta"] == 200.0              # 1200 - 1000 book
    assert abs(row["delta_pct"] - 0.2) < 1e-9
    assert p["priced"] is True and p["total_market"] == 1200.0
    assert p["prices_as_of"] == "2026-08-08"


def test_portfolio_live_populates_cache_reused_when_not_live(client, monkeypatch):
    _one_position(client)
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 120.0, "as_of": "2026-08-08"} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    client.get("/api/dashboard/portfolio", params={"live": "true"})

    # A later non-live read must serve the cached price (no network involved).
    def boom(_syms):
        raise AssertionError("non-live read must not fetch prices")

    monkeypatch.setattr(prices, "get_quotes", boom)
    p = client.get("/api/dashboard/portfolio").json()
    row = p["rows"][0]
    assert p["priced"] is True and row["live_price"] == 120.0
    assert row["as_of"] == "2026-08-08" and p["prices_as_of"] == "2026-08-08"


def test_portfolio_live_refresh_overwrites_cache(client, monkeypatch):
    _one_position(client)
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 120.0, "as_of": "2026-08-08"} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    client.get("/api/dashboard/portfolio", params={"live": "true"})
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 130.0, "as_of": "2026-08-09"} for s in syms},
    )
    client.get("/api/dashboard/portfolio", params={"live": "true"})

    p = client.get("/api/dashboard/portfolio").json()  # from cache
    assert p["rows"][0]["live_price"] == 130.0 and p["rows"][0]["as_of"] == "2026-08-09"


def test_portfolio_live_tolerates_price_failure(client, monkeypatch):
    _one_position(client, symbol="NOPE.XX", quantity=3, unit_price=50)

    def boom(_syms):
        raise prices.PriceError("no data")

    monkeypatch.setattr(prices, "get_quotes", boom)
    p = client.get("/api/dashboard/portfolio", params={"live": "true"}).json()
    row = p["rows"][0]
    assert row["market_value"] is None and row["book_value"] == 150
    # total_market falls back to book for unpriced rows; nothing priced -> None
    assert p["total_market"] is None and p["priced"] is False


def test_get_quotes_empty_and_blank_symbols():
    assert prices.get_quotes([]) == {}
    assert prices.get_quotes(["  ", ""]) == {}


# --- What the columns are allowed to claim -----------------------------------


def test_listing_currency_beats_a_hand_typed_one(client, monkeypatch):
    """A qty-based value was entered as quantity x the listing's unit price, so
    it is necessarily in the listing's currency. Trusting a wrong hand-typed
    field instead invented a 17% profit out of the EUR/USD rate."""
    from app import fx

    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        # Labelled USD (the share class) but quoted in EUR in Milan.
        json={"asset_name": "iShares Min Vol", "asset_class": "fund_etf", "symbol": "MVOL.MI",
              "quantity": 24, "unit_price": 67.07, "currency": "USD"},
    )
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {"2026-08-22": {"USD": 1.1681}})
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 67.07, "as_of": "2026-08-22"} for s in syms},
    )
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})

    p = client.get("/api/dashboard/portfolio", params={"live": "true"}).json()
    row = p["rows"][0]
    assert abs(row["book_value"] - 1609.68) < 0.01  # NOT divided by the FX rate
    assert abs(row["delta"]) < 0.01  # the phantom gain is gone
    assert "MVOL.MI trades in EUR" in (row["currency_note"] or "")


def test_a_blended_basis_is_never_called_a_known_cost(client, monkeypatch):
    """Without a recorded buy, "average cost" is just the price a snapshot was
    taken at — and ONE buy on top of it does not redeem the rest. The basis
    below is 1000 from the photo plus 600 actually paid: calling that a known
    cost would let a mostly-invented figure claim to be a profit, which is
    worse than saying nothing, because it arrives by doing the right thing."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2020-01-10"}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "iShares World", "asset_class": "fund_etf", "symbol": "VWCE.MI",
              "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )
    assert client.get("/api/dashboard/portfolio").json()["rows"][0]["cost_known"] is False

    client.post(
        "/api/transactions",
        json={"date": TODAY, "institution_id": iid, "asset_name": "iShares World",
              "symbol": "VWCE.MI", "quantity": 5, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
    )
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["cost_known"] is False, "37% of this basis is a price paid, not 100%"
    # the arithmetic is still right — it is the CLAIM about it that was wrong
    assert abs(row["avg_cost"] - (1600 / 15)) < 1e-9


def test_a_position_born_from_the_ledger_has_a_real_cost(client, monkeypatch):
    """The other side of the rule: when nothing came from a photograph, every
    unit's basis is a price actually paid, and the P/L is a true profit."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    client.post(
        "/api/transactions",
        json={"date": TODAY, "institution_id": iid, "asset_name": "iShares World",
              "symbol": "SWDA.MI", "quantity": 4, "unit_price": 90, "currency": "EUR", "price_currency": "EUR"},
    )
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["cost_known"] is True
    assert abs(row["avg_cost"] - 90.0) < 1e-9


def test_quote_endpoint_accepts_a_past_date(client, monkeypatch):
    monkeypatch.setattr(
        prices,
        "get_price_on",
        lambda s, on: {"symbol": s, "price": 142.5, "as_of": on.isoformat()},
    )
    body = client.get(
        "/api/prices/quote", params={"symbol": "VWCE.MI", "on": "2026-03-12"}
    ).json()
    assert body["price"] == 142.5 and body["as_of"] == "2026-03-12"
