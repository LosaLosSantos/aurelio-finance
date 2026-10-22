"""A Vanguard fund the hand map lacks is found in Vanguard's own list.

Brief BF (2026-10-22), the reader's D3 (c). The app knew two Vanguard funds,
by a hand map of ISIN to portfolio id, and every other Vanguard fund fell
through to justETF's top ten. Measured in the brief's P0 (2026-10-21): the
German site's product page lists every portfolio id it sells in its embedded
page state, and one `funds(portIds)` query on the GraphQL address the app
already uses answers each one's ISIN. Now a held fund the stored catalogue
names as Vanguard's, missing from the hand map, is looked up there; the map
read is kept with its day in `settings`, read again only on a later day and
only for a fund still missing, each read adding to it; a reader who holds no
Vanguard fund asks Vanguard nothing; the hand map stays the fallback. A read
that fails is said in words: kept for the day when Vanguard answered and its
list could not be read, kept nowhere when Vanguard did not answer.

The adapters run for real against a faked httpx, as `test_issuers.py` runs
them. The page below is the measured shape, its ids and ISINs invented but the
hand map's own pair.
"""

from __future__ import annotations

import datetime
import json

import httpx
import pytest

from app import composition, dated, issuers, models
from app.database import SessionLocal

REAL = {name: getattr(issuers, name) for name in ("fetch", "fetch_ishares", "fetch_vanguard")}
REAL_FETCH_ISSUER = composition._fetch_issuer

FOUND = "IE00ZZVANG01"  # an invented Vanguard fund, in the list below
ABSENT = "IE00ZZVANG02"  # another, which the list does not hold
OTHERS = "IE00ZZOTHR03"  # a fund of another issuer's
HAND_MAPPED = "IE00BK5BQT80"  # the hand map's, with its portfolio id 9679

GRAPHQL = "https://www.de.vanguard/gpx/graphql"
PAGE = "https://www.de.vanguard/professionell/anlageprodukte"
# The query P0 sent on 2026-10-21, written out here rather than read from the
# code under test.
FUNDS_QUERY = (
    "query FundsQuery($portIds: [String!]!) { funds(portIds: $portIds) { portId profile { "
    'portId fundFullName productTypeLevel1 polarisPdtTypeIndicator identifiers(altIds: ["ISIN"]) '
    "{ altId altIdCode altIdValue } } } }"
)


def _state(port_ids: str) -> str:
    """The product page as measured: the list in its embedded state."""
    state = {"_angular_initial_state": {":items": {"root": {":items": {
        "site-config": {":type": "europe-aem/components/config/site-config", "portIds": port_ids},
    }}}}}
    return (
        "<html><head><title>Anlageprodukte</title></head><body>"
        f'<script id="serverApp-state" type="application/json">{json.dumps(state)}</script>'
        "</body></html>"
    )


FUNDS_ANSWER = {"data": {"funds": [
    {"portId": "9679", "profile": {"identifiers": [{"altIdCode": "ISIN", "altIdValue": HAND_MAPPED}]}},
    {"portId": "E901", "profile": {"identifiers": [{"altIdCode": "ISIN", "altIdValue": FOUND}]}},
]}}

HOLDINGS_ANSWER = {"data": {"borHoldings": [{"holdings": {"items": [
    {"issuerName": "Apple Inc", "gicsSectorDescription": "Information Technology",
     "marketValuePercentage": "4.0", "bloombergIsoCountry": "US"},
], "lastItemKey": None}}]}}


