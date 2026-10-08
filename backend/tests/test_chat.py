"""The chat that reads, writes by proposing, and orchestrates the analyzer.

Streamed answers over the whole picture, stored as they ended; the tools it may
consult on the way; and the one card whose confirmation is a minute of model
calls reported step by step down the panel.

Every model call is faked at `advisor.stream_llm`, the boundary conftest
refuses by default. Nothing here reaches OpenRouter, and that matters more
than it did: a turn that calls a tool is TWO completions, so a fake that
covers only the first one has already paid for the second. The fakes below are
scripted per round for exactly that reason, and a round past the script is an
AssertionError rather than a replay — "the loop terminates" is then asserted by
construction and not by counting calls afterwards.

The two tests that exercise the real `stream_llm` do so against a fake SDK
client: one is about what the generator does when the reader leaves, which
decides whether an abandoned answer keeps billing, and the other is about
assembling a tool call out of the fragments it arrives in, which is the one
piece of protocol this app implements itself.
"""

from __future__ import annotations

import datetime
import json
import threading

import pandas as pd
import pytest
from pydantic import BaseModel

from app import (
    advisor, catalogue, chain, chat, composition, crud, models, prices, schemas, tools
)
from app.database import SessionLocal

# The real streaming function, captured at import time — before the autouse
# `offline` fixture swaps the module attribute for a refusal — so the one test
# that needs the genuine article can still reach it.
_REAL_STREAM_LLM = advisor.stream_llm


def _events(response) -> list[dict]:
    """Parse the SSE body back into its events, in order."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    out = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
        data = json.loads(lines[1][len("data: "):])
        assert data["kind"] == lines[0][len("event: "):], "event line and kind must agree"
        out.append(data)
    return out


def _kinds(events: list[dict]) -> list[str]:
    return [e["kind"] for e in events]


def _fake_stream(
    monkeypatch, pieces=("Hel", "lo"), fail_after: int | None = None, thoughts=(), rounds=None
):
    """Answer with `pieces` (after `thoughts`, if any), remembering what the
    model was asked. With `fail_after`, break the stream after that many
    pieces, the way a dropped connection would.

    With `rounds`, script each round trip on its own: `rounds[0]` is what the
    model streams first, `rounds[1]` what it streams once the tool results are
    in front of it. Asking for a round the script does not have is an
    AssertionError and not a replay of the last one — a fake that answers every
    call the same way turns one tool call into an infinite loop, and would let
    a missing bound pass as green."""
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        # A COPY of the list, because the caller keeps appending to its own as
        # the loop runs: recorded by reference, round one's record would show
        # the tool result that only round two was given, and every assertion
        # about what the model saw when would be reading the same list twice.
        seen.append(
            {
                "system": system_prompt,
                "messages": list(messages),
                "model": model,
                "tools": tools,
                "cache_at": cache_at,
            }
        )
        if rounds is not None:
            assert len(seen) <= len(rounds), f"round trip {len(seen)} is past the script"
            yield from rounds[len(seen) - 1]
            return
        for t in thoughts:
            yield ("thought", t)
        for i, p in enumerate(pieces):
            if fail_after is not None and i == fail_after:
                raise advisor.AdvisorError("LLM stream failed: connection reset")
            yield ("text", p)

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def _wants(name: str, arguments: str = "{}", call_id: str = "call_1"):
    """One tool call as `stream_llm` yields it."""
    return ("tool_call", advisor.ToolCall(id=call_id, name=name, arguments=arguments))


def _ask(client, content: str, conversation_id: int | None = None, model: str | None = None):
    body: dict = {"content": content, "conversation_id": conversation_id}
    if model:
        body["model"] = model
    return client.post("/api/chat", json=body)


def _text(message: dict) -> str:
    return "".join(b["text"] for b in message["blocks"] if b["kind"] == "text")


# --- The stream ----------------------------------------------------------------


def test_an_answer_is_start_deltas_then_exactly_one_done(client, monkeypatch):
    _fake_stream(monkeypatch, pieces=("Hel", "lo", "\n\nworld"))
    events = _events(_ask(client, "hi"))
    assert _kinds(events) == ["start", "delta", "delta", "delta", "done"]
    assert "".join(e["text"] for e in events[1:-1]) == "Hello\n\nworld"
    assert events[-1]["model"]  # says which model wrote it
    assert events[0]["conversation_id"] and events[0]["user_message_id"]


def test_a_broken_stream_ends_in_an_error_not_a_quiet_done(client, monkeypatch):
    """Done and broken must differ on the wire. A stream that stops after two
    pieces and says nothing looks, from the browser, exactly like a short
    answer — so the break is an event with a reason, and `done` never comes."""
    _fake_stream(monkeypatch, pieces=("one", "two", "three"), fail_after=2)
    events = _events(_ask(client, "hi"))
    assert _kinds(events) == ["start", "delta", "delta", "error"]
    assert "connection reset" in events[-1]["detail"]


def test_a_missing_key_is_an_error_event_and_reaches_no_network(client, monkeypatch):
    """The genuine stream_llm, with no key: it must refuse before it would
    ever build a client, and the refusal must reach the reader as words. The
    offline boundary is not what stops it here — the key check comes first,
    which is what this test is standing on."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(advisor, "stream_llm", _REAL_STREAM_LLM)
    events = _events(_ask(client, "hi"))
    assert _kinds(events) == ["start", "error"]
    assert "OPENROUTER_API_KEY" in events[-1]["detail"]


def test_leaving_mid_answer_closes_the_upstream_stream(monkeypatch):
    """Closing the generator early must close the SDK stream — that is the
    socket OpenRouter bills against. Starlette closes the generator when the
    browser disconnects; this is the half that turns that into a closed
    connection rather than a thread reading an answer nobody will see."""
    state = {"closed": False, "read": 0}

    class FakeChunk:
        # tool_calls is None on every chunk of a plain answer, and it is here
        # because a real ChoiceDelta always carries the attribute. A fake that
        # leaves it off is not standing in for the object it claims to.
        def __init__(self, text):
            delta = type("Delta", (), {"content": text, "tool_calls": None})()
            self.choices = [type("Choice", (), {"delta": delta})()]

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            state["closed"] = True

        def __iter__(self):
            for text in ("a", "b", "c", "d"):
                state["read"] += 1
                yield FakeChunk(text)

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            return FakeStream()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    monkeypatch.setattr(advisor, "_client", lambda: FakeClient())

    gen = _REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}], model="m")
    assert next(gen) == ("text", "a")
    gen.close()  # the reader left

    assert state["closed"], "the upstream stream was not closed"
    assert state["read"] == 1, "kept reading an answer nobody will see"


def test_the_models_reasoning_streams_as_thoughts_and_is_kept_folded(client, monkeypatch):
    """A thinking model spends seconds on reasoning before its first word, on a
    separate field; dropping it left the reader a spinner. It streams as
    `thought` events, is stored as its own block ahead of the text, and is
    never sent back to the model — the next turn carries only the words."""
    _fake_stream(monkeypatch, thoughts=("book 900, ", "market 2000"), pieces=("Up 1,100.",))
    events = _events(_ask(client, "am I up?"))
    assert _kinds(events) == ["start", "thought", "thought", "delta", "done"]
    cid = events[0]["conversation_id"]

    answer = client.get(f"/api/chat/conversations/{cid}").json()["messages"][1]
    assert [b["kind"] for b in answer["blocks"]] == ["thought", "text"]
    assert answer["blocks"][0]["text"] == "book 900, market 2000"
    assert _text(answer) == "Up 1,100."

    seen = _fake_stream(monkeypatch)
    _ask(client, "and now?", conversation_id=cid)
    assert seen[0]["messages"][-2] == {"role": "assistant", "content": "Up 1,100."}


# --- What is stored -----------------------------------------------------------


def test_a_conversation_is_stored_with_its_question_and_its_answer(client, monkeypatch):
    """Not the browser's memory: what was asked and what was answered are
    records, titled by the first question, and a reload finds them."""
    _fake_stream(monkeypatch, pieces=("Two ", "positions."))
    events = _events(_ask(client, "What do I own?"))
    cid = events[0]["conversation_id"]

    listed = client.get("/api/chat/conversations").json()
    assert [c["id"] for c in listed] == [cid]
    assert listed[0]["title"] == "What do I own?"

    conv = client.get(f"/api/chat/conversations/{cid}").json()
    assert [(m["seq"], m["role"]) for m in conv["messages"]] == [(1, "user"), (2, "assistant")]
    assert _text(conv["messages"][0]) == "What do I own?"
    answer = conv["messages"][1]
    assert _text(answer) == "Two positions."
    assert answer["status"] == "done" and answer["detail"] is None
    assert answer["model"] == events[-1]["model"]
    assert answer["id"] == events[-1]["message_id"]
    assert conv["messages"][0]["status"] is None  # a question does not end


