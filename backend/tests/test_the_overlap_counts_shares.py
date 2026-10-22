"""A company's stock, counted where it is stock.

Brief AR (2026-10-12): the look-through's companies and its overlap keyed every
holding line on the company's name alone, and a bond fund's issuer file lists
its issuers' notes under the issuers' names. On brief AR's seed copy one
company read as held via a bond fund and an equity fund, under "same stock
inside 2+ funds", and the analyst had to guess that the bond fund held debt.
iShares' file says what each line is (`assetClass`), and
the look-through now counts a line as a company's stock only when its file
calls it one, or says nothing of it. Every name, ISIN and figure here is
invented."""

from __future__ import annotations

import datetime

import httpx

from app import advisor, composition, issuers
from app.database import SessionLocal

# conftest refuses the adapter; here it runs for real against a faked httpx,
# captured at import before that fixture replaces it.
REAL_FETCH_ISHARES = issuers.fetch_ishares

TODAY = datetime.date.today().isoformat()
EQUITY_FUND, BOND_FUND, MIXED_FUND = "IE00ALFAEQ01", "IE00ALFABD02", "IE00ALFAMX03"


def _holdings_file(names, kinds, pcts):
    """iShares' holdings answer, in the shape `fetch_ishares` reads."""
    points = {
        "issueName": {"value": names},
        "isin": {"value": [None] * len(names)},
        "holdingPercent": {"value": pcts},
        "countryOfRisk": {"value": ["Germany"] * len(names)},
        "sectorName": {"value": ["Industrials"] * len(names)},
    }
    if kinds is not None:
        points["assetClass"] = {"value": kinds}
    return {"componentsByNameMap": {"holdings": {"containersByNameMap": {"all": {
        "dataPointsByNameMap": points}}}}}


def _answering(monkeypatch, answer):
    monkeypatch.setattr(issuers, "fetch_ishares", REAL_FETCH_ISHARES)
    monkeypatch.setattr(issuers, "ISHARES_PRODUCT_IDS", {BOND_FUND: "900002"})
    monkeypatch.setattr(
        httpx, "get", lambda url, **kw: httpx.Response(200, json=answer, request=httpx.Request("GET", url))
    )


def test_the_issuers_file_says_what_each_line_is(monkeypatch):
    _answering(monkeypatch, _holdings_file(
        ["ALFA CORP", "EUR CASH", "BETA CORP"], ["Fixed Income", "Cash", " Equity "], [0.6, 0.3, 0.1]
    ))
    got = issuers.fetch_ishares(BOND_FUND)
    assert {h["name"]: h.get("kind") for h in got["top_holdings"]} == {
        "Alfa Corp": "Fixed Income", "Eur Cash": "Cash", "Beta Corp": "Equity",
    }


def test_a_file_that_says_nothing_of_a_line_gives_it_no_kind(monkeypatch):
    """Absent and "not said" are one answer: no key, as on every entry cached
    before, rather than a None that a later reader could take for a kind."""
    _answering(monkeypatch, _holdings_file(["ALFA CORP"], None, [1.0]))
    (line,) = issuers.fetch_ishares(BOND_FUND)["top_holdings"]
    assert "kind" not in line


# --- The look-through ---------------------------------------------------------


def _held(client, *funds):
    """One account, one situation, each fund a position worth its value."""
    iid = client.post("/api/institutions", json={"name": "Banca Alfa"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    for isin, symbol, value in funds:
        assert client.post(f"/api/snapshots/{sid}/holdings", json={
            "asset_name": f"Fondo {symbol}", "asset_class": "fund_etf", "symbol": symbol,
            "isin": isin, "quantity": 1, "unit_price": value, "currency": "EUR",
        }).status_code == 201


def _files(monkeypatch, files):
    """The issuer answers for each ISIN in `files`; every other source has
    nothing, and nothing is a share's profile."""

    def issuer(isin):
        if isin not in files:
            raise composition.CompositionError(f"no file for {isin}")
        lines = files[isin]
        return {"name": None, "holdings_count": len(lines["top_holdings"]), **lines}

    def nothing(_arg):
        raise composition.CompositionError("nothing here")

    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda symbol: None)
    monkeypatch.setattr(composition, "_fetch_issuer", issuer)
    for name in ("_fetch_justetf", "_fetch_trackinsight", "_fetch_yf_sectors"):
        monkeypatch.setattr(composition, name, nothing)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)


def _line(name, pct, kind=None):
    return {"name": name, "pct": pct, "isin": None, **({"kind": kind} if kind else {})}


