"""Suggestions, and the watchlist they land in.

Three claims are being defended here and they are not the same claim.

THE MODEL CANNOT INVENT AN INSTRUMENT. A suggestion names an ISIN, that ISIN
has to be a row in the local registry, and everything the card says about the
fund — its name, its charge, its domicile, whether it accumulates — is read off
that row rather than out of the arguments. So the worst a model can do is name
something that does not exist, which is refused with a message telling it to
search first. The hallucinated ticker is the classic defect of a chatbot that
talks about funds, and it dies at the argument model.

A SUGGESTION IS NOT A WRITE. Accepting one moves no position, no total and no
projection: it parks an idea on a list that owns nothing. It goes through the
card machinery anyway, because the reader decides what enters their app — and
its button says what pressing it does.

AND THE REASONING IS THE ROW. Three text fields, all required, because the
third one — what the suggestion does not know — is the one a single free-text
box quietly loses. In a month the useful question about a line here is what it
rested on and what it was blind to.

The network is refused for every test by the `offline` fixture, which is also
what proves `lookup_symbol` degrades the way the picker's second lane does
rather than taking the turn down with it.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app import advisor, catalogue, crud, models, prices, tools
from app.database import SessionLocal

# Two funds that share a name and differ only in what they do with dividends,
# plus one that does not — the shapes the card has to tell apart. A cut of the
# same export `test_catalogue.py` uses, for the same reason: the twins are a
# quarter of the real registry.
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
            "name": "Vanguard FTSE All-World UCITS ETF (USD) Accumulating",
            "ticker": "VWCE", "dividends": "Accumulating", "ter": 0.14, "size": 49047,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 3757, "hedged": False,
        },
    ],
    index=pd.Index(
        ["IE00B4L5Y983", "IE000OHHIBC6", "IE00BK5BQT80"], name="isin"
    ),
)

ACC = "IE00B4L5Y983"
DIST = "IE000OHHIBC6"
WORLD = "IE00BK5BQT80"

# The three sentences a suggestion has to carry. Written out once so a test
# that is about something else does not spend four lines saying them again.
WHY = {
    "reason": "It is the only broad developed-market fund with a charge under 0.2%.",
    "based_on": "You hold nothing outside Europe, and your goal is 15 years out.",
    "unknowns": "I do not know your tax situation or whether a pension already covers this.",
}


@pytest.fixture
def loaded(client, monkeypatch):
    """A registry with rows in it. The download is faked; the SEARCH never
    touches the network in the first place, which is the design."""
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


def _ask_for(name: str, arguments: dict) -> advisor.ToolCall:
    return advisor.ToolCall(id="call_1", name=name, arguments=json.dumps(arguments))


def _answer(db, name: str, /, **arguments) -> dict:
    return tools.answer(db, _ask_for(name, arguments))


def _card(db, name: str, /, **arguments) -> dict:
    outcome = _answer(db, name, **arguments)
    assert "card" in outcome, outcome
    return outcome["card"]


def _accept(db, card: dict) -> dict:
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


# --- search_catalogue --------------------------------------------------------


def test_the_search_answers_from_sqlite_and_says_how_it_matched(loaded):
    """The local lane. It is the same call the instrument picker makes, so the
    two cannot disagree about what a word finds — and `coverage` travels with
    the result, because a search that had to loosen is a weaker claim about
    what was asked for."""
    with SessionLocal() as db:
        out = tools.invoke(db, _ask_for("search_catalogue", {"query": "vanguard all-world"}))

    assert out["ok"] is True
    result = out["result"]
    assert result["coverage"] == "all"
    assert [m["isin"] for f in result["families"] for m in f["members"]] == [WORLD]
    assert result["rows"] == 3, "the size of the registry travels with the answer"


def test_the_twins_always_travel_together(loaded):
    """A quarter of the real registry arrives in pairs that share a name and
    differ only in what they do with dividends. Returning one of a pair alone
    invites picking the wrong one without ever revealing there was a choice, so
    the search returns families and the tool passes them through whole."""
    with SessionLocal() as db:
        out = tools.invoke(db, _ask_for("search_catalogue", {"query": "core msci world"}))

    families = out["result"]["families"]
    assert len(families) == 1
    assert sorted(m["isin"] for m in families[0]["members"]) == sorted([ACC, DIST])
    assert sorted(m["distribution_policy"] for m in families[0]["members"]) == ["acc", "dist"]


def test_the_result_carries_the_two_columns_that_must_not_fill_a_field(loaded):
    """`base_ticker` is not a Yahoo symbol and `share_class_currency` is not
    the currency a holding trades in — the pair that has already cost this repo
    a phantom 17% gain. The warning is sent as DATA, because the system prompt
    does not travel with a tool result into the next turn's history and this
    does."""
    with SessionLocal() as db:
        out = tools.invoke(db, _ask_for("search_catalogue", {"query": "vanguard"}))

    reading = " ".join(out["result"]["reading"])
    assert "base_ticker is NOT a Yahoo symbol" in reading
    assert "share_class_currency" in reading
    assert "never a claim that the instrument does not exist" in reading


def test_nothing_found_is_a_fact_about_this_registry_and_not_about_the_market(loaded):
    with SessionLocal() as db:
        out = tools.invoke(db, _ask_for("search_catalogue", {"query": "zzzz nothing"}))

    assert out["result"]["coverage"] == "none" and out["result"]["families"] == []
    assert out["result"]["rows"] == 3 and out["result"]["fetched_at"]


# --- lookup_symbol -----------------------------------------------------------


def test_the_live_lane_says_when_the_source_did_not_answer(client, monkeypatch):
    """The `offline` fixture refuses `_fetch_lookup`, which is exactly what an
    outage looks like. `prices.lookup` swallows it and returns [] so the
    picker's other lane keeps working, so an empty list is two different claims
    — and `reachable` is what tells them apart. Presenting an outage as 'this
    instrument does not exist' teaches the reader to correct a symbol that was
    right."""
    with SessionLocal() as db:
        out = tools.invoke(db, _ask_for("lookup_symbol", {"query": "coca-cola"}))

    assert out["ok"] is True, "an unreachable source is not a broken tool"
    assert out["result"]["results"] == [] and out["result"]["reachable"] is False
    assert any("did not answer" in line for line in out["result"]["reading"])


def test_the_live_lane_never_hands_back_a_price_without_its_exchange(client, monkeypatch):
    """The source returns no currency, so the same company on two exchanges is
    two bare numbers in different money — 50.00 and 43.50, which look 15% apart
    and can be the same value. The rows carry their exchange and the reading
    says what that means."""
    monkeypatch.setattr(
        prices,
        "_fetch_lookup",
        lambda q, n: [
            {"symbol": "ACME", "name": "Acme Industries, Inc.", "quote_type": "EQUITY",
             "exchange": "NMS", "price": 50.00},
            {"symbol": "AC1.F", "name": "Acme Industries Inc.", "quote_type": "EQUITY",
             "exchange": "FRA", "price": 43.50},
        ],
    )
    with SessionLocal() as db:
        out = tools.invoke(db, _ask_for("lookup_symbol", {"query": "acme industries"}))

    assert out["result"]["reachable"] is True
    assert [(r["symbol"], r["exchange"]) for r in out["result"]["results"]] == [
        ("ACME", "NMS"),
        ("AC1.F", "FRA"),
    ]
    assert any("NEVER means anything without exchange" in l for l in out["result"]["reading"])


def test_the_two_lanes_are_two_tools(client):
    """Not a style point. Behind one call the instant lane waits for the slow
    one and an outage empties a list that had valid local results — the reason
    `routers/instruments.py` keeps two endpoints, and the reason the registry
    search above answered while the lookup could not reach anything."""
    assert tools.REGISTRY["search_catalogue"].propose is None
    assert tools.REGISTRY["lookup_symbol"].propose is None
    assert "search_instruments" not in tools.REGISTRY, "that name is the HTTP handler's"


# --- the suggestion card -----------------------------------------------------


def test_a_suggestion_is_drawn_from_the_registry_row_and_not_from_the_model(loaded):
    """The whole anti-hallucination argument in one assertion. The model chose
    WHICH fund; the name, the charge, the domicile and the policy on the card
    were all read off the row. There is no argument it could have used to
    attach a real ISIN to a wrong description."""
    with SessionLocal() as db:
        card = _card(db, "suggest_instrument", isin=WORLD, **WHY)

    assert card["outcome"] == "pending" and card["confirmation"] == "light"
    assert card["title"] == (
        "watch: Vanguard FTSE All-World UCITS ETF (USD) Accumulating, "
        "IE00BK5BQT80 · accumulating · TER 0.14% · Ireland · 49 047 M EUR"
    )
    assert card["verb"] == "Add to watchlist"
    assert "name" not in card["arguments"], "the name is not the model's to write"


def test_an_isin_the_registry_does_not_have_is_refused(loaded):
    """A plausible-looking ISIN is the one mistake nobody catches by reading, so
    it is caught here. The refusal names the remedy, because the model reads it
    and can correct itself on the next round trip."""
    with SessionLocal() as db:
        outcome = _answer(db, "suggest_instrument", isin="IE00BFMXXD54", **WHY)

    assert "card" not in outcome and outcome["ok"] is False
    assert "not in the local registry" in outcome["error"]
    assert "search_catalogue" in outcome["error"]


def test_an_empty_registry_is_a_different_refusal_from_a_missing_fund(client):
    """Two claims with two remedies. 'Nothing has been downloaded' and 'this
    fund is not among the ones I have' are the same distinction the app keeps
    everywhere between nobody answering and an answer of no."""
    with SessionLocal() as db:
        outcome = _answer(db, "suggest_instrument", isin=WORLD, **WHY)

    assert outcome["ok"] is False
    assert "registry is empty" in outcome["error"]
    assert "not a statement about the fund" in outcome["error"]


def test_the_card_names_the_twin_rather_than_letting_it_go_unmentioned(loaded):
    """The search returns families so a twin is never shown alone; a card is
    the narrowest result list there is, so it has to say the pair exists too.
    Otherwise the accumulating one is parked by a reader who never learned
    there was a distributing one."""
    with SessionLocal() as db:
        acc = _card(db, "suggest_instrument", isin=ACC, **WHY)
        world = _card(db, "suggest_instrument", isin=WORLD, **WHY)

    assert "distributing share class (IE000OHHIBC6)" in acc["consequence"]
    assert "share class" not in world["consequence"], "this one has no twin"


def test_the_card_says_that_nothing_about_their_money_changes(loaded):
    """The one card whose confirmation writes no record of theirs, arriving
    after four that do. The sentence comes from the tool for the same reason
    the diff's does: the panel renders every tool's proposals and cannot know."""
    with SessionLocal() as db:
        card = _card(db, "suggest_instrument", isin=WORLD, **WHY)

    assert "Nothing about your money changes" in card["consequence"]
    assert "no broker is connected" in card["consequence"]


def test_the_three_sentences_are_required_and_not_encouraged(loaded):
    """Why, on the basis of what, and what it does not know. Three fields
    rather than one free-text box, because the third is the one a box loses —
    it is the uncomfortable half, and it is the half worth having in a month.
    A model that omits it gets a validation error, not a thinner card."""
    with SessionLocal() as db:
        for missing in ("reason", "based_on", "unknowns"):
            args = {"isin": WORLD, **{k: v for k, v in WHY.items() if k != missing}}
            outcome = _answer(db, "suggest_instrument", **args)
            assert "card" not in outcome, missing
            assert missing in outcome["error"], outcome


def test_accepting_parks_the_idea_with_its_reasoning(loaded):
    """The loop closed. Nothing was written when the model called the tool;
    everything is written when the reader accepts, and what is written is the
    reasoning as much as the instrument."""
    with SessionLocal() as db:
        card = _card(db, "suggest_instrument", isin=WORLD, symbol="vwce.mi", **WHY)
        assert crud.get_watchlist_items(db) == [], "the model wrote"
        done = _accept(db, card)

    assert done["ok"] is True
    items = loaded.get("/api/watchlist").json()
    assert len(items) == 1
    item = items[0]
    assert item["isin"] == WORLD
    assert item["name"] == "Vanguard FTSE All-World UCITS ETF (USD) Accumulating"
    assert item["symbol"] == "VWCE.MI"
    assert (item["reason"], item["based_on"], item["unknowns"]) == (
        WHY["reason"],
        WHY["based_on"],
        WHY["unknowns"],
    )
    assert item["added_at"]
    assert done["result"]["watchlist_id"] == item["id"]


def test_a_suggestion_moves_no_total(loaded):
    """What "not a write card" MEANS, asserted against the numbers rather than
    against the word. A watchlist line is not a holding: net worth is what it
    was before the reader accepted."""
    before = loaded.get("/api/dashboard").json()

    with SessionLocal() as db:
        _accept(db, _card(db, "suggest_instrument", isin=WORLD, **WHY))

    assert loaded.get("/api/dashboard").json() == before


def test_the_same_fund_twice_is_the_same_idea_and_is_refused(loaded):
    """A duplicate whose only difference is which day it was written makes the
    list worse to read in exactly the month it exists to help. The refusal
    quotes the reason already on record, so the model can say why it is
    already there."""
    with SessionLocal() as db:
        _accept(db, _card(db, "suggest_instrument", isin=WORLD, **WHY))
        outcome = _answer(db, "suggest_instrument", isin=WORLD, **WHY)

    assert outcome["ok"] is False
    assert "already on the watchlist" in outcome["error"]
    assert WHY["reason"] in outcome["error"]


def test_a_card_goes_stale_when_the_registry_stops_saying_what_it_quoted(loaded, monkeypatch):
    """The catalogue is replaced wholesale on every refresh, so a fund can
    change its charge — or leave the market — between the proposal and the
    confirmation. The card quoted the charge in its title, so the two go stale
    together: what the reader was shown is no longer what the registry says."""
    with SessionLocal() as db:
        card = _card(db, "suggest_instrument", isin=WORLD, **WHY)

    cheaper = CATALOGUE.copy()
    cheaper.loc[WORLD, "ter"] = 0.09
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: cheaper)
    assert loaded.post("/api/instruments/catalogue/refresh").status_code == 200

    with SessionLocal() as db:
        done = _accept(db, card)

    assert done["ok"] is False and done["stale"] is True
    assert loaded.get("/api/watchlist").json() == []


def test_a_fund_that_left_the_registry_is_stale_and_not_a_500(loaded, monkeypatch):
    """The strongest form of the ground having moved: the card can no longer be
    DRAWN. Reported as stale because that is the same answer — what it says
    would happen is no longer what would happen — and because the alternative
    is an exception escaping into `chat.resume`'s unit of work."""
    with SessionLocal() as db:
        card = _card(db, "suggest_instrument", isin=WORLD, **WHY)

    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE.drop(index=[WORLD]))
    assert loaded.post("/api/instruments/catalogue/refresh").status_code == 200

    with SessionLocal() as db:
        done = _accept(db, card)

    assert done["ok"] is False and done["stale"] is True