def test_the_next_question_continues_the_conversation_the_model_saw(client, monkeypatch):
    """The server holds the history: the second turn carries the first
    question AND the first answer to the model, in order, and the stored
    conversation has all four turns."""
    seen = _fake_stream(monkeypatch, pieces=("first answer",))
    cid = _events(_ask(client, "first"))[0]["conversation_id"]
    _fake_stream(monkeypatch, pieces=("second answer",))
    events = _events(_ask(client, "second", conversation_id=cid))

    assert events[0]["conversation_id"] == cid
    assert seen[0]["messages"][-1] == {"role": "user", "content": "first"}

    conv = client.get(f"/api/chat/conversations/{cid}").json()
    assert [(_text(m), m["role"]) for m in conv["messages"]] == [
        ("first", "user"),
        ("first answer", "assistant"),
        ("second", "user"),
        ("second answer", "assistant"),
    ]
    # the history list keeps the live conversation on top. Timestamps are to
    # the second, so the clock is made to tick between turns: a test that
    # passed only because two turns fell in the same second would be luck.
    tick = {"s": 0}

    def later() -> str:
        tick["s"] += 1
        return f"2026-09-03T12:00:{tick['s']:02d}+00:00"

    monkeypatch.setattr(models, "_utcnow_iso", later)
    _fake_stream(monkeypatch)
    other = _events(_ask(client, "another"))[0]["conversation_id"]
    _fake_stream(monkeypatch)
    _ask(client, "back to the first", conversation_id=cid)
    assert [c["id"] for c in client.get("/api/chat/conversations").json()] == [cid, other]


def test_the_second_turn_hands_the_model_the_whole_history(client, monkeypatch):
    _fake_stream(monkeypatch, pieces=("answer one",))
    cid = _events(_ask(client, "one"))[0]["conversation_id"]
    seen = _fake_stream(monkeypatch, pieces=("answer two",))
    _ask(client, "two", conversation_id=cid)
    tail = seen[0]["messages"][-3:]
    assert [(m["role"], m["content"]) for m in tail] == [
        ("user", "one"),
        ("assistant", "answer one"),
        ("user", "two"),
    ]


def test_an_answer_that_broke_is_stored_as_it_ended(client, monkeypatch):
    """The words the reader saw are the words on record, and the ending with
    them — an error with its reason, not a shorter answer."""
    _fake_stream(monkeypatch, pieces=("one", "two", "three"), fail_after=2)
    cid = _events(_ask(client, "hi"))[0]["conversation_id"]
    answer = client.get(f"/api/chat/conversations/{cid}").json()["messages"][1]
    assert _text(answer) == "onetwo"
    assert answer["status"] == "error"
    assert "connection reset" in answer["detail"]


def test_a_reader_who_leaves_leaves_a_cut_answer_on_record(client, monkeypatch):
    """Closing the stream early — the browser gone, or Stop pressed — stores
    what had been written so far as `cut`, and the next turn carries those
    words to the model, because they are what the reader read."""
    _fake_stream(monkeypatch, pieces=("partial ", "answer ", "never seen"))
    with SessionLocal() as db:
        turn = chat.prepare(db, schemas.ChatRequest(content="hi"))
    gen = chat.stream(turn)
    assert next(gen).kind == "start"
    assert next(gen).text == "partial "
    assert next(gen).text == "answer "
    gen.close()

    conv = client.get(f"/api/chat/conversations/{turn.conversation_id}").json()
    answer = conv["messages"][1]
    assert _text(answer) == "partial answer "
    assert answer["status"] == "cut" and answer["detail"] is None

    seen = _fake_stream(monkeypatch)
    _ask(client, "go on", conversation_id=turn.conversation_id)
    assert seen[0]["messages"][-2] == {"role": "assistant", "content": "partial answer "}


def test_an_answer_with_no_words_is_not_repeated_to_the_model(client, monkeypatch):
    """An error before the first word stores an empty turn; the next question
    must not hand the model an empty assistant message."""
    _fake_stream(monkeypatch, pieces=("x",), fail_after=0)
    cid = _events(_ask(client, "hi"))[0]["conversation_id"]
    seen = _fake_stream(monkeypatch)
    _ask(client, "again", conversation_id=cid)
    roles = [m["role"] for m in seen[0]["messages"][-2:]]
    assert roles == ["user", "user"]


def test_deleting_a_conversation_forgets_every_turn(client, monkeypatch):
    _fake_stream(monkeypatch)
    cid = _events(_ask(client, "hi"))[0]["conversation_id"]
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 204
    assert client.get(f"/api/chat/conversations/{cid}").status_code == 404
    assert client.get("/api/chat/conversations").json() == []
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 404
    with SessionLocal() as db:
        assert db.query(models.ChatMessage).count() == 0


def test_a_question_for_a_conversation_that_does_not_exist_is_a_404(client, monkeypatch):
    seen = _fake_stream(monkeypatch)
    r = _ask(client, "hi", conversation_id=999)
    assert r.status_code == 404
    assert "999" in r.json()["detail"]
    assert seen == [] and client.get("/api/chat/conversations").json() == []


def _run_the_chain(monkeypatch, verdict="What this means for you.", contested=False):
    """One completed chain run in the database, without a card or a model.

    The confidant's verdict line is what decides the depth, so it is scripted
    here too: a run this suite calls "3 steps" is three because the colleague
    said the findings fit, not because the chain has three steps."""
    said = {"n": 0}

    def fake(system_prompt, user_content, model=None):
        said["n"] += 1
        text = verdict if system_prompt == chain.SYNTHESIS_SYSTEM_PROMPT else f"step {said['n']}"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += f"\n\nVERDICT: {'CONTESTED' if contested else 'FITS'}"
        return {"analysis": text, "model": model or "m", "cost": 0.004}

    monkeypatch.setattr(advisor, "call_llm", fake)
    with SessionLocal() as db:
        walk = chain.run_chain(db)
        while True:
            try:
                next(walk)
            except StopIteration as done:
                return done.value.id


# --- The context -------------------------------------------------------------


def test_the_model_reads_the_whole_picture_rebuilt_on_every_turn(client, monkeypatch):
    """No tools: the entire context goes with every turn, and it is built from
    the database at that moment — a position added between two questions is in
    the second one's context."""
    seen = _fake_stream(monkeypatch)

    cid = _events(_ask(client, "what do I own?"))[0]["conversation_id"]
    first = seen[0]["messages"][0]["content"]
    assert "# Today is " + datetime.date.today().isoformat() in first
    assert "## Net worth" in first and "## Income and expenses in force today" in first
    assert "(no investment positions)" in first

    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )

    _ask(client, "and now?", conversation_id=cid)
    second = seen[1]["messages"][0]["content"]
    assert "Vanguard All-World" in second
    assert seen[1]["system"] == chat.system_prompt(seen[1]["model"])


def test_the_last_analysis_arrives_as_a_date_and_an_opening_not_a_document(
    client, monkeypatch
):
    """What the context carries about a past analysis, and what it deliberately
    does not.

    The date, because noticing that a run predates the positions is the model's
    job and a date is cheap. The opening lines, verbatim, because the synthesis
    leads with what to do. NOT the whole verdict: it used to be pasted in every
    turn, and a document at full length sits at the same prominence as a picture
    rebuilt this second, which is how today's question gets answered with last
    month's conclusion. The rest is one `read_analysis` call away.
    """
    verdict = "Lead with this.\n\n" + "Then a great deal more. " * 60
    _run_the_chain(monkeypatch, verdict=verdict)

    seen = _fake_stream(monkeypatch)
    _ask(client, "what did the analysis say?")

    ctx = seen[0]["messages"][0]["content"]
    today = datetime.date.today().isoformat()
    assert f"Run 1, finished {today}, 3 steps" in ctx
    assert "Lead with this." in ctx
    assert "OPENING LINES only" in ctx and "read_analysis with run_id=1" in ctx
    assert verdict not in ctx, "the whole document travelled"


def test_the_chat_cannot_start_an_analysis_without_being_asked(client, monkeypatch):
    """A minute of waiting and a few cents stay a decision the reader takes.
    The model proposes; `run_chain` is unreachable until a card is confirmed."""

    def never(_db):
        raise AssertionError("the chat ran the chain on its own")

    monkeypatch.setattr(chain, "run_chain", never)
    seen = _fake_stream(
        monkeypatch, rounds=[[("text", "Want me to run a fresh analysis?")]]
    )
    assert _kinds(_events(_ask(client, "how am I doing?"))) == ["start", "delta", "done"]
    assert "You cannot steer it" in seen[0]["system"]


