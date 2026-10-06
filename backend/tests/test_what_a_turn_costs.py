"""What a turn was sent, recorded on the turn.

The figure this replaces lived in `chat.py`'s docstring: "2,237 tokens —
measured, not estimated". It was measured, once, on a saved portfolio, and by
2026-09-17 the same picture on the same portfolio was
3,748 tokens and the whole turn around it 11,119 — of which the tool
declarations alone were 4,842. Nothing was wrong with the measurement; what was
wrong was keeping it in prose, where nothing recomputes it and nothing notices
it has drifted.

So a turn records what the provider says it received, the way a chain step
records what the provider says it cost. The rules the tests below pin:

- summed across the turn's rounds, because a turn that calls a tool asks the
  model again with the whole conversation, and pays for it again;
- null, never zero, when the provider does not report usage — a zero is a
  measurement and "it did not say" is not;
- recorded even when the answer failed, because a turn that broke still cost
  what it was sent;
- never shown as an event: the reader asked a question, not for a receipt.

Since the chat asks Anthropic's models to cache (brief AD, 2026-10-05), the
token count stopped saying what a turn cost: on Opus 5.5 a token read from
the cache was billed at a twentieth of the input price. So the turn also records how many
of its tokens came from the cache, where a zero IS an answer (nothing came),
and what it cost, which is unknown, not smaller, when any round's price went
unreported.
"""

from __future__ import annotations

import json

import pytest

from app import advisor, crud, models
from app.database import SessionLocal

# The genuine generator, captured before the autouse `offline` fixture swaps it
# for a refusal — one test below is about the request it builds.
_REAL_STREAM_LLM = advisor.stream_llm


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

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
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
    """The input was paid for before the stream broke."""

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        yield _used(11119, cached=0, cost=0.0556)
        raise advisor.AdvisorError("LLM stream failed: connection reset")

    monkeypatch.setattr(advisor, "stream_llm", fake)

    _ask(client)

    (answer,) = _answers()
    assert (answer.status, answer.prompt_tokens, answer.cost) == ("error", 11119, 0.0556)


def test_the_reader_is_not_shown_a_receipt(client, monkeypatch):
    """A fact about the turn, not part of the answer: no event carries it, and
    no block of the stored message does either."""
    _streams(monkeypatch, [("text", "Hai 17.992 euro."), _used(11119, cached=0, cost=0.0556)])

    events = _events(_ask(client))

    assert [e["kind"] for e in events] == ["start", "delta", "done"]
    stored = json.dumps(_answers()[0].blocks)
    assert "11119" not in stored and "0.0556" not in stored


# --- What came from the cache, and what it cost ---------------------------------


def test_a_turn_records_what_its_rounds_read_from_the_cache_and_what_they_cost(
    client, monkeypatch
):
    """The figures of a turn with one tool round, shaped like the ones measured
    on 2026-10-05: the first round writes the cache, the second reads all of
    it back and pays a fraction. Both are summed, as the tokens always were."""
    _streams(
        monkeypatch,
        [
            ("tool_call", advisor.ToolCall(id="c1", name="get_look_through", arguments="{}")),
            _used(12039, cached=0, cost=0.060511),
        ],
        [("text", "I tuoi fondi si sovrappongono."), _used(13246, cached=12035, cost=0.00878)],
    )

    _ask(client)

    (answer,) = _answers()
    assert answer.prompt_tokens == 12039 + 13246
    assert answer.cached_tokens == 12035
    assert answer.cost == pytest.approx(0.060511 + 0.00878)


def test_nothing_read_from_the_cache_is_a_zero_and_not_a_gap(client, monkeypatch):
    """A cold turn, or a model that keeps no cache, reads nothing from it, and
    the provider says so. That is an answer, unlike a provider saying nothing,
    and it is stored as one."""
    _streams(monkeypatch, [("text", "Hai 17.992 euro."), _used(12039, cached=0, cost=0.060511)])

    _ask(client)

    (answer,) = _answers()
    assert answer.cached_tokens == 0


def test_a_round_whose_price_went_unsaid_makes_the_turns_cost_unknown(client, monkeypatch):
    """Never the sum of the prices that were said. The second round was paid
    for whatever it cost, so a turn stored at the first round's price alone
    would be a figure about money that is low without saying so. The tokens
    keep their own rule and are summed over what was reported."""
    _streams(
        monkeypatch,
        [
            ("tool_call", advisor.ToolCall(id="c1", name="get_look_through", arguments="{}")),
            _used(12039, cached=0, cost=0.060511),
        ],
        [("text", "I tuoi fondi si sovrappongono."), _used(13246, cached=12035, cost=None)],
    )

    _ask(client)

    (answer,) = _answers()
    assert answer.cost is None
    assert answer.prompt_tokens == 12039 + 13246


def test_the_stream_asks_the_provider_to_report_usage(monkeypatch):
    """The generator's own request. A stream reports usage only when asked to,
    so this is the line between a column that fills itself and one that stays
    null for good — and it is in a request body no test would otherwise read."""
    sent: dict = {}

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(())

    class _Completions:
        def create(self, **kwargs):
            sent.update(kwargs)
            return _Stream()

    class _Client:
        chat = type("chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(advisor, "_client", lambda: _Client())

    try:
        list(_REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}]))
    except advisor.AdvisorError:
        pass  # an empty stream is an empty response; not what this test is about

    assert sent["stream_options"] == {"include_usage": True}
