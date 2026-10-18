"""Observable contracts at the GitHub Copilot SDK boundary."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import advisor, copilot_provider, crud
from app.database import SessionLocal
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantUsageData,
    ExternalToolRequestedData,
    SessionErrorData,
    SessionIdleData,
    ToolExecutionCompleteData,
    ToolExecutionCompleteResult,
    ToolExecutionStartData,
)

_REAL_STREAM = copilot_provider.stream
_REAL_ADVISOR_STREAM = advisor.stream_llm
_REAL_MODELS = copilot_provider.models


class _Session:
    def __init__(self, captured: dict, failure: Exception | None = None):
        self.captured = captured
        self.failure = failure
        self.receiver = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def on(self, receiver):
        self.receiver = receiver
        return lambda: None

    async def send_and_wait(self, prompt, timeout):
        self.captured["prompt"] = prompt
        self.captured["timeout"] = timeout
        if self.failure is not None:
            raise self.failure
        events = []
        if not self.captured.get("final_only"):
            events.append(AssistantMessageDeltaData("Hello", "message-1"))
        events.extend(
            (
                ExternalToolRequestedData(
                    "request-1",
                    "session-1",
                    "call-1",
                    "lookup",
                    self.captured.get("tool_arguments", {"symbol": "VWCE"}),
                ),
                AssistantUsageData(
                    model="claude-opus-5.5", input_tokens=123, cache_read_tokens=17,
                    finish_reason="stop",
                ),
                SessionIdleData(),
            )
        )
        events = self.captured.get("events", events)
        for data in events:
            self.receiver(SimpleNamespace(agent_id=None, data=data, id=str(id(data))))
        if self.captured.get("raise_after_events"):
            raise RuntimeError("unavailable")
        return SimpleNamespace(data=AssistantMessageData("Hello", "message-1"))

    async def send_and_wait_typed(self, prompt, response_type, timeout):
        await self.send_and_wait(prompt, timeout)
        return response_type.model_validate(self.captured.get("answer", {"pages": []}))

    async def abort(self):
        self.captured["aborted"] = True


class _Client:
    def __init__(self, captured: dict, failure: Exception | None = None, **options):
        captured["client"] = options
        self.captured = captured
        self.failure = failure

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def create_session(self, **options):
        self.captured["session"] = options
        return _Session(self.captured, self.failure)

    async def list_models(self):
        return [SimpleNamespace(id="gpt-5.4", name="GPT")]


def test_stream_maps_copilot_text_tools_and_usage(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        copilot_provider,
        "CopilotClient",
        lambda **options: _Client(captured, **options),
    )
    messages = [{"role": "user", "content": "What do I hold?"}]
    declaration = {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up one symbol.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }

    pieces = list(
        _REAL_STREAM(
            "System rules", messages, "claude-opus-5.5", [declaration]
        )
    )

    assert pieces == [
        ("text", "Hello"),
        (
            "tool_call",
            copilot_provider.ToolRequest("call-1", "lookup", '{"symbol":"VWCE"}'),
        ),
        ("usage", copilot_provider.Usage(123, 17)),
    ]
    assert '"role":"user","content":"What do I hold?"' in captured["prompt"]
    assert captured["session"]["model"] == "claude-opus-5.5"
    assert captured["session"]["system_message"] == {
        "mode": "replace",
        "content": "System rules",
    }
    assert captured["session"]["enable_session_telemetry"] is False
    assert captured["session"]["enable_session_store"] is False
    assert captured["session"]["tools"][0].is_terminal is True
    assert captured["session"]["available_tools"].to_list() == ["custom:lookup"]


def test_stream_uses_final_messages_and_preserves_serialized_tool_arguments(monkeypatch):
    captured = {"final_only": True, "tool_arguments": '{"symbol":"VWCE"}'}
    monkeypatch.setattr(
        copilot_provider,
        "CopilotClient",
        lambda **options: _Client(captured, **options),
    )

    pieces = list(
        _REAL_STREAM(
            "system",
            [{"role": "user", "content": "hi"}],
            "claude-opus-5.5",
            [],
        )
    )

    assert pieces[0] == ("text", "Hello")
    assert pieces[1] == (
        "tool_call",
        copilot_provider.ToolRequest("call-1", "lookup", '{"symbol":"VWCE"}'),
    )


def test_stream_turns_sdk_failures_into_a_stable_provider_error(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        copilot_provider,
        "CopilotClient",
        lambda **options: _Client(captured, RuntimeError("session unavailable"), **options),
    )

    with pytest.raises(copilot_provider.CopilotError, match="session unavailable"):
        list(_REAL_STREAM("system", [{"role": "user", "content": "hi"}], "gpt-5.4"))


@pytest.mark.parametrize("operation", ["chat", "models", "search"])
def test_clients_keep_logged_in_authentication_and_session_tool_isolation(monkeypatch, operation):
    captured = {"events": [*_fetch_events(), SessionIdleData()]}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    if operation == "chat":
        list(_REAL_STREAM("system", [], "gpt-5.4"))
    elif operation == "models":
        assert asyncio.run(copilot_provider._list_models())[0].id == "gpt-5.4"
    else:
        asyncio.run(copilot_provider._search_web("rates", "gpt-5.4"))
    assert captured["client"].get("mode", "copilot-cli") == "copilot-cli"
    assert "base_directory" not in captured["client"]
    assert captured["client"]["use_logged_in_user"] is True
    if operation != "models":
        options = captured["session"]
        assert options["enable_config_discovery"] is False
        assert options["enable_skills"] is False
        assert options["enable_file_hooks"] is False
        assert options["enable_host_git_operations"] is False
        assert options["skip_custom_instructions"] is True
        assert options["available_tools"].to_list() == (
            ["builtin:web_fetch"] if operation == "search" else []
        )


@pytest.mark.parametrize("terminal", [
    AssistantUsageData(model="gpt-5.4", finish_reason="length"),
    AssistantUsageData(model="gpt-5.4", finish_reason="content_filter"),
    AssistantUsageData(model="gpt-5.4", content_filter_triggered=True),
    SessionIdleData(aborted=True),
])
def test_partial_answers_and_tool_requests_never_complete_on_failure(monkeypatch, terminal):
    captured = {"events": [
        AssistantMessageDeltaData("Partial", "message-1"),
        ExternalToolRequestedData("req", "session", "call", "lookup", {}),
        terminal, SessionIdleData(),
    ]}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    pieces = []
    with pytest.raises(copilot_provider.CopilotError):
        for piece in _REAL_STREAM("system", [], "gpt-5.4"):
            pieces.append(piece)
    assert not any(kind == "tool_call" for kind, _ in pieces)


@pytest.mark.parametrize("raised", [False, True])
def test_usage_sums_distinct_calls_and_precedes_terminal_failure(monkeypatch, raised):
    first = AssistantUsageData(model="gpt-5.4", api_call_id="one", input_tokens=100,
                               cache_read_tokens=10, finish_reason="tool_calls")
    captured = {"raise_after_events": raised, "events": [
        first, first,
        AssistantUsageData(model="gpt-5.4", api_call_id="two", input_tokens=200,
                           cache_read_tokens=20, finish_reason="stop"),
        SessionErrorData(message="unavailable", error_type="test"),
    ]}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    pieces = []
    with pytest.raises(copilot_provider.CopilotError, match="unavailable"):
        for piece in _REAL_STREAM("system", [], "gpt-5.4"):
            pieces.append(piece)
    assert pieces == [("usage", copilot_provider.Usage(300, 30))]


def test_a_message_without_terminal_idle_never_completes(monkeypatch):
    captured = {"events": [AssistantMessageDeltaData("Partial", "message-1")]}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    with pytest.raises(copilot_provider.CopilotError, match="did not complete"):
        list(_REAL_STREAM("system", [], "gpt-5.4"))


def test_failed_sdk_turn_persists_reported_tokens_without_executing_a_card(client, monkeypatch):
    captured = {"events": [
        AssistantMessageDeltaData("Partial", "message-1"),
        ExternalToolRequestedData("req", "session", "call", "write_goal", {}),
        AssistantUsageData(model="gpt-5.4", input_tokens=100, cache_read_tokens=20,
                           finish_reason="length"),
        SessionIdleData(),
    ]}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    monkeypatch.setattr(copilot_provider, "stream", _REAL_STREAM)
    monkeypatch.setattr(advisor, "stream_llm", _REAL_ADVISOR_STREAM)
    response = client.post("/api/chat", json={"content": "Hello", "model": "gpt-5.4"})
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert events[-1]["kind"] == "error"
    assert not any(event["kind"] == "card" for event in events)
    saved = client.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
    answer = saved["messages"][-1]
    assert answer["status"] == "error"
    with SessionLocal() as db:
        stored = crud.get_chat_conversation(db, events[0]["conversation_id"]).messages[-1]
        assert (stored.prompt_tokens, stored.cached_tokens, stored.cost) == (100, 20, None)
    assert client.get("/api/goals").json() == []


def test_an_empty_account_catalogue_is_an_error(monkeypatch):
    async def empty():
        return ()

    monkeypatch.setattr(copilot_provider, "_model_cache", (0.0, ()))
    monkeypatch.setattr(copilot_provider, "_list_models", empty)
    with pytest.raises(copilot_provider.CopilotError, match="no available models"):
        _REAL_MODELS()


def _fetch_events(success=True, content="Rates stayed at 4%."):
    return [
        ToolExecutionStartData("fetch-1", "web_fetch", {"url": "https://example.com/rates"}),
        ToolExecutionCompleteData(success, "fetch-1",
                                  result=ToolExecutionCompleteResult(content)),
    ]


@pytest.mark.parametrize("events,pages", [
    (_fetch_events(False), []),
    ([], []),
    (_fetch_events(), [{"url": "https://invented.com", "title": "No", "excerpt": "Rates stayed at 4%."}]),
    (_fetch_events(), [{"url": "https://example.com/rates", "title": "Rates", "excerpt": "Rates fell."}]),
])
def test_search_rejects_failed_retrieval_and_unfetched_sources(monkeypatch, events, pages):
    captured = {"events": [*events, SessionIdleData()], "answer": {"pages": pages}}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    with pytest.raises(copilot_provider.CopilotError):
        asyncio.run(copilot_provider._search_web("rates", "gpt-5.4"))


def test_search_verifies_fetched_excerpts_and_accumulates_usage(monkeypatch):
    page = {"url": "https://example.com/rates", "title": "Rates", "excerpt": "Rates stayed at 4%."}
    usage = [
        AssistantUsageData(model="gpt-5.4", api_call_id=str(n), input_tokens=n,
                           cache_read_tokens=10, finish_reason="stop")
        for n in (100, 200, 300)
    ]
    captured = {"events": [*_fetch_events(), *usage, SessionIdleData()], "answer": {"pages": [page]}}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    result = asyncio.run(copilot_provider._search_web("rates", "gpt-5.4"))
    assert result.pages == (page,)
    assert result.usage == copilot_provider.Usage(600, 30)


@pytest.mark.parametrize("terminal", [
    AssistantUsageData(model="gpt-5.4", finish_reason="length"),
    SessionIdleData(aborted=True),
])
def test_search_cannot_use_a_partial_answer_even_with_valid_sources(monkeypatch, terminal):
    page = {"url": "https://example.com/rates", "title": "Rates", "excerpt": "Rates stayed at 4%."}
    captured = {
        "events": [*_fetch_events(), terminal, SessionIdleData()],
        "answer": {"pages": [page]},
    }
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    with pytest.raises(copilot_provider.CopilotError):
        asyncio.run(copilot_provider._search_web("rates", "gpt-5.4"))