def test_the_system_prompt_carries_the_two_rules(client):
    """Answering about a real person's money: never a number that is not in
    the context, and a refusal that names its remedy.

    The third assertion used to read "You read; you do not write", and it had
    to move because the sentence stopped being true — the model can now reach a
    tool that would write. What it must never do is narrower and harder: it
    proposes, and nothing reaches the records until the reader confirms. A test
    pinning the old wording would have gone on passing over a prompt that told
    the model it had no such tool while handing it one."""
    assert "NEVER state a number that is not in the context" in chat.SYSTEM_PROMPT
    assert "say what the reader would have to enter" in chat.SYSTEM_PROMPT
    assert "You do not write; you PROPOSE" in chat.SYSTEM_PROMPT
    assert "nothing reaches their records until they press confirm" in chat.SYSTEM_PROMPT


# --- The model ---------------------------------------------------------------


def test_the_chat_model_is_the_request_then_the_env_then_the_app_default(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_CHAT_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "app/default")
    seen = _fake_stream(monkeypatch)

    _ask(client, "hi")
    assert seen[-1]["model"] == "app/default"

    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "chat/model")
    _ask(client, "hi")
    assert seen[-1]["model"] == "chat/model"

    r = _ask(client, "hi", model="picked/model")
    assert seen[-1]["model"] == "picked/model"
    done = _events(r)[-1]
    assert done["kind"] == "done" and done["model"] == "picked/model"


def test_the_dropdown_puts_the_default_first_and_lists_no_slug_twice(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "moonshotai/kimi-k2.6")
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", "moonshotai/kimi-k3")
    body = client.get("/api/chat/models").json()
    slugs = [m["slug"] for m in body["models"]]
    assert body["default"] == "moonshotai/kimi-k2.6"
    assert slugs[0] == "moonshotai/kimi-k2.6"
    assert len(slugs) == len(set(slugs))
    assert "moonshotai/kimi-k3" in slugs and "anthropic/claude-sonnet-4.6" in slugs
    assert all(m["note"] for m in body["models"])


def test_an_empty_question_is_refused_before_anything_is_stored(client, monkeypatch):
    seen = _fake_stream(monkeypatch)
    assert client.post("/api/chat", json={"content": ""}).status_code == 422
    assert seen == [] and client.get("/api/chat/conversations").json() == []


# --- The tools ----------------------------------------------------------------


def test_a_tool_is_run_between_two_round_trips_and_its_result_goes_back(client, monkeypatch):
    """The loop the whole step is for. The model streams a turn that asks for a
    tool and writes nothing; the tool runs; the assistant turn goes back into
    the messages WITH its calls attached, one `tool` turn answers it by id, and
    the model is asked again. It answers on the second pass, and the reader sees
    one uninterrupted answer with a line saying what was consulted."""
    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("get_look_through")],
            [("text", "Counting inside the funds, "), ("text", "coverage is 0%.")],
        ],
    )
    events = _events(_ask(client, "how much NVIDIA do I hold in total?"))
    assert _kinds(events) == ["start", "tool", "delta", "delta", "done"]
    assert events[1]["name"] == "get_look_through"

    assert len(seen) == 2, "a tool call is two completions, not one"
    asked, answered = seen[0]["messages"], seen[1]["messages"]
    assert len(answered) == len(asked) + 2  # the assistant's ask, and the answer to it

    request = answered[-2]
    assert request["role"] == "assistant" and request["content"] is None
    assert request["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_look_through", "arguments": "{}"},
        }
    ]
    result = answered[-1]
    assert result["role"] == "tool" and result["tool_call_id"] == "call_1"
    assert json.loads(result["content"])["ok"] is True


def test_the_tool_that_was_consulted_stays_with_the_answer_it_produced(client, monkeypatch):
    """Provenance, in the place it happened. An answer whose figures came from
    a tool must say so after a reload, and it must say so BETWEEN the paragraph
    that led to the call and the one that used it — the message is a sequence,
    and filing the call after all the words would put it where it did not
    happen."""
    _fake_stream(
        monkeypatch,
        rounds=[
            [("text", "Let me look inside them. "), _wants("get_look_through")],
            [("text", "Nothing could be decomposed.")],
        ],
    )
    cid = _events(_ask(client, "what is inside my funds?"))[0]["conversation_id"]

    answer = client.get(f"/api/chat/conversations/{cid}").json()["messages"][1]
    assert [b["kind"] for b in answer["blocks"]] == ["text", "tool", "text"]
    assert answer["blocks"][1] == {
        "kind": "tool",
        "name": "get_look_through",
        "ok": True,
        "detail": None,
    }
    assert _text(answer) == "Let me look inside them. Nothing could be decomposed."
    assert answer["status"] == "done"


def test_the_words_written_before_a_tool_call_are_not_dropped_from_the_history(
    client, monkeypatch
):
    """A model that says "let me check" and then asks for a tool has written a
    sentence of its own answer. It goes back in the assistant turn with the
    calls, because the next round reads that history and a paragraph deleted
    from it is a paragraph the model will contradict."""
    seen = _fake_stream(
        monkeypatch,
        rounds=[[("text", "Let me check."), _wants("get_look_through")], [("text", "Done.")]],
    )
    _ask(client, "check my funds")
    assert seen[1]["messages"][-2]["content"] == "Let me check."


def test_a_tool_that_does_not_exist_is_answered_to_the_model_not_to_the_reader(
    client, monkeypatch
):
    """A hallucinated tool name is the model's mistake and the model can fix
    it, so it comes back as a tool result naming the tools that DO exist, and
    the turn carries on. Raising instead would end the answer with "the answer
    broke off" over something the next round would have got right."""
    seen = _fake_stream(
        monkeypatch,
        rounds=[[_wants("get_everything")], [("text", "I cannot do that, but I can tell you…")]],
    )
    events = _events(_ask(client, "do everything"))
    assert _kinds(events) == ["start", "tool", "delta", "done"]

    result = json.loads(seen[1]["messages"][-1]["content"])
    assert result["ok"] is False
    assert "get_everything" in result["error"] and "get_look_through" in result["error"]


def test_arguments_that_are_not_json_come_back_as_something_to_correct(client, monkeypatch):
    """The arguments arrive as a string the model wrote character by character,
    and a model can write a broken one. Two different mistakes, told apart on
    purpose: text that is not JSON at all has to be rewritten, a field of the
    wrong type has to be corrected. A ValueError out of the parser would be
    neither — it would be a dead stream."""
    seen = _fake_stream(
        monkeypatch,
        rounds=[[_wants("get_look_through", arguments="{refresh: yes")], [("text", "Sorry.")]],
    )
    _ask(client, "look through, badly")
    result = json.loads(seen[1]["messages"][-1]["content"])
    assert result["ok"] is False and "not valid JSON" in result["error"]

    seen = _fake_stream(
        monkeypatch,
        rounds=[[_wants("get_look_through", arguments='{"refresh": "sometimes"}')], [("text", "…")]],
    )
    _ask(client, "look through, wrongly typed")
    result = json.loads(seen[1]["messages"][-1]["content"])
    assert result["ok"] is False and "do not fit get_look_through" in result["error"]


def test_a_model_that_only_ever_asks_for_tools_is_stopped_without_an_error(
    client, monkeypatch
):
    """The bound, and what it is for. A model that answers every tool result
    with the same call again would loop for as long as nobody was watching, and
    what it spends meanwhile is a bill rather than a turn. So the bound stays —
    and what changed is the ENDING. It used to be a raise, which meant a turn
    that ran out of rounds looked identical to a turn that broke, whether the
    model was looping or comparing four funds properly. Now the last round is
    asked with no tools, so the turn ends on the model's own words.

    The fake here still asks for a tool on that last round, which a model with
    no tools declared cannot really do. That is the point of scripting it: the
    call is dropped rather than run, because running it would buy a result no
    completion is left to read.
    """
    rounds = chat.MAX_COMPLETIONS_PER_TURN
    seen = _fake_stream(
        monkeypatch,
        rounds=[[_wants("get_look_through")]] * (rounds - 1)
        + [[("text", "I could not finish that."), _wants("get_look_through")]],
    )
    events = _events(_ask(client, "loop forever"))

    # Read off the constant rather than written out: the bound has moved twice
    # already, and a test that has to be edited alongside it is a test that
    # says nothing about the rule.
    assert _kinds(events) == ["start"] + ["tool"] * (rounds - 1) + ["delta", "done"]
    assert len(seen) == chat.MAX_COMPLETIONS_PER_TURN, "the bound is on completions"
    assert seen[-1]["tools"] is None, "the last round is asked with nothing to call"
    assert all(r["tools"] for r in seen[:-1]), "every earlier round has them"


