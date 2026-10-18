"""A commodity becomes a product that holds it, or a sentence.

Brief AQ (2026-10-12). Asked about gold in the brief's P0, the chat named a
physically backed ETC from the catalogue. The registry lists more than that
under a commodity's name, read on the test database's copy the same day: every
crude, Brent, wheat and natural gas product is swap based, following futures
and holding none of the commodity, and gold's name is also on funds of the
companies that mine it. A future is not an investment for this reader. So the
card says how a product holds what it tracks (the registry's replication), the
catalogue's reading says what each kind holds, and the prompt names a
commodity only through a product that holds it, or says why none can be named.

Every name and ISIN here is invented.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app import advisor, catalogue, prices, tools
from app.database import SessionLocal

GOLD, OIL, MINERS = "IE0000AQ0201", "IE0000AQ0202", "IE0000AQ0203"

REGISTRY = pd.DataFrame(
    [
        {"name": "Example Physical Gold ETC", "ticker": "EXPG", "dividends": "Accumulating",
         "ter": 0.12, "size": 3100, "replication": "Physically backed", "domicile_country": "Ireland",
         "currency": "USD", "number_of_holdings": None, "hedged": False},
        {"name": "Example Brent Crude Oil", "ticker": "EXBC", "dividends": "Accumulating",
         "ter": 0.49, "size": 900, "replication": "Swap based", "domicile_country": "Jersey",
         "currency": "USD", "number_of_holdings": None, "hedged": False},
        {"name": "Example Gold Miners UCITS ETF", "ticker": "EXGM", "dividends": "Accumulating",
         "ter": 0.53, "size": 1200, "replication": "Full replication", "domicile_country": "Ireland",
         "currency": "USD", "number_of_holdings": 60, "hedged": False},
    ],
    index=pd.Index([GOLD, OIL, MINERS], name="isin"),
)

WHY = {
    "reason": "Something that moves apart from shares, for a small part of savings.",
    "based_on": "You asked about gold, and everything you hold is shares.",
    "unknowns": "I do not know how long you would keep it, or your tax situation.",
}


@pytest.fixture
def loaded(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: REGISTRY)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


def _call(name: str, **arguments) -> dict:
    with SessionLocal() as db:
        return tools.answer(db, advisor.ToolCall(id="toolu_1", name=name,
                                                 arguments=json.dumps(arguments)))


def test_the_card_says_how_a_product_holds_what_it_tracks(loaded):
    gold = _call("suggest_instrument", isin=GOLD, **WHY)["card"]
    assert gold["title"] == (
        f"watch: Example Physical Gold ETC, {GOLD} · accumulating · TER 0.12% · Ireland · "
        "Physically backed · 3 100 M EUR"
    )
    oil = _call("suggest_instrument", isin=OIL, **WHY)["card"]
    assert " · Swap based · " in oil["title"]


def test_the_catalogue_says_what_each_kind_holds(loaded):
    found = _call("search_catalogue", query="gold")
    reading = " ".join(found["result"]["reading"])
    assert "'Physically backed' holds it itself: a metal in a vault, or coins." in reading
    assert ("'Swap based' holds none of it and follows an index through a contract with a bank, "
            "which for a commodity is an index of futures.") in reading
    replications = {m["isin"]: m["replication"] for f in found["result"]["families"] for m in f["members"]}
    assert replications[GOLD] == "Physically backed" and replications[MINERS] == "Full replication"


def test_a_future_is_still_no_card(loaded, monkeypatch):
    listed = [{"symbol": "EXGC=F", "name": "Example Gold Future", "quote_type": "future",
               "exchange": "CMX", "price": 2000.0}]
    monkeypatch.setattr(prices, "_fetch_lookup", lambda query, count: listed)
    refused = _call("suggest_instrument", symbol="EXGC=F", **WHY)
    assert refused["ok"] is False and "a coin, a future or an index gets none" in refused["error"]
