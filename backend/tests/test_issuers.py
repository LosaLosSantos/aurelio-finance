"""The issuers' own files: what happens when one of their endpoints moves.

These are the sites' own undocumented endpoints, and they move. iShares' product
screener (the map from ISIN to iShares' product id) began answering "File not
found." in September 2026 while its holdings endpoint kept working. The network
is faked here: `httpx.get` and `httpx.post` answer as the sites did."""

from __future__ import annotations

import datetime
import time
import types

import httpx
import pytest

from app import issuers

# conftest refuses the adapters wholesale. Here they run for real, captured at
# import before that fixture replaces them, against a faked httpx: the network
# edge they actually call, so nothing here can leave the machine.
REAL = {name: getattr(issuers, name) for name in ("fetch", "fetch_ishares", "fetch_vanguard")}

VWCE = "IE00BK5BQT80"  # Vanguard FTSE All-World, in VANGUARD_PORT_IDS
WORLD = "IE00B4L5Y983"  # iShares Core MSCI World USD (Acc)


def _response(url, status=200, json=None, text=None):
    request = httpx.Request("GET", url)
    if json is not None:
        return httpx.Response(status, json=json, request=request)
    return httpx.Response(status, text=text or "", request=request)


VANGUARD_ANSWER = {
    "data": {
        "borHoldings": [
            {
                "holdings": {
                    "items": [
                        {
                            "issuerName": "Apple Inc",
                            "gicsSectorDescription": "Information Technology",
                            "marketValuePercentage": "4.0",
                            "bloombergIsoCountry": "US",
                        }
                    ],
                    "lastItemKey": None,
                }
            }
        ]
    }
}


@pytest.fixture
def screener_moved(monkeypatch):
    """iShares' screener answers as it did from September 2026; Vanguard answers."""
    for name, fn in REAL.items():
        monkeypatch.setattr(issuers, name, fn)
    monkeypatch.setattr(issuers, "_ISHARES_MAP", None)

    def get(url, **kw):
        if url == issuers.ISHARES_SCREENER:
            return _response(url, 404, text="File not found.")
        raise AssertionError(f"unexpected GET {url}")

    def post(url, **kw):
        assert url == issuers.VANGUARD_GRAPHQL
        return _response(url, json=VANGUARD_ANSWER)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)


def test_a_vanguard_fund_is_still_asked_of_vanguard_when_ishares_moved(screener_moved):
    """iShares is asked first. Its broken screener must not stop the next
    adapter from answering for a fund that was never iShares' to begin with."""
    got = issuers.fetch(VWCE)
    assert got["holdings_count"] == 1 and got["top_holdings"][0]["name"] == "Apple Inc"


def test_a_moved_screener_is_said_in_words(screener_moved):
    """The next person to meet the move should see why in one line, not a
    status code."""
    with pytest.raises(issuers.IssuerError) as caught:
        issuers.fetch(WORLD)
    said = str(caught.value)
    assert said.startswith("iShares moved its product screener: ")
    assert "'File not found'" in said and issuers.ISHARES_SCREENER in said
    assert f"seen {datetime.date.today().isoformat()}" in said


def test_the_day_a_move_was_seen_is_the_readers_day(screener_moved, monkeypatch):
    """At 22:30 UTC it is already the next day in Rome. The sighting used to be
    dated in UTC while the test above, and the reader, count local days, so
    that test failed every night between midnight and 02:00 in Italy (found by
    brief AG, 2026-10-06). The issuer's clock is frozen at that hour here, and
    the day expected is the machine's own calendar at that instant, read
    through `time.localtime`. On a machine that keeps UTC, as CI does, the two
    days coincide and this checks only that the day is the local one."""
    frozen = datetime.datetime(2026, 10, 5, 22, 30, tzinfo=datetime.timezone.utc)

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(
        issuers,
        "datetime",
        types.SimpleNamespace(
            datetime=Clock, timezone=datetime.timezone, timedelta=datetime.timedelta, date=datetime.date
        ),
    )
    with pytest.raises(issuers.IssuerError) as caught:
        issuers.fetch(WORLD)
    readers_day = datetime.date(*time.localtime(frozen.timestamp())[:3]).isoformat()
    assert f"seen {readers_day}" in str(caught.value)


