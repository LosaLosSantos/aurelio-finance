"""An answer that did not finish is not an answer.

The first real analysis, on 2026-10-02, built five steps on an analyst's text
that stopped at "The top four": `call_llm` refused only an EMPTY answer and
never read how an answer ended, so a cut one was stored as a whole one. The
chat had the same blind spot on its streaming side, where a cut answer was
stored as `done`.

What a cut looks like was measured on the wire before this was built
(2026-10-02, four paid calls): a token cap gives `finish_reason:
"length"` on both paths, with `native_finish_reason` "max_tokens" from
Anthropic and "length" from Alibaba, and a model that spends the cap reasoning
writes nothing at all. A provider failing partway is OpenRouter's documented
shape, not a measurement: a chunk carrying a top-level `error` and
`finish_reason: "error"` on a stream, a 200 holding only `error` on a plain
request.

So these tests go through the real `call_llm` and `stream_llm` and fake only
the transport inside the real openai client. The rule under test is how those
two read the JSON; faking the functions themselves would skip it.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, chain, models
from app.database import SessionLocal

REAL_CALL_LLM, REAL_STREAM_LLM = advisor.call_llm, advisor.stream_llm


def _completion(text, finish="stop", native=None, cost=0.004):
    """One plain answer as OpenRouter sends it. `cost=None` leaves the price out
    of `usage`, the way a provider that does not say leaves it out."""
    usage = {"prompt_tokens": 40, "completion_tokens": 16, "total_tokens": 56}
    if cost is not None:
        usage["cost"] = cost
    return 200, {
        "id": "gen-test",
        "object": "chat.completion",
        "created": 1,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish,
                "native_finish_reason": native,
            }
        ],
        "usage": usage,
    }


def _chunk(content=None, finish=None, native=None, tool=None):
    """One chunk of a streamed answer; the finish reason is null on all but the
    last ones, as on the wire."""
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tool is not None:
        delta["tool_calls"] = [tool]
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish, "native_finish_reason": native}
        ],
    }


# The chunk a stream ends with when it was asked to report usage: no choice,
# only what the provider counted.
USAGE = {
    "id": "gen-test",
    "object": "chat.completion.chunk",
    "created": 1,
    "model": "m",
    "choices": [],
    "usage": {"prompt_tokens": 40, "completion_tokens": 16, "total_tokens": 56, "cost": 0.001},
}

LOOK_THROUGH = {
    "index": 0,
    "id": "call_1",
    "type": "function",
    "function": {"name": "get_look_through", "arguments": "{}"},
}


def _stream(*chunks, done=True):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    return 200, (body + ("data: [DONE]\n\n" if done else "")).encode()


@pytest.fixture
def openrouter(monkeypatch):
    """OpenRouter answering each call with the next entry of `openrouter.script`,
    and refusing any call past it with a 500. Scripts are written so that
    today's code, which goes on after a cut step, runs to the end: a run that
    raised only because it fell off the script would pass for the wrong
    reason."""

    class Fake:
        script: list = []
        asked: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.asked.append(json.loads(request.content))
        if not Fake.script:
            return httpx.Response(500, json={"error": {"code": 500, "message": "past the script"}})
        status, body = Fake.script.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(status, json=body)

    def client():
        return advisor.sdk().OpenAI(
            base_url=advisor.OPENROUTER_BASE_URL,
            api_key="invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    monkeypatch.setattr(advisor, "call_llm", REAL_CALL_LLM)
    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "_client", client)
    return Fake


def _drain(db):
    walk = chain.run_chain(db)
    while True:
        try:
            next(walk)
        except StopIteration as done:
            return done.value


def _rows(db) -> tuple[int, int]:
    return db.query(models.ChainRun).count(), db.query(models.ChainStep).count()


def _reads_as_words(sentence: str) -> None:
    # chr(0x2014) is the em dash and chr(0x2013) the en dash, kept out of the
    # source like the other test that forbids them.
    for raw in ("{", "}", "AdvisorError", "Unfinished", chr(0x2014), f" {chr(0x2013)} "):
        assert raw not in sentence, f"{raw!r} in: {sentence}"


FITS = "Nothing here needs answering.\n\nVERDICT: FITS"


# --- The analysis --------------------------------------------------------------


@pytest.mark.parametrize(
    "finish, native",
    [
        ("length", "max_tokens"),  # Anthropic, measured
        ("length", "length"),  # Alibaba, measured
        ("content_filter", None),
        ("error", "error"),
        (None, None),  # nobody said it finished
        ("tool_calls", "tool_use"),  # the chain offers no tools
    ],
)
def test_a_first_step_that_did_not_finish_stops_the_run_and_keeps_nothing(
    client, openrouter, finish, native
):
    openrouter.script = [
        _completion("Japan: 5.0%\n\nThe top four", finish=finish, native=native),
        _completion(FITS),
        _completion("The verdict."),
    ]
    with SessionLocal() as db:
        with pytest.raises(advisor.AdvisorError) as stopped:
            _drain(db)
        assert _rows(db) == (0, 0)
    assert len(openrouter.asked) == 1, "the run went on after a step that did not finish"
    said = str(stopped.value)
    assert 'The analysis stopped at step 1, "The numbers, on their own merits", and nothing from this run was kept.' in said
    _reads_as_words(said)


def test_a_later_step_that_did_not_finish_stops_the_run_and_keeps_nothing(client, openrouter):
    openrouter.script = [
        _completion("The findings.", cost=0.004),
        _completion(FITS, cost=0.003),
        _completion("You should first", finish="length", native="max_tokens", cost=0.002),
    ]
    with SessionLocal() as db:
        with pytest.raises(advisor.AdvisorError) as stopped:
            _drain(db)
        assert _rows(db) == (0, 0)
    said = str(stopped.value)
    assert said.startswith(
        "The model stopped before finishing its answer: it reached its length limit "
        "(OpenRouter reported length, the provider max_tokens)."
    ), said
    assert 'The analysis stopped at step 3, "What this means for you", and nothing from this run was kept.' in said
    # The cut step is billed like any other, so its own price is in the sum.
    assert "Until it stopped it had cost $0.009, as OpenRouter reported it." in said
    _reads_as_words(said)


def test_a_run_whose_every_step_stopped_normally_is_kept_as_before(client, openrouter):
    openrouter.script = [_completion("The findings."), _completion(FITS), _completion("The verdict.")]
    with SessionLocal() as db:
        run = _drain(db)
        assert [s.role for s in run.steps] == ["analyst", "confidant", "synthesis"]
        assert [s.cost for s in run.steps] == [0.004, 0.004, 0.004]
        assert run.verdict == "The verdict."
        assert _rows(db) == (1, 3)


def test_a_step_whose_price_was_not_reported_is_unknown_never_zero(client, openrouter):
    openrouter.script = [
        _completion("The findings.", cost=0.004),
        _completion(FITS, cost=None),
        _completion("You should first", finish="length", native="max_tokens", cost=0.002),
    ]
    with SessionLocal() as db:
        with pytest.raises(advisor.AdvisorError) as stopped:
            _drain(db)
    said = str(stopped.value)
    assert (
        "OpenRouter reported $0.006 for steps 1 and 3 and no price for step 2, "
        "so what the run cost is not known."
    ) in said
    assert "had cost" not in said


def test_a_step_that_failed_says_where_the_analysis_stopped(client, openrouter):
    """Not a cut: a refusal, which already stopped the run. What it lacked was
    the step it stopped at, that nothing was kept, and what had been spent."""
    openrouter.script = [
        _completion("The findings.", cost=0.004),
        (502, {"error": {"code": 502, "message": "Provider returned error"}}),
    ]
    with SessionLocal() as db:
        with pytest.raises(advisor.AdvisorError) as stopped:
            _drain(db)
        assert _rows(db) == (0, 0)
    said = str(stopped.value)
    assert said.startswith("OpenRouter refused the call to "), said
    assert 'The analysis stopped at step 2, "Where this would fail this person", and nothing from this run was kept.' in said
    assert "OpenRouter reported $0.004 for step 1 and no price for step 2, so what the run cost is not known." in said
    _reads_as_words(said)


def test_a_plain_answer_that_failed_partway_says_what_the_provider_said(openrouter):
    """OpenRouter's documented shape for a provider failing partway through a
    plain request: a 200 whose body holds only `error`. It was refused already,
    but as "an empty response", with the provider's words dropped."""
    openrouter.script = [(200, {"error": {"code": 502, "message": "Provider returned error"}})]
    with pytest.raises(advisor.AdvisorError) as stopped:
        advisor.call_llm("s", "u", model="m")
    said = str(stopped.value)
    assert "Provider returned error" in said
    assert "empty response" not in said
    _reads_as_words(said)