def test_accepting_the_same_card_twice_is_refused_by_the_endpoint(loaded, monkeypatch):
    """Through the real door, because a decision taken twice would file the
    idea twice and the compare-and-swap that stops it lives in `crud`, not in
    the tool."""
    seen: list = []

    def fake_stream(system, messages, model=None, tools=None, cache_at=None):
        seen.append(messages)
        yield ("text", "Parked it.")

    monkeypatch.setattr(advisor, "stream_llm", fake_stream)

    with SessionLocal() as db:
        card = _card(db, "suggest_instrument", isin=WORLD, **WHY)
        conv = crud.create_chat_conversation(db)
        crud.append_chat_message(db, conv, "assistant", [card])

    body = {"decision": "confirm", "model": None}
    assert loaded.post(f"/api/chat/cards/{card['card_id']}", json=body).status_code == 200
    again = loaded.post(f"/api/chat/cards/{card['card_id']}", json=body)
    assert again.status_code == 409 and "already" in again.json()["detail"]
    assert len(loaded.get("/api/watchlist").json()) == 1


# --- the list itself ---------------------------------------------------------


def test_the_list_reads_from_the_top_and_a_line_can_be_dropped(loaded):
    """A watchlist is read newest first, and dropping an idea recomputes
    nothing because it owned nothing."""
    with SessionLocal() as db:
        _accept(db, _card(db, "suggest_instrument", isin=WORLD, **WHY))
        _accept(db, _card(db, "suggest_instrument", isin=ACC, **WHY))

    items = loaded.get("/api/watchlist").json()
    assert [i["isin"] for i in items] == [ACC, WORLD], "most recently added first"

    assert loaded.delete(f"/api/watchlist/{items[0]['id']}").status_code == 204
    assert [i["isin"] for i in loaded.get("/api/watchlist").json()] == [WORLD]
    assert loaded.delete(f"/api/watchlist/{items[0]['id']}").status_code == 404


def test_the_reasoning_outlives_the_registry_row_it_named(loaded, monkeypatch):
    """`isin` is deliberately not a foreign key onto `instruments`: that table
    is replaced wholesale on every refresh, so a constraint would make a fund
    leaving the market delete what was written about it. In a month the useful
    question is what the idea rested on, and that has to survive the row."""
    with SessionLocal() as db:
        _accept(db, _card(db, "suggest_instrument", isin=WORLD, **WHY))

    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE.drop(index=[WORLD]))
    assert loaded.post("/api/instruments/catalogue/refresh").status_code == 200

    items = loaded.get("/api/watchlist").json()
    assert len(items) == 1 and items[0]["unknowns"] == WHY["unknowns"]
    with SessionLocal() as db:
        assert db.get(models.Instrument, WORLD) is None
