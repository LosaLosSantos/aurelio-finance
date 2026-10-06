"""The local instrument registry: identity is chosen, not typed.

The catalogue download is monkeypatched, so these never hit the network — which
is also the point of the design: the search itself never touches it either.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app import catalogue

# A cut of the real justETF export (rows as it listed them on 2026-09-04),
# keeping exactly the shapes that matter: an Acc/Dist pair with identical
# names, a sibling whose name differs by one word, and funds whose catalogue
# ticker is NOT a Yahoo symbol.
CATALOGUE = pd.DataFrame(
    [
        {
            "name": "iShares Core MSCI World UCITS ETF USD (Acc)",
            "ticker": "EUNL", "dividends": "Accumulating", "ter": 0.20, "size": 127563,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1280, "hedged": False,
        },
        {
            "name": "iShares Core MSCI World UCITS ETF USD (Dist)",
            "ticker": "IWDD", "dividends": "Distributing", "ter": 0.20, "size": 803,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1280, "hedged": False,
        },
        {
            "name": "iShares Core MSCI World UCITS ETF EUR Hedged (Dist)",
            "ticker": "IWLE", "dividends": "Distributing", "ter": 0.30, "size": 1811,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "EUR", "number_of_holdings": 1280, "hedged": True,
        },
        {
            "name": "Vanguard FTSE All-World UCITS ETF (USD) Accumulating",
            "ticker": "VWCE", "dividends": "Accumulating", "ter": 0.14, "size": 49047,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 3757, "hedged": False,
        },
        {
            "name": "Vanguard S&P 500 UCITS ETF (USD) Distributing",
            "ticker": "VUSA", "dividends": "Distributing", "ter": 0.07, "size": 46065,
            "replication": "Full replication", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 503, "hedged": False,
        },
    ],
    index=pd.Index(
        [
            "IE00B4L5Y983", "IE000OHHIBC6", "IE00BKBF6H24",
            "IE00BK5BQT80", "IE00B3XXRP09",
        ],
        name="isin",
    ),
)


@pytest.fixture
def loaded(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE)
    r = client.post("/api/instruments/catalogue/refresh")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_catalogue_reports_what_it_holds(loaded):
    """A picker searching a download from months ago is a different tool from
    one searching today's, so the age is never assumed."""
    assert loaded["rows"] == 5
    assert loaded["fetched_at"] and loaded["source"] == "justetf"


def test_the_full_name_finds_the_fund_and_not_its_near_miss(client, loaded):
    """The catalogue is keyed on the full name, share class included, so a
    query naming the USD class finds that pair and not the EUR-hedged sibling
    that shares every other word of it."""
    body = client.get("/api/instruments/search", params={"q": "Core MSCI World USD"}).json()
    assert body["coverage"] == "all"
    isins = [m["isin"] for f in body["families"] for m in f["members"]]
    assert "IE000OHHIBC6" in isins  # the Dist member of the pair
    assert "IE00BKBF6H24" not in isins, "the hedged near-miss came back"


def test_the_twins_always_travel_together(client, loaded):
    """They carry identical names and differ only in what they do with
    dividends, so showing one alone invites picking it without ever revealing
    there was a choice."""
    body = client.get("/api/instruments/search", params={"q": "Core MSCI World USD"}).json()
    (family,) = body["families"]
    assert sorted(m["distribution_policy"] for m in family["members"]) == ["acc", "dist"]


def test_raw_input_with_punctuation_does_not_explode(client, loaded):
    """`MATCH 'Vanguard FTSE All-World'` raises `no such column: World` — the
    hyphen makes FTS5 parse the tail as a column expression."""
    r = client.get("/api/instruments/search", params={"q": "Vanguard FTSE All-World"})
    assert r.status_code == 200
    assert r.json()["families"], "the query that used to raise now finds the fund"


def test_a_loosened_match_says_that_it_loosened(client, loaded):
    """Finding something while you are still typing is useful; presenting it as
    if every word matched is not."""
    exact = client.get("/api/instruments/search", params={"q": "Vanguard All-World"}).json()
    partial = client.get("/api/instruments/search", params={"q": "vangu"}).json()
    assert exact["coverage"] == "all"
    assert partial["coverage"] == "partial" and partial["families"]


def test_a_single_character_returns_nothing(client, loaded):
    """It would match thousands of rows: noise pretending to be a shortlist."""
    assert client.get("/api/instruments/search", params={"q": "V"}).json()["families"] == []


def test_it_carries_the_fields_that_tell_two_rows_apart(client, loaded):
    body = client.get("/api/instruments/search", params={"q": "Core MSCI World USD"}).json()
    member = body["families"][0]["members"][0]
    assert member["ter"] == 0.2 and member["domicile"] == "Ireland"
    assert member["replication"] and member["size_meur"]


def test_the_catalogue_ticker_is_not_a_yahoo_symbol(client, loaded):
    """It says IWLE for this fund: the catalogue's code, not a Yahoo symbol.
    A holding is priced by the symbol of the listing it trades on, so this is
    carried for recognition, never as a symbol."""
    body = client.get("/api/instruments/search", params={"q": "Core MSCI World EUR Hedged"}).json()
    (member,) = body["families"][0]["members"]
    assert member["base_ticker"] == "IWLE"
    assert member["isin"] == "IE00BKBF6H24"


