"""A refusal says what the provider said, after OpenRouter's words.

Brief AJ's P1 (2026-10-08) met "Provider returned error" and nothing more:
OpenRouter's error carries the provider's name and its own answer in
`metadata` (`provider_name`, `raw`), and `advisor._refused` read only the
message. Measured at `c61e5bc` (brief BE): a 502 whose `raw` named its cause
ended "OpenRouter said: Provider returned error." and carried neither the
provider nor the cause. Every body here is invented.
"""

from __future__ import annotations

import httpx

from app import advisor

MODEL = "anthropic/claude-opus-5.5"


def _refusal(status: int, error: dict) -> str:
    openai = advisor.sdk()
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status, json={"error": error}, request=request)
    kind = {400: openai.BadRequestError, 429: openai.RateLimitError, 502: openai.InternalServerError}
    exc = kind[status]("Error code: %d" % status, response=response, body=error)
    return str(advisor._refused(exc, MODEL, chat=True))


def test_the_providers_words_come_after_openrouters():
    said = _refusal(502, {
        "message": "Provider returned error",
        "code": 502,
        "metadata": {
            "provider_name": "Anthropic",
            "raw": '{"type":"error","error":{"type":"invalid_request_error",'
                   '"message":"messages.3: tool_use ids must be unique"}}',
        },
    })
    assert said.endswith(
        "OpenRouter said: Provider returned error. "
        "Anthropic said: messages.3: tool_use ids must be unique."
    )


def test_a_provider_that_answered_in_plain_text_is_quoted_on_one_line():
    said = _refusal(429, {
        "message": "Provider returned error",
        "code": 429,
        "metadata": {"provider_name": "Example Cloud", "raw": "Too many requests,\n  slow down.\n"},
    })
    assert said.endswith("Example Cloud said: Too many requests, slow down.")


def test_a_long_answer_is_cut_at_its_bound():
    said = _refusal(502, {
        "message": "Provider returned error",
        "code": 502,
        "metadata": {"provider_name": "Example Cloud", "raw": "<html>" + "x" * 1000 + "</html>"},
    })
    quoted = said.split("Example Cloud said: ", 1)[1]
    assert len(quoted) == advisor.PROVIDER_WORDS_MAX
    assert quoted.endswith("x…")


def test_a_provider_with_no_name_is_the_provider():
    said = _refusal(400, {
        "message": "Provider returned error",
        "code": 400,
        "metadata": {"raw": {"error": {"message": "prompt is too long"}}},
    })
    assert "The provider said: prompt is too long." in said


def test_an_error_with_no_metadata_reads_as_it_did():
    """A guard: nothing passed on, nothing added."""
    said = _refusal(429, {"message": "Rate limit exceeded", "code": 429})
    assert said.endswith("OpenRouter said: Rate limit exceeded.")
