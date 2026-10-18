"""The analysis's own tools: what the catalogue holds on a fund's index, what an
instrument is, what a change would weigh, and nothing else.

Brief AR (2026-10-12). In the brief's P0 (paid, a test copy) the analyst called
a fund's 0.20% a year "efficient" against nothing, where the catalogue held
funds on the same index from 0.05%; guessed what a bond fund's overlap was;
read a position's kind from its name. `analyst_tools` gives the analysis and
its revision four read-only tools here (and the web search, which the step
runs): none reads the person, none names a security the records do not hold,
and a call to any other name runs nothing. Every name, ISIN, symbol and figure
here is invented."""

from __future__ import annotations

import datetime
import json

import pandas as pd
import pytest

from app import advisor, analyst_tools, catalogue, composition, prices, sizing
from app.database import SessionLocal

TODAY = datetime.date.today()
DAY = (TODAY - datetime.timedelta(days=30)).isoformat()

HELD = "IE00EXAMPL01"  # Alfa Core Example World, held
CHEAP, SWAP, HEDGED, TWIN = "IE00EXAMPL02", "IE00EXAMPL03", "IE00EXAMPL04", "IE00EXAMPL05"
SMALL, SCREENED, BOND = "IE00EXAMPL06", "IE00EXAMPL07", "IE00EXAMPL08"
LONG_BRAND, HEDGED_BEFORE = "IE00EXAMPL09", "IE00EXAMPL10"


def _fund(name, ter, policy="Accumulating", replication="Optimized sampling", hedged=False, size=1000):
    return {"name": name, "ticker": None, "dividends": policy, "ter": ter, "size": size,
            "replication": replication, "domicile_country": "Ireland", "currency": "USD",
            "number_of_holdings": 1200, "hedged": hedged}


REGISTRY = pd.DataFrame(
    [
        _fund("Alfa Core Example World UCITS ETF USD (Acc)", 0.20, size=90000),
        _fund("Beta Example World UCITS ETF 1C", 0.12, size=20000),
        _fund("Gamma Example World Swap UCITS ETF Dist", 0.05, "Distributing", "Swap based"),
        _fund("Delta Example World UCITS ETF EUR Hedged (Acc)", 0.15, hedged=True),
        _fund("Alfa Example World UCITS ETF (Dist)", 0.50, "Distributing", size=8000),
        _fund("Beta Example World Small Cap UCITS ETF 1C", 0.30),
        _fund("Beta ESG Example World UCITS ETF 1C", 0.10),
        _fund("Gamma Core Example Aggregate Bond UCITS ETF Acc", 0.08),
        # A brand of several words, and the hedging written before "UCITS".
        _fund("Zeta Street Bank Example World UCITS ETF", 0.07),
        _fund("Epsilon Example World EUR Hedged UCITS ETF (Acc)", 0.11, hedged=True),
    ],
    index=pd.Index([HELD, CHEAP, SWAP, HEDGED, TWIN, SMALL, SCREENED, BOND, LONG_BRAND, HEDGED_BEFORE],
                   name="isin"),
)

LOOKUP = {
    "EXSH.MI": {"symbol": "EXSH.MI", "name": "Example Share SpA", "quote_type": "EQUITY", "exchange": "MIL",
                "price": 12.0},
    "EXOT.MI": {"symbol": "EXOT.MI", "name": "Another Example SpA", "quote_type": "EQUITY", "exchange": "MIL",
                "price": 30.0},
}


@pytest.fixture
def records(client, monkeypatch):
    """The registry loaded; 6,000 EUR of the held fund by its ISIN and 50
    shares of EXSH.MI at 12.00 at Banca Alfa; Yahoo answering for the two
    symbols above; every composition source answering for the held fund and
    the bond fund only."""
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: REGISTRY)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    iid = client.post("/api/institutions", json={"name": "Banca Alfa", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": DAY}).json()["id"]
    for body in (
        {"asset_name": "Alfa Core Example World", "asset_class": "fund_etf", "isin": HELD,
         "quantity": 60, "unit_price": 100, "currency": "EUR"},
        {"asset_name": "Example Share", "asset_class": "equity", "symbol": "EXSH.MI",
         "quantity": 50, "unit_price": 12, "currency": "EUR"},
    ):
        assert client.post(f"/api/snapshots/{sid}/holdings", json=body).status_code == 201

    def lookup(query, count):
        return [dict(LOOKUP[query])] if query in LOOKUP else []

    def window(symbol, start, end):
        return [((TODAY - datetime.timedelta(days=1)).isoformat(), LOOKUP[symbol]["price"])]

    monkeypatch.setattr(prices, "_fetch_lookup", lookup)
    monkeypatch.setattr(prices, "_fetch_close_window", window)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    monkeypatch.setattr(prices, "_fetch_name", lambda symbol: LOOKUP[symbol]["name"])
    files = {
        HELD: {"name": None, "countries": [{"name": "United States", "pct": 70.0}, {"name": "Japan", "pct": 30.0}],
               "sectors": [{"name": "Industrials", "pct": 100.0}],
               "top_holdings": [{"name": "Example Company", "pct": 3.0, "isin": None}], "holdings_count": 1200},
        BOND: {"name": None, "countries": [{"name": "Germany", "pct": 100.0}],
               "sectors": [{"name": "Treasuries", "pct": 100.0}], "top_holdings": [], "holdings_count": 900},
    }

    def issuer(isin):
        if isin not in files:
            raise composition.CompositionError("no file")
        return dict(files[isin])

    monkeypatch.setattr(composition, "_fetch_issuer", issuer)
    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda symbol: (
        {"name": "Example Share SpA", "country": "Italy", "sector": "Utilities"} if symbol == "EXSH.MI" else None))
    for name in ("_fetch_justetf", "_fetch_trackinsight", "_fetch_yf_sectors"):
        monkeypatch.setattr(composition, name, lambda *a: (_ for _ in ()).throw(composition.CompositionError("none")))
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)


