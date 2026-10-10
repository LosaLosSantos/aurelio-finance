"""What the chat has already read is not paid for again.

Every round of a chat turn sends the whole conversation again, and with
Anthropic's models nothing of it is kept unless the request asks. Since brief
AD (2026-10-05) the chat asks, for those models only: a marker on the system
prompt, which keeps the tool declarations with it since they come first in
what a provider caches; one on the picture; one on the question before the
newest, which closes what the next turn sends again unchanged; and the
top-level one for the end of each round. None on the tool-free last round,
whose writes nothing could read. Measured on the wire before this was built
(a paid probe, 2026-10-05): on Opus 5.5 a second round read all
12,035 tokens the first had written, at a twentieth of the input price.

The other models in the menu cache by themselves or not at all, and what a
marker would do to them is unmeasured, so their requests stay exactly what
they were. That is the second half of what these tests pin: for them nothing
changes, and for Anthropic's models nothing changes but the markers and the
place of the last-round notice.

They go through the real `stream_llm` and `call_llm` and the real openai
client, and fake only the transport under it: the rule is about the bytes of
the request, and a fake of the functions would skip exactly that.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from app import advisor, chat, tools

REAL_CALL_LLM, REAL_STREAM_LLM = advisor.call_llm, advisor.stream_llm

OPUS = "anthropic/claude-opus-5.5"
OTHERS = ["qwen/qwen3.8-max-0902", "openai/gpt-6.1-sol-pro", "moonshotai/kimi-k3"]
KEEP = {"type": "ephemeral"}
PAGE = {"kind": "portfolio"}


# --- OpenRouter, scripted -------------------------------------------------------


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


# The usage chunk a streamed call ends with, shaped like round 2 of the probe
# (2026-10-05): everything it read, how much of it came from the cache and what
# it was written, and the price.
USAGE = {
    "id": "gen-test",
    "object": "chat.completion.chunk",
    "created": 1,
    "model": "m",
    "choices": [],
    "usage": {
        "prompt_tokens": 13246,
        "completion_tokens": 16,
        "total_tokens": 13262,
        "prompt_tokens_details": {"cached_tokens": 12035, "cache_write_tokens": 1209},
        "cost": 0.00878,
    },
}


def _sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _says(text: str) -> bytes:
    return _sse(_chunk({"content": text}), _chunk({}, "stop"), USAGE)


def _calls(name: str, arguments: dict, call_id: str) -> bytes:
    tool = {
        "index": 0,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return _sse(_chunk({"tool_calls": [tool]}), _chunk({}, "tool_calls"), USAGE)


# A tool whose answer is the same bytes every time, on an empty database: there
# is no run 1, and the result says so.
def _reads_run_one(n: int) -> bytes:
    return _calls("read_analysis", {"run_id": 1}, f"call_{n}")


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
        answer = Fake.script.pop(0)
        if isinstance(answer, bytes):
            return httpx.Response(
                200, content=answer, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=answer)

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


def _markers(body: dict) -> list[str]:
    """Where a request asks for the cache: "system", a message's index in
    `messages` (the system message is 0), and "top" for the top level."""
    where = []
    for i, message in enumerate(body["messages"]):
        content = message.get("content")
        if isinstance(content, list) and any("cache_control" in part for part in content):
            where.append("system" if message["role"] == "system" else str(i))
    if "cache_control" in body:
        where.append("top")
    return where


def _text(message: dict) -> str | None:
    content = message.get("content")
    return content[0]["text"] if isinstance(content, list) else content


# --- Which models -----------------------------------------------------------------


@pytest.mark.parametrize(
    "model, asks",
    [
        (OPUS, True),
        ("anthropic/claude-sonnet-4.6", True),
        ("~anthropic/claude-sonnet-latest", True),
        *[(other, False) for other in OTHERS],
    ],
)
def test_only_anthropics_models_are_asked_to_cache(model, asks):
    assert advisor.caches_on_request(model) is asks


# --- Where the cache is asked for ------------------------------------------------------


def test_a_first_turn_keeps_the_tools_the_system_prompt_the_picture_and_its_end(
    client, openrouter
):
    """The system prompt's marker keeps the tool declarations too, since they
    come before it in what is cached; the picture's keeps it for the next turn;
    the top level keeps the end. A first turn has no earlier conversation, so
    three markers and not four."""
    openrouter.script = [_says("Hai 17.992 euro.")]

    _ask(client, "quanto ho da parte?", OPUS)

    (body,) = openrouter.asked
    assert _markers(body) == ["system", "1", "top"]
    assert body["messages"][0]["content"] == [
        {"type": "text", "text": chat.system_prompt(OPUS), "cache_control": KEEP}
    ]
    assert _text(body["messages"][1]).startswith("Here is my complete financial picture")
    assert body["cache_control"] == KEEP
    assert body["tools"], "the tools are what the system prompt's marker keeps with it"


def test_every_round_asks_again_and_the_round_without_tools_asks_nothing(
    client, openrouter, monkeypatch
):
    """Three rounds, so that the second is the one told it is the last with
    tools and the third has none. The first two ask for the cache in the same
    places, and the notice goes at the end of its round, after the tool result,
    where it leaves the round's cache whole. The third asks for nothing:
    everything a provider caches begins with the tools, so what a round without
    them wrote could be read only by another round without them."""
    monkeypatch.setattr(chat, "MAX_COMPLETIONS_PER_TURN", 3)
    openrouter.script = [_reads_run_one(1), _reads_run_one(2), _says("Non ho trovato analisi.")]

    _ask(client, "cosa diceva l'ultima analisi?", OPUS)

    first, second, third = openrouter.asked
    assert _markers(first) == _markers(second) == ["system", "1", "top"]
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][-1] == {"role": "user", "content": chat.LAST_TOOL_ROUND_NOTICE}
    assert second["messages"][-2]["role"] == "tool"
    assert _text(second["messages"][0]) == chat.system_prompt(OPUS)

    assert "cache_control" not in json.dumps(third)
    assert "tools" not in third
    assert third["messages"][0] == {"role": "system", "content": chat.system_prompt(OPUS)}
    assert all(m["content"] != chat.LAST_TOOL_ROUND_NOTICE for m in third["messages"])


def test_a_later_turn_also_keeps_the_conversation_before_its_newest_question(
    client, openrouter
):
    """The fourth marker. The newest question goes out with the whole of its
    screen note and comes back next turn with its label only, so the marker
    sits on the question BEFORE it: the end of what the next turn sends again
    byte for byte. Four in all, Anthropic's limit."""
    openrouter.script = [_says("Hai 17.992 euro."), _says("Sono in tre conti.")]

    conversation = _ask(client, "quanto ho da parte?", OPUS)
    _ask(client, "e dove?", OPUS, conversation)

    turn_one, turn_two = openrouter.asked
    assert _markers(turn_two) == ["system", "1", "3", "top"]
    earlier, newest = turn_two["messages"][3], turn_two["messages"][-1]
    assert _text(earlier) == "<screen>Portfolio</screen>\n\nquanto ho da parte?"
    assert newest["role"] == "user" and newest["content"].startswith("<screen>\nPortfolio\n")
    # What the marker keeps is what the next turn will send again: the turn
    # before ended its question with the whole note, and this one sends the
    # label instead, so that question is the first byte the two turns differ.
    assert _text(turn_one["messages"][3]) != _text(earlier)
    assert turn_one["messages"][1] == turn_two["messages"][1]


