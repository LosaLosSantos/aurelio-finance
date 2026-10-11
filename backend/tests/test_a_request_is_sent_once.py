"""A request to OpenRouter is sent once, unless the reader is told.

Brief AN, item 10 (2026-10-10), closing two bullets of the record: the SDK
repeating a failed request twice without a word (found by brief Z), and the
chat's own requests keeping that default (found by brief AM). The openai SDK
(2.41.0, read in its `_constants.py` and `_base_client.py`) sends a request up
to three times on its own: again after a connection error or a timeout, and
after a 408, 409, 429 or any 5xx. The app's client took that default, so a
round of the chat or a step of the analysis could be sent three times with
nothing said, and what an attempt before the last one cost was in no record.

The chat sends each request once and says the failure (`advisor._refused`
words every status, a timeout and no connection): the reader asks again, or
picks another model, knowing.

The analysis keeps one retry, of one kind. A failed step stops the run, and
the next run starts again from the first step, so a refusal that would have
passed in a second costs the reader a whole analysis. OpenRouter answers 200
as soon as a provider accepts a request (its page on errors), so a 500, 502 or
503 means that no provider took it, and its page on failover says that a
request which fails is not billed. The same page reports 429s that consumed
credits, so a 429 is not asked again; nor is a timeout (408, 504, or the SDK's
own) or a dropped connection, where a provider may have been at work. The
step's line says when it was asked again.

Through the app's own client, with only its transport replaced: what is under
test is how that client is configured.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, chain, tools
from app.database import SessionLocal

REAL_CLIENT = advisor._client
REAL_STREAM_LLM = advisor.stream_llm
REAL_CALL_LLM = advisor.call_llm

OPUS = "anthropic/claude-opus-5.5"
COMPLETIONS = "/api/v1/chat/completions"


def _refusal(status: int, message: str) -> tuple[int, dict]:
    return status, {"error": {"code": status, "message": message}}


NO_PROVIDER = _refusal(503, "No available provider meets your routing requirements")
MODEL_DOWN = _refusal(502, "Your chosen model is down")
INTERNAL = _refusal(500, "Internal Server Error")
RATE_LIMITED = _refusal(429, "Rate limit exceeded")
TIMED_OUT = _refusal(408, "Request timed out")
GATEWAY_TIMEOUT = _refusal(504, "Gateway Timeout")


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": OPUS,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _says(text: str) -> tuple[int, bytes]:
    """A streamed answer of the chat, as OpenRouter sends it."""
    usage = {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": OPUS,
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0.0001},
    }
    chunks = [_chunk({"content": text}), _chunk({}, "stop"), usage]
    return 200, ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _answers(text: str) -> tuple[int, dict]:
    """A whole answer, as a step of the analysis receives it."""
    return 200, {
        "id": "gen-test",
        "object": "chat.completion",
        "created": 1,
        "model": OPUS,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.001},
    }


@pytest.fixture
def openrouter(monkeypatch):
    """The app's own client, its transport answering each request with the next
    entry of `openrouter.script`: a (status, body) pair, or an exception the
    transport raises. Every request is counted in `asked`."""

    class Fake:
        script: list = []
        asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.asked.append(request.url.path)
        assert Fake.script, f"request {len(Fake.asked)} is past the script"
        answer = Fake.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(status, json=body)

    def client():
        made = REAL_CLIENT()
        made._client._transport = httpx.MockTransport(handler)
        return made

    monkeypatch.setenv("OPENROUTER_API_KEY", "invalid")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", OPUS)
    for role in ("OPENROUTER_MODEL", "OPENROUTER_ANALYST_MODEL", "OPENROUTER_CONFIDANT_MODEL"):
        monkeypatch.delenv(role, raising=False)
    monkeypatch.setattr(advisor, "_client", client)
    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "call_llm", REAL_CALL_LLM)
    monkeypatch.setattr(advisor, "_fetch_model_list", lambda: {OPUS})
    Fake.script, Fake.asked = [], []
    return Fake


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _ends_on_a_sentence(events: list[dict]) -> str:
    assert events[-1]["kind"] == "error", [e["kind"] for e in events]
    return events[-1]["detail"]


# --- The chat ------------------------------------------------------------------------


def test_the_app_client_resends_nothing_by_itself(monkeypatch):
    """The setting itself, on the client every call of the app is built from:
    the chat's rounds, the analysis's steps and the web search's requests.
    Built with an invalid key, so the test does not read backend/.env, which
    a fresh clone (and CI) does not have, and sends nothing."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "invalid")
    assert REAL_CLIENT().max_retries == 0


@pytest.mark.parametrize(
    "failure",
    [NO_PROVIDER, MODEL_DOWN, INTERNAL, RATE_LIMITED, TIMED_OUT, GATEWAY_TIMEOUT],
    ids=["503", "502", "500", "429", "408", "504"],
)
def test_a_round_of_the_chat_that_is_refused_is_sent_once_and_said(client, openrouter, failure):
    """A refusal ends the answer with its sentence, after one request. The
    script holds an answer after it, which a second request would have
    received: on the code before this brief, the SDK sent that second request
    and the reader saw an answer with no word of the first."""
    openrouter.script = [failure, _says("Ciao.")]
    said = _ends_on_a_sentence(_events(client.post("/api/chat", json={"content": "ciao"})))
    assert openrouter.asked == [COMPLETIONS], "the round was sent more than once"
    assert f"with {failure[0]}" in said, said