def _call(name, **arguments):
    with SessionLocal() as db:
        return analyst_tools.answer(db, advisor.ToolCall(id="call_1", name=name, arguments=json.dumps(arguments)))


# --- What the catalogue holds on a fund's index ----------------------------------------


def test_the_catalogue_says_how_many_funds_share_the_index_and_at_which_cost(records):
    got = _call("catalogue_same_index", isin=HELD)
    assert got["ok"], got
    result = got["result"]
    assert result["index_as_the_names_give_it"] == "Example World"
    # The cheaper one, the swap, both hedged ones, the held fund's twin and the
    # brand of three words: not the small cap (another index) nor the ESG one
    # (another exposure before it), nor the bond fund.
    assert result["other_funds_on_it"] == {
        "funds": 6, "lowest_ter_pct": 0.05, "highest_ter_pct": 0.5,
        "cheaper_than_this_fund": 5, "as_cheap_as_this_fund": 0, "dearer_than_this_fund": 1,
    }
    assert result["with_this_funds_hedging_and_dividend_policy"] == {
        "funds": 2, "lowest_ter_pct": 0.07, "highest_ter_pct": 0.12,
        "cheaper_than_this_fund": 2, "as_cheap_as_this_fund": 0, "dearer_than_this_fund": 0,
    }
    assert result["by_replication"]["Swap based"]["lowest_ter_pct"] == 0.05
    assert result["currency_hedged"]["funds"] == 2
    assert result["fund"]["name"] == "Alfa Core Example World UCITS ETF USD (Acc)"


def test_the_catalogue_names_no_fund_but_the_held_one(records):
    """The reader's choice (2026-10-12): the analysis says what the catalogue
    holds, and the chat names a fund on a card. No other name and no other ISIN
    reaches the analyst through this tool."""
    text = json.dumps(_call("catalogue_same_index", isin=HELD), ensure_ascii=False)
    for name in ("Beta", "Gamma", "Delta", "Zeta", "Epsilon", "Alfa Example World UCITS ETF (Dist)"):
        assert name not in text, name
    for isin in (CHEAP, SWAP, HEDGED, TWIN, SMALL, SCREENED, BOND, LONG_BRAND, HEDGED_BEFORE):
        assert isin not in text, isin


def test_a_fund_not_held_is_counted_without_its_name(records):
    got = _call("catalogue_same_index", isin=CHEAP)
    assert got["ok"] and got["result"]["fund"]["name"] == "not held, so not named"


def test_a_fund_the_catalogue_does_not_hold_is_said_in_words(records):
    got = _call("catalogue_same_index", isin="IE00EXAMPL99")
    assert got == {"ok": False, "error": (
        "The fund catalogue does not hold IE00EXAMPL99.")}


# --- What an instrument is ---------------------------------------------------------------


def test_a_held_funds_facts_are_the_catalogues_line(records):
    got = _call("instrument_facts", isin=HELD)
    assert got["ok"], got
    facts = got["result"]
    assert facts["kind"] == "fund" and facts["held"] is True
    assert facts["name"] == "Alfa Core Example World UCITS ETF USD (Acc)"
    assert facts["ter_pct"] == 0.2 and facts["distribution"] == "accumulating"
    assert facts["catalogue"].startswith("justETF's list of funds for private investors in Europe, 10 funds")


def test_a_held_share_is_what_yahoo_lists_with_its_latest_close(records):
    got = _call("instrument_facts", symbol="exsh.mi")
    assert got["ok"], got
    facts = got["result"]
    assert facts["kind"] == "EQUITY" and facts["exchange"] == "MIL" and facts["held"] is True
    assert facts["name"] == "Example Share SpA"
    assert facts["latest_close"] == {
        "price": 12.0, "currency": "EUR", "as_of": (TODAY - datetime.timedelta(days=1)).isoformat(),
    }


def test_an_instrument_not_held_is_described_without_its_name(records):
    share = _call("instrument_facts", symbol="EXOT.MI")["result"]
    fund = _call("instrument_facts", isin=CHEAP)["result"]
    assert share["name"] == fund["name"] == "not held, so not named"
    assert "Another Example" not in json.dumps(share) and "Beta" not in json.dumps(fund)


