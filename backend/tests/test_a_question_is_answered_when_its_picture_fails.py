"""A question is answered even when the picture of the records cannot be built.

Issue #4's sessions, 2026-10-18: `chat.prepare` stored the question, then built
the picture, and the route caught only a conversation that does not exist. Any
failure while the picture was built answered 500 with the question already
stored. Measured at `c61e5bc` (brief BE) with a picture that raises: a new
conversation answered 500 before `start`, so the browser never learnt its id
and the retry opened a second conversation, each holding a question with no
answer; an old conversation kept its question unanswered; and a card confirmed
while the picture failed ran its write, was stored confirmed, and answered 500
with no reply, a second confirmation 409.

The picture is now built on the stream, after `start` and after `decided`: a
failure there is an `error` like any other ending, said, stored as the turn's
answer, and nothing is asked of the model. Every name here is invented.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app import advisor, chain, chat, tools
from conftest import script_the_chain


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    out = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.split("\n")
        out.append(json.loads(lines[1][len("data: "):]))
    return out


def _kinds(events: list[dict]) -> list[str]:
    return [e["kind"] for e in events]


def _model(monkeypatch, rounds: list[list[tuple]] | None = None) -> list[list[dict]]:
    """The model, answering "Fine." to any round, or `rounds` in order; what
    each round was sent is kept, so a test can say nothing was asked."""
    asked: list[list[dict]] = []

    def stream(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        asked.append(list(messages))
        if rounds is not None:
            yield from rounds[len(asked) - 1]
            return
        yield ("text", "Fine.")

    monkeypatch.setattr(advisor, "stream_llm", stream)
    return asked


def _the_picture_fails(monkeypatch) -> None:
    def broken(db):
        raise RuntimeError("a fault while the picture is built")

    monkeypatch.setattr(advisor, "build_context", broken)


def _the_picture_works(monkeypatch, real=advisor.build_context) -> None:
    monkeypatch.setattr(advisor, "build_context", real)


def _ask(client, content: str, conversation_id: int | None = None):
    return client.post("/api/chat", json={"content": content, "conversation_id": conversation_id})


def _conversations(client) -> list[dict]:
    return [
        client.get(f"/api/chat/conversations/{c['id']}").json()
        for c in client.get("/api/chat/conversations").json()
    ]


def _turns(conversation: dict) -> list[tuple]:
    def text(m: dict) -> str:
        return "".join(b.get("text", "") for b in m["blocks"] if b["kind"] == "text")

    return [(m["role"], text(m), m["status"], m["detail"]) for m in conversation["messages"]]


# --- A question ------------------------------------------------------------------


def test_a_new_conversation_says_where_it_is_and_answers_the_failure(client, monkeypatch):
    asked = _model(monkeypatch)
    _the_picture_fails(monkeypatch)

    events = _events(_ask(client, "How much cash do I have?"))

    assert _kinds(events) == ["start", "error"]
    assert events[0]["conversation_id"] and events[0]["user_message_id"]
    assert events[1]["detail"] == chat.PICTURE_FAILED
    assert asked == [], "nothing is asked of the model without its picture"
    (conversation,) = _conversations(client)
    assert conversation["id"] == events[0]["conversation_id"]
    assert _turns(conversation) == [
        ("user", "How much cash do I have?", None, None),
        ("assistant", "", "error", chat.PICTURE_FAILED),
    ]


def test_a_second_try_goes_to_the_same_conversation(client, monkeypatch):
    _model(monkeypatch)
    _the_picture_fails(monkeypatch)
    first = _events(_ask(client, "How much cash do I have?"))

    again = _events(_ask(client, "How much cash do I have?", first[0]["conversation_id"]))

    assert _kinds(again) == ["start", "error"]
    assert again[0]["conversation_id"] == first[0]["conversation_id"]
    (conversation,) = _conversations(client)
    assert [(role, status) for role, _, status, _ in _turns(conversation)] == [
        ("user", None), ("assistant", "error"), ("user", None), ("assistant", "error"),
    ]


def test_an_old_conversation_answers_the_failure(client, monkeypatch):
    _model(monkeypatch)
    first = _events(_ask(client, "Hello"))
    assert _kinds(first) == ["start", "delta", "done"]
    _the_picture_fails(monkeypatch)

    events = _events(_ask(client, "And my debts?", first[0]["conversation_id"]))

    assert _kinds(events) == ["start", "error"]
    (conversation,) = _conversations(client)
    assert _turns(conversation)[-2:] == [
        ("user", "And my debts?", None, None),
        ("assistant", "", "error", chat.PICTURE_FAILED),
    ]


def test_the_next_good_turn_reads_both_questions_and_no_failure(client, monkeypatch):
    _model(monkeypatch)
    _the_picture_fails(monkeypatch)
    first = _events(_ask(client, "How much cash do I have?"))
    _the_picture_works(monkeypatch)
    asked = _model(monkeypatch)

    events = _events(_ask(client, "And now?", first[0]["conversation_id"]))

    assert _kinds(events) == ["start", "delta", "done"]
    sent = [m["content"] for m in asked[0][2:]]
    assert sent == ["How much cash do I have?", "And now?"]


# --- A card ----------------------------------------------------------------------


class _Args(BaseModel):
    what: str
    amount: float


def _a_card_tool(monkeypatch) -> list[dict]:
    written: list[dict] = []
    monkeypatch.setitem(
        tools.REGISTRY,
        "record_thing",
        tools.Tool(
            name="record_thing",
            description="Record a thing.",
            arguments=_Args,
            run=lambda db, args: written.append(args.model_dump()) or {"recorded": args.what},
            propose=lambda db, args: tools.Proposal(
                title=f"record: {args.what}", fingerprint="v1", confirmation="light", diff=[]
            ),
        ),
    )
    return written


def _propose(client, monkeypatch, tool: str, arguments: str = "{}") -> dict:
    call = advisor.ToolCall(id="call_1", name=tool, arguments=arguments)
    _model(monkeypatch, rounds=[[("text", "I can do that:"), ("tool_call", call)]])
    events = _events(_ask(client, "Please do it"))
    return next(e["card"] for e in events if e["kind"] == "card")


def test_a_card_confirmed_while_the_picture_fails_keeps_its_decision(client, monkeypatch):
    written = _a_card_tool(monkeypatch)
    card = _propose(client, monkeypatch, "record_thing", '{"what": "a lamp", "amount": 40}')
    asked = _model(monkeypatch)
    _the_picture_fails(monkeypatch)

    events = _events(client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}))

    assert _kinds(events) == ["start", "decided", "error"]
    assert events[1]["card"]["outcome"] == "confirmed"
    assert events[2]["detail"] == f"{chat.PICTURE_FAILED} {chat.DECISION_KEPT}"
    assert written == [{"what": "a lamp", "amount": 40.0}]
    assert asked == []
    again = client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})
    assert again.status_code == 409
    assert written == [{"what": "a lamp", "amount": 40.0}], "written once"


def test_the_analysis_confirmed_while_the_picture_fails_keeps_its_decision(client, monkeypatch):
    """The analyzer's card is settled on the stream, after its steps: a picture
    that fails after that says the decision stands, and the run is kept."""
    card = _propose(client, monkeypatch, "run_analysis")

    def step(system_prompt, user_content, model=None):
        text = "The verdict." if system_prompt == chain.SYNTHESIS_SYSTEM_PROMPT else "a step"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += "\n\nVERDICT: FITS"
        return {"analysis": text, "model": "role/model", "cost": 0.004}

    script_the_chain(monkeypatch, step)
    asked = _model(monkeypatch)
    _the_picture_fails(monkeypatch)

    events = _events(client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}))

    assert _kinds(events) == ["start", "step", "step", "step", "decided", "error"]
    assert events[-1]["detail"] == f"{chat.PICTURE_FAILED} {chat.DECISION_KEPT}"
    assert asked == []
    runs = client.get("/api/advisor/chain")
    assert runs.status_code == 200 and len(runs.json()) == 1, "the run is kept"
