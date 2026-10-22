"""What each line of a Vanguard file is, read from the file itself.

Brief BF (2026-10-22), the reader's (b) after the build's review. Vanguard's
holdings carry `securityType` on every line, which the adapter's own query
did not ask, so every line reached the look-through with no kind. Measured in
the brief's P0 (2026-10-21) on the site's own answers: a hedged bond fund's
first page put a nameless "company" at 153.425% (its 141 currency lines) and
its governments among the companies of a position recorded otherwise than as
Bonds, and FTSE All-World's first page 0.8087% of futures, swaps and currency
lines. The holdings are now asked as P0 sent the site's own query; a share's
codes read as "Equity", every other code as it is. And a file more than half
of whose value is other funds (LifeStrategy 9494: 99.5335% in ETF lines, read
as United Kingdom 64.38% and Germany 35.15%) is left to the next source.

The adapter runs for real against a faked httpx. Every line is invented, in
the shapes P0 read: the codes, the unnamed currency lines; the fund is the
hand map's, so no list is read.
"""

from __future__ import annotations

import datetime
import json

import httpx
import pytest

from app import composition, crud, issuers
from app.database import SessionLocal

REAL = {name: getattr(issuers, name) for name in ("fetch", "fetch_ishares", "fetch_vanguard")}
REAL_FETCH_ISSUER = composition._fetch_issuer

HAND_MAPPED = "IE00BK5BQT80"  # the hand map's, with its portfolio id 9679
GRAPHQL = "https://www.de.vanguard/gpx/graphql"
# The site's own holdings query as P0 sent it on 2026-10-21, written out here
# rather than read from the code under test.
P0_HOLDINGS_QUERY = """query FundsHoldingsQuery($portIds: [String!], $securityTypes: [String!], $lastItemKey: String) {
    funds(portIds: $portIds) {
      profile {
        fundFullName
        fundCurrency
        primarySectorEquityClassification
      }
    }
    borHoldings(portIds: $portIds) {
      holdings(limit: 1500, securityTypes: $securityTypes, lastItemKey: $lastItemKey) {
        items {
          issuerName
          securityLongDescription
          gicsSectorDescription
          icbSectorDescription
          icbIndustryDescription
          marketValuePercentage
          sedol1
          quantity
          ticker
          securityType
          finalMaturity
          effectiveDate
          marketValueBaseCurrency
          bloombergIsoCountry
          couponRate
        }
        totalHoldings
        lastItemKey
      }
    }
  }"""


def _line(name, pct, security_type, country=None, sector=None):
    return {
        "issuerName": name, "marketValuePercentage": str(pct), "securityType": security_type,
        "bloombergIsoCountry": country, "gicsSectorDescription": sector,
    }


EQUITY_FILE = [
    _line("Example Chips Corp", 5.0, "EQ.STOCK", "US", "Information Technology"),
    _line("Example Property Trust", 1.0, "EQ.REIT", "US", "Real Estate"),
    _line("Example Bank Pref", 0.5, "EQ.PREF", "GB", "Financials"),
    _line("Example Index Future", 0.2, "DE.IND", "US"),
    _line("Example Bank Swap", 0.1, "CT.PORTSWAP"),
    _line(None, 0.4, "CT.FOREX"),
    _line(None, 0.1, "CRNY"),
]
HEDGED_BOND_FILE = [
    _line("Example Treasury Note", 23.0, "FI.US_GOV", "US"),
    _line("Example Republic Bond", 3.4, "FI.NONUS_GOV", "FR"),
    _line("Example Chips Corp", 1.0, "FI.CORP", "US", "Information Technology"),
    _line(None, 106.0, "CT.FOREX"),
    _line(None, 46.0, "CT.SPOT"),
]
FUND_OF_FUNDS_FILE = [
    _line("Vanguard Example World UCITS ETF", 60.0, "EQ.ETF", "GB"),
    _line("Vanguard Example Bond UCITS ETF", 39.5335, "EQ.ETF", "DE"),
    _line(None, 0.4665, "CRNY", "XE"),
]


