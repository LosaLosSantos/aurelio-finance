"""The chat knows what it did before, and what became of each of its cards.

Brief AN (2026-10-10), item 9 and the part of item 1 that is about cards.

What it called. A past answer used to reach the model as its words and its
cards, and the read tools it had called were dropped (`chat._wire`). On
2026-10-02 the chat, re-reading its own "I searched twice", saw no search and
retracted three true statements as invented (the record's bullet "The chat
retracts true statements because it cannot see its own past tool calls").
Each past call now goes back in the protocol's own shape, the call as the model
made it, answered by one fixed line: its result is not kept, what it found is
in the words written from it. A call that was refused goes back with its
refusal. Those bytes never change once the turn is over, so a later turn still
reads them from the cache (brief AM's test, `test_every_turn_reads_the_one_
before.py`, holds with them).

What became of a card. Confirmed, rejected, or stale: a card refused at its
confirmation because what it was drawn against had changed is stored as
stale, can no longer be decided, and is read back as stale by the next turn.
Until now the refusal stored nothing, and every later turn read the card as
still waiting.

How many. Up to three cards in one answer, of any kind, each confirmed on its
own (the reader, 2026-10-10; the three were suggestions only, 2026-10-06), and
never two for one record: confirming the first would leave the second stale.

The model is faked at `advisor.stream_llm`; the tools are the real ones.
"""

from __future__ import annotations

import json

import pytest

from app import advisor, chat, crud, models
from app.database import SessionLocal

QUESTION = "How did you react to the 2022 fall?"


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    """`stream_llm` answering each round from `rounds`, keeping what each was
    asked. A round past the script is an AssertionError, never a replay."""
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        seen.append({"system": system_prompt, "messages": list(messages), "tools": tools})
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        yield from rounds[len(seen) - 1]

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def _call(name: str, arguments: dict | str, call_id: str) -> tuple:
    said = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ("tool_call", advisor.ToolCall(id=call_id, name=name, arguments=said))


def _ask(client, content: str, conversation_id: int | None = None) -> list[dict]:
    return _events(
        client.post("/api/chat", json={"content": content, "conversation_id": conversation_id})
    )


def _decide(client, card_id: str, decision: str = "confirm"):
    return client.post(f"/api/chat/cards/{card_id}", json={"decision": decision})


def _answered(client, answer: str) -> None:
    """An answer in the questionnaire to a question the form does not ask."""
    saved = client.put(
        "/api/survey",
        json=[{"question_key": "how_did_you_react", "topic": "Behaviour", "question": QUESTION, "answer": answer}],
    )
    assert saved.status_code == 200, saved.text


def _changes_the_answer(client, monkeypatch, to: str) -> tuple[int, dict]:
    _script(
        monkeypatch,
        [[("text", "I can change it:"), _call("update_profile", {"question": QUESTION, "answer": to}, "call_1")]],
    )
    events = _ask(client, "In 2022 I bought more, write it down")
    (card,) = [e["card"] for e in events if e["kind"] == "card"]
    return events[0]["conversation_id"], card


def _stored_card(card_id: str) -> dict:
    with SessionLocal() as db:
        return crud.find_chat_card(db, card_id)[1]


# --- What became of a card -------------------------------------------------------------


def test_a_card_refused_as_stale_is_stored_as_stale(client, monkeypatch):
    """The answer changed in another window between the card and its
    confirmation: refused, nothing written, and the card says so for good."""
    _answered(client, "I held.")
    _, card = _changes_the_answer(client, monkeypatch, "I bought more.")
    _answered(client, "I sold half.")

    refused = _decide(client, card["card_id"])

    assert refused.status_code == 409
    assert "no longer what would happen" in refused.json()["detail"]
    assert _stored_card(card["card_id"])["outcome"] == "stale"
    assert [a["answer"] for a in client.get("/api/survey").json()] == ["I sold half."]


@pytest.mark.parametrize("decision", ["confirm", "reject"])
def test_a_stale_card_is_not_decided_again(client, monkeypatch, decision):
    _answered(client, "I held.")
    _, card = _changes_the_answer(client, monkeypatch, "I bought more.")
    _answered(client, "I sold half.")
    assert _decide(client, card["card_id"]).status_code == 409

    again = _decide(client, card["card_id"], decision)

    assert again.status_code == 409
    assert "no longer what would happen" in again.json()["detail"]
    assert _stored_card(card["card_id"])["outcome"] == "stale"


