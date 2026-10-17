"""Copilot token usage is recorded on each completed or failed chat turn.

Usage is summed across tool rounds. Missing figures remain null rather than
becoming invented zeroes, and cached input is recorded separately. Copilot
subscription usage is not a USD price, so the cost field remains empty.
"""

from __future__ import annotations

import json


from app import advisor, crud, models
from app.database import SessionLocal



def _ask(client, content: str = "quanto ho da parte?"):
    return client.post("/api/chat", json={"content": content, "conversation_id": None})


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    out = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.split("\n")
        out.append(json.loads(lines[1][len("data: "):]))
    return out


def _answers() -> list[models.ChatMessage]:
    with SessionLocal() as db:
        conv = crud.get_chat_conversations(db)[0]
        return [
            m
            for m in crud.get_chat_conversation(db, conv.id).messages
            if m.role == "assistant"
        ]


def _streams(monkeypatch, *rounds) -> None:
    """Script the model round by round, each round a list of yielded pairs."""
    seen: list[int] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        seen.append(1)
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        yield from rounds[len(seen) - 1]

    monkeypatch.setattr(advisor, "stream_llm", fake)


def _used(prompt: int | None, cached: int | None = None, cost: float | None = None):
    """One round's usage, as `stream_llm` yields it."""
    return ("usage", advisor.Usage(prompt_tokens=prompt, cached_tokens=cached, cost=cost))


def test_a_turn_records_what_the_provider_says_it_received(client, monkeypatch):
    _streams(monkeypatch, [("text", "Hai 17.992 euro."), _used(11119)])

    _ask(client)

    (answer,) = _answers()
    assert answer.prompt_tokens == 11119


def test_a_turn_that_called_a_tool_paid_for_every_round(client, monkeypatch):
    """Two completions, two prompts, and the second one carries the first
    round's words and the tool's result on top of everything the first was
    sent. Recording only one of them would report a turn as costing less than
    it did — and the tool-using turns are the expensive ones."""
    _streams(
        monkeypatch,
        [
            ("tool_call", advisor.ToolCall(id="c1", name="get_look_through", arguments="{}")),
            _used(11119),
        ],
        [("text", "I tuoi fondi si sovrappongono."), _used(12750)],
    )

    _ask(client)

    (answer,) = _answers()
    assert answer.prompt_tokens == 11119 + 12750


def test_a_provider_that_says_nothing_records_nothing(client, monkeypatch):
    """Not zero. The chat model is configurable, so a provider that reports no
    usage is a real case, and a turn stored as costing 0 tokens would be a
    measurement nobody made — the exact failure this column exists to end. The
    same holds for the two figures beside it."""
    _streams(monkeypatch, [("text", "Hai 17.992 euro.")])

    _ask(client)

    (answer,) = _answers()
    assert (answer.prompt_tokens, answer.cached_tokens, answer.cost) == (None, None, None)


def test_an_answer_that_broke_still_records_what_it_was_sent(client, monkeypatch):
    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        yield _used(11119, cached=0)
        raise advisor.AdvisorError("Copilot stream failed: connection reset")

    monkeypatch.setattr(advisor, "stream_llm", fake)
    _ask(client)

    (answer,) = _answers()
    assert (answer.status, answer.prompt_tokens, answer.cost) == ("error", 11119, None)


def test_the_reader_is_not_shown_token_usage(client, monkeypatch):
    """Usage metadata belongs to the stored turn, not the answer stream."""
    _streams(monkeypatch, [("text", "Hai 17.992 euro."), _used(11119, cached=0)])

    events = _events(_ask(client))

    assert [e["kind"] for e in events] == ["start", "delta", "done"]
    assert "11119" not in json.dumps(_answers()[0].blocks)


# --- Cached input ------------------------------------------------------------


def test_a_turn_records_cached_tokens_across_rounds(client, monkeypatch):
    _streams(
        monkeypatch,
        [
            ("tool_call", advisor.ToolCall(id="c1", name="get_look_through", arguments="{}")),
            _used(12039, cached=0),
        ],
        [("text", "I tuoi fondi si sovrappongono."), _used(13246, cached=12035)],
    )
    _ask(client)

    (answer,) = _answers()
    assert answer.prompt_tokens == 12039 + 13246
    assert answer.cached_tokens == 12035
    assert answer.cost is None


def test_nothing_read_from_the_cache_is_a_zero_and_not_a_gap(client, monkeypatch):
    _streams(monkeypatch, [("text", "Hai 17.992 euro."), _used(12039, cached=0)])
    _ask(client)

    (answer,) = _answers()
    assert answer.cached_tokens == 0