@pytest.fixture
def holdings(monkeypatch):
    """Vanguard's holdings query, faked at httpx: `pages` answered in turn,
    each request kept in `asked` as (url, headers, body)."""

    class Site:
        pages: list[list[dict]] = []
        asked: list[tuple] = []

    for name, fn in REAL.items():
        monkeypatch.setattr(issuers, name, fn)

    def post(url, **kw):
        Site.asked.append((url, kw.get("headers") or {}, kw["json"]))
        page = Site.pages.pop(0) if Site.pages else []
        answer = {"data": {"borHoldings": [{"holdings": {
            "items": page, "totalHoldings": len(page), "lastItemKey": "next" if Site.pages else None,
        }}]}}
        return httpx.Response(200, json=answer, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    Site.asked = []
    return Site


def test_the_holdings_are_asked_as_p0_sent_them(holdings):
    holdings.pages = [EQUITY_FILE]
    issuers.fetch_vanguard(HAND_MAPPED)
    ((url, headers, body),) = holdings.asked
    assert url == GRAPHQL
    assert body == {
        "operationName": "FundsHoldingsQuery",
        "variables": {"portIds": ["9679"], "lastItemKey": None},
        "query": P0_HOLDINGS_QUERY,
    }
    assert {k: headers[k] for k in ("Content-Type", "X-Consumer-ID", "Accept")} == {
        "Content-Type": "application/json", "X-Consumer-ID": "de7", "Accept": "application/json",
    }


def test_each_line_says_what_it_is(holdings):
    """A share's codes are "Equity"; every other code is said as it is; a
    line its file says nothing of has no kind."""
    holdings.pages = [EQUITY_FILE + [_line("Example Untyped Ltd", 0.3, None, "US")]]
    got = issuers.fetch_vanguard(HAND_MAPPED)
    assert sorted((h["name"], h.get("kind")) for h in got["top_holdings"]) == [
        ("", "CRNY"),
        ("", "CT.FOREX"),
        ("Example Bank Pref", "Equity"),
        ("Example Bank Swap", "CT.PORTSWAP"),
        ("Example Chips Corp", "Equity"),
        ("Example Index Future", "DE.IND"),
        ("Example Property Trust", "Equity"),
        ("Example Untyped Ltd", None),
    ]


def test_more_than_half_in_other_funds_is_a_fund_of_funds(holdings):
    """The rule's edge: half the fund in ETF lines is read; more is not."""
    half = [_line("Vanguard Example ETF", 50.0, "EQ.ETF", "GB"), _line("Example Chips Corp", 50.0, "EQ.STOCK", "US")]
    holdings.pages = [half]
    assert issuers.fetch_vanguard(HAND_MAPPED)["holdings_count"] == 2
    more = [_line("Vanguard Example ETF", 50.01, "MF.MF", "GB"), _line("Example Chips Corp", 49.99, "EQ.STOCK", "US")]
    holdings.pages = [more]
    with pytest.raises(issuers.FundOfFunds):
        issuers.fetch_vanguard(HAND_MAPPED)


def test_a_fund_of_funds_says_why_it_is_not_read(holdings, monkeypatch):
    def not_ishares(isin):
        raise issuers.IssuerError("not ours")

    holdings.pages = [FUND_OF_FUNDS_FILE]
    with pytest.raises(issuers.FundOfFunds) as said:
        issuers.fetch_vanguard(HAND_MAPPED)
    assert str(said.value) == (
        f"Vanguard's file for {HAND_MAPPED} lists other funds (99.53% of it), not their "
        "holdings: a fund of funds is read from the next source."
    )
    monkeypatch.setattr(issuers, "fetch_ishares", not_ishares)
    holdings.pages = [FUND_OF_FUNDS_FILE]
    with pytest.raises(issuers.IssuerError) as dispatched:
        issuers.fetch(HAND_MAPPED)
    assert str(dispatched.value) == str(said.value)


# --- The whole way, as the Portfolio page asks it ------------------------------------


JUSTETF_ANSWER = {
    "name": "Vanguard Example LifeStrategy UCITS ETF",
    "countries": [{"name": "United States", "pct": 50.0}, {"name": "Japan", "pct": 10.0}],
    "sectors": [{"name": "Information Technology", "pct": 20.0}],
    "top_holdings": [{"name": "Example Chips Corp", "pct": 3.0, "isin": None}],
    "holdings_count": None,
}


def _waterfall(monkeypatch, justetf=None):
    """iShares says the fund is not its own; the issuer step runs for real;
    justETF answers with `justetf` when given; no other source answers."""

    def not_ishares(isin):
        raise issuers.IssuerError("not ours")

    def nothing(_arg):
        raise composition.CompositionError("nothing here")

    def from_justetf(isin):
        if justetf is None:
            raise composition.CompositionError("nothing here")
        return justetf

    monkeypatch.setattr(issuers, "fetch_ishares", not_ishares)
    monkeypatch.setattr(composition, "_fetch_issuer", REAL_FETCH_ISSUER)
    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda symbol: None)
    monkeypatch.setattr(composition, "_fetch_justetf", from_justetf)
    for name in ("_fetch_trackinsight", "_fetch_yf_sectors"):
        monkeypatch.setattr(composition, name, nothing)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)


