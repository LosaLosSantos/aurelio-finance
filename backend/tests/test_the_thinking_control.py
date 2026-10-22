"""The chat's Thinking control: normal, or the model's one lighter position.

Brief BF (2026-10-22). Beside the model menu the reader picks "normal", what
the model does when nothing is said, or the one lighter position the model
really has, measured in the brief's paid P0 through the app's own loop: Opus
5.5, GPT-6.1 Sol Pro and Qwen 3.8 Max refuse to stop reasoning (OpenRouter
answers `effort: "none"` with a 400 before routing), so theirs is `effort:
low`, said "light"; Kimi K3 (`effort: none`) and Kimi K2.6 (`enabled: false`)
reasoned 0 tokens, so theirs is said "off". Sonnet 4.6 has none (it reasons
nothing when nothing is said), nor does a model set only in backend/.env.

What these pin: normal sends exactly what the chat sent before the control;
the lighter position goes on every round of a turn, a card's turn included;
a position the model does not have is refused before anything is stored or
written; the web search keeps its own setting; the analysis takes nothing
from the control (the reader's D2); and the round's reasoning does not go
back with its calls (the reader's D4, a stated limit).

Through the app's own client with only its transport replaced, and the real
`stream_llm`, `call_llm` and `call_round`: the rule is about the bytes sent.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, chat, models, websearch
from app.database import SessionLocal

REAL_CLIENT = advisor._client
REAL_STREAM_LLM = advisor.stream_llm
REAL_CALL_LLM = advisor.call_llm
REAL_CALL_ROUND = advisor.call_round

OPUS = "anthropic/claude-opus-5.5"
SONNET = "anthropic/claude-sonnet-4.6"
GPT = "openai/gpt-6.1-sol-pro"
QWEN = "qwen/qwen3.8-max-0902"
K3 = "moonshotai/kimi-k3"
K26 = "moonshotai/kimi-k2.6"
PAGE = {"kind": "portfolio"}

# What each model's lighter position is called and sends, written out from the
# measured table rather than read from the code under test.
LIGHTER = {
    OPUS: ("light", {"effort": "low"}),
    GPT: ("light", {"effort": "low"}),
    QWEN: ("light", {"effort": "low"}),
    K3: ("off", {"effort": "none"}),
    K26: ("off", {"enabled": False}),
}


# --- OpenRouter, scripted at the transport ------------------------------------------


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
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0.0001},
}


def _stream(*chunks: dict) -> tuple[int, bytes]:
    return 200, ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _says(text: str) -> tuple[int, bytes]:
    return _stream(_chunk({"content": text}), _chunk({}, "stop"), USAGE)


def _calls(name: str, arguments: dict, call_id: str, thought: str | None = None) -> tuple[int, bytes]:
    """A round that asks for one tool, with the reasoning streamed first when
    `thought` is given, as OpenRouter streams Opus 5.5's: the text on
    `reasoning`, the same text and then its signature as `reasoning_details`
    pieces under one index (brief AT's saved answer)."""
    tool = {
        "index": 0,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    chunks = []
    if thought is not None:
        piece = {"type": "reasoning.text", "format": "anthropic-claude-v1", "index": 0}
        chunks += [
            _chunk({"reasoning": thought, "reasoning_details": [{**piece, "text": thought}]}),
            _chunk({"reasoning_details": [{**piece, "signature": "sig-test"}]}),
        ]
    chunks += [_chunk({"tool_calls": [tool]}), _chunk({}, "tool_calls"), USAGE]
    return _stream(*chunks)


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


def _searched() -> tuple[int, dict]:
    """The web search's own answer: one page, one search run."""
    return 200, {
        "id": "gen-search",
        "object": "chat.completion",
        "created": 1,
        "model": websearch.SEARCH_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "done",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "url": "https://example.org/a-page",
                                "title": "A page",
                                "content": "What the page says.",
                            },
                        }
                    ],
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "cost": 0.0073,
            "server_tool_use_details": {"web_search_requests": 1},
        },
    }


@pytest.fixture
def openrouter(monkeypatch):
    """The app's own client, its transport answering each request with the next
    entry of `openrouter.script` and keeping every request body in `bodies`."""

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
    for variable in advisor.MODEL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(advisor, "_client", client)
    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "call_llm", REAL_CALL_LLM)
    monkeypatch.setattr(advisor, "call_round", REAL_CALL_ROUND)
    monkeypatch.setattr(advisor, "_fetch_model_list", lambda: {})
    Fake.script, Fake.bodies = [], []
    return Fake


_UNSET = object()


def _ask(client, model: str, thinking=_UNSET, content: str = "How much cash do I have?"):
    body = {"content": content, "conversation_id": None, "model": model, "page": PAGE}
    if thinking is not _UNSET:
        body["thinking"] = thinking
    return client.post("/api/chat", json=body)


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _chat_bodies(bodies: list[dict]) -> list[dict]:
    """The chat's own rounds: the requests that stream."""
    return [b for b in bodies if b.get("stream")]