EQUITY_FILE = {
    "countries": [{"name": "United States", "pct": 100.0}],
    "sectors": [{"name": "Industrials", "pct": 100.0}],
    "top_holdings": [_line("ALFA CORP", 5.0, "Equity"), _line("EUR CASH", 1.0, "Cash")],
}
BOND_FILE = {
    "countries": [{"name": "Germany", "pct": 100.0}],
    "sectors": [{"name": "Corporates", "pct": 100.0}],
    "top_holdings": [_line("Alfa Corp", 2.0, "Fixed Income"), _line("EUR CASH", 1.0, "Cash")],
}


def _look_through():
    with SessionLocal() as db:
        return composition.compute_portfolio_composition(db)


def test_a_companys_notes_in_a_bond_fund_are_not_its_stock_held_twice(client, monkeypatch):
    _held(client, (EQUITY_FUND, "ALFAEQ.DE", 600), (BOND_FUND, "ALFABD.DE", 400))
    _files(monkeypatch, {EQUITY_FUND: EQUITY_FILE, BOND_FUND: BOND_FILE})
    body = _look_through()
    assert body["overlap"] == [], body["overlap"]
    # Alfa's stock is the equity fund's line alone: 60% of 5.
    assert {c["name"]: c["pct"] for c in body["companies"]} == {"ALFA CORP": 3.0}


def test_cash_futures_and_currencies_are_never_a_company(client, monkeypatch):
    futures = {**EQUITY_FILE, "top_holdings": [
        _line("ALFA CORP", 5.0, "Equity"), _line("EUR CASH", 1.0, "Cash"),
        _line("ALFA INDEX DEC 26", 0.8, "Futures"), _line("USD/EUR", 0.2, "FX"),
    ]}
    _held(client, (EQUITY_FUND, "ALFAEQ.DE", 1000))
    _files(monkeypatch, {EQUITY_FUND: futures})
    assert [c["name"] for c in _look_through()["companies"]] == ["ALFA CORP"]


def test_a_file_that_carries_both_counts_a_companys_shares_and_not_its_notes(client, monkeypatch):
    """A multi-asset fund's file lists one company's shares and its bonds: the
    companies take the shares, 4%, where they used to take both, 7%."""
    mixed = {
        "countries": [{"name": "Italy", "pct": 100.0}],
        "sectors": [{"name": "Utilities", "pct": 100.0}],
        "top_holdings": [
            _line("GAMMA SPA", 4.0, "Equity"), _line("Gamma Spa", 3.0, "Fixed Income"),
            _line("USD CASH", 2.0, "Cash"),
        ],
    }
    _held(client, (MIXED_FUND, "ALFAMX.DE", 1000))
    _files(monkeypatch, {MIXED_FUND: mixed})
    assert {c["name"]: c["pct"] for c in _look_through()["companies"]} == {"GAMMA SPA": 4.0}


def test_the_countries_and_the_sectors_keep_every_line(client, monkeypatch):
    """Guard: only the companies and the overlap read a line's kind."""
    _held(client, (EQUITY_FUND, "ALFAEQ.DE", 600), (BOND_FUND, "ALFABD.DE", 400))
    _files(monkeypatch, {EQUITY_FUND: EQUITY_FILE, BOND_FUND: BOND_FILE})
    body = _look_through()
    assert {c["name"]: c["pct"] for c in body["countries"]} == {"United States": 60.0, "Germany": 40.0}
    assert body["coverage_pct"] == 100.0


def test_lines_whose_kind_nobody_said_count_as_they_always_did(client, monkeypatch):
    """Guard: a published top ten says nothing of what a line is, and neither
    does an entry cached before; one company inside two such funds still
    overlaps."""
    plain = {
        "countries": [{"name": "Germany", "pct": 100.0}],
        "sectors": [{"name": "Industrials", "pct": 100.0}],
        "top_holdings": [_line("DELTA AG", 3.0)],
    }
    _held(client, (EQUITY_FUND, "ALFAEQ.DE", 500), (MIXED_FUND, "ALFAMX.DE", 500))
    _files(monkeypatch, {EQUITY_FUND: plain, MIXED_FUND: plain})
    (delta,) = _look_through()["overlap"]
    assert delta["name"] == "DELTA AG" and delta["pct"] == 3.0
    assert sorted(delta["funds"]) == ["ALFAEQ.DE", "ALFAMX.DE"]


def test_the_analyst_reads_no_stock_held_twice_for_a_bond(client, monkeypatch):
    _held(client, (EQUITY_FUND, "ALFAEQ.DE", 600), (BOND_FUND, "ALFABD.DE", 400))
    _files(monkeypatch, {EQUITY_FUND: EQUITY_FILE, BOND_FUND: BOND_FILE})
    with SessionLocal() as db:
        context = advisor.build_portfolio_context(db)
    # The overlap's heading since brief BF; an overlap of none is no heading.
    assert "Overlapping top holdings" not in context
    assert "Alfa Corp: " not in context and "ALFA CORP: " not in context