@pytest.fixture
def vanguard(monkeypatch):
    """Vanguard's site, faked at httpx: the page, the list's query and the
    holdings query, each request kept in `asked` as (method, url, body). The
    page and the list's answer can be an exception, and each its own status."""

    class Site:
        page = _state("9679,9505,E901")
        page_status = 200
        funds = FUNDS_ANSWER
        funds_status = 200
        asked: list[tuple] = []

    for name, fn in REAL.items():
        monkeypatch.setattr(issuers, name, fn)

    def get(url, **kw):
        Site.asked.append(("GET", url, None))
        if isinstance(Site.page, Exception):
            raise Site.page
        return httpx.Response(Site.page_status, text=Site.page, request=httpx.Request("GET", url))

    def post(url, **kw):
        body = kw["json"]
        Site.asked.append(("POST", url, body))
        if body["operationName"] != "FundsQuery":
            return httpx.Response(200, json=HOLDINGS_ANSWER, request=httpx.Request("POST", url))
        if isinstance(Site.funds, Exception):
            raise Site.funds
        return httpx.Response(Site.funds_status, json=Site.funds, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    Site.asked = []
    return Site


def _catalogue(*funds):
    """Rows of the stored fund catalogue: (isin, name)."""
    with SessionLocal() as db:
        for isin, name in funds:
            db.add(models.Instrument(
                isin=isin, name=name, family_key=name.lower(), source="justetf",
                fetched_at="2026-10-21T00:00:00+00:00",
            ))
        db.commit()


def _kept():
    with SessionLocal() as db:
        row = db.get(models.Setting, issuers.VANGUARD_KEPT)
        return json.loads(row.value) if row is not None else None


def _list_reads(asked) -> int:
    return sum(1 for method, url, _ in asked if method == "GET" and url == PAGE)


def test_a_vanguard_fund_the_hand_map_lacks_is_found_in_vanguards_list(vanguard, empty_database):
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    got = issuers.fetch_vanguard(FOUND)
    assert got["holdings_count"] == 1 and got["top_holdings"][0]["name"] == "Apple Inc"
    page, listing, holdings = vanguard.asked
    assert page == ("GET", PAGE, None)
    assert listing[:2] == ("POST", GRAPHQL)
    assert listing[2] == {
        "operationName": "FundsQuery",
        "variables": {"portIds": ["9679", "9505", "E901"]},
        "query": FUNDS_QUERY,
    }
    assert holdings[1] == GRAPHQL and holdings[2]["variables"]["portIds"] == ["E901"]


def test_the_list_read_is_kept_with_its_day(vanguard, empty_database):
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    issuers.fetch_vanguard(FOUND)
    assert _kept() == {"day": dated.today(), "ports": {HAND_MAPPED: "9679", FOUND: "E901"}}


def test_a_fund_found_once_is_never_asked_about_again(vanguard, empty_database, monkeypatch):
    """The next look-through of it, today or any later day, reads the kept
    map and asks only for the holdings."""
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    issuers.fetch_vanguard(FOUND)
    later = (datetime.date.today() + datetime.timedelta(days=40)).isoformat()
    monkeypatch.setattr(dated, "today", lambda: later)
    vanguard.asked.clear()
    issuers.fetch_vanguard(FOUND)
    assert [method for method, _, _ in vanguard.asked] == ["POST"]
    assert vanguard.asked[0][2]["operationName"] == "FundsHoldingsQuery"


def test_a_fund_the_list_lacks_today_is_not_read_for_again_today(vanguard, empty_database):
    _catalogue(
        (FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"),
        (ABSENT, "Vanguard Example Bond UCITS ETF (EUR) Distributing"),
    )
    issuers.fetch_vanguard(FOUND)
    vanguard.asked.clear()
    with pytest.raises(issuers.IssuerError, match="no known Vanguard portfolio id"):
        issuers.fetch_vanguard(ABSENT)
    assert vanguard.asked == []


def test_a_later_day_reads_it_again_for_a_fund_still_missing(vanguard, empty_database, monkeypatch):
    _catalogue((ABSENT, "Vanguard Example Bond UCITS ETF (EUR) Distributing"))
    with pytest.raises(issuers.IssuerError):
        issuers.fetch_vanguard(ABSENT)
    assert _list_reads(vanguard.asked) == 1
    later = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(dated, "today", lambda: later)
    vanguard.funds = {"data": {"funds": [
        *FUNDS_ANSWER["data"]["funds"],
        {"portId": "E902", "profile": {"identifiers": [{"altIdCode": "ISIN", "altIdValue": ABSENT}]}},
    ]}}
    assert issuers.fetch_vanguard(ABSENT)["holdings_count"] == 1
    assert _list_reads(vanguard.asked) == 2
    assert _kept()["day"] == later


def test_a_reader_who_holds_no_vanguard_fund_asks_vanguard_nothing(vanguard, empty_database):
    """A fund of another issuer's, and one the catalogue does not list at all:
    not Vanguard's to look up, and nothing is asked."""
    _catalogue((OTHERS, "iShares Example World UCITS ETF (Acc)"))
    for isin in (OTHERS, "IE00ZZNONE04"):
        with pytest.raises(issuers.IssuerError, match="no known Vanguard portfolio id"):
            issuers.fetch_vanguard(isin)
    assert vanguard.asked == []
    assert _kept() is None


def test_the_hand_map_needs_no_list(vanguard, empty_database):
    assert issuers.fetch_vanguard(HAND_MAPPED)["holdings_count"] == 1
    assert _list_reads(vanguard.asked) == 0


MOVED = (
    "Vanguard's product page no longer lists its funds where the app reads them ({page}, seen {day}). "
    "A fund missing from VANGUARD_PORT_IDS in app/issuers.py falls back to the next source."
)


def test_a_page_that_moved_is_said_in_words_and_kept_for_the_day(vanguard, empty_database, monkeypatch):
    """Vanguard answered and its list could not be read: said in words, kept
    with the day, and said again that day for another fund without asking;
    the next day asks again."""
    _catalogue(
        (FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"),
        (ABSENT, "Vanguard Example Bond UCITS ETF (EUR) Distributing"),
    )
    vanguard.page = "<html><body>A new page</body></html>"
    moved = MOVED.format(page=PAGE, day=datetime.date.today().isoformat())
    with pytest.raises(issuers.VanguardListUnread) as said:
        issuers.fetch_vanguard(FOUND)
    assert str(said.value) == moved
    assert _kept() == {"day": dated.today(), "ports": {}, "unread": moved}
    vanguard.asked.clear()
    with pytest.raises(issuers.VanguardListUnread) as again:
        issuers.fetch_vanguard(ABSENT)
    assert str(again.value) == moved and vanguard.asked == []
    later = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(dated, "today", lambda: later)
    vanguard.page = _state("9679,9505,E901")
    assert issuers.fetch_vanguard(FOUND)["holdings_count"] == 1
    assert _list_reads(vanguard.asked) == 1
    assert _kept() == {"day": later, "ports": {HAND_MAPPED: "9679", FOUND: "E901"}}


def test_a_refused_query_is_said_and_kept_for_the_day(vanguard, empty_database):
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    vanguard.funds = {"errors": [{"message": "Cannot query field funds"}]}
    with pytest.raises(issuers.VanguardListUnread, match="Vanguard refused the query for its list of funds") as said:
        issuers.fetch_vanguard(FOUND)
    assert _kept() == {"day": dated.today(), "ports": {}, "unread": str(said.value)}


@pytest.mark.parametrize(
    "where, outage, said",
    [
        ("page", httpx.ConnectTimeout("timed out"), r"Vanguard's product page did not answer \(ConnectTimeout\)"),
        ("page", 503, "Vanguard's product page answered 503"),
        ("funds", httpx.ReadTimeout("timed out"), r"Vanguard's list of funds did not answer \(ReadTimeout\)"),
        ("funds", 502, "Vanguard's list of funds answered 502"),
    ],
)
def test_an_outage_is_said_and_kept_nowhere(vanguard, empty_database, where, outage, said):
    """Vanguard did not answer: said in words, kept nowhere, and asked again
    at the next look the same day, as an outage is elsewhere in the app."""
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    if isinstance(outage, int):
        setattr(vanguard, f"{where}_status", outage)
    else:
        setattr(vanguard, where, outage)
    with pytest.raises(issuers.IssuerUnreachable, match=said) as raised:
        issuers.fetch_vanguard(FOUND)
    assert not isinstance(raised.value, issuers.VanguardListUnread)
    assert _kept() is None
    vanguard.page, vanguard.page_status = _state("9679,9505,E901"), 200
    vanguard.funds, vanguard.funds_status = FUNDS_ANSWER, 200
    assert issuers.fetch_vanguard(FOUND)["holdings_count"] == 1
    assert _list_reads(vanguard.asked) == 2


def test_an_answer_with_errors_beside_its_funds_keeps_the_pairs_it_holds(vanguard, empty_database, caplog):
    """One id of the list failing in Vanguard's answer does not throw the
    others away; the errors go to the log."""
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    vanguard.funds = {**FUNDS_ANSWER, "errors": [{"message": "portId 9505 not found"}]}
    assert issuers.fetch_vanguard(FOUND)["holdings_count"] == 1
    assert _kept() == {"day": dated.today(), "ports": {HAND_MAPPED: "9679", FOUND: "E901"}}
    assert "answered 2 ISINs and errors" in caplog.text


def test_entries_not_of_the_measured_shape_are_skipped(vanguard, empty_database):
    """A null fund, a fund with no profile, a null identifier: skipped, and
    the pair beside them found."""
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    vanguard.funds = {"data": {"funds": [
        None,
        {"portId": "9679", "profile": None},
        {"portId": "E901", "profile": {"identifiers": [None, {"altIdCode": "ISIN", "altIdValue": FOUND}]}},
    ]}}
    assert issuers.fetch_vanguard(FOUND)["holdings_count"] == 1
    assert _kept()["ports"] == {FOUND: "E901"}


@pytest.mark.parametrize(
    "answer, said",
    [
        ({"data": ["not", "an", "object"]}, "Vanguard's list of funds answered no ISIN"),
        ({"data": {"funds": "none"}}, "Vanguard's list of funds answered no ISIN"),
        (["a", "list"], "Vanguard refused the query for its list of funds"),
    ],
)
def test_an_answer_with_no_pair_of_the_measured_shape_is_said(vanguard, empty_database, answer, said):
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    vanguard.funds = answer
    with pytest.raises(issuers.VanguardListUnread, match=said):
        issuers.fetch_vanguard(FOUND)


def test_a_later_read_adds_to_the_map(vanguard, empty_database, monkeypatch):
    """A fund found once keeps its id when a later list no longer names it,
    and is not asked about again."""
    _catalogue(
        (FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"),
        (ABSENT, "Vanguard Example Bond UCITS ETF (EUR) Distributing"),
    )
    issuers.fetch_vanguard(FOUND)
    later = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(dated, "today", lambda: later)
    vanguard.funds = {"data": {"funds": [
        {"portId": "E902", "profile": {"identifiers": [{"altIdCode": "ISIN", "altIdValue": ABSENT}]}},
    ]}}
    assert issuers.fetch_vanguard(ABSENT)["holdings_count"] == 1
    assert _kept() == {"day": later, "ports": {HAND_MAPPED: "9679", FOUND: "E901", ABSENT: "E902"}}
    vanguard.asked.clear()
    issuers.fetch_vanguard(FOUND)
    assert [method for method, _, _ in vanguard.asked] == ["POST"]


def test_a_read_that_cannot_be_kept_still_opens_the_fund(vanguard, empty_database, monkeypatch, caplog):
    """The database busy past its wait: the id just read still opens the
    fund, the failure goes to the log, and nothing is kept."""
    from contextlib import contextmanager

    from sqlalchemy.exc import OperationalError

    from app import database

    @contextmanager
    def busy(db):
        raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))
        yield db

    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    monkeypatch.setattr(database, "sole_writer", busy)
    assert issuers.fetch_vanguard(FOUND)["holdings_count"] == 1
    assert _kept() is None
    assert "Vanguard's list was read and could not be kept" in caplog.text


def test_the_dispatcher_keeps_the_reason(vanguard, empty_database, monkeypatch):
    """iShares says it is not its fund; Vanguard's list cannot be read: the
    dispatcher raises with Vanguard's reason, for the waterfall to keep."""
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))

    def not_ishares(isin):
        raise issuers.IssuerError("not ours")

    monkeypatch.setattr(issuers, "fetch_ishares", not_ishares)
    vanguard.page = "<html></html>"
    with pytest.raises(issuers.IssuerError) as said:
        issuers.fetch(FOUND)
    assert str(said.value).startswith("Vanguard's product page no longer lists its funds")


