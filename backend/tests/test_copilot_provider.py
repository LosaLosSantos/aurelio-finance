"""Observable contracts at the GitHub Copilot SDK boundary."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import anyio
import pytest

from app import advisor, chat, copilot_provider, crud, schemas
from app.database import SessionLocal
from app.routers.chat import _stream
from copilot import CopilotClient
from copilot.client import RuntimeConnection
from copilot.session_fs_provider import create_session_fs_adapter
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
_REAL_COMPLETE = copilot_provider.complete
_REAL_CALL_ROUND = advisor.call_round
_REAL_ADVISOR_STREAM = advisor.stream_llm
_REAL_MODELS = copilot_provider.models
_REAL_SEARCH_WEB = copilot_provider.search_web


class _Session:
    def __init__(self, captured: dict, failure: Exception | None = None):
        self.captured = captured
        self.failure = failure
        self.receiver = None
        self.stopped = asyncio.Event()

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
                    model=self.captured["session"]["model"], input_tokens=123, cache_read_tokens=17,
                    finish_reason="stop",
                ),
                SessionIdleData(),
            )
        )
        events = self.captured.get("events", events)
        for data in events:
            self.receiver(SimpleNamespace(agent_id=None, data=data, id=str(id(data))))
        if self.captured.get("wait_for_abort"):
            self.captured["worker"] = threading.current_thread()
            await self.stopped.wait()
        if self.captured.get("raise_after_events"):
            raise RuntimeError("unavailable")
        return SimpleNamespace(data=AssistantMessageData("Hello", "message-1"))

    async def send_and_wait_typed(self, prompt, response_type, timeout):
        await self.send_and_wait(prompt, timeout)
        return response_type.model_validate(self.captured.get("answer", {"pages": []}))

    async def abort(self):
        self.captured["aborted"] = True
        self.stopped.set()


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
        if self.captured.get("persist_transcript"):
            filesystem = options["create_session_fs_handler"](None)
            path = str(Path(self.captured["client"]["session_fs"]["session_state_path"]) / "events.jsonl")
            await filesystem.write_file(path, '{"prompt":"My balance is 1000"}\n')
            assert await filesystem.read_file(path) == '{"prompt":"My balance is 1000"}\n'
            assert Path(path).is_file()
            self.captured["transcript"] = Path(path)
        return _Session(self.captured, self.failure)

    async def list_models(self):
        return [SimpleNamespace(id="gpt-5.4", name="GPT")]


@pytest.mark.parametrize("asgi_version", ["2.0", "2.4"])
@pytest.mark.parametrize("partial", [False, True])
def test_disconnect_aborts_a_provider_waiting_for_its_next_event(
    client, monkeypatch, asgi_version, partial
):
    waiting = threading.Event()
    captured = {
        "wait_for_abort": True,
        "events": [AssistantMessageDeltaData("Partial", "message-1")] if partial else [],
    }

    class WaitingSession(_Session):
        async def send_and_wait(self, prompt, timeout):
            waiting.set()
            try:
                return await asyncio.wait_for(super().send_and_wait(prompt, timeout), timeout=2)
            except TimeoutError:
                captured["timed_out"] = True
                raise

        async def __aexit__(self, *exc):
            captured["closed"] = True
            return False

    class WaitingClient(_Client):
        async def create_session(self, **options):
            captured["session"] = options
            return WaitingSession(captured)

    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: WaitingClient(captured, **options)
    )
    monkeypatch.setattr(copilot_provider, "stream", _REAL_STREAM)
    monkeypatch.setattr(advisor, "stream_llm", _REAL_ADVISOR_STREAM)
    store_answer = chat._store_answer

    def store_after_cleanup(*args, **kwargs):
        assert captured.get("closed"), "SDK cleanup must finish before persistence"
        return store_answer(*args, **kwargs)

    monkeypatch.setattr(chat, "_store_answer", store_after_cleanup)
    with SessionLocal() as db:
        turn = chat.prepare(db, schemas.ChatRequest(content="hi"))
    sent = []

    async def disconnect():
        ready = anyio.Event()

        async def receive():
            await ready.wait()
            assert await anyio.to_thread.run_sync(waiting.wait, 2)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body":
                if not partial or b"Partial" in message["body"]:
                    ready.set()

        await _stream(chat.stream(turn))(
            {"type": "http", "asgi": {"spec_version": asgi_version}}, receive, send
        )

    anyio.run(disconnect)
    assert captured.get("aborted"), "Disconnect must abort without waiting for another SDK event"
    assert not captured.get("timed_out")
    assert not captured["worker"].is_alive()
    with SessionLocal() as db:
        answer = crud.get_chat_conversation(db, turn.conversation_id).messages[-1]
        assert answer.status == "cut"
        assert json.loads(answer.blocks) == (
            [{"kind": "text", "text": "Partial"}] if partial else []
        )
    assert not any(b"event: done" in message.get("body", b"") for message in sent)


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
    monkeypatch.delenv("COPILOT_DISABLE_KEYTAR", raising=False)
    monkeypatch.delenv("COPILOT_HOME", raising=False)
    spawn = Mock(side_effect=RuntimeError("spawn captured"))
    monkeypatch.setattr("copilot.client.subprocess.Popen", spawn)
    options = dict(captured["client"])
    options["connection"] = RuntimeConnection.for_stdio(
        path=sys.executable, args=options["connection"].args,
    )
    sdk_client = CopilotClient(**options)
    with pytest.raises(RuntimeError, match="spawn captured"):
        asyncio.run(sdk_client._start_cli_server())
    assert "COPILOT_DISABLE_KEYTAR" not in spawn.call_args.kwargs["env"]
    assert "COPILOT_HOME" not in spawn.call_args.kwargs["env"]
    assert "--no-auto-login" not in spawn.call_args.args[0]
    assert "--auth-token-env" not in spawn.call_args.args[0]
    assert "--log-dir" in spawn.call_args.args[0]
    if operation != "models":
        options = captured["session"]
        assert not options.get("interactive_user", False)
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
@pytest.mark.parametrize("model", ["gpt-5.4", "auto"])
def test_partial_answers_and_tool_requests_never_complete_on_failure(monkeypatch, terminal, model):
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
        for piece in _REAL_STREAM("system", [], model):
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


@pytest.mark.parametrize("model", ["definitely-not-a-copilot-model", "gpt-5.4"])
def test_sdk_model_fallback_is_an_error_not_a_successful_answer(client, monkeypatch, model):
    captured = {"events": [
        AssistantMessageDeltaData("Hello", "message-1"),
        ExternalToolRequestedData("req", "session", "call", "write_goal", {}),
        AssistantUsageData(model="claude-sonnet-5.5", input_tokens=100,
                           finish_reason="stop"),
        SessionIdleData(),
    ]}
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    monkeypatch.setattr(copilot_provider, "stream", _REAL_STREAM)
    monkeypatch.setattr(advisor, "stream_llm", _REAL_ADVISOR_STREAM)

    response = client.post(
        "/api/chat", json={"content": "Hello", "model": model}
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert events[-1]["kind"] == "error"
    assert model in events[-1]["detail"]
    assert "claude-sonnet-5.5" in events[-1]["detail"]
    assert not any(event["kind"] in ("done", "card") for event in events)
    saved = client.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
    assert saved["messages"][-1]["status"] == "error"
    assert client.get("/api/goals").json() == []


@pytest.mark.parametrize("operation", ["chat", "complete", "round"])
def test_auto_selection_records_the_resolved_model(client, monkeypatch, operation):
    captured = {"events": [
        AssistantMessageDeltaData("Hello", "message-1"),
        AssistantUsageData(model="gpt-6-luna", input_tokens=100, cache_read_tokens=20,
                           finish_reason="stop"),
        SessionIdleData(),
    ]}
    if operation == "round":
        captured["events"].insert(
            1, ExternalToolRequestedData("req", "session", "call", "lookup", {"symbol": "VWCE"})
        )
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    monkeypatch.setattr(copilot_provider, "stream", _REAL_STREAM)
    monkeypatch.setattr(advisor, "stream_llm", _REAL_ADVISOR_STREAM)

    if operation == "chat":
        response = client.post("/api/chat", json={"content": "Hello", "model": "auto"})
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert events[-1]["kind"] == "done", events[-1]
        assert events[-1]["model"] == "gpt-6-luna"
        saved = client.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
        answer = saved["messages"][-1]
        assert answer["status"] == "done"
        assert answer["model"] == "gpt-6-luna"
        with SessionLocal() as db:
            stored = crud.get_chat_conversation(db, events[0]["conversation_id"]).messages[-1]
            assert (stored.prompt_tokens, stored.cached_tokens, stored.cost) == (100, 20, None)
    elif operation == "complete":
        result = _REAL_COMPLETE("system", "Hello", "auto")
        assert result.model == "gpt-6-luna"
        assert result.content == "Hello"
    else:
        result = _REAL_CALL_ROUND("system", [{"role": "user", "content": "Hello"}], "auto")
        assert result.model == "gpt-6-luna"
        assert result.content == "Hello"
        assert result.calls == (advisor.ToolCall("call", "lookup", '{"symbol":"VWCE"}'),)
    assert captured["session"]["model"] == "auto"


def test_closing_advisor_stream_aborts_sdk_and_removes_session_files(monkeypatch):
    captured = {
        "events": [AssistantMessageDeltaData("Partial", "message-1")],
        "wait_for_abort": True,
        "persist_transcript": True,
    }
    monkeypatch.setattr(
        copilot_provider, "CopilotClient", lambda **options: _Client(captured, **options)
    )
    pending = _REAL_STREAM("system", [], "gpt-5.4")
    monkeypatch.setattr(copilot_provider, "stream", lambda *args, **kwargs: pending)
    response = _REAL_ADVISOR_STREAM("system", [], "gpt-5.4")
    try:
        assert next(response) == ("text", "Partial")
        response.close()
        assert captured["aborted"] is True
        assert not captured["worker"].is_alive()
        assert not captured["transcript"].exists()
        assert not Path(captured["client"]["working_directory"]).exists()
    finally:
        response.close()
        pending.close()


@pytest.mark.parametrize("operation", ["chat", "search"])
@pytest.mark.parametrize("failed", [False, True])
def test_sdk_transcripts_are_removed_after_success_or_failure(monkeypatch, operation, failed):
    captured = {
        "persist_transcript": True,
        "events": [*_fetch_events(), SessionIdleData()],
    }
    monkeypatch.setattr(
        copilot_provider, "CopilotClient",
        lambda **options: _Client(
            captured, RuntimeError("unavailable") if failed else None, **options,
        ),
    )

    def run():
        if operation == "chat":
            return list(_REAL_STREAM("system", [], "gpt-5.4"))
        return _REAL_SEARCH_WEB("rates", "gpt-5.4")

    if failed:
        with pytest.raises(copilot_provider.CopilotError, match="unavailable"):
            run()
    else:
        run()
    assert not captured["transcript"].exists()
    assert not Path(captured["client"]["working_directory"]).exists()


def test_session_files_support_runtime_operations_without_accessing_other_storage(tmp_path):
    filesystem = copilot_provider._SessionFiles(str(tmp_path))

    async def exercise():
        await filesystem.mkdir("state", recursive=False, mode=0o700)
        await filesystem.write_file("state/events.jsonl", "first\n", mode=0o600)
        await filesystem.append_file("state/events.jsonl", "second\n", mode=0o600)
        assert await filesystem.read_file("state/events.jsonl") == "first\nsecond\n"
        info = await filesystem.stat("state/events.jsonl")
        assert info.is_file and not info.is_directory and info.size == 13
        assert (await filesystem.stat("state")).is_directory
        assert await filesystem.readdir("state") == ["events.jsonl"]
        entries = await filesystem.readdir_with_types(".")
        assert [(entry.name, entry.type.value) for entry in entries] == [("state", "directory")]
        entries = await filesystem.readdir_with_types("state")
        assert [(entry.name, entry.type.value) for entry in entries] == [("events.jsonl", "file")]
        await filesystem.rename("state/events.jsonl", "state/moved.jsonl")
        assert not await filesystem.exists("state/events.jsonl")
        assert await filesystem.exists("state/moved.jsonl")
        await filesystem.rm("state/moved.jsonl", recursive=False, force=False)
        await filesystem.rm("state/missing.jsonl", recursive=False, force=True)
        await filesystem.rm("state", recursive=False, force=False)
        await filesystem.write_file("nested/state/events.jsonl", "temporary")
        await filesystem.rm("nested", recursive=True, force=False)
        assert await filesystem.readdir(".") == []
        with pytest.raises(PermissionError):
            await filesystem.write_file("../outside.jsonl", "not allowed")
        with pytest.raises(PermissionError):
            await filesystem.read_file(str(tmp_path.parent / "outside.jsonl"))
        adapter = create_session_fs_adapter(filesystem)
        missing = await adapter.read_file(SimpleNamespace(path="missing.jsonl"))
        assert missing.error.code.value == "ENOENT"

    asyncio.run(exercise())


def test_model_discovery_reflects_account_changes_on_every_request(monkeypatch):
    inventories = iter([
        (copilot_provider.Model("gpt-5.4", "GPT"),),
        (copilot_provider.Model("claude-opus-5.5", "Claude"),),
    ])

    async def discover():
        return next(inventories)

    monkeypatch.setattr(copilot_provider, "_list_models", discover)
    assert _REAL_MODELS()[0].id == "gpt-5.4"
    assert _REAL_MODELS()[0].id == "claude-opus-5.5"


def test_an_empty_account_catalogue_is_an_error(monkeypatch):
    async def empty():
        return ()

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
