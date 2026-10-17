"""A card is done when it is done, and the turn after it is short.

The decision is emitted on the stream before the model's follow-up. It remains
final if that follow-up fails, and later turns include the decision without
ending a model request on the model's own words. Every fund here is invented;
model calls are faked at `advisor.stream_llm`.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app import advisor, catalogue, chat, tools


# Two invented funds, the shape of the reader's request: two cards from one
# answer.
CATALOGUE = pd.DataFrame(
    [
        {
            "name": "Example Global Equity UCITS ETF Acc",
            "ticker": "XGLO", "dividends": "Accumulating", "ter": 0.12, "size": 2100,
            "replication": "Physical", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1500, "hedged": False,
        },
        {
            "name": "Example Emerging Equity UCITS ETF Acc",
            "ticker": "XEME", "dividends": "Accumulating", "ter": 0.18, "size": 900,
            "replication": "Physical", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1200, "hedged": False,
        },
    ],
    index=pd.Index(["IE0000AJ0001", "IE0000AJ0002"], name="isin"),
)
FIRST, SECOND = "IE0000AJ0001", "IE0000AJ0002"
WHY = {
    "reason": "An invented reason.",
    "based_on": "An invented answer in the questionnaire.",
    "unknowns": "Invented unknowns.",
}



@pytest.fixture
def loaded(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _kinds(events: list[dict]) -> list[str]:
    return [e["kind"] for e in events]


def _suggest(isin: str, call_id: str) -> tuple:
    return (
        "tool_call",
        advisor.ToolCall(
            id=call_id, name="suggest_instrument", arguments=json.dumps({"isin": isin, **WHY})
        ),
    )


def _script(monkeypatch, rounds):
    """`stream_llm` answering each round from `rounds`, in order, and keeping
    what each was asked. An entry that is an exception is raised instead, the
    way a refused call raises before its first piece. A round past the script
    is an AssertionError, never a replay."""
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        seen.append(
            {"system": system_prompt, "messages": list(messages), "tools": tools, "model": model}
        )
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        answer = rounds[len(seen) - 1]
        if isinstance(answer, Exception):
            raise answer
        yield from answer

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def _two_cards(client, monkeypatch) -> tuple[int, list[dict]]:
    """The reader's question: one answer, two fund cards. Returns the
    conversation's id and the two cards."""
    _script(
        monkeypatch,
        [[("text", "Two to look at, one card each."), _suggest(FIRST, "call_1"), _suggest(SECOND, "call_2")]],
    )
    events = _events(client.post("/api/chat", json={"content": "Two funds to watch?"}))
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert len(cards) == 2
    return events[0]["conversation_id"], cards


def _decide(client, card_id: str, decision: str = "confirm"):
    return client.post(f"/api/chat/cards/{card_id}", json={"decision": decision})


def _stored_cards(client, conversation_id: int) -> list[dict]:
    messages = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"]
    return [b for m in messages for b in m["blocks"] if b["kind"] == "card"]


# --- The card follows its decision ---------------------------------------------------


def test_the_decision_is_said_before_the_reply_and_stands_when_the_reply_fails(
    loaded, monkeypatch
):
    """The reader's sequence. Both cards are decided on the stream before any
    reply, each as it is stored; the second reply fails, and the second card
    is decided all the same, which is what the panel shows from that event
    on. Before brief AJ the stream said nothing of the decision, and the panel
    learnt it only from a reply that ended well."""
    conversation_id, (first, second) = _two_cards(loaded, monkeypatch)

    _script(monkeypatch, [[("text", "Added.")]])
    events = _events(_decide(loaded, first["card_id"]))
    assert _kinds(events) == ["start", "decided", "delta", "done"]
    assert events[1]["card"]["card_id"] == first["card_id"]
    assert events[1]["card"]["outcome"] == "confirmed"
    assert events[1]["card"]["result"]["isin"] == FIRST

    _script(monkeypatch, [advisor.AdvisorError("GitHub Copilot refused the call.")])
    events = _events(_decide(loaded, second["card_id"]))
    assert _kinds(events) == ["start", "decided", "error"]
    assert events[1]["card"]["card_id"] == second["card_id"]
    assert events[1]["card"]["outcome"] == "confirmed"

    stored = _stored_cards(loaded, conversation_id)
    assert [c["outcome"] for c in stored] == ["confirmed", "confirmed"]
    assert events[1]["card"] == stored[1], "the event is the card as stored"
    assert sorted(i["isin"] for i in loaded.get("/api/watchlist").json()) == [FIRST, SECOND]
    # The server's answer to a second press, unchanged: the decision is taken
    # once. The panel no longer offers the button that asked it.
    again = _decide(loaded, second["card_id"])
    assert again.status_code == 409
    assert "already confirmed" in again.json()["detail"]


def test_a_failure_after_the_decision_says_the_decision_is_saved(loaded, monkeypatch):
    _, (first, _) = _two_cards(loaded, monkeypatch)
    _script(monkeypatch, [advisor.AdvisorError("GitHub Copilot refused the call.")])

    events = _events(_decide(loaded, first["card_id"]))

    assert events[-1]["detail"] == (
        "GitHub Copilot refused the call. Your answer to the card is saved: only "
        "this reply to it is missing."
    )


def test_a_failure_on_a_question_says_nothing_about_a_card(loaded, monkeypatch):
    """A guard: the sentence about a decision belongs to a turn that answers
    one."""
    _script(monkeypatch, [advisor.AdvisorError("GitHub Copilot refused the call.")])
    events = _events(loaded.post("/api/chat", json={"content": "How am I doing?"}))
    assert events[-1]["detail"] == "GitHub Copilot refused the call."