def test_a_model_that_spent_its_limit_reasoning_is_said_to_have_written_nothing(openrouter):
    """Measured on qwen3.8-max-0902: all 16 tokens of the cap went to reasoning
    and `content` came back null. Refused before, but as an empty response,
    which says nothing about why."""
    openrouter.script = [_completion(None, finish="length", native="length", cost=0.000248)]
    with pytest.raises(advisor.Unfinished) as stopped:
        advisor.call_llm("s", "u", model="m")
    assert str(stopped.value) == (
        "The model stopped before writing its answer: it reached its length limit "
        "(OpenRouter reported length)."
    )
    assert stopped.value.cost == 0.000248


# --- The chat ----------------------------------------------------------------------


def _ask(client) -> list[dict]:
    response = client.post(
        "/api/chat", json={"content": "How many months does my cash cover?", "conversation_id": None}
    )
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _stored_answer(client, events) -> dict:
    cid = events[0]["conversation_id"]
    return client.get(f"/api/chat/conversations/{cid}").json()["messages"][1]


def _text(message: dict) -> str:
    return "".join(b["text"] for b in message["blocks"] if b["kind"] == "text")


def test_a_chat_answer_the_provider_cut_is_kept_and_never_stored_as_done(client, openrouter):
    openrouter.script = [
        _stream(_chunk("Your cash covers "), _chunk("about"), _chunk("", "length", "max_tokens"), USAGE)
    ]
    events = _ask(client)
    assert [e["kind"] for e in events] == ["start", "delta", "delta", "error"]
    answer = _stored_answer(client, events)
    assert answer["status"] == "error"
    assert _text(answer) == "Your cash covers about", "the words the reader saw are the words on record"
    assert answer["detail"] == (
        "The model stopped before finishing its answer: it reached its length limit "
        "(OpenRouter reported length, the provider max_tokens)."
    )
    # What the turn was sent is still recorded: the cost of a cut turn is not
    # the cost of no turn.
    with SessionLocal() as db:
        stored = db.get(models.ChatMessage, answer["id"])
        assert stored.prompt_tokens == 40