@pytest.mark.parametrize(
    "model, where",
    [
        # Anthropic's: after the round's tool results, where it does not cost
        # the round its cache (LAST_TOOL_ROUND_NOTICE says why, with figures).
        ("anthropic/claude-opus-5.5", "last message"),
        # Every other model: in the system prompt, as it always was.
        ("qwen/qwen3.8-max-0902", "system prompt"),
    ],
)
def test_the_last_round_is_offered_no_tools_and_the_one_before_is_told_so(
    client, monkeypatch, model, where
):
    """The deadline, in the two places it lives.

    `tools=None` on the final completion is what makes "ran out of rounds"
    unrepresentable: `stream_llm` omits the field entirely for a falsy list, so
    the model is not offered something it would get no answer to.

    THE NOTICE IS PROSE AND THIS SUITE CANNOT JUDGE WHETHER A MODEL HEEDS IT,
    the same way `test_a_request_for_a_recommendation_...` cannot judge whether
    a model decides to suggest anything. What is asserted is delivery: the
    sentence reaches the model on the second-to-last round and on no other.
    Whether it then proposes early is a question for a live model, asked by
    hand. Nothing depends on the answer — the round after it has no tools
    regardless, so the notice removes a surprise and never enforces a thing.

    Where it reaches the model depends on the model: at the end of the round
    for one that caches only on request, in the system prompt for the rest.
    """
    rounds = chat.MAX_COMPLETIONS_PER_TURN
    seen = _fake_stream(
        monkeypatch,
        rounds=[[_wants("get_look_through")]] * (rounds - 1) + [[("text", "Here is what I have.")]],
    )
    _ask(client, "keep looking", model=model)

    def told(r: dict) -> dict:
        return {
            "system prompt": chat.LAST_TOOL_ROUND_NOTICE in r["system"],
            "last message": r["messages"][-1]
            == {"role": "user", "content": chat.LAST_TOOL_ROUND_NOTICE},
        }

    carried = [n for n, r in enumerate(seen, 1) if any(told(r).values())]
    assert carried == [rounds - 1], "told once, on the last round that can act on it"
    assert told(seen[rounds - 2]) == {
        "system prompt": where == "system prompt",
        "last message": where == "last message",
    }
    assert "last round with tools" in chat.LAST_TOOL_ROUND_NOTICE
    assert seen[rounds - 2]["tools"], "and that round still has them"


def test_a_turn_that_calls_nothing_is_still_one_round_trip(client, monkeypatch):
    """The tools cost a turn nothing until one is asked for. The second
    completion happens because there were calls to answer, never because the
    loop exists."""
    seen = _fake_stream(monkeypatch, pieces=("Two positions.",))
    assert _kinds(_events(_ask(client, "what do I own?"))) == ["start", "delta", "done"]
    assert len(seen) == 1


def test_the_model_is_offered_the_tools_with_schemas_it_did_not_have_to_be_told(
    client, monkeypatch
):
    """Nothing is transcribed. The schema the model is shown is generated from
    `LookThroughArgs`, so the two cannot disagree: rename the field or reword
    its description and this test moves with the model, which is exactly what a
    hand-written copy would not do. This codebase already paid for a copied
    schema once, in `schema.d.ts`.

    The list is compared against the REGISTRY rather than against names written
    out here, for the same reason: a tool added and not declared, or declared
    twice, fails without anybody having to remember this line. OpenRouter's
    web search rides beside them for Anthropic's models (brief AG) and is not
    one of them: nothing here runs it, so the REGISTRY has no entry for it."""
    seen = _fake_stream(monkeypatch)
    _ask(client, "hi")

    declared = [t for t in seen[0]["tools"] if t.get("type") == "function"]
    assert sorted(t["function"]["name"] for t in declared) == sorted(tools.REGISTRY)
    looked = next(
        t for t in declared if t["function"]["name"] == "get_look_through"
    )["function"]["parameters"]
    assert set(looked["properties"]) == set(tools.LookThroughArgs.model_fields)
    assert (
        looked["properties"]["refresh"]["description"]
        == tools.LookThroughArgs.model_fields["refresh"].description
    )


def test_the_look_through_is_a_tool_because_the_picture_does_not_carry_it(client):
    """The reason it earns an exception to "no read tools", stated as a test.
    The context has thirteen sections and the composition is in none of them —
    it lives in the analyst's context, not the chat's — so "how much NVIDIA in
    total" is unanswerable without the tool. And the reason it is not simply
    added to the context is network: on a cache miss it walks the fund issuers,
    once per position, on every turn including "hello"."""
    with SessionLocal() as db:
        context = chat.build_chat_context(db)
    assert "Look-through" not in context and "Overlapping top holdings" not in context
    assert "get_look_through" in tools.REGISTRY


def test_the_look_through_reads_the_cache_and_does_not_ask_for_fresh_figures(
    client, monkeypatch
):
    """Cache-first by default. `refresh` is what turns one question into a
    walk of every fund issuer, so the model has to ask for it explicitly and
    the default has to be the cheap one."""
    asked: list[bool] = []

    def spy(db, refresh=False):
        asked.append(refresh)
        return {"rows": [], "coverage_pct": 0.0, "undecomposed_pct": 0.0, "total_value": 1.0}

    monkeypatch.setattr(composition, "compute_portfolio_composition", spy)
    with SessionLocal() as db:
        tools.invoke(db, advisor.ToolCall(id="c", name="get_look_through", arguments="{}"))
        tools.invoke(
            db,
            advisor.ToolCall(
                id="c", name="get_look_through", arguments='{"refresh": true}'
            ),
        )
    assert asked == [False, True]