# --- The turn after a decision ---------------------------------------------------------


def test_the_turn_after_a_decision_ends_on_the_apps_note(loaded, monkeypatch):
    """What was decided, what still waits, and what is asked: briefly, no
    second answer, no lookup run again. Without it the turn ended on the
    cards' tool results, which a model reads as its own tools answering in
    the middle of the answer it was writing, so it went on writing it."""
    _, (first, second) = _two_cards(loaded, monkeypatch)
    seen = _script(monkeypatch, [[("text", "Added.")]])

    _events(_decide(loaded, first["card_id"]))

    note = seen[0]["messages"][-1]
    assert note["role"] == "user"
    said = note["content"]
    assert said.startswith("THE READER HAS JUST ANSWERED A CARD")
    assert f'They accepted "{first["title"]}": it is on their watchlist now.' in said
    assert f'Still waiting for their answer, from the same reply: "{second["title"]}".' in said
    assert "do not run again the lookups" in said
    assert "running a tool again is for a new question" in said
    # The exchange the note follows is still the protocol's: the cards' calls,
    # then one tool turn each, the first confirmed and the second waiting.
    tool_turns = [m for m in seen[0]["messages"] if m["role"] == "tool"]
    assert [json.loads(m["content"])["outcome"] for m in tool_turns] == ["confirmed", "pending"]


def test_after_the_second_decision_the_request_ends_on_the_note_not_on_the_models_words(
    loaded, monkeypatch
):
    """After the first card's reply, the second request must end on app words,
    not on the model's prior answer."""
    _, (first, second) = _two_cards(loaded, monkeypatch)
    _script(monkeypatch, [[("text", "The first one is on your watchlist.")]])
    _events(_decide(loaded, first["card_id"]))

    seen = _script(monkeypatch, [[("text", "And the second.")]])
    _events(_decide(loaded, second["card_id"]))

    sent = seen[0]["messages"]
    assert sent[-2] == {"role": "assistant", "content": "The first one is on your watchlist."}
    assert sent[-1]["role"] == "user"
    assert f'They accepted "{second["title"]}"' in sent[-1]["content"]
    assert "Still waiting" not in sent[-1]["content"], "nothing else waits"


def test_a_rejection_is_said_and_not_proposed_again(loaded, monkeypatch):
    _, (first, _) = _two_cards(loaded, monkeypatch)
    seen = _script(monkeypatch, [[("text", "Fine.")]])

    _events(_decide(loaded, first["card_id"], "reject"))

    said = seen[0]["messages"][-1]["content"]
    assert f'They rejected "{first["title"]}": nothing was written.' in said
    assert "Do not propose it again unless they ask for it." in said


def test_the_turn_after_a_decision_is_asked_twice_at_most(loaded, monkeypatch):
    """The reader's bound (2026-10-08): one round with the tools, then one
    with none. A model that reads the note answers on the first; one that
    looks something up anyway gets its result and one round to write in."""
    _, (first, _) = _two_cards(loaded, monkeypatch)
    lookup = (
        "tool_call",
        advisor.ToolCall(id="call_9", name="search_catalogue", arguments='{"query": "example"}'),
    )
    seen = _script(monkeypatch, [[lookup], [lookup, ("text", "Added.")]])

    events = _events(_decide(loaded, first["card_id"]))

    assert _kinds(events)[-1] == "done"
    assert len(seen) == 2 == chat.DECISION_ROUNDS
    assert seen[0]["tools"] is not None, "the first round keeps the tools, and the cache with them"
    assert seen[1]["tools"] is None, "the second can only write"


def test_the_turn_after_a_decision_carries_no_deadline(loaded, monkeypatch):
    """A guard. The last-round notice says "propose it NOW"; the turn after a
    decision is told the opposite, and is never told both."""
    _, (first, _) = _two_cards(loaded, monkeypatch)
    lookup = (
        "tool_call",
        advisor.ToolCall(id="call_9", name="search_catalogue", arguments='{"query": "example"}'),
    )
    seen = _script(monkeypatch, [[lookup], [("text", "Added.")]])

    _events(_decide(loaded, first["card_id"]))

    for asked in seen:
        assert chat.LAST_TOOL_ROUND_NOTICE not in asked["system"]
        assert all(chat.LAST_TOOL_ROUND_NOTICE not in str(m.get("content")) for m in asked["messages"])


# --- No request ends on the model's own words --------------------------------------------


def _last_roles(seen: list[dict]) -> list[str]:
    return [asked["messages"][-1]["role"] for asked in seen]


def test_no_request_the_chat_sends_ends_on_the_models_own_words(loaded, monkeypatch):
    """Every shape of turn the reader's round went through, and one more: a
    question; a decision on a card; a decision after another card's reply; a
    question after that; and a decision on a card left waiting while a later
    question was answered. Each request ends on the reader's question, a tool
    result, or the app's note, never on the model."""
    conversation_id, (first, second) = _two_cards(loaded, monkeypatch)

    decided = _script(monkeypatch, [[("text", "Added.")]])
    _events(_decide(loaded, first["card_id"]))

    asked_later = _script(monkeypatch, [[("text", "Something else, answered.")]])
    _events(
        loaded.post(
            "/api/chat",
            json={"content": "Something else?", "conversation_id": conversation_id},
        )
    )

    decided_later = _script(monkeypatch, [[("text", "Added too.")]])
    _events(_decide(loaded, second["card_id"]))

    asked = decided + asked_later + decided_later
    assert len(asked) == 3
    assert "assistant" not in _last_roles(asked)


