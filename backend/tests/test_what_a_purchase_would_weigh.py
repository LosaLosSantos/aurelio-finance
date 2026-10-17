"""What a purchase would weigh, read by the look-through, and how much, read
from the records: the chat's `size_purchase`.

Brief AQ (2026-10-12). In the brief's P0 the chat read the look-through once
in three scouting answers, and never said what a purchase would weigh in a
region, a sector, a company or a currency; every "how much" was its own
arithmetic. `composition.weigh_purchase` folds a purchase into the look-through
as a held position is weighed, and compares; `size_purchase` returns that with
the room `sizing` computes, for a fund the catalogue holds or a share Yahoo
lists, and refuses the instrument, never the figures, when neither verifies it.

Every name, ISIN, symbol and amount here is invented.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app import advisor, catalogue, chat, composition, dated, prices, tools
from app.database import SessionLocal

TODAY = "2026-03-10"
WORLD, US, GOLD, MISSING = "IE0000AQ0001", "IE0000AQ0002", "IE0000AQ0003", "IE0000AQ0009"

REGISTRY = pd.DataFrame(
    [
        {"name": "Example World Equity UCITS ETF Acc", "ticker": "EXWD", "dividends": "Accumulating",
         "ter": 0.19, "size": 4200, "replication": "Optimized sampling", "domicile_country": "Ireland",
         "currency": "USD", "number_of_holdings": 1500, "hedged": False},
        {"name": "Example US Equity UCITS ETF Acc", "ticker": "EXUS", "dividends": "Accumulating",
         "ter": 0.07, "size": 9100, "replication": "Full replication", "domicile_country": "Ireland",
         "currency": "USD", "number_of_holdings": 500, "hedged": False},
        {"name": "Example Physical Gold ETC", "ticker": "EXGD", "dividends": "Accumulating",
         "ter": 0.12, "size": 3100, "replication": "Physically backed", "domicile_country": "Ireland",
         "currency": "USD", "number_of_holdings": None, "hedged": False},
    ],
    index=pd.Index([WORLD, US, GOLD], name="isin"),
)

# What the sources say each fund holds, and what Yahoo's profile says of the share.
FUNDS = {
    WORLD: {
        "name": "Example World Equity",
        "countries": [{"name": "United States", "pct": 60.0}, {"name": "Japan", "pct": 10.0},
                      {"name": "Italy", "pct": 5.0}],
        "sectors": [{"name": "Information Technology", "pct": 30.0}, {"name": "Financials", "pct": 15.0}],
        "top_holdings": [{"name": "NVIDIA Corp", "pct": 5.0, "isin": None},
                         {"name": "Apple Inc", "pct": 4.0, "isin": None},
                         {"name": "Example Company", "pct": 2.0, "isin": None}],
        "holdings_count": 1500,
    },
    US: {
        "name": "Example US Equity",
        "countries": [{"name": "United States", "pct": 100.0}],
        "sectors": [{"name": "Information Technology", "pct": 35.0}, {"name": "Health Care", "pct": 12.0}],
        "top_holdings": [{"name": "NVIDIA Corp", "pct": 8.0, "isin": None},
                         {"name": "Apple Inc", "pct": 5.0, "isin": None},
                         {"name": "Microsoft Corp", "pct": 6.0, "isin": None}],
        "holdings_count": 500,
    },
}
SHARES = {"EXCO.MI": {"name": "Example Company", "country": "Italy", "sector": "Consumer Discretionary"}}


@pytest.fixture
def sources(monkeypatch):
    """Every source of a composition answers from the tables above, and
    nothing else; the market is out, so no refusal is remembered."""

    def nothing(*args):
        raise composition.CompositionError("nothing here")

    def justetf(isin):
        if isin in FUNDS:
            return dict(FUNDS[isin])
        raise composition.CompositionError("justETF has nothing for it")

    monkeypatch.setattr(composition, "_fetch_equity_profile",
                        lambda symbol: dict(SHARES[symbol]) if symbol in SHARES else None)
    monkeypatch.setattr(composition, "_fetch_issuer", nothing)
    monkeypatch.setattr(composition, "_fetch_justetf", justetf)
    monkeypatch.setattr(composition, "_fetch_trackinsight", nothing)
    monkeypatch.setattr(composition, "_fetch_yf_sectors", nothing)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)
    prices._reset_reachability()
    monkeypatch.setattr(prices, "_fetch_probe", lambda symbol: False)


@pytest.fixture
def held(client, sources, monkeypatch):
    """6,000 EUR of the world fund, held by its ISIN at Broker A; the registry
    loaded; an account with 10,000 on 1 March, a salary of 3,000 and rent of
    1,000 paid from it on the 5th."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: REGISTRY)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    broker = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{broker}/snapshots", json={"date": "2026-03-01"}).json()["id"]
    made = client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Example World Equity", "asset_class": "fund_etf", "isin": WORLD,
        "quantity": 60, "unit_price": 100, "currency": "EUR"})
    assert made.status_code == 201, made.text
    bank = client.post("/api/institutions", json={"name": "Example Bank", "type": "bank"}).json()["id"]
    client.post(f"/api/institutions/{bank}/cash-anchors",
                json={"date": "2026-03-01", "amount": 10000, "currency": "EUR"})
    for path, body in (
        ("/api/income-sources", {"name": "Salary", "amount": 3000, "kind": "active", "category": "salary",
                                 "start_date": "2025-01-27"}),
        ("/api/expenses", {"name": "Rent", "amount": 1000, "nature": "essential", "category": "housing",
                           "start_date": "2025-01-05"}),
    ):
        made = client.post(path, json={**body, "currency": "EUR", "frequency": "monthly",
                                       "institution_id": bank})
        assert made.status_code == 201, made.text
    return client