def test_the_look_through_says_what_it_could_not_look_inside(client):
    """Coverage travels with the figures, and so does what they mean. With no
    source reachable — which is every test run, and a real outage besides —
    nothing decomposes, and the honest report of that is 0% covered and 100%
    unknown. An empty country list with no coverage beside it would read as
    "you own nothing anywhere"."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )

    with SessionLocal() as db:
        outcome = tools.invoke(
            db, advisor.ToolCall(id="c", name="get_look_through", arguments="{}")
        )

    assert outcome["ok"] is True
    result = outcome["result"]
    assert result["coverage_pct"] == 0.0 and result["undecomposed_pct"] == 100.0
    assert result["total_value"] == 1000.0
    assert [r["symbol"] for r in result["rows"]] == ["VWCE.MI"]
    assert result["rows"][0]["decomposed"] is False and result["rows"][0]["error"]
    assert any("UNKNOWN, not empty" in line for line in result["reading"])


def test_a_tool_call_is_assembled_from_the_fragments_it_arrived_in(monkeypatch):
    """The one piece of the protocol this app implements itself. The name
    arrives once and the arguments a few characters at a time, tied together
    only by `index`; every fragment after the first carries None where the id
    and the name were, and copying those across would erase them. Two calls
    interleave, which is why the accumulator is keyed and not a running
    string."""

    def fragment(index, call_id=None, name=None, arguments=None):
        function = type("Fn", (), {"name": name, "arguments": arguments})()
        return type("Frag", (), {"index": index, "id": call_id, "function": function})()

    class FakeChunk:
        # A round that asks for tools ends on `tool_calls`, said by its last
        # chunk; a stream that never says how it ended is refused as unfinished.
        def __init__(self, *fragments, finish_reason=None):
            delta = type("Delta", (), {"content": None, "tool_calls": list(fragments)})()
            self.choices = [
                type("Choice", (), {"delta": delta, "finish_reason": finish_reason})()
            ]

    chunks = [
        FakeChunk(fragment(0, call_id="call_a", name="get_look_through", arguments="")),
        FakeChunk(fragment(1, call_id="call_b", name="other", arguments='{"a"')),
        FakeChunk(fragment(0, arguments='{"refr')),
        FakeChunk(fragment(1, arguments=": 1}")),
        FakeChunk(fragment(0, arguments='esh": true}'), finish_reason="tool_calls"),
    ]

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(chunks)

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["tools"] == [{"a": 1}], "the tools travel to the API"
            return FakeStream()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    monkeypatch.setattr(advisor, "_client", lambda: FakeClient())

    pieces = list(
        _REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}], tools=[{"a": 1}])
    )
    assert pieces == [
        ("tool_call", advisor.ToolCall("call_a", "get_look_through", '{"refresh": true}')),
        ("tool_call", advisor.ToolCall("call_b", "other", '{"a": 1}')),
    ]


def test_a_turn_that_only_asked_for_a_tool_is_not_an_empty_response(monkeypatch):
    """A turn that calls a tool writes no content at all, and "the model
    returned an empty response" is exactly what an unfixed emptiness check
    would say about every one of them — an error on the one path the whole step
    exists to open."""

    class FakeChunk:
        def __init__(self):
            fn = type("Fn", (), {"name": "get_look_through", "arguments": "{}"})()
            frag = type("Frag", (), {"index": 0, "id": "call_1", "function": fn})()
            delta = type("Delta", (), {"content": None, "tool_calls": [frag]})()
            self.choices = [type("Choice", (), {"delta": delta, "finish_reason": "tool_calls"})()]

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter([FakeChunk()])

    class FakeClient:
        chat = type(
            "Chat", (), {"completions": type("C", (), {"create": lambda self, **k: FakeStream()})()}
        )()

    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    monkeypatch.setattr(advisor, "_client", lambda: FakeClient())

    kinds = [k for k, _ in _REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}])]
    assert kinds == ["tool_call"]


# --- Propose, confirm, resume -------------------------------------------------
#
# No write tool exists yet, so the plumbing is exercised with a fake one. It is
# a real Tool in the real registry — registered by the fixture, not injected
# past it — so what these tests prove about the round trip is what STEP 3's
# first genuine write tool will inherit.


class _RecordThingArgs(BaseModel):
    what: str
    amount: float = 0.0


def _fake_tool(monkeypatch, *, confirmation="light", diff=(), fingerprint="v1", run=None):
    """A write tool in the registry, and the record of what it was asked to do.

    `fingerprint` is a plain value rather than something computed, so a test
    can move the ground under a card by changing it — which is exactly what a
    second tab writing between proposal and confirmation does, and the only
    way to reproduce it without a second tab."""
    ground = {"fingerprint": fingerprint}
    written: list[dict] = []

    def _run(db, args):
        if run is not None:
            return run(db, args)
        written.append(args.model_dump())
        return {"recorded": args.what, "amount": args.amount}

    monkeypatch.setitem(
        tools.REGISTRY,
        "record_thing",
        tools.Tool(
            name="record_thing",
            description="Record a thing.",
            arguments=_RecordThingArgs,
            run=_run,
            propose=lambda db, args: tools.Proposal(
                title=f"record: {args.what} · {args.amount:.2f}",
                fingerprint=ground["fingerprint"],
                confirmation=confirmation,
                diff=list(diff),
            ),
        ),
    )
    return {"written": written, "ground": ground}


def _propose(client, monkeypatch, arguments='{"what": "a gold necklace", "amount": 500}'):
    """One turn that ends on a card. Returns (events, the card)."""
    _fake_stream(
        monkeypatch,
        rounds=[[("text", "I can record that:"), _wants("record_thing", arguments=arguments)]],
    )
    events = _events(_ask(client, "my grandmother gave me a 500 euro gold necklace"))
    card = next(e["card"] for e in events if e["kind"] == "card")
    return events, card


def _decide(client, card_id: str, decision: str, model: str | None = None):
    body: dict = {"decision": decision}
    if model:
        body["model"] = model
    return client.post(f"/api/chat/cards/{card_id}", json=body)


def test_a_proposed_write_ends_the_turn_on_a_card_and_writes_nothing(client, monkeypatch):
    """The shape every write rides on. The model drafts the change, the card
    says exactly what would happen, and the turn ends there — DONE, not a
    fourth ending: `cut` is inferred from the absence of a terminal event, so a
    turn stopping cleanly on a card has to say so, or the panel reports a
    perfectly good proposal as an answer that broke off."""
    state = _fake_tool(monkeypatch)
    events, card = _propose(client, monkeypatch)

    assert _kinds(events) == ["start", "delta", "card", "done"]
    assert card["title"] == "record: a gold necklace · 500.00"
    assert card["arguments"] == {"what": "a gold necklace", "amount": 500.0}
    assert card["outcome"] == "pending" and card["result"] is None
    assert card["card_id"] and card["call_id"] == "call_1"
    assert state["written"] == [], "the model wrote"


def test_the_card_is_stored_with_the_turn_and_is_still_there_on_a_reload(client, monkeypatch):
    """A closed browser leaves nothing pending, because nothing was pending in
    the browser: the card is a stored block, so it comes back with the
    conversation, and so does the fact that it was never answered."""
    _fake_tool(monkeypatch)
    _, card = _propose(client, monkeypatch)

    conv = client.get("/api/chat/conversations").json()[0]
    stored = client.get(f"/api/chat/conversations/{conv['id']}").json()["messages"][1]
    assert [b["kind"] for b in stored["blocks"]] == ["text", "card"]
    assert stored["blocks"][1] == card
    assert stored["status"] == "done"


def test_confirming_runs_the_tool_records_the_outcome_and_answers(client, monkeypatch):
    """The whole round trip. The write happens once, the card stops being a
    proposal and becomes a receipt, and the model is told what it produced so
    it can say so in words the reader reads."""
    state = _fake_tool(monkeypatch)
    _, card = _propose(client, monkeypatch)

    seen = _fake_stream(monkeypatch, pieces=("Recorded.",))
    events = _events(_decide(client, card["card_id"], "confirm"))
    assert _kinds(events) == ["start", "decided", "delta", "done"]
    assert events[0]["user_message_id"] is None, "nobody asked a question"

    assert state["written"] == [{"what": "a gold necklace", "amount": 500.0}]

    settled = client.get(
        f"/api/chat/conversations/{events[0]['conversation_id']}"
    ).json()["messages"][1]["blocks"][1]
    assert settled["outcome"] == "confirmed"
    assert settled["result"] == {"recorded": "a gold necklace", "amount": 500.0}
    assert events[1]["card"] == settled, "the stream said the decision as it is stored"

    # and the model was told, in the protocol's own shape
    # A confirm appends no turn of the reader's: the exchange comes right
    # before the app's note about the decision, which ends the list.
    request, result = seen[0]["messages"][-3], seen[0]["messages"][-2]
    note = seen[0]["messages"][-1]
    assert note["role"] == "user" and note["content"].startswith(
        "THE READER HAS JUST ANSWERED A CARD"
    )
    assert request["role"] == "assistant"
    assert request["tool_calls"][0]["function"]["name"] == "record_thing"
    assert result["role"] == "tool" and result["tool_call_id"] == "call_1"
    answered = json.loads(result["content"])
    assert answered["outcome"] == "confirmed"
    assert answered["written"] == {"recorded": "a gold necklace", "amount": 500.0}


def test_rejecting_writes_nothing_and_still_says_so_on_record(client, monkeypatch):
    """A card whose outcome is not stored is a "done!" with no receipt, and a
    rejection needs one just as much: without it the history shows a proposal
    that looks unanswered, and the model proposes it again."""
    state = _fake_tool(monkeypatch)
    _, card = _propose(client, monkeypatch)

    seen = _fake_stream(monkeypatch, pieces=("Understood.",))
    events = _events(_decide(client, card["card_id"], "reject"))
    assert _kinds(events) == ["start", "decided", "delta", "done"]
    assert state["written"] == []

    settled = client.get(
        f"/api/chat/conversations/{events[0]['conversation_id']}"
    ).json()["messages"][1]["blocks"][1]
    assert settled["outcome"] == "rejected" and settled["result"] is None
    assert events[1]["card"] == settled
    # The tool turn says it, and so does the app's note after it.
    assert json.loads(seen[0]["messages"][-2]["content"])["outcome"] == "rejected"
    assert "They rejected" in seen[0]["messages"][-1]["content"]


def test_a_card_nobody_answered_is_carried_back_as_unanswered(client, monkeypatch):
    """The API pairs an assistant turn's calls with the `tool` turns that
    answer them and refuses a conversation missing one — so a card the reader
    walked away from cannot be a gap. "Still waiting" is the answer, and it is
    also the true one."""
    _fake_tool(monkeypatch)
    _, card = _propose(client, monkeypatch)

    seen = _fake_stream(monkeypatch, pieces=("Still waiting on you.",))
    _ask(client, "anything else?", conversation_id=1)

    result = json.loads(seen[0]["messages"][-2]["content"])
    assert result["outcome"] == "pending"
    assert "neither confirmed nor rejected" in result["note"]
    assert seen[0]["messages"][-3]["tool_calls"][0]["id"] == card["call_id"]


def test_a_card_is_decided_once(client, monkeypatch):
    """A second confirm would run the write twice, and there is nothing in a
    ledger that says a row was meant to be one row."""
    state = _fake_tool(monkeypatch)
    _, card = _propose(client, monkeypatch)

    _fake_stream(monkeypatch)
    assert _decide(client, card["card_id"], "confirm").status_code == 200
    again = _decide(client, card["card_id"], "confirm")
    assert again.status_code == 409 and "already confirmed" in again.json()["detail"]
    assert len(state["written"]) == 1


def test_a_stale_card_is_refused_and_says_to_ask_again(client, monkeypatch):
    """Between proposing and confirming, the ground can move — from another
    tab, from a catch-up, from the reader themselves in another window. What
    makes a card stale is not its age: a ten-second-old one can be stale and a
    three-day-old one perfectly good. It is that what the proposal was drawn
    against changed, which is what the fingerprint is for, and a refusal is
    the only honest answer because the card is describing a write that would
    no longer be that write."""
    state = _fake_tool(monkeypatch)
    _, card = _propose(client, monkeypatch)

    state["ground"]["fingerprint"] = "v2"  # somebody else wrote
    refused = _decide(client, card["card_id"], "confirm")

    assert refused.status_code == 409
    assert "no longer what" in refused.json()["detail"]
    assert state["written"] == [], "a stale card was written anyway"
    still = client.get("/api/chat/conversations/1").json()["messages"][1]["blocks"][1]
    assert still["outcome"] == "pending", "a refused card must stay answerable"


def test_a_write_that_fails_leaves_no_card_saying_it_worked(client, monkeypatch):
    """The write and the record of it are one unit of work, and this is what
    that buys. A card reading "confirmed" over a write that rolled back is the
    receipt lying about the thing it is a receipt for — and it would be
    invisible, because both halves look like they landed."""

    def explode(db, args):
        raise RuntimeError("the ledger said no")

    _fake_tool(monkeypatch, run=explode)
    _, card = _propose(client, monkeypatch)

    refused = _decide(client, card["card_id"], "confirm")
    assert refused.status_code == 409 and "the ledger said no" in refused.json()["detail"]

    still = client.get("/api/chat/conversations/1").json()["messages"][1]["blocks"][1]
    assert still["outcome"] == "pending" and still["result"] is None


def test_a_write_that_fails_HALFWAY_leaves_nothing_behind(client, monkeypatch):
    """The guarantee the unit of work actually buys, and the one the test above
    does not reach: a tool that raises before touching anything proves only
    that nothing happened, which would be true with no transaction at all.
    This one writes a row and THEN fails. Both halves land or neither does —
    otherwise a chat-proposed write could leave an institution nobody asked
    for, under a card that still says "pending"."""

    def half(db, args):
        crud.create_institution(db, schemas.InstitutionCreate(name="Half-written"))
        raise RuntimeError("and then it fell over")

    _fake_tool(monkeypatch, run=half)
    _, card = _propose(client, monkeypatch)

    assert _decide(client, card["card_id"], "confirm").status_code == 409
    assert client.get("/api/institutions").json() == [], "a rolled-back write survived"
    still = client.get("/api/chat/conversations/1").json()["messages"][1]["blocks"][1]
    assert still["outcome"] == "pending"


def test_a_photograph_carries_a_diff_and_an_event_does_not(client, monkeypatch):
    """The rule is the domain's, and it is about reversibility rather than
    size. An event — a transaction, a dated valuation — is a dated claim,
    verifiable, undone by deleting it, so a light confirmation is enough. A
    photograph is the record OF a day: editing a snapshot restates what that
    day said and re-anchors every projection after it, and deleting the edit
    does not give the old day back. So it has to show what that day currently
    says, line by line, before anybody presses confirm."""
    _fake_tool(monkeypatch)
    _, event_card = _propose(client, monkeypatch)
    assert event_card["confirmation"] == "light" and event_card["diff"] == []

    _fake_tool(
        monkeypatch,
        confirmation="diff",
        diff=[
            {"field": "quantity", "now": "10", "proposed": "12"},
            {"field": "unit_price", "now": None, "proposed": "128.40"},
        ],
    )
    _, photo_card = _propose(client, monkeypatch)
    assert photo_card["confirmation"] == "diff"
    assert [d["field"] for d in photo_card["diff"]] == ["quantity", "unit_price"]
    # null and zero are different claims: that day says nothing about the price
    assert photo_card["diff"][1]["now"] is None


def test_a_result_that_json_cannot_carry_is_stored_anyway(client, monkeypatch):
    """A write tool returns what it wrote, and what it wrote has dates in it —
    `add_real_asset` returns a dated valuation, which is the next thing this
    brief builds. The blocks column is JSON text, so a `datetime.date` in there
    is not a bad row, it is an uncaught TypeError in the middle of a confirmed
    write. Coerced at the boundary the value enters, once, to the ISO string
    that is the right way to keep a date anyway."""
    _fake_tool(
        monkeypatch,
        run=lambda db, args: {"real_asset_id": 7, "valued_on": datetime.date(2026, 9, 4)},
    )
    _, card = _propose(client, monkeypatch)

    _fake_stream(monkeypatch, pieces=("Recorded.",))
    assert _decide(client, card["card_id"], "confirm").status_code == 200

    settled = client.get("/api/chat/conversations/1").json()["messages"][1]["blocks"][1]
    assert settled["outcome"] == "confirmed"
    assert settled["result"] == {"real_asset_id": 7, "valued_on": "2026-09-04"}


def test_a_card_that_could_not_be_stored_is_never_stored(client, monkeypatch):
    """The quietest way this could go wrong, and it is permanent. A card is
    written into a JSON column and read back through `ChatCardBlock`, so a tool
    that draws a malformed one — a diff whose sides are numbers rather than the
    text a diff is read as — would put a block in the row that every later read
    of that conversation chokes on. One mistake, and the conversation is
    unreadable for good. So the card is built through the schema at the
    boundary the mistake enters, and a tool that draws a bad one is told so."""
    _fake_tool(
        monkeypatch,
        confirmation="diff",
        diff=[{"field": "quantity", "now": 10, "proposed": 12}],
    )
    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("record_thing", '{"what": "x"}')],
            [("text", "I could not draft that.")],
        ],
    )
    events = _events(_ask(client, "record it"))
    assert _kinds(events) == ["start", "tool", "delta", "done"]

    told = json.loads(seen[1]["messages"][-1]["content"])
    assert told["ok"] is False and "cannot be stored" in told["error"]

    conv = client.get("/api/chat/conversations/1")
    assert conv.status_code == 200, "the conversation became unreadable"
    assert [b["kind"] for b in conv.json()["messages"][1]["blocks"]] == ["tool", "text"]


def test_two_windows_confirming_at_once_write_once(client, monkeypatch):
    """A decision is taken once, and the check that reads "pending" is not what
    makes that true: two tabs — the same two tabs the staleness rule exists for
    — both read pending, both run the tool, and the ledger gets two rows for
    one purchase. Measured before the compare-and-swap: two 200s and the write
    landed twice. The loser now gets a 409 and its half of the work is rolled
    back with it.

    A tool may still RUN twice; only one commits. Anything a tool does outside
    the database would therefore happen twice, and nothing here does."""

    def run(db, args):
        crud.create_institution(db, schemas.InstitutionCreate(name=args.what))
        return {"recorded": args.what}

    _fake_tool(monkeypatch, run=run)
    _, card = _propose(client, monkeypatch, arguments='{"what": "Broker A"}')
    _fake_stream(monkeypatch, pieces=("Recorded.",))

    codes: list[int] = []
    together = threading.Barrier(2, timeout=10)

    def press():
        together.wait()
        codes.append(
            client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}).status_code
        )

    threads = [threading.Thread(target=press) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert sorted(codes) == [200, 409], codes
    assert len(client.get("/api/institutions").json()) == 1, "the write landed twice"
    settled = client.get("/api/chat/conversations/1").json()["messages"][1]["blocks"][1]
    assert settled["outcome"] == "confirmed"


def test_a_card_that_does_not_exist_is_a_404(client, monkeypatch):
    seen = _fake_stream(monkeypatch)
    r = _decide(client, "nosuchcard", "confirm")
    assert r.status_code == 404 and "nosuchcard" in r.json()["detail"]
    assert seen == []


def test_the_look_through_is_not_a_write_and_still_runs_when_asked(client, monkeypatch):
    """The two halves of the registry, told apart by one field. A tool with a
    `propose` never runs on the model's say-so; one without it is a read and
    runs immediately. Nothing else decides."""
    assert tools.REGISTRY["get_look_through"].propose is None
    seen = _fake_stream(
        monkeypatch, rounds=[[_wants("get_look_through")], [("text", "Coverage is 0%.")]]
    )
    assert _kinds(_events(_ask(client, "what is inside my funds?"))) == [
        "start",
        "tool",
        "delta",
        "done",
    ]
    assert len(seen) == 2, "a read answers in the same turn; only a write ends it"


# The registry the test below searches. Three rows and not thirty: what is
# being exercised is the round trip, and a fixture the size of the real export
# would only make the assertions harder to read. Two small-cap funds and one
# that is not, so the search has something to tell apart.
_SMALL_CAP_CATALOGUE = pd.DataFrame(
    [
        {
            "name": "Xtrackers MSCI World Small Cap UCITS ETF 1C",
            "ticker": "XSWC", "dividends": "Accumulating", "ter": 0.25, "size": 140,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 3284, "hedged": False,
        },
        {
            "name": "SPDR MSCI World Small Cap UCITS ETF",
            "ticker": "ZPRS", "dividends": "Accumulating", "ter": 0.45, "size": 900,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 3500, "hedged": False,
        },
        {
            "name": "Vanguard FTSE All-World UCITS ETF (USD) Accumulating",
            "ticker": "VWCE", "dividends": "Accumulating", "ter": 0.14, "size": 49047,
            "replication": "Optimized sampling", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 3757, "hedged": False,
        },
    ],
    index=pd.Index(["IE000F354Q61", "IE00BCBJG560", "IE00BK5BQT80"], name="isin"),
)


def test_a_request_for_a_recommendation_searches_then_ends_on_a_card(client, monkeypatch):
    """Asking to be recommended a fund: search, propose, card, three sentences.

    THIS TESTS THE PLUMBING AND NOT THE JUDGEMENT. The model is faked, so what
    is proved here is that a `suggest_instrument` call arriving after a
    `search_catalogue` call becomes a card carrying the reasoning, and that
    nothing reaches the watchlist before the reader says yes. It proves
    NOTHING about whether a real model, reading the prompt, decides to make
    that call — that is a question about a live model and it is asked by hand,
    outside this suite, because the `offline` fixture means no test may ask
    OpenRouter anything. Nobody should ever read a green here as the model
    complying.
    """
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: _SMALL_CAP_CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200

    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("search_catalogue", '{"query": "world small cap"}')],
            [
                ("text", "Un'idea da guardare:"),
                _wants(
                    "suggest_instrument",
                    json.dumps(
                        {
                            "isin": "IE000F354Q61",
                            "reason": "It is the broad small-cap sleeve your equity misses.",
                            "based_on": "You hold only large-cap world funds, and your "
                            "horizon in the questionnaire is 15 years.",
                            "unknowns": "I do not know your tax situation, or whether a "
                            "pension already covers this.",
                        }
                    ),
                    call_id="call_2",
                ),
            ],
        ],
    )
    events = _events(_ask(client, "mi consigli un ETF per le small cap"))
    assert _kinds(events) == ["start", "tool", "delta", "card", "done"]

    # the search happened, offline, and its result went back to the model
    found = json.loads(seen[1]["messages"][-1]["content"])["result"]
    assert found["coverage"] == "all"
    assert "IE000F354Q61" in json.dumps(found)

    card = next(e["card"] for e in events if e["kind"] == "card")
    assert "Xtrackers MSCI World Small Cap" in card["title"] and "IE000F354Q61" in card["title"]
    assert card["verb"] == "Add to watchlist"
    # all three sentences travelled, which is the whole shape of a suggestion
    assert card["arguments"]["reason"].startswith("It is the broad small-cap")
    assert "questionnaire" in card["arguments"]["based_on"]
    assert "tax situation" in card["arguments"]["unknowns"]

    # and it is still only a proposal
    assert card["outcome"] == "pending"
    assert client.get("/api/watchlist").json() == []


# What the live lane answers with while the comparison below runs. Faked rather
# than left to the `offline` fixture's refusal, because a lookup that comes back
# empty is a different turn: the model would have three blanks to reason about
# instead of three candidates, and the route being tested is the one it takes
# when the tools all work.
_QUOTES = {
    "XSWC": [{"symbol": "XSWC.DE", "name": "Xtrackers MSCI World Small Cap UCITS ETF 1C",
              "quote_type": "ETF", "exchange": "GER", "price": 41.20}],
    "ZPRS": [{"symbol": "ZPRS.L", "name": "SPDR MSCI World Small Cap UCITS ETF",
              "quote_type": "ETF", "exchange": "LSE", "price": 55.10}],
    "VWCE": [{"symbol": "VWCE.DE", "name": "Vanguard FTSE All-World UCITS ETF",
              "quote_type": "ETF", "exchange": "GER", "price": 132.80}],
}


def _small_cap_desk(client, monkeypatch):
    """The registry loaded and the live lane answering, ready to be compared."""
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: _SMALL_CAP_CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    monkeypatch.setattr(prices, "_fetch_lookup", lambda q, count: _QUOTES.get(q, [])[:count])


def _looks_up(ticker: str):
    return _wants("lookup_symbol", json.dumps({"query": ticker}), call_id=f"call_{ticker}")


def _proposes(isin: str):
    return _wants(
        "suggest_instrument",
        json.dumps(
            {
                "isin": isin,
                "reason": "The cheaper of the two small-cap funds: 20bp a year "
                "less than the other, for the same index.",
                "based_on": "Your equity is large-cap world only, and the "
                "questionnaire puts your horizon at 15 years.",
                "unknowns": "I do not know your tax situation, or whether a pension "
                "already covers small caps.",
            }
        ),
        call_id="call_propose",
    )


def test_a_thorough_comparison_before_a_suggestion_still_reaches_the_card(
    client, monkeypatch
):
    """The route a capable model actually takes, which the suite had never
    walked. The test above it fakes the MINIMUM path — search, propose, two
    rounds — and a minimum path proves the plumbing and nothing about the
    budget. This one is the transcript that broke: `search_catalogue`, then
    `lookup_symbol` once per candidate because comparing before choosing is
    the diligence worth having, then the card. Five completions.

    Under the old cap of five that turn could not draw its card — the fifth
    round was the one that raised — so the model announced a card and never
    made one. The assertion is simply that the card arrives, and it fails on
    any cap that punishes a three-way comparison.
    """
    _small_cap_desk(client, monkeypatch)
    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("search_catalogue", '{"query": "world small cap"}')],
            [_looks_up("XSWC")],
            [_looks_up("ZPRS")],
            [_looks_up("VWCE")],
            [("text", "Le ho confrontate. "), _proposes("IE000F354Q61")],
        ],
    )
    events = _events(_ask(client, "mi consigli un ETF per small cap?"))

    assert _kinds(events) == ["start", "tool", "tool", "tool", "tool", "delta", "card", "done"]
    assert len(seen) == 5, "search, three lookups, the proposal"
    card = next(e["card"] for e in events if e["kind"] == "card")
    assert "Xtrackers MSCI World Small Cap" in card["title"]
    assert card["outcome"] == "pending" and client.get("/api/watchlist").json() == []

    # and the comparison had something to compare: each lookup answered
    quoted = json.loads(seen[4]["messages"][-1]["content"])["result"]
    assert quoted["reachable"] is True and quoted["results"][0]["symbol"] == "VWCE.DE"


def test_a_comparison_one_round_too_long_ends_in_words_and_not_a_break(
    client, monkeypatch
):
    """The boundary, walked one round past the cap. Five candidates is search
    plus five lookups — six rounds, all the tool-carrying rounds there are — so
    the proposal has nowhere to go. What the reader gets is the model's prose,
    ending `done`.

    That is the whole change in one assertion. The same route under the old
    shape ended on "the model asked for tools N times without ever writing an
    answer", which reads to the reader as a broken app rather than as a turn
    that ran long. A cap has to exist and a runaway has to stop; what must
    never happen is a stop that looks like a crash.

    Whether the prose actually explains what it could not finish is the model's
    business and this suite fakes the model. What it can hold is that the words
    are the ending: no error event, and the card the sixth round would have
    drawn is simply absent rather than half-drawn.
    """
    _small_cap_desk(client, monkeypatch)
    tickers = ["XSWC", "ZPRS", "VWCE", "XSWC", "ZPRS"]
    seen = _fake_stream(
        monkeypatch,
        rounds=[[_wants("search_catalogue", '{"query": "world small cap"}')]]
        + [[_looks_up(t)] for t in tickers]
        + [[("text", "Ho guardato cinque fondi e non mi resta un giro per la carta.")]],
    )
    events = _events(_ask(client, "confrontane cinque"))

    assert len(seen) == chat.MAX_COMPLETIONS_PER_TURN
    assert _kinds(events) == ["start"] + ["tool"] * 6 + ["delta", "done"]
    assert "error" not in _kinds(events)
    assert not any(e["kind"] == "card" for e in events)

    answer = client.get("/api/chat/conversations/1").json()["messages"][1]
    assert answer["status"] == "done" and _text(answer).startswith("Ho guardato cinque fondi")


# --- The analyzer, orchestrated -----------------------------------------------
#
# The chain used to be a page with a button and a blocking POST. It is a card
# the model proposes, the reader confirms, and then WATCHES: the confirm stream
# carries one `step` event per finished step before the model is asked to say
# anything at all. What is asserted below is that shape, and the two things it
# must not cost — the information asymmetry, and a card that reads confirmed
# over a run that did not happen.


def _propose_analysis(client, monkeypatch):
    """One turn that ends on the analyzer's card. Returns the card."""
    _fake_stream(
        monkeypatch,
        rounds=[[("text", "Worth a fresh look:"), _wants("run_analysis")]],
    )
    events = _events(_ask(client, "analyse my situation"))
    return next(e["card"] for e in events if e["kind"] == "card")