def test_a_screener_that_does_not_answer_does_not_stop_vanguard_either(monkeypatch):
    for name, fn in REAL.items():
        monkeypatch.setattr(issuers, name, fn)
    monkeypatch.setattr(issuers, "_ISHARES_MAP", None)

    def get(url, **kw):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _response(url, json=VANGUARD_ANSWER))
    assert issuers.fetch(VWCE)["holdings_count"] == 1
    with pytest.raises(issuers.IssuerError, match="did not answer"):
        issuers.fetch(WORLD)


HOLDINGS_ANSWER = {
    "componentsByNameMap": {"holdings": {"containersByNameMap": {"all": {"dataPointsByNameMap": {
        "issueName": {"value": ["Sandisk", "Carpenter Technology"]},
        "isin": {"value": ["US80004C2008", "US1442851036"]},
        "holdingPercent": {"value": [0.5, 0.4]},
        "countryOfRisk": {"value": ["United States", "United States"]},
        "sectorName": {"value": ["Information Technology", "Materials"]},
    }}}}}
}


def test_a_fund_in_the_hand_map_needs_no_screener(monkeypatch):
    """The fallback for the day the screener moves: the holdings endpoint is
    asked directly with the id the map holds."""
    for name, fn in REAL.items():
        monkeypatch.setattr(issuers, name, fn)
    monkeypatch.setattr(issuers, "ISHARES_PRODUCT_IDS", {WORLD: "251882"})
    asked = []

    def get(url, **kw):
        if url == issuers.ISHARES_SCREENER:
            raise AssertionError("the screener was asked for a fund the map already holds")
        asked.append(kw["params"]["portfolioId"])
        return _response(url, json=HOLDINGS_ANSWER)

    monkeypatch.setattr(httpx, "get", get)
    got = issuers.fetch(WORLD)
    assert asked == ["251882"] and got["holdings_count"] == 2


def test_the_moved_screener_is_the_reason_the_cached_entry_gives(client, monkeypatch, screener_moved):
    """Through the waterfall: the issuer cannot be asked, justETF answers, and
    the entry written says why the issuer's file is not what it holds."""
    import json

    from app import composition, crud
    from app.database import SessionLocal

    monkeypatch.setattr(composition, "_fetch_issuer", lambda isin: issuers.fetch(isin))
    monkeypatch.setattr(composition, "_fetch_justetf", lambda isin: {
        "name": "iShares Core MSCI World UCITS ETF",
        "countries": [{"name": "United States", "pct": 60.0}],
        "sectors": [{"name": "Industrials", "pct": 20.0}],
        "top_holdings": [{"name": "Sandisk", "pct": 0.5, "isin": None}],
        "holdings_count": None,
    })
    with SessionLocal() as db:
        c = composition.get_composition(db, WORLD)
        row = crud.get_composition_cache(db, WORLD)
        errors = json.loads(row.data)["errors"]
    assert c["source"] == "justetf"
    assert any(e.startswith("Issuer: IssuerError: iShares moved its product screener: ") for e in errors), errors



def test_the_screener_at_its_new_address_maps_the_fund_to_its_product_id(monkeypatch):
    """The address found on 2026-09-25, asked with the parameters the page
    itself sends, answering in the shape it had that day: {productId: {isin,
    portfolioId}}. The fund's id is the one iShares' own screener gave."""
    # Written out here, not borrowed from the code under test: a test that
    # compares the request with issuers.ISHARES_SCREENER agrees with any address.
    assert issuers.ISHARES_SCREENER == (
        "https://www.ishares.com/varnish-api/blk-product-screener-server/api/v1/"
        "product-screener/product-data"
    )
    for name, fn in REAL.items():
        monkeypatch.setattr(issuers, name, fn)
    monkeypatch.setattr(issuers, "_ISHARES_MAP", None)
    asked = []

    def get(url, **kw):
        if url == issuers.ISHARES_SCREENER:
            assert kw["params"] == {
                "country": "de", "language": "de", "siteName": "de-ishares-v2", "userType": "individual",
            }
            return _response(url, json={
                "251882": {"isin": WORLD, "portfolioId": 251882, "fundName": "iShares Core MSCI World UCITS ETF"},
                "900001": {"isin": "IE000NOTHER9", "portfolioId": 900001, "fundName": "Another iShares fund"},
            })
        asked.append(kw["params"]["portfolioId"])
        return _response(url, json=HOLDINGS_ANSWER)

    monkeypatch.setattr(httpx, "get", get)
    got = issuers.fetch(WORLD)
    assert asked == ["251882"] and got["holdings_count"] == 2