def test_more_than_two_messages_named_is_refused_before_anything_is_sent(openrouter):
    """With the system prompt and the end, a third message would be a fifth
    marker, which Anthropic refuses with a 400 after the call has been made."""
    messages = [{"role": "user", "content": f"q{n}"} for n in range(3)]
    with pytest.raises(ValueError, match="2 at most"):
        list(REAL_STREAM_LLM("system", messages, model=OPUS, tools=None, cache_at=(0, 1, 2)))
    assert openrouter.asked == []


# --- Nothing else changes ---------------------------------------------------------


def _conversation(client, openrouter, monkeypatch, model: str) -> list[dict]:
    """Two turns, the first with two tool rounds and the third round tool-free,
    so the notice round and the round with no tools both happen."""
    monkeypatch.setattr(chat, "MAX_COMPLETIONS_PER_TURN", 3)
    openrouter.asked = []
    openrouter.script = [
        _reads_run_one(1),
        _reads_run_one(2),
        _says("Non ho trovato analisi."),
        _says("Nessuna."),
    ]
    conversation = _ask(client, "cosa diceva l'ultima analisi?", model)
    _ask(client, "e prima?", model, conversation)
    return list(openrouter.asked)


@pytest.mark.parametrize("model", OTHERS)
def test_every_other_model_is_sent_what_it_was_sent_before(
    client, openrouter, monkeypatch, model
):
    """No marker anywhere, every message's words a plain string, the notice
    in the system prompt on its round and nowhere else."""
    bodies = _conversation(client, openrouter, monkeypatch, model)

    assert len(bodies) == 4
    for n, body in enumerate(bodies, start=1):
        assert "cache_control" not in json.dumps(body), f"request {n}"
        assert all(
            isinstance(m["content"], str) or (m["role"] == "assistant" and m["content"] is None)
            for m in body["messages"]
        ), f"request {n}"
        told = n == 2
        assert body["messages"][0] == {
            "role": "system",
            "content": chat.SYSTEM_PROMPT + ("\n\n" + chat.LAST_TOOL_ROUND_NOTICE if told else ""),
        }, f"request {n}"


