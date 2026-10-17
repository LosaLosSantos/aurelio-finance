"""Observable contracts at the GitHub Copilot SDK boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import copilot_provider
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantUsageData,
    ExternalToolRequestedData,
)

_REAL_STREAM = copilot_provider.stream


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
                    model="claude-opus-5.5", input_tokens=123, cache_read_tokens=17
                ),
            )
        )
        for data in events:
            self.receiver(SimpleNamespace(agent_id=None, data=data))
        return SimpleNamespace(data=AssistantMessageData("Hello", "message-1"))

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