@pytest.mark.parametrize(
    "failure, sentence",
    [
        (httpx.ConnectError("connection refused"), "could not be reached"),
        (httpx.ReadTimeout("timed out"), "did not answer in time"),
    ],
    ids=["no connection", "timeout"],
)
def test_a_round_of_the_chat_that_gets_no_answer_is_sent_once_and_said(
    client, openrouter, failure, sentence
):
    openrouter.script = [failure, _says("Ciao.")]
    said = _ends_on_a_sentence(_events(client.post("/api/chat", json={"content": "ciao"})))
    assert openrouter.asked == [COMPLETIONS], "the round was sent more than once"
    assert sentence in said, said


# --- The analysis --------------------------------------------------------------------


@pytest.mark.parametrize("refusal", [NO_PROVIDER, MODEL_DOWN, INTERNAL], ids=["503", "502", "500"])
def test_a_step_no_provider_took_is_asked_once_more_and_says_so(openrouter, refusal):
    """OpenRouter answered with a status, so no provider accepted the request
    (it answers 200 as soon as one does), and a request that failed is not
    billed (its page on failover). The second ask is said, with the status."""
    openrouter.script = [refusal, _answers("The numbers.")]
    result = advisor.call_llm("system", "user", model=OPUS)
    assert openrouter.asked == [COMPLETIONS, COMPLETIONS]
    assert result["analysis"] == "The numbers."
    assert result["asked_again"] == (
        f"asked again after OpenRouter's {refusal[0]}, which it says it does not bill"
    )


def test_a_step_answered_at_once_says_nothing_about_asking(openrouter):
    openrouter.script = [_answers("The numbers.")]
    result = advisor.call_llm("system", "user", model=OPUS)
    assert openrouter.asked == [COMPLETIONS]
    assert result["asked_again"] is None


@pytest.mark.parametrize(
    "failure, sentence",
    [
        (RATE_LIMITED, "with 429"),
        (TIMED_OUT, "with 408"),
        (GATEWAY_TIMEOUT, "with 504"),
        (httpx.ReadTimeout("timed out"), "did not answer in time"),
        (httpx.ConnectError("connection refused"), "could not be reached"),
    ],
    ids=["429", "408", "504", "timeout", "no connection"],
)
def test_a_step_that_may_have_been_billed_or_worked_on_is_not_asked_again(
    openrouter, failure, sentence
):
    """A 429 (the failover page reports some that consumed credits), and every
    kind of timeout or dropped connection, where a provider may have been at
    work: one request, and the step stops with the sentence."""
    openrouter.script = [failure, _answers("The numbers.")]
    with pytest.raises(advisor.AdvisorError) as stopped:
        advisor.call_llm("system", "user", model=OPUS)
    assert openrouter.asked == [COMPLETIONS], "the step was asked again"
    assert sentence in str(stopped.value), str(stopped.value)


def test_a_step_refused_twice_stops_and_says_it_was_asked_twice(openrouter):
    openrouter.script = [NO_PROVIDER, NO_PROVIDER]
    with pytest.raises(advisor.AdvisorError) as stopped:
        advisor.call_llm("system", "user", model=OPUS)
    assert openrouter.asked == [COMPLETIONS, COMPLETIONS]
    said = str(stopped.value)
    assert "with 503" in said
    assert said.endswith(
        "The step was asked twice: OpenRouter had refused the first ask with 503 "
        "too, which it says it does not bill."
    ), said


def test_the_step_asked_again_says_so_in_its_line(client, openrouter):
    """The analysis as the chat runs it: each finished step is a line the
    reader reads while the run goes on, and the one asked again says so."""
    openrouter.script = [
        NO_PROVIDER,
        _answers("The numbers."),
        _answers("It fits.\n\nVERDICT: FITS"),
        _answers("What this means for you."),
    ]
    with SessionLocal() as db:
        walk = tools._walk_analysis(db, tools.RunAnalysisArgs())
        lines = []
        while True:
            try:
                lines.append(next(walk).label)
            except StopIteration:
                break
    assert lines == [
        "The numbers, on their own merits (asked again after OpenRouter's 503, "
        "which it says it does not bill)",
        "Where this would fail this person",
        "What this means for you",
    ]
    assert len(openrouter.asked) == 4


def test_the_analysis_card_says_which_steps_may_be_asked_twice(client):
    """The card quotes how many model calls a run makes, so the one kind of
    second ask is said there too, before the reader confirms."""
    with SessionLocal() as db:
        card = tools.answer(db, advisor.ToolCall(id="call_1", name="run_analysis", arguments="{}"))
    consequence = card["card"]["consequence"]
    assert (
        f"{chain.MIN_STEPS} model calls, up to {chain.MAX_STEPS} if the disagreement is real"
        in consequence
    )
    assert (
        "A step OpenRouter turns away with 500, 502 or 503, which it says it does not "
        "bill, is asked once more."
    ) in consequence