def test_a_stream_that_closed_without_saying_it_finished_is_not_done(client, openrouter):
    openrouter.script = [_stream(_chunk("Your cash covers "), _chunk("about"), done=False)]
    events = _ask(client)
    assert [e["kind"] for e in events] == ["start", "delta", "delta", "error"]
    assert events[-1]["detail"] == (
        "The model stopped before finishing its answer: the provider never said it had finished."
    )


def test_a_round_cut_while_asking_for_a_tool_runs_no_tool(client, openrouter):
    """A call whose arguments may have stopped mid-JSON is not run: nothing
    finished asking for it."""
    openrouter.script = [
        _stream(_chunk(tool=LOOK_THROUGH), _chunk(None, "length", "max_tokens"), USAGE),
        _stream(_chunk("Nothing to look inside yet."), _chunk("", "stop", "end_turn"), USAGE),
    ]
    events = _ask(client)
    assert "tool" not in [e["kind"] for e in events]
    assert events[-1]["kind"] == "error"
    assert len(openrouter.asked) == 1


def test_a_round_that_ended_on_its_tool_calls_still_runs_them(client, openrouter):
    openrouter.script = [
        _stream(_chunk(tool=LOOK_THROUGH), _chunk(None, "tool_calls", "tool_use"), USAGE),
        _stream(_chunk("Nothing to look inside yet."), _chunk("", "stop", "end_turn"), USAGE),
    ]
    events = _ask(client)
    assert [e["kind"] for e in events] == ["start", "tool", "delta", "done"]


def test_a_chat_answer_that_stopped_normally_is_done(client, openrouter):
    openrouter.script = [_stream(_chunk("Six months."), _chunk("", "stop", "end_turn"), USAGE)]
    events = _ask(client)
    assert [e["kind"] for e in events] == ["start", "delta", "done"]
    assert _stored_answer(client, events)["status"] == "done"