# --- The whole way, as the Portfolio page asks it ------------------------------------


JUSTETF_ANSWER = {
    "name": "Vanguard Example Equity UCITS ETF (USD) Accumulating",
    "countries": [{"name": "United States", "pct": 100.0}],
    "sectors": [{"name": "Information Technology", "pct": 100.0}],
    "top_holdings": [{"name": "Apple Inc", "pct": 5.0, "isin": None}],
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


def _hold(client):
    """The fund, held: one account, one situation, one position."""
    iid = client.post("/api/institutions", json={"name": "Banca Alfa"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": datetime.date.today().isoformat()}
    ).json()["id"]
    assert client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo ZZVG", "asset_class": "fund_etf", "symbol": "ZZVG",
        "isin": FOUND, "quantity": 1, "unit_price": 1000, "currency": "EUR",
    }).status_code == 201


def test_a_held_vanguard_fund_opens_through_the_look_through(vanguard, client, monkeypatch):
    """A held fund the hand map lacks is read from Vanguard's file, and the
    list is kept while the request's own session is open."""
    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    _waterfall(monkeypatch)
    _hold(client)

    got = client.get("/api/dashboard/portfolio/composition").json()
    (row,) = got["rows"]
    assert (row["decomposed"], row["source"], row["holdings_count"]) == (True, "issuer", 1)
    assert got["companies"] == [{"name": "Apple Inc", "pct": 4.0}]
    assert [(method, url) for method, url, _ in vanguard.asked] == [
        ("GET", PAGE), ("POST", GRAPHQL), ("POST", GRAPHQL),
    ]
    assert _kept() == {"day": dated.today(), "ports": {HAND_MAPPED: "9679", FOUND: "E901"}}


def test_a_list_that_cannot_be_read_leaves_the_fund_to_the_next_source(vanguard, client, monkeypatch):
    """The page moved: the look-through opens the fund from justETF's top
    ten, and the cached entry keeps Vanguard's reason in words."""
    from app import crud

    _catalogue((FOUND, "Vanguard Example Equity UCITS ETF (USD) Accumulating"))
    _waterfall(monkeypatch, justetf=JUSTETF_ANSWER)
    vanguard.page = "<html></html>"
    _hold(client)

    got = client.get("/api/dashboard/portfolio/composition").json()
    (row,) = got["rows"]
    assert (row["decomposed"], row["source"]) == (True, "justetf")
    with SessionLocal() as db:
        errors = json.loads(crud.get_composition_cache(db, "ZZVG").data)["errors"]
    assert errors == [
        "Issuer: IssuerError: " + MOVED.format(page=PAGE, day=datetime.date.today().isoformat())
    ]