def _unmarked(body: dict) -> dict:
    """An Anthropic request with the cache taken out of it: the markers gone,
    every marked text back to the plain string it was, and the notice back in
    the system prompt, where every other model reads it. And the web taken
    out, which Anthropic's models are offered since brief AG and the others
    are not (tests/test_the_web_is_a_tool_of_the_app.py): `search_web` from
    its tools, and its rules from its system prompt. And the session every
    request to them names since brief AM
    (tests/test_every_turn_reads_the_one_before.py), which the others do not."""
    body = copy.deepcopy(body)
    assert body.pop("session_id") == advisor.SESSION_ID
    body.pop("cache_control", None)
    if "tools" in body:
        (web,) = tools.web_search(OPUS)
        assert body["tools"].count(web) == 1
        body["tools"] = [t for t in body["tools"] if t != web]
    for message in body["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            (part,) = content
            assert set(part) == {"type", "text", "cache_control"}
            message["content"] = part["text"]
    system = body["messages"][0]
    assert system["content"].count(chat.WEB_RULES) == 1
    system["content"] = system["content"].replace(chat.WEB_RULES, "")
    if body["messages"][-1] == {"role": "user", "content": chat.LAST_TOOL_ROUND_NOTICE}:
        body["messages"].pop()
        body["messages"][0]["content"] += "\n\n" + chat.LAST_TOOL_ROUND_NOTICE
    return body


def test_the_markers_are_all_that_changes_for_an_anthropic_model(
    client, openrouter, monkeypatch
):
    """The same two turns, once on Opus and once on Qwen. Taken out of Opus's
    requests, the cache and the web search leave exactly Qwen's, model name
    aside: the words, the order, the app's tools and every other field are
    what they would have been."""
    opus = _conversation(client, openrouter, monkeypatch, OPUS)
    qwen = _conversation(client, openrouter, monkeypatch, "qwen/qwen3.8-max-0902")

    assert len(opus) == len(qwen) == 4
    assert [_markers(b) for b in opus] == [
        ["system", "1", "top"],
        ["system", "1", "top"],
        [],
        ["system", "1", "3", "top"],
    ]
    for n, (cached, plain) in enumerate(zip(opus, qwen), start=1):
        assert cached.pop("model") == OPUS and plain.pop("model") == "qwen/qwen3.8-max-0902"
        assert _unmarked(cached) == plain, f"request {n}"


# --- The analysis asks for nothing ----------------------------------------------------


def test_the_analysis_asks_for_no_cache_even_on_an_anthropic_model(openrouter):
    """Its steps each have a system prompt of their own, and the system prompt
    comes first in what is cached: nothing one step kept could be read by
    another, so a marker would only make every step pay more."""
    openrouter.script = [
        {
            "id": "gen-test",
            "object": "chat.completion",
            "created": 1,
            "model": OPUS,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Findings."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 40, "completion_tokens": 16, "total_tokens": 56, "cost": 0.004},
        }
    ]

    advisor.call_llm("You are an analyst.", "Here is the portfolio.", model=OPUS)

    (body,) = openrouter.asked
    assert "cache_control" not in json.dumps(body)
    assert body["messages"][0] == {"role": "system", "content": "You are an analyst."}


# --- What the provider says it read -----------------------------------------------------


def test_the_stream_reads_what_came_from_the_cache_and_what_it_cost(openrouter):
    """Off the real SDK's parse of the usage chunk: `cached_tokens` one level
    down, in `prompt_tokens_details`, and `cost`, OpenRouter's own field."""
    openrouter.script = [_says("Ok.")]

    pieces = list(REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}], model=OPUS))

    assert ("usage", advisor.Usage(prompt_tokens=13246, cached_tokens=12035, cost=0.00878)) in pieces