def _propose_analysis(client, openrouter, model: str) -> dict:
    """One turn that ends on the analyzer's card, which takes no arguments."""
    openrouter.script = [_calls("run_analysis", {}, "call_card")]
    events = _events(_ask(client, model, content="Run an analysis of everything."))
    card = next(e["card"] for e in events if e["kind"] == "card")
    openrouter.bodies.clear()
    return card


# --- The menu ---------------------------------------------------------------------


def test_the_menu_offers_each_models_lighter_position(client, openrouter):
    menu = client.get("/api/chat/models").json()
    offered = {m["slug"]: m["thinking"] for m in menu["models"]}
    for slug, (word, _) in LIGHTER.items():
        assert offered[slug]["lighter"] == word, slug
        assert offered[slug]["measured"], slug
    assert offered[SONNET] is None


def test_a_model_set_only_in_backend_env_has_no_control(client, openrouter, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "someone/a-model-nobody-measured")
    menu = client.get("/api/chat/models").json()
    entry = next(m for m in menu["models"] if m["slug"] == "someone/a-model-nobody-measured")
    assert entry["thinking"] is None


# --- Normal sends what the chat sent before ------------------------------------------


@pytest.mark.parametrize("model", [OPUS, SONNET, K3])
def test_normal_sends_what_a_question_sent_before(client, openrouter, model):
    """No field, null, and "normal" are the same request, and none of them
    names any reasoning: the requests the chat sent before the control."""
    sent = []
    for thinking in (_UNSET, None, "normal"):
        openrouter.script = [_says("You have it on record.")]
        _events(_ask(client, model, thinking))
        sent.append(openrouter.bodies.pop())
    assert all("reasoning" not in body for body in sent)
    assert sent[0] == sent[1] == sent[2]


# --- The lighter position, on every round -------------------------------------------


@pytest.mark.parametrize("model", list(LIGHTER))
def test_the_lighter_position_goes_on_every_round_of_a_question(client, openrouter, model):
    """Six rounds that ask for a tool, then the round with no tools: all seven
    carry it."""
    word, reasoning = LIGHTER[model]
    openrouter.script = [
        *[_calls("get_look_through", {}, f"call_{n}") for n in range(1, 7)],
        _says("Nothing is held to look through."),
    ]
    events = _events(_ask(client, model, word))
    assert events[-1]["kind"] == "done", events[-1]
    rounds = _chat_bodies(openrouter.bodies)
    assert len(rounds) == chat.MAX_COMPLETIONS_PER_TURN == 7
    assert [body["reasoning"] for body in rounds] == [reasoning] * 7
    assert "tools" not in rounds[-1] and all("tools" in body for body in rounds[:-1])


def test_a_cards_turn_carries_it_on_each_of_its_rounds(client, openrouter):
    """The reply to a rejected card: its round with tools and its round with
    none."""
    card = _propose_analysis(client, openrouter, K26)
    openrouter.script = [
        _calls("get_look_through", {}, "call_after"),
        _says("Understood: no analysis now."),
    ]
    response = client.post(
        f"/api/chat/cards/{card['card_id']}",
        json={"decision": "reject", "model": K26, "thinking": "off"},
    )
    assert _events(response)[-1]["kind"] == "done"
    rounds = _chat_bodies(openrouter.bodies)
    assert len(rounds) == chat.DECISION_ROUNDS == 2
    assert [body["reasoning"] for body in rounds] == [{"enabled": False}] * 2


# --- A position the model does not have ------------------------------------------------


@pytest.mark.parametrize(
    "model, thinking, said",
    [
        (SONNET, "light", "anthropic/claude-sonnet-4.6 offers no Thinking setting; ask without one."),
        (OPUS, "off", 'anthropic/claude-opus-5.5 offers Thinking normal or light, not "off".'),
        (K3, "light", 'moonshotai/kimi-k3 offers Thinking normal or off, not "light".'),
    ],
)
def test_a_position_the_model_does_not_have_is_refused_before_anything_is_stored(
    client, openrouter, model, thinking, said
):
    response = _ask(client, model, thinking)
    assert response.status_code == 422
    assert response.json()["detail"] == said
    assert client.get("/api/chat/conversations").json() == []
    assert openrouter.bodies == []


def test_a_word_outside_the_three_is_refused_before_anything_is_stored(client, openrouter):
    response = _ask(client, OPUS, "deep")
    assert response.status_code == 422
    assert client.get("/api/chat/conversations").json() == []
    assert openrouter.bodies == []