def _weigh(**purchase) -> dict:
    with SessionLocal() as db:
        return composition.weigh_purchase(db, composition.Purchase(**purchase))


# --- The look-through, before and after -------------------------------------------------


def test_a_fund_is_weighed_as_a_held_one_and_its_moves_said(held):
    weighs = _weigh(name="Example US Equity", value=2000.0, isin=US)
    assert (weighs["investments_before"], weighs["investments_after"]) == (6000.0, 8000.0)
    assert weighs["its_weight_in_the_investments_pct"] == 25.0
    assert (weighs["looked_inside"], weighs["why_not"], weighs["source"]) == (True, None, "justetf")
    moves = weighs["moves"]
    assert moves["countries"] == [
        {"name": "United States", "before_pct": 60.0, "after_pct": 70.0},
        {"name": "Japan", "before_pct": 10.0, "after_pct": 7.5},
        {"name": "Italy", "before_pct": 5.0, "after_pct": 3.75},
    ]
    assert moves["sectors"] == [
        {"name": "Financials", "before_pct": 15.0, "after_pct": 11.25},
        {"name": "Health Care", "before_pct": 0.0, "after_pct": 3.0},
        {"name": "Information Technology", "before_pct": 30.0, "after_pct": 31.25},
    ]
    assert moves["currencies"][0] == {"name": "USD", "before_pct": 60.0, "after_pct": 70.0}
    assert moves["companies"] == [
        {"name": "Microsoft Corp", "before_pct": 0.0, "after_pct": 1.5},
        {"name": "NVIDIA Corp", "before_pct": 5.0, "after_pct": 5.75},
        {"name": "Example Company", "before_pct": 2.0, "after_pct": 1.5},
        {"name": "Apple Inc", "before_pct": 4.0, "after_pct": 4.25},
    ]
    # What it holds that is already held through the world fund; not Microsoft,
    # which only the purchase would bring.
    assert weighs["already_held_through_other_positions"] == [
        {"name": "NVIDIA Corp", "before_pct": 5.0, "after_pct": 5.75, "held_through": [WORLD]},
        {"name": "Apple Inc", "before_pct": 4.0, "after_pct": 4.25, "held_through": [WORLD]},
    ]
    assert (weighs["coverage_before_pct"], weighs["coverage_after_pct"]) == (100.0, 100.0)


def test_a_share_is_its_own_company_counted_with_what_the_funds_hold_of_it(held):
    weighs = _weigh(name="Example Company", value=2000.0, symbol="EXCO.MI")
    assert weighs["source"] == "equity"
    assert weighs["moves"]["countries"][0] == {"name": "Italy", "before_pct": 5.0, "after_pct": 28.75}
    assert weighs["moves"]["companies"][0] == {
        "name": "Example Company", "before_pct": 2.0, "after_pct": 26.5}
    assert weighs["already_held_through_other_positions"] == [
        {"name": "Example Company", "before_pct": 2.0, "after_pct": 26.5, "held_through": [WORLD]},
    ]


def test_a_purchase_nothing_can_look_inside_is_weighed_and_said_as_that(held):
    weighs = _weigh(name="Example Physical Gold ETC", value=2000.0, isin=GOLD)
    assert weighs["its_weight_in_the_investments_pct"] == 25.0
    assert weighs["looked_inside"] is False and weighs["why_not"]
    assert all(moves == [] for moves in weighs["moves"].values())
    assert weighs["already_held_through_other_positions"] == []
    assert (weighs["coverage_before_pct"], weighs["coverage_after_pct"]) == (100.0, 75.0)


def test_a_fund_already_held_is_not_said_to_be_held_twice(held):
    """The purchase considered is the question, not a second position."""
    with SessionLocal() as db:
        conv = composition.fx.Converter(db)
        fetched = [(p, *composition._composition_of(db, p, False)) for p in composition._held(db, conv)]
        position = composition._Considered(None, WORLD, "Example World Equity", None, 1000.0)
        after = composition._aggregate(db, conv, fetched, (position, *composition._composition_of(db, position, False)))
    assert not any("held as two positions" in note for note in after["notes"])