def test_the_card_comes_first_and_quotes_what_the_last_run_measured(client, monkeypatch):
    """The reader is asked before the spend, and what they are told is a
    MEASUREMENT. The call count is a fact about the code; the seconds and the
    price are read off the last run and simply left out when there has never
    been one — "about a minute, a few cents" would be a guess printed as a
    fact, and nothing on this screen is."""
    first = _propose_analysis(client, monkeypatch)
    assert first["tool"] == "run_analysis" and first["outcome"] == "pending"
    assert first["title"] == "Run the analyzer over everything on record"
    assert first["arguments"] == {}, "an argument here would be steering it"
    assert f"{chain.MIN_STEPS} model calls" in first["consequence"]
    assert "no measured time or cost to quote" in first["consequence"]

    _run_the_chain(monkeypatch)
    second = _propose_analysis(client, monkeypatch)
    assert "The last run took" in second["consequence"]
    assert "cost $0.012" in second["consequence"], "three steps at 0.004"


def test_confirming_streams_a_step_per_finished_step_then_the_answer(client, monkeypatch):
    """The sentence the old page refused to fake, and the reason the work moved
    onto the stream. Every write but this one happens before the first byte; a
    minute of that rule is a minute of a spinner that cannot say which minute
    it is on."""
    card = _propose_analysis(client, monkeypatch)

    calls = {"n": 0}

    def chain_call(system_prompt, user_content, model=None):
        calls["n"] += 1
        text = "The verdict, at length." if system_prompt == chain.SYNTHESIS_SYSTEM_PROMPT else "x"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += "\n\nVERDICT: FITS"
        return {"analysis": text, "model": "role/model", "cost": 0.004}

    monkeypatch.setattr(advisor, "call_llm", chain_call)
    seen = _fake_stream(monkeypatch, pieces=("The analyzer says:",))

    events = _events(_decide(client, card["card_id"], "confirm"))
    # Decided once its run is stored, which is after the steps.
    assert _kinds(events) == ["start", "step", "step", "step", "decided", "delta", "done"]
    steps = [e for e in events if e["kind"] == "step"]
    assert [e["step_no"] for e in steps] == [1, 2, 3]
    assert [e["label"] for e in steps] == [
        "The numbers, on their own merits",
        "Where this would fail this person",
        "What this means for you",
    ]
    assert all(e["tool"] == "run_analysis" and e["duration_ms"] is not None for e in steps)
    # and only THEN was the model asked anything
    assert len(seen) == 1


