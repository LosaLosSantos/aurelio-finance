"""A confirmed card's write reaches the next turn's rebuilt context."""

from __future__ import annotations

import json

from app import advisor

def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        seen.append({"system": system_prompt, "messages": list(messages)})
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        yield from rounds[len(seen) - 1]

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def test_the_turn_after_a_confirmed_card_reads_its_write_in_the_picture_above_the_question(
    client, monkeypatch
):
    """What the prompt says, held to the code: the picture the question was
    asked with has no such line, and the picture of the turn that answers the
    card has it, at the top, before the question that asked for it."""
    bank = client.post("/api/institutions", json={"name": "Example Bank"}).json()["id"]
    anchored = client.post(
        f"/api/institutions/{bank}/cash-anchors",
        json={"date": "2026-09-30", "amount": 2000.0, "currency": "EUR"},
    )
    assert anchored.status_code == 201, anchored.text
    arguments = {
        "action": "add", "side": "expense", "name": "Climbing gym", "account": "Example Bank",
        "amount": 45, "first_payment": "2026-11-03", "nature": "discretionary",
        "category": "leisure",
    }
    call = advisor.ToolCall(id="call_1", name="write_flow", arguments=json.dumps(arguments))
    asked = _script(monkeypatch, [[("text", "Here it is:"), ("tool_call", call)]])
    events = _events(client.post("/api/chat", json={"content": "Add the climbing gym, 45 a month."}))
    card = next(e["card"] for e in events if e["kind"] == "card")
    assert "Climbing gym" not in asked[0]["messages"][0]["content"]

    answered = _script(monkeypatch, [[("text", "Done.")]])
    _events(client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}))

    messages = answered[0]["messages"]
    assert "Climbing gym" in messages[0]["content"]
    question = next(
        i for i, m in enumerate(messages) if "Add the climbing gym" in json.dumps(m["content"])
    )
    assert question > 0
    assert "newer than everything after it" in answered[0]["system"]