def test_yahoo_silent_says_nothing_about_the_instrument(records, monkeypatch):
    def silent(query, count):
        raise TimeoutError("timed out")

    monkeypatch.setattr(prices, "_fetch_lookup", silent)
    got = _call("instrument_facts", symbol="EXSH.MI")
    assert not got["ok"] and "that says nothing about EXSH.MI" in got["error"]


def test_one_instrument_is_named_at_a_time(records):
    got = _call("instrument_facts", isin=HELD, symbol="EXSH.MI")
    assert not got["ok"] and "not both and not neither" in got["error"]


# --- What a change would weigh -------------------------------------------------------------


def test_a_sale_shrinks_the_investments_and_moves_the_axes(records):
    got = _call("weigh_change", sell=HELD, sell_amount=3000)
    assert got["ok"], got
    weighed = got["result"]
    assert weighed["investments_before"] == 6600.0 and weighed["investments_after"] == 3600.0
    assert weighed["sold"]["its_weight_before_pct"] == round(6000 / 6600 * 100, 2)
    assert weighed["sold"]["its_weight_after_pct"] == round(3000 / 3600 * 100, 2)
    assert weighed["bought"] is None
    us = next(m for m in weighed["moves"]["countries"] if m["name"] == "United States")
    assert us["before_pct"] == round(0.7 * 6000 / 6600 * 100, 2)
    assert us["after_pct"] == round(0.7 * 3000 / 3600 * 100, 2)


def test_a_switch_keeps_the_investments_and_names_no_fund_not_held(records):
    got = _call("weigh_change", sell=HELD, sell_amount=2000, buy_isin=BOND, buy_amount=2000)
    assert got["ok"], got
    weighed = got["result"]
    assert weighed["investments_before"] == weighed["investments_after"] == 6600.0
    assert weighed["bought"]["instrument"] == f"{BOND}, not held, so not named"
    assert weighed["bought"]["looked_inside"] is True
    assert "Aggregate" not in json.dumps(weighed)


def test_more_of_a_fund_held_is_weighed_with_its_positions_holdings(client, records, monkeypatch):
    """A fund held under a ticker, bought again by its ISIN: the purchase is
    weighed with the composition the position was read with, and no source is
    asked a second time for a file already in hand."""
    iid = client.post("/api/institutions", json={"name": "Banca Beta", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": DAY}).json()["id"]
    assert client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Gamma Core Example Aggregate Bond", "asset_class": "fund_etf", "symbol": "EXBD.MI",
        "isin": BOND, "quantity": 10, "unit_price": 100, "currency": "EUR"}).status_code == 201
    asked = []
    answering = composition._fetch_issuer

    def counted(isin):
        asked.append(isin)
        return answering(isin)

    monkeypatch.setattr(composition, "_fetch_issuer", counted)
    got = _call("weigh_change", buy_isin=BOND, buy_amount=500)
    assert got["ok"], got
    assert got["result"]["bought"]["looked_inside"] is True
    assert asked.count(BOND) == 1, asked


def test_a_sale_larger_than_the_position_is_refused_in_words(records):
    got = _call("weigh_change", sell="EXSH.MI", sell_amount=900)
    assert got == {"ok": False, "error": (
        "EXSH.MI is worth 600.00 EUR; a sale of 900.00 is more than it holds.")}


def test_a_sale_of_nothing_held_is_refused_in_words(records):
    got = _call("weigh_change", sell="NONE.MI", sell_amount=10)
    assert not got["ok"] and got["error"].startswith("No position is held under 'NONE.MI'")


def test_a_change_needs_what_and_how_much(records):
    assert not _call("weigh_change", buy_isin=BOND)["ok"]
    assert not _call("weigh_change")["ok"]


# --- Nothing else -------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["size_purchase", "read_analysis", "update_profile", "search_catalogue",
                                  "write_goal", "suggest_instrument"])
def test_a_tool_the_analysis_is_not_offered_runs_nothing(records, monkeypatch, name):
    """The chat's tools are not the analysis's: `size_purchase`'s room reads the
    profile and the goals, `read_analysis` a verdict written to the person."""

    def must_not_run(*args, **kwargs):
        raise AssertionError("the room was read")

    monkeypatch.setattr(sizing, "room", must_not_run)
    got = _call(name, isin=HELD, amount_now=100)
    assert got == {"ok": False, "error": (
        f"There is no tool called {name!r} in the analysis, and it ran nothing. Its tools are: "
        "get_look_through, catalogue_same_index, instrument_facts, weigh_change, search_web.")}


def test_the_web_is_declared_for_supported_copilot_models():
    names = lambda model: [d["function"]["name"] for d in analyst_tools.declarations(model, 3)]  # noqa: E731
    assert names("claude-opus-5.5") == [
        "get_look_through", "catalogue_same_index", "instrument_facts", "weigh_change", "search_web"]
    assert names("unsupported-model") == [
        "get_look_through", "catalogue_same_index", "instrument_facts", "weigh_change"]