def test_the_next_turn_reads_that_the_card_went_stale(client, monkeypatch):
    _answered(client, "I held.")
    conversation_id, card = _changes_the_answer(client, monkeypatch, "I bought more.")
    _answered(client, "I sold half.")
    _decide(client, card["card_id"])

    seen = _script(monkeypatch, [[("text", "It changed meanwhile.")]])
    _ask(client, "what happened?", conversation_id)

    (result,) = [m for m in seen[0]["messages"] if m["role"] == "tool"]
    said = json.loads(result["content"])
    assert said["outcome"] == "stale"
    assert "nothing was written" in said["note"]


def test_a_card_whose_ground_did_not_move_is_still_confirmed(client, monkeypatch):
    """A guard: storing a refusal changes nothing for a card that is not stale."""
    _answered(client, "I held.")
    _, card = _changes_the_answer(client, monkeypatch, "I bought more.")
    _script(monkeypatch, [[("text", "Changed.")]])
    assert _decide(client, card["card_id"]).status_code == 200
    assert _stored_card(card["card_id"])["outcome"] == "confirmed"


# --- What it called ----------------------------------------------------------------------


def test_a_later_turn_reads_each_tool_an_earlier_turn_called(client, monkeypatch):
    """The call as the model made it, answered by the fixed line, between the
    words written before it and after it."""
    _script(
        monkeypatch,
        [
            [("text", "Let me look. "), _call("search_catalogue", {"query": "small cap"}, "call_9")],
            [("text", "The registry is empty.")],
        ],
    )
    conversation_id = _ask(client, "a small cap fund?")[0]["conversation_id"]

    seen = _script(monkeypatch, [[("text", "Yes, I searched.")]])
    _ask(client, "did you search?", conversation_id)

    sent = seen[0]["messages"]
    asked_first = next(i for i, m in enumerate(sent) if m["role"] == "user" and "a small cap fund?" in m["content"])
    assert sent[asked_first + 1 : asked_first + 4] == [
        {
            "role": "assistant",
            "content": "Let me look. ",
            "tool_calls": [
                {
                    "id": "call_9",
                    "type": "function",
                    "function": {"name": "search_catalogue", "arguments": '{"query": "small cap"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_9",
            "content": json.dumps({"ok": True, "note": chat.PAST_CALL}),
        },
        {"role": "assistant", "content": "The registry is empty."},
    ]
    assert sent[-1]["role"] == "user" and "did you search?" in sent[-1]["content"]


def test_a_call_that_was_refused_is_read_back_with_its_refusal(client, monkeypatch):
    _script(
        monkeypatch,
        [
            [_call("search_catalogue", "{not json", "call_3")],
            [("text", "I could not search.")],
        ],
    )
    conversation_id = _ask(client, "search?")[0]["conversation_id"]
    seen = _script(monkeypatch, [[("text", "Right.")]])
    _ask(client, "so?", conversation_id)

    calls = [m for m in seen[0]["messages"] if m.get("tool_calls")]
    assert calls[0]["content"] is None
    assert calls[0]["tool_calls"][0]["function"] == {"name": "search_catalogue", "arguments": "{}"}
    (result,) = [m for m in seen[0]["messages"] if m["role"] == "tool"]
    said = json.loads(result["content"])
    assert said["ok"] is False and "not valid JSON" in said["error"]


def test_a_call_stored_before_its_arguments_were_kept_is_read_back_without_them(client, monkeypatch):
    """A conversation stored before this brief: its tool blocks carry no call
    id and no arguments. The call still goes back, with an id made from where
    it is stored, and its line says the arguments were not kept."""
    with SessionLocal() as db:
        conv = crud.create_chat_conversation(db)
        crud.append_chat_message(db, conv, "user", [{"kind": "text", "text": "a fund?"}])
        answer = crud.append_chat_message(
            db,
            conv,
            "assistant",
            [
                {"kind": "text", "text": "Ho cercato. "},
                {"kind": "tool", "name": "search_catalogue", "ok": True, "detail": None},
                {"kind": "text", "text": "Niente."},
            ],
            status="done",
        )
        conversation_id, message_id = conv.id, answer.id

    seen = _script(monkeypatch, [[("text", "Sì.")]])
    _ask(client, "hai cercato?", conversation_id)

    sent = seen[0]["messages"]
    (call,) = [m for m in sent if m.get("tool_calls")]
    assert call["tool_calls"] == [
        {
            "id": f"past_{message_id}_1",
            "type": "function",
            "function": {"name": "search_catalogue", "arguments": "{}"},
        }
    ]
    (result,) = [m for m in sent if m["role"] == "tool"]
    assert json.loads(result["content"]) == {"ok": True, "note": chat.PAST_CALL_UNKEPT}


def test_a_tool_block_keeps_its_call_id_and_its_arguments(client, monkeypatch):
    """What the next turn is rebuilt from, as stored."""
    _script(
        monkeypatch,
        [
            [_call("search_catalogue", {"query": "small cap", "limit": 3}, "call_4")],
            [("text", "Nothing.")],
        ],
    )
    conversation_id = _ask(client, "a small cap fund?")[0]["conversation_id"]
    answer = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"][1]
    (block,) = [b for b in answer["blocks"] if b["kind"] == "tool"]
    assert block == {
        "kind": "tool",
        "name": "search_catalogue",
        "ok": True,
        "detail": None,
        "call_id": "call_4",
        "arguments": {"query": "small cap", "limit": 3},
    }


# --- How many cards ----------------------------------------------------------------------


def _thing(n: int) -> dict:
    return {"name": f"invented thing {n}", "value": 10 * n, "currency": "EUR"}


def test_up_to_three_cards_of_any_kind_in_one_answer(client, monkeypatch):
    """Two assets, an answer in the questionnaire, and a third asset: three
    cards, and the fourth is refused where it was asked for, in words."""
    _script(
        monkeypatch,
        [
            [
                _call("add_real_asset", _thing(1), "call_1"),
                _call("add_real_asset", _thing(2), "call_2"),
                _call("update_profile", {"question": QUESTION, "answer": "I held."}, "call_3"),
                _call("add_real_asset", _thing(4), "call_4"),
            ]
        ],
    )
    events = _ask(client, "record all of it")

    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert [c["tool"] for c in cards] == ["add_real_asset", "add_real_asset", "update_profile"]
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert refused["name"] == "add_real_asset"
    assert refused["detail"] == (
        "3 cards are already up in this answer, the most one answer holds, so this one "
        "was not drawn: say so, and draw it in the next answer if they still want it."
    )


def test_never_two_cards_for_one_record_in_one_answer(client, monkeypatch):
    """Two changes of the same answer: confirming the first would leave the
    second stale, so the second is not drawn."""
    _answered(client, "I held.")
    _script(
        monkeypatch,
        [
            [
                _call("update_profile", {"question": QUESTION, "answer": "I bought more."}, "call_1"),
                _call("update_profile", {"question": QUESTION, "answer": "I sold."}, "call_2"),
            ]
        ],
    )
    events = _ask(client, "change it twice")

    assert len([e for e in events if e["kind"] == "card"]) == 1
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert refused["detail"] == (
        f'This answer already has a card for the answer to "{QUESTION}": one card a '
        "record, since confirming one would leave the other out of date."
    )


def test_cards_that_each_add_a_new_row_are_not_one_record(client, monkeypatch):
    """A guard: two new assets are two records."""
    _script(
        monkeypatch,
        [[_call("add_real_asset", _thing(1), "call_1"), _call("add_real_asset", _thing(2), "call_2")]],
    )
    events = _ask(client, "two things")
    assert len([e for e in events if e["kind"] == "card"]) == 2
    assert [e for e in events if e["kind"] == "tool"] == []


def test_the_prompt_says_what_the_chat_reads_of_its_past_turns():
    """Brief AB's rule said past turns reach the model as words alone; they now
    carry their calls, and not what the calls returned."""
    for model in ("anthropic/claude-opus-5.5", "qwen/qwen3.8-max-0902"):
        prompt = chat.system_prompt(model)
        assert "without the lookups behind them" not in prompt
        assert (
            "Your earlier turns reach you with the tools they called and what became "
            "of their cards, but not what the tools returned"
        ) in prompt
        assert "up to three cards in one answer, of any kind" in prompt