def test_the_look_through_itself_reads_as_it_did(held):
    body = held.get("/api/dashboard/portfolio/composition").json()
    assert body["coverage_pct"] == 100.0
    assert [c["name"] for c in body["countries"]] == ["United States", "Japan", "Italy"]
    assert len(body["companies"]) == 3


# --- size_purchase ------------------------------------------------------------------------


def _size(**arguments) -> dict:
    with SessionLocal() as db:
        return tools.invoke(db, advisor.ToolCall(id="call_1", name="size_purchase",
                                                 arguments=json.dumps(arguments)))


def test_with_no_argument_it_is_the_room_alone(held):
    outcome = _size()
    assert outcome["ok"] is True
    result = outcome["result"]
    assert set(result) == {"room", "reading"}
    room = result["room"]
    # 10,000 less the rent of 5 March; six months of rent kept aside.
    assert room["cash"]["on_the_accounts"] == 9000.0
    assert (room["reserve"]["amount"], room["cash_above_reserve"]) == (6000.0, 3000.0)
    assert room["each_month"]["left_after_commitments"] == 2000.0
    assert room["financial_wealth"] == 15000.0


def test_a_fund_and_a_sum_say_what_the_registry_says_and_what_the_sum_weighs(held):
    result = _size(isin=US, amount_now=2000)["result"]
    assert result["instrument"] == {
        "kind": "fund", "isin": US, "name": "Example US Equity UCITS ETF Acc",
        "distribution": "accumulating", "ter_pct": 0.07, "domicile": "Ireland",
        "replication": "Full replication", "size_meur": 9100, "holdings": 500,
        "share_class_currency": "USD",
        "registry": "justETF's list of products for private investors in Europe, as the app downloaded it",
    }
    now = result["now"]
    assert (now["amount"], now["share_of_financial_wealth_pct"], now["within_cash_above_reserve"]) == (
        2000, 13.33, True)
    assert now["weighs"]["its_weight_in_the_investments_pct"] == 25.0
    assert _size(isin=US, amount_now=3500)["result"]["now"]["within_cash_above_reserve"] is False


def test_a_share_says_its_listing_currency_as_yahoo_gives_it(held, monkeypatch):
    listed = [{"symbol": "EXCO.MI", "name": "Example Company", "quote_type": "equity",
               "exchange": "MIL", "price": 12.5}]
    monkeypatch.setattr(prices, "_fetch_lookup", lambda query, count: listed)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    result = _size(symbol="EXCO.MI", amount_now=500)["result"]
    assert result["instrument"] == {"kind": "share", "symbol": "EXCO.MI", "name": "Example Company",
                                    "exchange": "MIL", "listing_currency": "EUR"}
    assert result["now"]["weighs"]["source"] == "equity"
    # Yahoo silent on the currency: never inferred from the exchange.
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: (_ for _ in ()).throw(OSError("silent")))
    assert _size(symbol="EXCO.MI")["result"]["instrument"]["listing_currency"] == "not given by Yahoo"


def test_an_instrument_nothing_verifies_is_refused_and_the_room_still_said(held):
    result = _size(isin=MISSING, amount_now=1000)["result"]
    assert "is not in the local registry" in result["instrument"]["refused"]
    assert "weighs" not in result["now"]
    assert result["room"]["cash_above_reserve"] == 3000.0


def test_a_monthly_sum_is_said_against_what_is_left_after_the_commitments(held):
    each = _size(amount_monthly=500)["result"]["each_month"]
    assert (each["share_of_left_after_commitments_pct"], each["within_left_after_commitments"]) == (25.0, True)
    assert _size(amount_monthly=2500)["result"]["each_month"]["within_left_after_commitments"] is False


def test_a_fund_and_a_share_at_once_do_not_fit(held):
    outcome = _size(isin=US, symbol="EXCO.MI")
    assert outcome["ok"] is False and "not both" in outcome["error"]


def test_every_figure_travels_with_what_it_means(held):
    reading = " ".join(_size()["result"]["reading"])
    assert "never work out a reserve" in reading
    assert "the app's default, which you say is the app's and never theirs" in reading
    assert "a card refuses one above them" in reading
    # Brief AQ's P1 bis: two answers took an account's deficit off the room
    # again, though the sum on the accounts already nets it.
    assert "an account below zero netted in it" in reading
    assert "Never take it off the room a second time." in reading


# --- The chat is told ------------------------------------------------------------------------


def test_every_model_is_told_how_much_is_not_its_to_work_out():
    for prompt in (chat.SYSTEM_PROMPT, chat.system_prompt("claude-opus-5.5")):
        assert "`size_purchase` reads from their records the figures an amount stands on" in prompt
        assert "never work out a reserve, what is left after their commitments" in prompt
        assert "what a goal needs or lacks, or a weight yourself" in prompt
        assert "`lookup_symbol`, `size_purchase`, `read_analysis`" in prompt
    declared = [d["function"]["name"] for d in tools.declarations()]
    assert "size_purchase" in declared