def test_what_comes_back_is_the_opening_and_the_address_not_the_document(
    client, monkeypatch
):
    """The verdict is a document. In the card it would be a document in a
    32%-wide column; in the tool result it would be a document in the history
    of every turn after it, at the same prominence as a picture rebuilt this
    second. So the result carries what is bounded — when, how deep, how much —
    plus its opening lines and the id to read the rest with."""
    card = _propose_analysis(client, monkeypatch)
    verdict = "Sell nothing this week.\n\n" + "And here is why, at length. " * 40

    def chain_call(system_prompt, user_content, model=None):
        text = verdict if system_prompt == chain.SYNTHESIS_SYSTEM_PROMPT else "x"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += "\n\nVERDICT: FITS"
        return {"analysis": text, "model": "role/model", "cost": 0.004}

    monkeypatch.setattr(advisor, "call_llm", chain_call)
    seen = _fake_stream(monkeypatch, pieces=("Read.",))
    events = _events(_decide(client, card["card_id"], "confirm"))

    settled = client.get(
        f"/api/chat/conversations/{events[0]['conversation_id']}"
    ).json()["messages"][1]["blocks"][1]
    assert settled["outcome"] == "confirmed"
    result = settled["result"]
    assert result["run_id"] == 1 and result["steps"] == 3
    assert result["revision_rounds"] == 0 and result["cost_usd"] == 0.012
    assert result["opening"].startswith("Sell nothing this week.")
    assert result["opening"].endswith("[…]") and len(result["opening"]) < len(verdict)
    assert "read_analysis with run_id=1" in result["read_in_full"]

    # the model was handed exactly that, and never the whole thing (in the
    # tool turn before the app's note, which ends the list)
    answered = json.loads(seen[0]["messages"][-2]["content"])
    assert answered["outcome"] == "confirmed"
    assert answered["written"]["run_id"] == 1
    assert verdict not in json.dumps(seen[0]["messages"])