def _hold(client, asset_class="fund_etf"):
    """The fund, held under `asset_class`: one account, one situation."""
    iid = client.post("/api/institutions", json={"name": "Banca Alfa"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": datetime.date.today().isoformat()}
    ).json()["id"]
    assert client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo ZZVW", "asset_class": asset_class, "symbol": "ZZVW",
        "isin": HAND_MAPPED, "quantity": 1, "unit_price": 1000, "currency": "EUR",
    }).status_code == 201


def test_an_equity_funds_other_lines_name_no_company(holdings, client, monkeypatch):
    """Its futures, swaps and currency lines, named or not, are no company;
    the countries keep every line that names one, as an iShares file's do."""
    _waterfall(monkeypatch)
    _hold(client)
    holdings.pages = [EQUITY_FILE]
    got = client.get("/api/dashboard/portfolio/composition").json()
    assert got["companies"] == [
        {"name": "Example Chips Corp", "pct": 5.0},
        {"name": "Example Property Trust", "pct": 1.0},
        {"name": "Example Bank Pref", "pct": 0.5},
    ]
    assert got["overlap"] == []
    assert {c["name"]: c["pct"] for c in got["countries"]} == {"United States": 6.2, "United Kingdom": 0.5}


def test_a_hedged_bond_fund_recorded_as_stocks_names_no_company(holdings, client, monkeypatch):
    """Recorded under Stocks & ETF, which no longer decides for a Vanguard
    file: its bonds and its currency lines are no company; its countries are
    its bonds'."""
    _waterfall(monkeypatch)
    _hold(client, "fund_etf")
    holdings.pages = [HEDGED_BOND_FILE]
    got = client.get("/api/dashboard/portfolio/composition").json()
    assert got["companies"] == []
    assert {c["name"]: c["pct"] for c in got["countries"]} == {"United States": 24.0, "France": 3.4}


def test_a_fund_of_funds_is_left_to_the_next_source(holdings, client, monkeypatch):
    """The look-through opens it from justETF, and the cached entry keeps
    the reason in words."""
    _waterfall(monkeypatch, justetf=JUSTETF_ANSWER)
    _hold(client)
    holdings.pages = [FUND_OF_FUNDS_FILE]
    got = client.get("/api/dashboard/portfolio/composition").json()
    (row,) = got["rows"]
    assert (row["decomposed"], row["source"]) == (True, "justetf")
    assert {c["name"] for c in got["countries"]} == {"United States", "Japan"}
    with SessionLocal() as db:
        errors = json.loads(crud.get_composition_cache(db, "ZZVW").data)["errors"]
    assert errors == [
        f"Issuer: IssuerError: Vanguard's file for {HAND_MAPPED} lists other funds (99.53% of "
        "it), not their holdings: a fund of funds is read from the next source."
    ]
