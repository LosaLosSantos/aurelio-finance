"""A 402 says what OpenRouter said, and is never asked again.

Brief AP, item 2 (2026-10-12). Every 402 was said as "the account behind the
API key has no credit left". Brief AO's paid run met one on 2026-10-11 that
said nothing of the kind: the key's own limit could not cover the most the
request might write, "This request requires more credits, or fewer
max_tokens", with the tokens asked for and those the key could still pay for,
and `metadata.limit_source` "openrouter_key_limit". OpenRouter's page on
limits (read 2026-10-12) names three sources for a 402 and says to branch on
them: the key's limit, the account's credit (`openrouter_credits`) and the
requests still running on the account (`openrouter_in_flight_budget`, which
passes, with a `Retry-After`). The sentence now says which, with the figures
when OpenRouter gives them and where the reader acts on openrouter.ai, then
OpenRouter's own words as before. "No credit left" is no longer the app's to
say: no 402 measured or documented says it.

The bodies: the key's limit as measured, its key's address invented; the
in-flight budget as OpenRouter's page prints it; the account's credit with the
page's metadata and a message in the measured one's shape, since the page
prints none for that source. Through the app's own client, with only its
transport replaced; every figure is invented.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import advisor, chain
from app.database import SessionLocal

REAL_CLIENT = advisor._client
REAL_STREAM_LLM = advisor.stream_llm
REAL_CALL_LLM = advisor.call_llm
# The analyst's steps ask in rounds since brief AR (`advisor.call_round`).
REAL_CALL_ROUND = advisor.call_round

OPUS = "anthropic/claude-opus-5.5"
COMPLETIONS = "/api/v1/chat/completions"

# An address of OpenRouter's page for one key, with an invented key hash.
KEY_PAGE = "https://openrouter.ai/workspaces/default/keys/" + "0123456789abcdef" * 4

KEY_LIMIT = {
    "error": {
        "message": (
            "This request requires more credits, or fewer max_tokens. You requested up to "
            f"8192 tokens, but can only afford 3120. To increase, visit {KEY_PAGE} and adjust "
            "the key's total limit"
        ),
        "code": 402,
        "metadata": {
            "limit_source": "openrouter_key_limit",
            "remedy_hint": (
                "Raise or remove this API key's usage limit at https://openrouter.ai/settings/keys, "
                "or use a key without a limit."
            ),
        },
    }
}

CREDITS = {
    "error": {
        "message": (
            "This request requires more credits, or fewer max_tokens. You requested up to "
            "16384 tokens, but can only afford 9050."
        ),
        "code": 402,
        "metadata": {"reason": "weight_exceeds_budget", "limit_source": "openrouter_credits"},
    }
}

# As OpenRouter's page on limits prints it.
IN_FLIGHT = {
    "error": {
        "code": 402,
        "message": (
            "This request would exceed your available credits given your current in-flight "
            "requests. Retry after in-flight requests settle, or add credits."
        ),
        "metadata": {
            "reason": "in_flight_budget_exhausted",
            "limit_source": "openrouter_in_flight_budget",
            "remedy_hint": (
                "Retry after your in-flight requests settle (see the Retry-After header). Adding "
                "credits at https://openrouter.ai/settings/credits raises your in-flight budget, "
                "up to a capped ceiling."
            ),
        },
    }
}

UNNAMED = {"error": {"code": 402, "message": "Invented words."}}

SAID_KEY_LIMIT = (
    f"OpenRouter refused the call to {OPUS} with 402: what the API key may still spend under its "
    "limit does not cover this request, which may write up to 8,192 tokens while the key can pay "
    "for 3,120. Raise or remove the key's limit on openrouter.ai (Settings, Keys), then ask again. "
    "OpenRouter said: This request requires more credits, or fewer max_tokens. You requested up "
    f"to 8192 tokens, but can only afford 3120. To increase, visit {KEY_PAGE} and adjust the "
    "key's total limit."
)
SAID_CREDITS = (
    f"OpenRouter refused the call to {OPUS} with 402: the credit on the account behind the API "
    "key does not cover this request, which may write up to 16,384 tokens while the credit can "
    "pay for 9,050. Add credit on openrouter.ai (Settings, Credits), then ask again. OpenRouter "
    "said: This request requires more credits, or fewer max_tokens. You requested up to 16384 "
    "tokens, but can only afford 9050."
)
SAID_IN_FLIGHT = (
    f"OpenRouter refused the call to {OPUS} with 402: the requests still running on the account, "
    "or just finished, are using what OpenRouter lets it spend at once. Wait 20 seconds, then ask "
    "again; adding credit on openrouter.ai raises that amount. OpenRouter said: This request "
    "would exceed your available credits given your current in-flight requests. Retry after "
    "in-flight requests settle, or add credits."
)
SAID_UNNAMED = (
    f"OpenRouter refused the call to {OPUS} with 402: the API key or the account behind it does "
    "not have the credit this request needs. Add credit, or raise the key's limit, on "
    "openrouter.ai (Settings, Credits or Keys), then ask again. OpenRouter said: Invented words."
)


def _answers(text: str) -> tuple[int, dict, dict]:
    return 200, {
        "id": "gen-test",
        "object": "chat.completion",
        "created": 1,
        "model": OPUS,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.001},
    }, {}


@pytest.fixture
def openrouter(monkeypatch):
    """The app's own client, its transport answering each request with the
    next (status, body, headers) of `openrouter.script`; every request
    counted in `asked`."""

    class Fake:
        script: list = []
        asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.asked.append(request.url.path)
        assert Fake.script, f"request {len(Fake.asked)} is past the script"
        status, body, headers = Fake.script.pop(0)
        return httpx.Response(status, json=body, headers=headers)

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
    Fake.script, Fake.asked = [], []
    return Fake


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


KINDS = [
    pytest.param(KEY_LIMIT, {}, SAID_KEY_LIMIT, id="the key's limit"),
    pytest.param(CREDITS, {}, SAID_CREDITS, id="the account's credit"),
    pytest.param(IN_FLIGHT, {"retry-after": "20"}, SAID_IN_FLIGHT, id="the requests still running"),
    pytest.param(UNNAMED, {}, SAID_UNNAMED, id="no source named"),
]


@pytest.mark.parametrize(("body", "headers", "sentence"), KINDS)
def test_the_chat_says_what_openrouter_said_and_asks_once(client, openrouter, body, headers, sentence):
    """A 402 ends the answer with its sentence, after one request: the script
    holds an answer a second request would have received."""
    openrouter.script = [(402, body, headers), _answers("Ciao.")]
    events = _events(client.post("/api/chat", json={"content": "ciao"}))
    assert events[-1]["kind"] == "error"
    assert events[-1]["detail"] == sentence
    assert openrouter.asked == [COMPLETIONS], "a 402 was asked again"


@pytest.mark.parametrize(("body", "headers", "sentence"), KINDS)
def test_a_step_of_the_analysis_says_the_same_and_is_not_asked_again(openrouter, body, headers, sentence):
    openrouter.script = [(402, body, headers), _answers("The numbers.")]
    with pytest.raises(advisor.AdvisorError) as stopped:
        advisor.call_llm("system", "user", model=OPUS)
    assert str(stopped.value) == sentence
    assert openrouter.asked == [COMPLETIONS], "a 402 was asked again"


def test_the_analysis_stops_at_its_step_with_the_sentence(client, openrouter):
    openrouter.script = [(402, KEY_LIMIT, {}), _answers("The numbers.")]
    with SessionLocal() as db:
        walk = chain.run_chain(db)
        with pytest.raises(advisor.AdvisorError) as stopped:
            next(walk)
    said = str(stopped.value)
    assert said.startswith(SAID_KEY_LIMIT), said
    assert 'The analysis stopped at step 1, "The numbers, on their own merits", and nothing from this run was kept.' in said
    assert openrouter.asked == [COMPLETIONS]


def test_the_requests_still_running_without_a_wait_say_a_moment(openrouter):
    openrouter.script = [(402, IN_FLIGHT, {})]
    with pytest.raises(advisor.AdvisorError) as stopped:
        advisor.call_llm("system", "user", model=OPUS)
    assert "Wait a moment, then ask again; adding credit on openrouter.ai raises that amount." in str(stopped.value)
