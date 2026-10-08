"""A model OpenRouter no longer serves is said in words: which one, that it is
gone, where it is set, and what OpenRouter lists instead.

Measured on 2026-09-29 before this was built, OpenRouter faked at the HTTP
layer: a chat turn showed `LLM call failed: Error code: 404 - {'error':
{'code': 404, 'message': 'No endpoints found for qwen/qwen3.8-max.'}}`, an
analysis the same under `run_analysis failed: AdvisorError:`. The reader's
short name had already left OpenRouter's public list while still answering
(2026-09-24), so neither a refusal nor an absence alone says a model is gone.
Together they do: a 400 or 404 for a model the public list no longer has.

OpenRouter's documentation gives the envelope, {"error": {"code", "message"}},
and no wording for this case, so the two messages faked here are assumptions.
The tests go through the real `call_llm` and `stream_llm` and fake only the
transport inside the real openai client, because the mapping under test lives
inside them.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, tools

REAL_CALL_LLM, REAL_STREAM_LLM = advisor.call_llm, advisor.stream_llm
GONE = "qwen/qwen3.8-max"
LISTED_TODAY = {"qwen/qwen3.8-max-0902", "qwen/qwen3.8-max-prime", "anthropic/claude-sonnet-4.6"}
NO_ENDPOINTS = (404, {"error": {"code": 404, "message": f"No endpoints found for {GONE}."}})
NOT_A_MODEL = (400, {"error": {"code": 400, "message": f"{GONE} is not a valid model ID"}})


@pytest.fixture
def openrouter(monkeypatch):
    """OpenRouter answering every call with `openrouter.answer`, and the
    reader's .env reduced to one model line: OPENROUTER_MODEL=qwen/qwen3.8-max."""

    class Fake:
        answer = NO_ENDPOINTS
        asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.asked.append(request.url.path)
        code, body = Fake.answer
        return httpx.Response(code, json=body)

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
    for var in ("OPENROUTER_CHAT_MODEL", "OPENROUTER_ANALYST_MODEL", "OPENROUTER_CONFIDANT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", GONE)
    return Fake


@pytest.fixture
def public_list(monkeypatch):
    """OpenRouter's public list of models, as `public_list.ids`, counting how
    often it is asked."""

    class Fake:
        ids = set(LISTED_TODAY)
        asked = 0
        fails: Exception | None = None

    def fetch() -> set[str]:
        Fake.asked += 1
        if Fake.fails is not None:
            raise Fake.fails
        return set(Fake.ids)

    monkeypatch.setattr(advisor, "_fetch_model_list", fetch)
    return Fake


def _chat_error(client) -> str:
    """Ask one question and return what the panel shows: the error event."""
    with client.stream("POST", "/api/chat", json={"content": "Come sto andando?"}) as response:
        lines = list(response.iter_lines())
    kinds = [line[7:] for line in lines if line.startswith("event: ")]
    assert "error" in kinds, kinds
    data = [line[6:] for line in lines if line.startswith("data: ")]
    return json.loads(data[kinds.index("error")])["detail"]