def test_the_share_class_currency_is_carried_but_is_not_the_trading_currency(client, loaded):
    """justETF says USD for VWCE, which quotes in EUR in Milan. Filling a
    holding's currency from this recreates the phantom 17% gain."""
    body = client.get("/api/instruments/search", params={"q": "Vanguard All-World"}).json()
    (member,) = body["families"][0]["members"]
    assert member["share_class_currency"] == "USD"


def test_a_failed_download_leaves_the_stored_copy_alone(client, loaded, monkeypatch):
    """A picker that empties itself when the network blinks is worse than one
    that is a little out of date."""
    def boom():
        raise RuntimeError("source unreachable")

    monkeypatch.setattr(catalogue, "_fetch_overview", boom)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 502
    assert client.get("/api/instruments/catalogue").json()["rows"] == 5
    assert client.get("/api/instruments/search", params={"q": "Core MSCI World"}).json()["families"]


def test_searching_an_empty_registry_is_not_an_error(client):
    """Before the first download there is simply nothing to find, and the
    caller is told how many rows there are so it can say why."""
    body = client.get("/api/instruments/search", params={"q": "Vanguard"}).json()
    assert body["families"] == [] and body["rows"] == 0


def test_family_key_strips_only_the_twin_distinction():
    a = catalogue.family_key("iShares Core MSCI World UCITS ETF USD (Acc)")
    d = catalogue.family_key("iShares Core MSCI World UCITS ETF USD (Dist)")
    assert a == d
    # ...and does not collapse funds that are genuinely different
    assert a != catalogue.family_key("iShares Core MSCI World Small Cap UCITS ETF USD")


# --- The live lane: everything the fund catalogue cannot hold ----------------


LOOKUP = {
    "Acme Industries": [
        {"symbol": "ACME", "name": "Acme Industries, Inc.", "quote_type": "equity",
         "exchange": "NMS", "price": 50.00},
        # Same company, Frankfurt, EUROS — and the name is identical. Nothing
        # but the exchange separates them, which is why the price may never be
        # rendered without it.
        {"symbol": "AC1.F", "name": "Acme Industries Inc.", "quote_type": "equity",
         "exchange": "FRA", "price": 43.50},
    ],
    "Bitcoin": [
        # Yahoo ranks two dated contracts ABOVE the coin.
        {"symbol": "MBT=F", "name": "Micro Bitcoin Futures,Aug-2026",
         "quote_type": "future", "exchange": "CME", "price": 65750.0},
        {"symbol": "BTC-USD", "name": "Bitcoin USD", "quote_type": "cryptocurrency",
         "exchange": "CCC", "price": 65884.0},
    ],
}


@pytest.fixture
def live(monkeypatch):
    from app import prices

    monkeypatch.setattr(
        prices, "_fetch_lookup", lambda q, count: LOOKUP.get(q, [])[:count]
    )


def test_the_live_lane_finds_what_the_catalogue_cannot(client, live):
    """A share's name searched in the fund catalogue can only find funds that
    share a word with it. Shares need the other lane, and it is the only source
    of a quotable symbol."""
    body = client.get("/api/instruments/lookup", params={"q": "Acme Industries"}).json()
    assert body["reachable"] is True
    assert [r["symbol"] for r in body["results"]] == ["ACME", "AC1.F"]


def test_every_priced_row_carries_its_exchange(client, live):
    """The lookup returns NO currency, so 50.00 and 43.50 for the same company
    read as 15% apart and can be the same value. A price is only meaningful
    beside the exchange it came from."""
    body = client.get("/api/instruments/lookup", params={"q": "Acme Industries"}).json()
    for row in body["results"]:
        assert row["price"] is not None
        assert row["exchange"], "a price without its exchange invites a false comparison"


def test_a_dated_contract_is_marked_as_one(client, live):
    """Yahoo puts two futures above the coin for 'Bitcoin'. The type is what
    lets the caller say so — a contract that expires would otherwise be the
    most likely thing to click."""
    body = client.get("/api/instruments/lookup", params={"q": "Bitcoin"}).json()
    kinds = [r["quote_type"] for r in body["results"]]
    assert kinds[0] == "future" and "cryptocurrency" in kinds


def test_an_unreachable_source_is_not_a_missing_instrument(client, monkeypatch):
    """'Nothing answered' and 'this does not exist' are different claims, and
    presenting the first as the second teaches people to correct symbols that
    were right all along."""
    from app import prices

    def boom(q, count):
        raise RuntimeError("network down")

    monkeypatch.setattr(prices, "_fetch_lookup", boom)
    body = client.get("/api/instruments/lookup", params={"q": "Acme Industries"}).json()
    assert body["results"] == [] and body["reachable"] is False


def test_the_live_lane_going_quiet_leaves_the_catalogue_alone(client, loaded, monkeypatch):
    """Two lanes, two endpoints, exactly so one cannot empty the other."""
    from app import prices

    monkeypatch.setattr(prices, "_fetch_lookup", lambda q, count: 1 / 0)
    assert client.get("/api/instruments/lookup", params={"q": "Core MSCI"}).json()["results"] == []
    assert client.get("/api/instruments/search", params={"q": "Core MSCI World USD"}).json()["families"]


def test_a_single_character_never_reaches_the_network(client, monkeypatch):
    from app import prices

    called = []
    monkeypatch.setattr(prices, "_fetch_lookup", lambda q, count: called.append(q) or [])
    client.get("/api/instruments/lookup", params={"q": "V"})
    assert called == [], "one letter is not a search"
