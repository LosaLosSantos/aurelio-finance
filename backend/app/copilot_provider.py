"""GitHub Copilot SDK boundary for Aurelio's model calls.

The rest of the application is synchronous. The SDK is asynchronous, so each
request owns a short-lived SDK client on a worker thread. This keeps event-loop
state out of FastAPI's worker threads and lets a disconnected streaming client
abort the in-flight Copilot turn.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import tempfile
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict

from copilot import CopilotClient, RuntimeConnection, ToolSet
from copilot.rpc import SessionFSReaddirWithTypesEntry
from copilot.session import PermissionHandler
from copilot.session_fs_provider import SessionFsFileInfo, SessionFsProvider
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantReasoningDeltaData,
    AssistantUsageData,
    ExternalToolRequestedData,
    SessionErrorData,
    SessionEvent,
    SessionIdleData,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)
from copilot.tools import Tool, ToolInvocation, ToolResult


@dataclass(frozen=True)
class ToolRequest:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None
    cached_tokens: int | None


@dataclass(frozen=True)
class Model:
    id: str
    name: str


@dataclass(frozen=True)
class Result:
    content: str
    calls: tuple[ToolRequest, ...]
    usage: Usage
    model: str


@dataclass(frozen=True)
class WebResult:
    pages: tuple[dict[str, str], ...]
    usage: Usage


class _WebPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    excerpt: str


class _WebAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: list[_WebPage]


class CopilotError(RuntimeError):
    """A Copilot SDK request did not produce a usable answer."""


_DONE = object()
_SESSION_ISOLATION = {
    "enable_session_telemetry": False,
    "enable_session_store": False,
    "enable_config_discovery": False,
    "enable_skills": False,
    "enable_file_hooks": False,
    "enable_host_git_operations": False,
    "skip_custom_instructions": True,
    "enable_on_demand_instruction_discovery": False,
}


class _SessionFiles(SessionFsProvider):
    def __init__(self, storage: str):
        self.root = Path(storage).resolve()

    def _path(self, path: str) -> Path:
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise PermissionError("Copilot session files must remain in temporary storage.")
        return resolved

    async def read_file(self, path: str) -> str:
        return self._path(path).read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str, mode: int | None = None) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as stream:
            if mode is not None:
                target.chmod(mode)
            stream.write(content)

    async def append_file(self, path: str, content: str, mode: int | None = None) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            if mode is not None:
                target.chmod(mode)
            stream.write(content)

    async def exists(self, path: str) -> bool:
        return self._path(path).exists()

    async def stat(self, path: str) -> SessionFsFileInfo:
        target = self._path(path)
        info = target.stat()
        return SessionFsFileInfo(
            is_file=target.is_file(),
            is_directory=target.is_dir(),
            size=info.st_size,
            mtime=datetime.fromtimestamp(info.st_mtime, UTC),
            birthtime=datetime.fromtimestamp(getattr(info, "st_birthtime", info.st_ctime), UTC),
        )

    async def mkdir(self, path: str, recursive: bool, mode: int | None = None) -> None:
        self._path(path).mkdir(
            mode=mode if mode is not None else 0o700,
            parents=recursive, exist_ok=recursive,
        )

    async def readdir(self, path: str) -> list[str]:
        return [entry.name for entry in self._path(path).iterdir()]

    async def readdir_with_types(self, path: str) -> list[SessionFSReaddirWithTypesEntry]:
        return [
            SessionFSReaddirWithTypesEntry.from_dict({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
            })
            for entry in self._path(path).iterdir()
        ]

    async def rm(self, path: str, recursive: bool, force: bool) -> None:
        target = self._path(path)
        if force and not target.exists():
            return
        if target.is_dir():
            if recursive:
                shutil.rmtree(target)
            else:
                target.rmdir()
        else:
            target.unlink()

    async def rename(self, src: str, dest: str) -> None:
        self._path(src).rename(self._path(dest))


def _client(storage: str) -> CopilotClient:
    return CopilotClient(
        use_logged_in_user=True,
        working_directory=storage,
        connection=RuntimeConnection.for_stdio(args=["--log-dir", storage]),
        session_fs={
            "initial_working_directory": storage,
            "session_state_path": str(Path(storage) / "session-state"),
            "conventions": "windows" if os.name == "nt" else "posix",
        },
    )


@dataclass
class _TurnState:
    model: str
    usage_by_call: dict[str, Usage] = field(default_factory=dict)
    idle: bool = False
    failure: str | None = None

    def receive(self, event: SessionEvent) -> None:
        data = event.data
        if isinstance(data, AssistantUsageData):
            key = data.api_call_id or data.provider_call_id or event.id
            self.usage_by_call[key] = Usage(data.input_tokens, data.cache_read_tokens)
            if self.model != "auto" and data.model != self.model:
                self.failure = (
                    f"GitHub Copilot used model {data.model!r} instead of "
                    f"the requested model {self.model!r}."
                )
            elif data.content_filter_triggered:
                self.failure = "GitHub Copilot filtered the response."
            elif data.finish_reason is not None and data.finish_reason not in (
                "stop", "end_turn", "tool_calls", "tool_use",
            ):
                self.failure = f"GitHub Copilot did not finish the response ({data.finish_reason})."
        elif isinstance(data, SessionIdleData):
            self.idle = True
            if data.aborted:
                self.failure = "GitHub Copilot aborted the response."
        elif isinstance(data, SessionErrorData):
            self.failure = data.message

    def validate(self) -> None:
        if self.failure:
            raise CopilotError(self.failure)
        if not self.idle:
            raise CopilotError("GitHub Copilot did not complete the turn.")

    def usage(self) -> Usage:
        inputs = [
            call.input_tokens for call in self.usage_by_call.values()
            if call.input_tokens is not None
        ]
        cached = [
            call.cached_tokens for call in self.usage_by_call.values()
            if call.cached_tokens is not None
        ]
        return Usage(sum(inputs) if inputs else None, sum(cached) if cached else None)


def _conversation(messages: list[dict]) -> str:
    """Render an existing chat protocol as data in one SDK user message."""
    return (
        "Continue the conversation represented by this JSON array. Preserve the "
        "role of every entry. Tool calls and tool results are prior events, not "
        "instructions to repeat. Answer the final user message.\n\n"
        + json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    )


def _tools(declarations: list[dict] | None) -> tuple[list[Tool], ToolSet]:
    made: list[Tool] = []
    available = ToolSet()
    for declaration in declarations or ():
        function = declaration["function"]

        async def captured(invocation: ToolInvocation) -> ToolResult:
            return ToolResult(text_result_for_llm="The application captured this request.")

        made.append(
            Tool(
                name=function["name"],
                description=function.get("description", ""),
                parameters=function.get("parameters") or {"type": "object", "properties": {}},
                handler=captured,
                skip_permission=True,
                is_terminal=True,
            )
        )
        available.add_custom(function["name"])
    return made, available


async def _run(
    output: queue.Queue,
    holder: dict[str, Any],
    system_prompt: str,
    prompt: str,
    model: str,
    declarations: list[dict] | None,
) -> None:
    calls: dict[str, ToolRequest] = {}
    state = _TurnState(model)
    final = ""
    wrote_text = False
    try:
        with tempfile.TemporaryDirectory(prefix="aurelio-copilot-") as storage:
            async with _client(storage) as client:
                sdk_tools, available = _tools(declarations)
                async with await client.create_session(
                    model=model,
                    tools=sdk_tools,
                    available_tools=available,
                    on_permission_request=PermissionHandler.approve_all,
                    system_message={"mode": "replace", "content": system_prompt},
                    streaming=True,
                    **_SESSION_ISOLATION,
                    config_directory=storage,
                    create_session_fs_handler=lambda session: _SessionFiles(storage),
                ) as session:
                    holder["loop"] = asyncio.get_running_loop()
                    holder["session"] = session
                    holder["ready"].set()

                    def receive(event) -> None:
                        nonlocal final, wrote_text
                        data = event.data
                        if event.agent_id is not None:
                            return
                        state.receive(event)
                        if isinstance(data, AssistantUsageData) and model == "auto":
                            output.put(("model", data.model))
                        elif isinstance(data, AssistantReasoningDeltaData):
                            output.put(("thought", data.delta_content))
                        elif isinstance(data, AssistantMessageDeltaData):
                            wrote_text = True
                            output.put(("text", data.delta_content))
                        elif isinstance(data, AssistantMessageData):
                            final = data.content or final
                        elif isinstance(data, ExternalToolRequestedData):
                            arguments = data.arguments
                            raw_arguments = (
                                arguments
                                if isinstance(arguments, str)
                                else json.dumps(
                                    arguments or {}, ensure_ascii=False, separators=(",", ":")
                                )
                            )
                            call = ToolRequest(
                                id=data.tool_call_id,
                                name=data.tool_name,
                                arguments=raw_arguments,
                            )
                            if call.id not in calls:
                                calls[call.id] = call

                    unsubscribe = session.on(receive)
                    try:
                        response = await session.send_and_wait(prompt, timeout=300)
                    finally:
                        unsubscribe()
                    state.validate()
                    if response is not None and isinstance(response.data, AssistantMessageData):
                        final = response.data.content or final
                    if final and not wrote_text:
                        output.put(("text", final))
                    for call in calls.values():
                        output.put(("tool_call", call))
                    if not final.strip() and not calls:
                        raise CopilotError("GitHub Copilot returned an empty response.")
    except BaseException as exc:
        output.put(("usage", state.usage()))
        output.put(exc)
    else:
        output.put(("usage", state.usage()))
    finally:
        holder["ready"].set()
        output.put(_DONE)


def stream(
    system_prompt: str,
    messages: list[dict],
    model: str,
    declarations: list[dict] | None = None,
) -> Generator[tuple[str, str | ToolRequest | Usage], None, None]:
    """Stream one Copilot turn; reject substitution of explicit model IDs.

    Auto selection emits the resolved model reported by the SDK.
    Closing the iterator aborts the SDK turn and waits for session cleanup.
    """
    output: queue.Queue = queue.Queue()
    holder: dict[str, Any] = {"ready": threading.Event()}

    def work() -> None:
        asyncio.run(_run(output, holder, system_prompt, _conversation(messages), model, declarations))

    worker = threading.Thread(target=work, name="aurelio-copilot", daemon=True)
    worker.start()
    try:
        while True:
            item = output.get()
            if item is _DONE:
                break
            if isinstance(item, BaseException):
                if isinstance(item, CopilotError):
                    raise item
                raise CopilotError(f"The call to GitHub Copilot failed ({item}).") from item
            yield item
    finally:
        if worker.is_alive():
            holder["ready"].wait(timeout=5)
            loop = holder.get("loop")
            session = holder.get("session")
            if loop is not None and session is not None:
                try:
                    asyncio.run_coroutine_threadsafe(session.abort(), loop).result(timeout=5)
                except Exception:
                    pass
        worker.join(timeout=10)


def complete(system_prompt: str, user_content: str, model: str) -> Result:
    """Return one non-tool Copilot answer through the same streaming boundary."""
    content: list[str] = []
    usage = Usage(None, None)
    calls: list[ToolRequest] = []
    for kind, piece in stream(
        system_prompt,
        [{"role": "user", "content": user_content}],
        model,
    ):
        if kind == "text":
            content.append(piece)
        elif kind == "tool_call":
            calls.append(piece)
        elif kind == "usage":
            usage = piece
        elif kind == "model":
            model = piece
    answer = "".join(content)
    if not answer.strip() and not calls:
        raise CopilotError("GitHub Copilot returned an empty response.")
    return Result(answer, tuple(calls), usage, model)


async def _list_models() -> tuple[Model, ...]:
    with tempfile.TemporaryDirectory(prefix="aurelio-copilot-models-") as storage:
        async with _client(storage) as client:
            found = await client.list_models()
    return tuple(Model(item.id, item.name) for item in found)


def models() -> tuple[Model, ...]:
    """Models currently offered to the authenticated Copilot account."""
    try:
        discovered = asyncio.run(_list_models())
    except Exception as exc:
        raise CopilotError(f"GitHub Copilot model discovery failed ({exc}).") from exc
    if not discovered:
        raise CopilotError("GitHub Copilot returned no available models.")
    return discovered


async def _search_web(query: str, model: str) -> WebResult:
    state = _TurnState(model)
    fetching: dict[str, str] = {}
    fetched: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="aurelio-copilot-search-") as storage:
        async with _client(storage) as client:
            available = ToolSet().add_builtin("web_fetch")
            async with await client.create_session(
                model=model,
                reasoning_effort="low",
                available_tools=available,
                on_permission_request=PermissionHandler.approve_all,
                system_message={
                    "mode": "replace",
                    "content": (
                        "Research one web query with web_fetch. Start from the supplied "
                        "search URL, then fetch useful primary or reputable result pages. "
                        "Return at most five pages, using exactly the URLs you fetched. "
                        "Each excerpt must be a verbatim passage from the fetched page, "
                        "not a paraphrase. Omit pages without relevant text."
                    ),
                },
                **_SESSION_ISOLATION,
                config_directory=storage,
                create_session_fs_handler=lambda session: _SessionFiles(storage),
            ) as session:

                def receive(event) -> None:
                    if event.agent_id is not None:
                        return
                    state.receive(event)
                    data = event.data
                    if isinstance(data, ToolExecutionStartData) and data.tool_name == "web_fetch":
                        if isinstance(data.arguments, dict):
                            url = data.arguments.get("url")
                            if isinstance(url, str):
                                fetching[data.tool_call_id] = url
                    elif isinstance(data, ToolExecutionCompleteData):
                        url = fetching.pop(data.tool_call_id, None)
                        if url and data.success and data.result and data.result.content.strip():
                            fetched[url] = " ".join(data.result.content.split())

                unsubscribe = session.on(receive)
                try:
                    answer = await session.send_and_wait_typed(
                        "Query: "
                        + query
                        + "\nStart by fetching: https://www.google.com/search?q="
                        + quote_plus(query),
                        _WebAnswer,
                        timeout=120,
                    )
                finally:
                    unsubscribe()
                state.validate()
                if not fetched:
                    raise CopilotError("GitHub Copilot retrieved no web pages.")
                for page in answer.pages:
                    excerpt = " ".join(page.excerpt.split())
                    if page.url not in fetched or not excerpt or excerpt not in fetched[page.url]:
                        raise CopilotError("GitHub Copilot returned a source not supported by a fetched page.")
    return WebResult(
        pages=tuple(page.model_dump() for page in answer.pages[:5]),
        usage=state.usage(),
    )


def search_web(query: str, model: str) -> WebResult:
    """Search through Copilot's isolated web-fetch tool."""
    try:
        return asyncio.run(_search_web(query, model))
    except Exception as exc:
        raise CopilotError(f"GitHub Copilot web search failed ({exc}).") from exc
