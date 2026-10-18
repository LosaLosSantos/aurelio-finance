"""Every request the app sends names the most its answer may be.

Brief AP, item 1 (2026-10-12). The chat's rounds and the analysis's steps were
sent with no `max_tokens`, and OpenRouter then holds, against what the key may
still spend, a fixed cap of output: 65,536 tokens on Opus 5.5, $1.31 at $20
per million. Brief AO's paid run met it on 2026-10-11, a 402 at the sixth
request ("This request requires more credits, or fewer max_tokens"), while a
reply costs cents. Now a round of the chat names 8,192 tokens and a step of
the analysis 16,384, each chosen from the longest answers on record (see
`advisor.CHAT_MAX_TOKENS`); the web search keeps the 1,024 it already named.
An answer cut there says the figure.

Through the app's own client, with only its transport replaced: what is under
test is the request each of them sends.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, chain, chat, websearch
from app.database import SessionLocal

REAL_CLIENT = advisor._client
REAL_STREAM_LLM = advisor.stream_llm
REAL_CALL_LLM = advisor.call_llm
# The analyst's steps ask in rounds since brief AR (`advisor.call_round`).
REAL_CALL_ROUND = advisor.call_round

OPUS = "anthropic/claude-opus-5.5"


def _chunk(delta: dict, finish: str | None = None, native: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": OPUS,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish, "native_finish_reason": native}],
    }


USAGE = {
    "id": "gen-test",
    "object": "chat.completion.chunk",
    "created": 1,
    "model": OPUS,
    "choices": [],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0.0001},
}


def _stream(*chunks: dict) -> tuple[int, bytes]:
    return 200, ("".join(f"data: {json.dumps(c)}\n\n" for c in (*chunks, USAGE)) + "data: [DONE]\n\n").encode()


def _says(text: str) -> tuple[int, bytes]:
    return _stream(_chunk({"content": text}), _chunk({}, "stop", "end_turn"))


def _calls(name: str, arguments: dict) -> tuple[int, bytes]:
    call = {"index": 0, "id": "call_1", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}
    return _stream(_chunk({"tool_calls": [call]}), _chunk({}, "tool_calls", "tool_use"))


def _answers(text: str, finish: str = "stop", native: str | None = None) -> tuple[int, dict]:
    return 200, {
        "id": "gen-test",
        "object": "chat.completion",
        "created": 1,
        "model": OPUS,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": finish, "native_finish_reason": native}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.001},
    }


@pytest.fixture
def openrouter(monkeypatch):
    """The app's own client, its transport answering each request with the
    next entry of `openrouter.script` and keeping each request's body."""

    class Fake:
        script: list = []
        bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.bodies.append(json.loads(request.content))
        assert Fake.script, f"request {len(Fake.bodies)} is past the script"
        status, body = Fake.script.pop(0)
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
    monkeypatch.setattr(advisor, "call_round", REAL_CALL_ROUND)
    monkeypatch.setattr(advisor, "_fetch_model_list", lambda: {OPUS: None})
    Fake.script, Fake.bodies = [], []
    return Fake


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


# --- The chat ------------------------------------------------------------------------


def test_every_round_of_a_turn_names_the_chat_ceiling(client, openrouter):
    """A round that asks for a tool and the round that answers from it: each
    request names 8,192."""
    openrouter.script = [_calls("search_catalogue", {"query": "world equity"}), _says("None here.")]
    events = _events(client.post("/api/chat", json={"content": "any world fund?"}))
    assert events[-1]["kind"] == "done", events[-1]
    assert len(openrouter.bodies) == 2
    assert [b["max_tokens"] for b in openrouter.bodies] == [8192, 8192]
    assert all("tools" in b for b in openrouter.bodies)


def test_the_round_asked_with_no_tools_names_it_too(client, openrouter, monkeypatch):
    """The last round of a turn is asked with no tools; its first round is its
    last when the turn may ask once."""
    monkeypatch.setattr(chat, "MAX_COMPLETIONS_PER_TURN", 1)
    openrouter.script = [_says("Hello.")]
    _events(client.post("/api/chat", json={"content": "ciao"}))
    (body,) = openrouter.bodies
    assert "tools" not in body
    assert body["max_tokens"] == 8192


def test_the_reply_to_a_confirmed_card_names_it(client, openrouter):
    openrouter.script = [_calls("write_goal", {"action": "add", "name": "A cushion", "type": "emergency_fund"})]
    events = _events(client.post("/api/chat", json={"content": "add a goal"}))
    card = next(e["card"] for e in events if e["kind"] == "card")
    openrouter.script = [_says("It is on record.")]
    _events(client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}))
    assert [b["max_tokens"] for b in openrouter.bodies] == [8192, 8192]


def test_a_reply_cut_at_the_ceiling_says_the_figure(client, openrouter):
    openrouter.script = [_stream(_chunk({"content": "Your cash covers "}), _chunk({}, "length", "max_tokens"))]
    events = _events(client.post("/api/chat", json={"content": "how long does my cash last?"}))
    assert events[-1]["kind"] == "error"
    assert events[-1]["detail"] == (
        "The model stopped before finishing its answer: it reached its length limit, the 8,192 "
        "tokens the app allows a reply, its reasoning included (OpenRouter reported length, the "
        "provider max_tokens)."
    )


# --- The analysis --------------------------------------------------------------------


def _drain(db):
    walk = chain.run_chain(db)
    while True:
        try:
            next(walk)
        except StopIteration as done:
            return done.value


def test_every_step_of_the_analysis_names_the_step_ceiling(client, openrouter):
    """Its one second ask too: a step OpenRouter turned away with a 503."""
    openrouter.script = [
        (503, {"error": {"code": 503, "message": "No available provider meets your routing requirements"}}),
        _answers("The numbers."),
        _answers("It fits.\n\nVERDICT: FITS"),
        _answers("What this means for you."),
    ]
    with SessionLocal() as db:
        run = _drain(db)
        assert run.verdict == "What this means for you."
    assert [b["max_tokens"] for b in openrouter.bodies] == [16384, 16384, 16384, 16384]


def test_a_step_cut_at_the_ceiling_says_the_figure(openrouter):
    openrouter.script = [_answers("The top four", finish="length", native="max_tokens")]
    with pytest.raises(advisor.Unfinished) as stopped:
        advisor.call_llm("system", "user", model=OPUS)
    assert str(stopped.value) == (
        "The model stopped before finishing its answer: it reached its length limit, the 16,384 "
        "tokens the app allows a step, its reasoning included (OpenRouter reported length, the "
        "provider max_tokens)."
    )


# --- The web search ------------------------------------------------------------------


def test_the_search_keeps_its_own_ceiling(openrouter):
    """Its request named its ceiling before this brief, and keeps it."""
    openrouter.script = [_answers("done")]
    websearch.search("ECB deposit rate decision")
    (body,) = openrouter.bodies
    assert body["max_tokens"] == 1024 == websearch.MAX_TOKENS
    assert body["model"] == websearch.SEARCH_MODEL


def test_the_ceilings_are_the_ones_chosen():
    assert advisor.CHAT_MAX_TOKENS == 8192
    assert advisor.STEP_MAX_TOKENS == 16384
