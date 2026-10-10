"""Every turn of the chat can read the one before it from the cache.

Brief AM (2026-10-09). Brief AD built the cache (2026-10-05), and its paid
probe saw a second turn read the tools, the system prompt and the picture.
Brief AL's paid probe P1 (2026-10-08) found that no turn of the reader's had
done so since brief AG: on a request that declares OpenRouter's web search,
only the end-of-request marker keeps anything. These tests pin the two things
the app itself owes a turn that is to read the one before it.

The bytes. What the next turn sends again (the tools, the system prompt, the
picture, and the conversation up to the question before the newest) is the
same, byte for byte, from one turn to the next while nothing on record
changes; and a write changes the picture and nothing before it. Brief AL's
plan measured this on the app before anything was built, so these hold on the
code before brief AM too: they are here so that nothing after it breaks them.

And the route. Every chat request to an Anthropic model names one session,
the app's, so OpenRouter sends it where the turn before it went, even when
the picture changed (OpenRouter otherwise names a conversation by its first
messages, and the picture is one of them).

They go through the real `stream_llm` and the real openai client over a faked
transport: the rules are about the bytes of the request.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, chat

REAL_STREAM_LLM = advisor.stream_llm

OPUS = "anthropic/claude-opus-5.5"
ANTHROPICS = [OPUS, "anthropic/claude-sonnet-4.6", "~anthropic/claude-sonnet-latest"]
OTHERS = ["qwen/qwen3.8-max-0902", "openai/gpt-6.1-sol-pro", "moonshotai/kimi-k3"]
PAGE = {"kind": "portfolio"}


# --- OpenRouter, scripted ---------------------------------------------------------


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


USAGE = {
    "id": "gen-test",
    "object": "chat.completion.chunk",
    "created": 1,
    "model": "m",
    "choices": [],
    "usage": {
        "prompt_tokens": 12925,
        "completion_tokens": 16,
        "total_tokens": 12941,
        "prompt_tokens_details": {"cached_tokens": 12644, "cache_write_tokens": 277},
        "cost": 0.0042498,
    },
}


def _sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _says(text: str) -> bytes:
    return _sse(_chunk({"content": text}), _chunk({}, "stop"), USAGE)


def _reads_run_one(n: int) -> bytes:
    """A round that asks for one of the app's read tools, whose answer is the
    same bytes every time on an empty database."""
    tool = {
        "index": 0,
        "id": f"call_{n}",
        "type": "function",
        "function": {"name": "read_analysis", "arguments": json.dumps({"run_id": 1})},
    }
    return _sse(_chunk({"tool_calls": [tool]}), _chunk({}, "tool_calls"), USAGE)


@pytest.fixture
def openrouter(monkeypatch):
    """The real client over a transport that answers each call with the next
    entry of `openrouter.script` and keeps every request body in `asked`."""

    class Fake:
        script: list = []
        asked: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.asked.append(json.loads(request.content))
        assert Fake.script, "a call past the script"
        return httpx.Response(
            200, content=Fake.script.pop(0), headers={"content-type": "text/event-stream"}
        )

    def client():
        return advisor.sdk().OpenAI(
            base_url=advisor.OPENROUTER_BASE_URL,
            api_key="invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "_client", client)
    Fake.script, Fake.asked = [], []
    return Fake


def _ask(client, content: str, model: str, conversation_id: int | None = None) -> int:
    response = client.post(
        "/api/chat",
        json={"content": content, "conversation_id": conversation_id, "model": model, "page": PAGE},
    )
    assert response.status_code == 200, response.text
    assert '"kind": "done"' in response.text or '"kind":"done"' in response.text, response.text
    start = json.loads(response.text.split("\n\n")[0].split("\n")[1][len("data: "):])
    return start["conversation_id"]


def _kept_up_to(body: dict) -> int:
    """The index in `messages` of the last message a request asked the cache
    to keep: where what the next turn can read ends."""
    marked = [
        i
        for i, m in enumerate(body["messages"])
        if i > 0 and isinstance(m.get("content"), list)
        and any("cache_control" in part for part in m["content"])
    ]
    return marked[-1]


def _plain(message: dict) -> dict:
    """A message as the provider reads its words: a marked one back to the
    plain string it carries. Where a marker sits moves from turn to turn; the
    words it keeps must not."""
    content = message.get("content")
    if isinstance(content, list):
        (part,) = content
        return {**message, "content": part["text"]}
    return message


def _bytes(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# --- The bytes the next turn sends again ------------------------------------------


def test_what_the_next_turn_sends_again_is_byte_identical_while_nothing_changes(
    client, openrouter
):
    """Three turns, nothing written between them. Each turn's request keeps,
    up to its last marker, what the next one sends again: the tools, the
    system prompt with its marker, the picture, and every message up to the
    question before the newest, which the next turn sends with its label as
    this one did."""
    openrouter.script = [_says("Hai 17.992 euro."), _says("In tre conti."), _says("Prego.")]

    conversation = _ask(client, "quanto ho da parte?", OPUS)
    _ask(client, "e dove?", OPUS, conversation)
    _ask(client, "grazie", OPUS, conversation)

    for n, (before, after) in enumerate(zip(openrouter.asked, openrouter.asked[1:]), start=1):
        assert _bytes(after["tools"]) == _bytes(before["tools"]), f"turn {n}"
        assert _bytes(after["messages"][0]) == _bytes(before["messages"][0]), f"turn {n}"
        upto = _kept_up_to(before)
        kept = [_plain(m) for m in before["messages"][1 : upto + 1]]
        again = [_plain(m) for m in after["messages"][1 : upto + 1]]
        assert _bytes(again) == _bytes(kept), f"turn {n}"
    # The third turn keeps the second turn's question, not only the picture.
    assert _kept_up_to(openrouter.asked[2]) > _kept_up_to(openrouter.asked[0])


def test_a_write_changes_the_picture_and_nothing_before_it(client, openrouter):
    """A goal recorded between two turns: the picture says so, and the tools
    and the system prompt, which come before it in what a provider caches,
    are the same bytes as before."""
    openrouter.script = [_says("Nessun obiettivo."), _says("Ora uno.")]

    conversation = _ask(client, "che obiettivi ho?", OPUS)
    made = client.post(
        "/api/goals",
        json={"name": "Emergency fund", "type": "emergency_fund", "currency": "EUR"},
    )
    assert made.status_code == 201, made.text
    _ask(client, "e adesso?", OPUS, conversation)

    before, after = openrouter.asked
    assert _bytes(after["tools"]) == _bytes(before["tools"])
    assert _bytes(after["messages"][0]) == _bytes(before["messages"][0])
    assert "Emergency fund" not in _plain(before["messages"][1])["content"]
    assert "Emergency fund" in _plain(after["messages"][1])["content"]


# --- The route ----------------------------------------------------------------------


@pytest.mark.parametrize("model", ANTHROPICS)
def test_every_request_of_the_chat_names_the_apps_session(client, openrouter, monkeypatch, model):
    """Every round of every turn, the tool-free last round included: it reads
    nothing from the cache, and the turn after it still has to reach the
    provider that holds what the rounds before it kept."""
    monkeypatch.setattr(chat, "MAX_COMPLETIONS_PER_TURN", 3)
    openrouter.script = [
        _reads_run_one(1),
        _reads_run_one(2),
        _says("Non ho trovato analisi."),
        _says("Nessuna."),
    ]

    conversation = _ask(client, "cosa diceva l'ultima analisi?", model)
    _ask(client, "e prima?", model, conversation)

    assert len(openrouter.asked) == 4
    assert "tools" not in openrouter.asked[2], "the third round is the one with no tools"
    for n, body in enumerate(openrouter.asked, start=1):
        # One fixed name for the app's chat: no conversation number, no
        # date, nothing a request could tell about whose it is.
        assert body["session_id"] == "aurelio-chat", f"request {n}"


def test_the_session_is_named_whether_or_not_the_cache_is_asked(openrouter):
    """A call to an Anthropic model that asks the cache for nothing (the round
    with no tools) still names the session."""
    openrouter.script = [_says("Ciao.")]
    pieces = list(REAL_STREAM_LLM("system", [{"role": "user", "content": "ciao"}], model=OPUS))
    assert ("text", "Ciao.") in pieces
    (body,) = openrouter.asked
    assert body["session_id"] == advisor.SESSION_ID
    assert "cache_control" not in json.dumps(body)


@pytest.mark.parametrize("model", OTHERS)
def test_the_other_models_name_no_session(client, openrouter, model):
    """Their requests are what they were before: OpenRouter routes them as it
    always has."""
    openrouter.script = [_says("Ciao."), _says("Ciao.")]
    conversation = _ask(client, "ciao", model)
    _ask(client, "ancora", model, conversation)
    for body in openrouter.asked:
        assert "session_id" not in body