def test_the_whole_verdict_is_one_tool_call_away(client, monkeypatch):
    """The second deliberate exception to "reading needs no tools". A past
    analysis is unbounded and matters in one conversation out of ten, so it is
    fetched by the turn that needs it rather than carried by all of them."""
    verdict = "Sell nothing.\n\n" + "The reasoning, at length. " * 40
    run_id = _run_the_chain(monkeypatch, verdict=verdict)

    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("read_analysis", arguments=json.dumps({"run_id": run_id}))],
            [("text", "It said to sell nothing.")],
        ],
    )
    events = _events(_ask(client, "what exactly did it say?"))
    assert _kinds(events) == ["start", "tool", "delta", "done"]

    fetched = json.loads(seen[1]["messages"][-1]["content"])
    assert fetched["ok"] is True
    assert fetched["result"]["verdict"] == verdict
    assert [s["role"] for s in fetched["result"]["steps"]] == [
        "analyst",
        "confidant",
        "synthesis",
    ]


def test_asking_for_a_run_that_does_not_exist_is_answered_to_the_model(client, monkeypatch):
    """A id the model invented is a mistake it can correct on the next round
    trip, so it comes back as a tool result naming the one that does exist —
    not as a stream that dies of a LookupError."""
    run_id = _run_the_chain(monkeypatch)
    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("read_analysis", arguments=json.dumps({"run_id": run_id + 99}))],
            [("text", "Sorry — I had the wrong id.")],
        ],
    )
    _events(_ask(client, "what did run 100 say?"))

    answered = json.loads(seen[1]["messages"][-1]["content"])
    assert answered["ok"] is False
    assert f"The most recent one is {run_id}" in answered["error"]


def test_the_sub_agents_never_read_a_word_of_the_conversation(client, monkeypatch):
    """THE rule, and the one this whole step is arranged around. The chain's
    value is that the analyst has not seen the person and the confidant has not
    seen a figure — and a model asked to brief a colleague summarises, and a
    summary carries the numbers across. So the orchestrator decides whether,
    when, and what to do with the answer, and never what they read."""
    client.put(
        "/api/survey",
        json=[{"question_key": "self_narrative", "topic": "In your words",
               "question": "Tell us about yourself", "answer": "I panic when markets drop."}],
    )
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )

    _fake_stream(
        monkeypatch,
        rounds=[[("text", "My aunt died and I am frightened of losing money."),
                 _wants("run_analysis")]],
    )
    events = _events(_ask(client, "my aunt died and I am frightened of losing money"))
    card = next(e["card"] for e in events if e["kind"] == "card")

    asked: list[dict] = []

    def chain_call(system_prompt, user_content, model=None):
        asked.append({"system": system_prompt, "user": user_content})
        text = "x"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += "\n\nVERDICT: FITS"
        return {"analysis": text, "model": "m", "cost": None}

    monkeypatch.setattr(advisor, "call_llm", chain_call)
    _fake_stream(monkeypatch, pieces=("Done.",))
    _events(_decide(client, card["card_id"], "confirm"))

    assert len(asked) == 3
    for step in asked:
        assert "my aunt" not in step["user"].lower(), "the conversation reached a sub-agent"
        assert "frightened" not in step["user"].lower()
    assert "Vanguard All-World" in asked[0]["user"]  # the analyst read the records
    assert "I panic" not in asked[0]["user"]         # and not the person
    assert "I panic" in asked[1]["user"]             # the confidant read the person
    assert "1000" not in asked[1]["user"]            # and not one figure


def test_a_chain_that_breaks_leaves_the_card_answerable_and_says_why(client, monkeypatch):
    """A half-run chain is never saved, and the card must not read confirmed
    over it. The refusal arrives as an `error` event rather than a status code
    because by then a minute has gone by and the stream is already open — which
    is the one ending the client already knows how to show."""
    card = _propose_analysis(client, monkeypatch)

    calls = {"n": 0}

    def flaky(system_prompt, user_content, model=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise advisor.AdvisorError("LLM call failed: boom")
        return {"analysis": "x", "model": "m", "cost": None}

    monkeypatch.setattr(advisor, "call_llm", flaky)
    events = _events(_decide(client, card["card_id"], "confirm"))
    assert _kinds(events) == ["start", "step", "error"]
    assert "boom" in events[-1]["detail"]

    still = client.get("/api/chat/conversations/1").json()["messages"][1]["blocks"][1]
    assert still["outcome"] == "pending" and still["result"] is None
    with SessionLocal() as db:
        assert db.query(models.ChainRun).count() == 0


def test_the_analyzer_is_the_one_write_that_runs_on_the_stream(client, monkeypatch):
    """One field decides it, and the two halves of the registry cannot
    disagree about which one they are in: a tool declares `run` or `walk` and
    never both, and never neither."""
    assert tools.REGISTRY["run_analysis"].walk is not None
    assert tools.REGISTRY["run_analysis"].run is None
    assert all(
        (t.run is None) != (t.walk is None) for t in tools.REGISTRY.values()
    )
    with pytest.raises(TypeError):
        tools.Tool(name="neither", description="", arguments=_RecordThingArgs)