def _analysis_error() -> str:
    """Confirm an analysis the way a card does, and return its error."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        walk = tools.settle(db, "run_analysis", {}, tools._DEPENDS_ON_NOTHING)
        while True:
            try:
                next(walk)
            except StopIteration as done:
                outcome = done.value
                break
    assert outcome["ok"] is False
    return outcome["error"]


def _reads_as_words(sentence: str) -> None:
    # chr(0x2014) is the em dash, kept out of the source so a count of dashes
    # in this repository does not find the test that forbids them.
    for raw in ("{", "}", "Error code", "AdvisorError", "LLM call failed", chr(0x2014)):
        assert raw not in sentence, f"{raw!r} in: {sentence}"


# --- A model that is gone ---------------------------------------------------------


@pytest.mark.parametrize("answer", [NO_ENDPOINTS, NOT_A_MODEL], ids=["404", "400"])
def test_a_chat_turn_whose_model_is_gone_says_so_where_it_is_set_and_what_is_listed(
    client, openrouter, public_list, answer
):
    openrouter.answer = answer
    said = openrouter.answer[1]["error"]["message"].rstrip(".")

    sentence = _chat_error(client)

    for words in (
        f"The model {GONE} is no longer served by OpenRouter: it refused the call ({said}), "
        "and its public list of models no longer has it.",
        "It is set by OPENROUTER_MODEL in backend/.env.",
        "OpenRouter still lists qwen/qwen3.8-max-0902, a dated version of it.",
    ):
        assert words in sentence, sentence
    _reads_as_words(sentence)


def test_an_analysis_whose_model_is_gone_says_the_same_unwrapped(openrouter, public_list):
    sentence = _analysis_error()

    assert sentence.startswith(f"The model {GONE} is no longer served by OpenRouter"), sentence
    assert "It is set by OPENROUTER_MODEL in backend/.env." in sentence
    _reads_as_words(sentence)
    assert "run_analysis failed" not in sentence


# --- What it offers instead ------------------------------------------------------


def test_only_a_numeric_suffix_is_a_dated_version():
    # qwen/qwen3.8-max-prime is a different model, not a date.
    assert advisor._dated(GONE, {"qwen/qwen3.8-max-prime"}) == []
    assert advisor._dated(GONE, LISTED_TODAY) == ["qwen/qwen3.8-max-0902"]
    assert advisor._dated(GONE, {"qwen/qwen3.8-max-0902", "qwen/qwen3.8-max-1015"}) == [
        "qwen/qwen3.8-max-0902",
        "qwen/qwen3.8-max-1015",
    ]
    # Not a prefix match either: another model's dated name is not this one's,
    # and a dated name that goes on is a variant of it.
    assert advisor._dated(
        GONE, {"qwen/qwen3.8-max-prime-0902", "qwen/qwen3.8-maxi-0902", "qwen/qwen3.8-max-0902-preview"}
    ) == []


def test_with_no_dated_version_listed_nothing_is_offered(client, openrouter, public_list):
    public_list.ids = {"qwen/qwen3.8-max-prime", "anthropic/claude-sonnet-4.6"}

    sentence = _chat_error(client)

    assert "no longer served" in sentence
    assert "still lists" not in sentence
    assert "prime" not in sentence


# --- Where it is set -------------------------------------------------------------


@pytest.mark.parametrize(
    "env, model, expected",
    [
        ({"OPENROUTER_MODEL": GONE}, GONE, "It is set by OPENROUTER_MODEL in backend/.env."),
        ({"OPENROUTER_CHAT_MODEL": GONE}, GONE, "It is set by OPENROUTER_CHAT_MODEL in backend/.env."),
        (
            {"OPENROUTER_CHAT_MODEL": GONE, "OPENROUTER_MODEL": GONE},
            GONE,
            "It is set by OPENROUTER_CHAT_MODEL and OPENROUTER_MODEL in backend/.env.",
        ),
        ({"OPENROUTER_ANALYST_MODEL": GONE}, GONE, "It is set by OPENROUTER_ANALYST_MODEL in backend/.env."),
        ({}, advisor.DEFAULT_MODEL, "It is the app's built-in default (DEFAULT_MODEL in backend/app/advisor.py)."),
        ({}, "moonshotai/kimi-k3", "It was picked in the chat's model menu."),
    ],
    ids=["model", "chat", "chat-and-model", "analyst", "built-in", "menu"],
)
def test_where_it_is_set(monkeypatch, env, model, expected):
    for var in advisor.MODEL_VARIABLES:
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)

    assert advisor._where_set(model) == expected


# --- Refusals that are not a model gone ------------------------------------------


def test_a_refusal_of_a_model_still_listed_is_not_called_gone(client, openrouter, public_list):
    public_list.ids = LISTED_TODAY | {GONE}

    sentence = _chat_error(client)

    # What the status means, what to do, and OpenRouter's own words last
    # (brief AJ: the words alone were all the reader got, 2026-10-08).
    assert sentence == (
        f"OpenRouter refused the call to {GONE} with 404: it has nowhere to send it. "
        "Ask again in a few minutes, or pick another model in the menu under the "
        f"question. OpenRouter said: No endpoints found for {GONE}."
    )
    assert "no longer served" not in sentence


def test_a_public_list_that_does_not_answer_is_said(client, openrouter, public_list):
    public_list.fails = httpx.ConnectError("no route to host")

    sentence = _chat_error(client)

    assert sentence.startswith(f"OpenRouter refused the call to {GONE} with 404: it has nowhere to send it.")
    assert f"OpenRouter said: No endpoints found for {GONE}." in sentence
    assert "could not be checked: its public list of models did not answer (no route to host)." in sentence
    assert "no longer served" not in sentence
    _reads_as_words(sentence)


def test_any_other_refusal_reads_in_words_and_asks_the_list_nothing(client, openrouter, public_list):
    openrouter.answer = (401, {"error": {"code": 401, "message": "User not found."}})

    sentence = _chat_error(client)

    assert sentence == (
        f"OpenRouter refused the call to {GONE} with 401: it does not accept the API "
        "key in backend/.env (OPENROUTER_API_KEY). Check the key on openrouter.ai, put "
        "the right one in backend/.env, and start the app again. OpenRouter said: User "
        "not found."
    )
    assert public_list.asked == 0