def test_a_card_answered_with_a_position_its_model_does_not_have_decides_nothing(
    client, openrouter
):
    card = _propose_analysis(client, openrouter, OPUS)
    response = client.post(
        f"/api/chat/cards/{card['card_id']}",
        json={"decision": "confirm", "model": OPUS, "thinking": "off"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == (
        'anthropic/claude-opus-5.5 offers Thinking normal or light, not "off".'
    )
    assert openrouter.bodies == [], "no step of the analysis was asked"
    assert _outcomes(client) == ["pending"]


def _outcomes(client) -> list[str]:
    conversation = client.get("/api/chat/conversations").json()[0]
    stored = client.get(f"/api/chat/conversations/{conversation['id']}").json()
    return [b["outcome"] for m in stored["messages"] for b in m["blocks"] if b["kind"] == "card"]


def _profile_answers() -> list[tuple]:
    with SessionLocal() as db:
        return [(r.question, r.answer) for r in db.query(models.SurveyResponse).all()]


@pytest.mark.parametrize("decision, outcome", [("confirm", "confirmed"), ("reject", "rejected")])
def test_a_writing_card_answered_with_a_position_its_model_does_not_have_writes_nothing(
    client, openrouter, decision, outcome
):
    """A card that writes a profile answer when confirmed, and a rejection,
    which writes the card's outcome: each sent with a position its model
    does not have is refused before anything is written, and the same
    decision with none goes through."""
    question = "Who would help you if you lost your income?"
    openrouter.script = [
        _calls("update_profile", {"question": question, "answer": "A sister, for a while."}, "call_card")
    ]
    events = _events(_ask(client, OPUS, content="Note that a sister would help."))
    card = next(e["card"] for e in events if e["kind"] == "card")
    openrouter.bodies.clear()
    refused = client.post(
        f"/api/chat/cards/{card['card_id']}",
        json={"decision": decision, "model": SONNET, "thinking": "light"},
    )
    assert refused.status_code == 422
    assert openrouter.bodies == []
    assert _outcomes(client) == ["pending"] and _profile_answers() == []
    openrouter.script = [_says("Done.")]
    taken = client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": decision, "model": SONNET})
    assert _events(taken)[-1]["kind"] == "done"
    assert _outcomes(client) == [outcome]
    assert _profile_answers() == ([(question, "A sister, for a while.")] if decision == "confirm" else [])


# --- What the control leaves alone ------------------------------------------------------


def test_the_web_search_keeps_its_own_setting(client, openrouter, monkeypatch):
    """The search runs on its own model with its own `effort: low`, whatever
    the chat's position. Opus's lighter position is set apart for the test,
    since it sends the same `effort: low` as the search."""
    monkeypatch.setitem(
        chat.THINKING, OPUS, chat.Lighter("light", {"effort": "minimal"}, "a stand-in figure")
    )
    openrouter.script = [
        _calls("search_web", {"query": "UCITS world index funds"}, "call_search"),
        _searched(),
        _says("Two of them are on record."),
    ]
    events = _events(_ask(client, OPUS, "light", content="Find me a world index fund."))
    assert events[-1]["kind"] == "done", events[-1]
    search = next(b for b in openrouter.bodies if b["model"] == websearch.SEARCH_MODEL)
    assert search["reasoning"] == {"effort": "low"}
    assert [b["reasoning"] for b in _chat_bodies(openrouter.bodies)] == [{"effort": "minimal"}] * 2


def test_the_analysis_takes_nothing_from_the_control(client, openrouter):
    """The reader's D2: a run confirmed from a light turn asks each of its
    steps as it always did, and only the chat's reply after it is light."""
    card = _propose_analysis(client, openrouter, OPUS)
    openrouter.script = [
        _answers("The numbers."),
        _answers("It fits.\n\nVERDICT: FITS"),
        _answers("What this means for you."),
        _says("The analyzer says it fits."),
    ]
    response = client.post(
        f"/api/chat/cards/{card['card_id']}",
        json={"decision": "confirm", "model": OPUS, "thinking": "light"},
    )
    assert _events(response)[-1]["kind"] == "done"
    steps = [b for b in openrouter.bodies if not b.get("stream")]
    assert len(steps) == 3
    assert all("reasoning" not in body for body in steps)
    assert [b["reasoning"] for b in _chat_bodies(openrouter.bodies)] == [{"effort": "low"}]


def test_the_reasoning_does_not_go_back_with_the_calls(client, openrouter):
    """The reader's D4, a stated limit: the round's thought is shown and
    stored, and the round after it is sent the calls and the words only."""
    openrouter.script = [
        _calls("get_look_through", {}, "call_1", thought="First the funds."),
        _says("Nothing is held to look through."),
    ]
    events = _events(_ask(client, OPUS, "light"))
    assert [e["text"] for e in events if e["kind"] == "thought"] == ["First the funds."]
    second = _chat_bodies(openrouter.bodies)[1]
    asked = next(m for m in second["messages"] if m.get("tool_calls"))
    assert set(asked) == {"role", "content", "tool_calls"}
