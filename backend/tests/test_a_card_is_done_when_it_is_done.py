"""A card is done when it is done, and the turn after it is short.

The reader's first test round of the chat on real data (2026-10-08) asked for
two funds and got two cards. The first confirmation was followed by a reply
that redid the answer's lookups and wrote the answer again; the reply to the
second failed with OpenRouter's 400 ('Server tool "openrouter:web_search"
failed: invalid request (400)'), shown as it came, and the second card kept its
buttons though its row was written: pressing again answered "That card was
already confirmed. A decision is taken once."

What these tests pin, in that order:
- the decision is on the stream (`decided`, the card as stored) before the
  reply, and stands when the reply fails;
- the turn after a decision ends on the app's note, says what was decided and
  what still waits, and is asked at most twice;
- no request the chat sends ends on the model's own words, the shape the 400
  answered: rebuilt on test data and sent to Opus 5.5 on 2026-10-08, it was
  refused with or without the web, and cost nothing;
- a failure from the provider reaches the reader as a sentence: what it
  means, what to do, and OpenRouter's words last.

Every fund here is invented. The model is faked at `advisor.stream_llm`, or
at the transport under the real openai client where the sentence is built.
"""

from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest

from app import advisor, catalogue, chat, tools

REAL_STREAM_LLM, REAL_CALL_LLM = advisor.stream_llm, advisor.call_llm
OPUS = "anthropic/claude-opus-5.5"

# Two invented funds, the shape of the reader's request: two cards from one
# answer.
CATALOGUE = pd.DataFrame(
    [
        {
            "name": "Example Global Equity UCITS ETF Acc",
            "ticker": "XGLO", "dividends": "Accumulating", "ter": 0.12, "size": 2100,
            "replication": "Physical", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1500, "hedged": False,
        },
        {
            "name": "Example Emerging Equity UCITS ETF Acc",
            "ticker": "XEME", "dividends": "Accumulating", "ter": 0.18, "size": 900,
            "replication": "Physical", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1200, "hedged": False,
        },
    ],
    index=pd.Index(["IE0000AJ0001", "IE0000AJ0002"], name="isin"),
)
FIRST, SECOND = "IE0000AJ0001", "IE0000AJ0002"
WHY = {
    "reason": "An invented reason.",
    "based_on": "An invented answer in the questionnaire.",
    "unknowns": "Invented unknowns.",
}

# The body OpenRouter answered the reader's second reply with.
READERS_400 = {
    "error": {
        "code": 400,
        "message": 'Server tool "openrouter:web_search" failed: invalid request (400)',
    }
}


@pytest.fixture
def loaded(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _kinds(events: list[dict]) -> list[str]:
    return [e["kind"] for e in events]


def _suggest(isin: str, call_id: str) -> tuple:
    return (
        "tool_call",
        advisor.ToolCall(
            id=call_id, name="suggest_instrument", arguments=json.dumps({"isin": isin, **WHY})
        ),
    )


def _script(monkeypatch, rounds):
    """`stream_llm` answering each round from `rounds`, in order, and keeping
    what each was asked. An entry that is an exception is raised instead, the
    way a refused call raises before its first piece. A round past the script
    is an AssertionError, never a replay."""
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        seen.append(
            {"system": system_prompt, "messages": list(messages), "tools": tools, "model": model}
        )
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        answer = rounds[len(seen) - 1]
        if isinstance(answer, Exception):
            raise answer
        yield from answer

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def _two_cards(client, monkeypatch) -> tuple[int, list[dict]]:
    """The reader's question: one answer, two fund cards. Returns the
    conversation's id and the two cards."""
    _script(
        monkeypatch,
        [[("text", "Two to look at, one card each."), _suggest(FIRST, "call_1"), _suggest(SECOND, "call_2")]],
    )
    events = _events(client.post("/api/chat", json={"content": "Two funds to watch?"}))
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert len(cards) == 2
    return events[0]["conversation_id"], cards


def _decide(client, card_id: str, decision: str = "confirm"):
    return client.post(f"/api/chat/cards/{card_id}", json={"decision": decision})


def _stored_cards(client, conversation_id: int) -> list[dict]:
    messages = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"]
    return [b for m in messages for b in m["blocks"] if b["kind"] == "card"]


# --- The card follows its decision ---------------------------------------------------


def test_the_decision_is_said_before_the_reply_and_stands_when_the_reply_fails(
    loaded, monkeypatch
):
    """The reader's sequence. Both cards are decided on the stream before any
    reply, each as it is stored; the second reply fails, and the second card
    is decided all the same, which is what the panel shows from that event
    on. Before brief AJ the stream said nothing of the decision, and the panel
    learnt it only from a reply that ended well."""
    conversation_id, (first, second) = _two_cards(loaded, monkeypatch)

    _script(monkeypatch, [[("text", "Added.")]])
    events = _events(_decide(loaded, first["card_id"]))
    assert _kinds(events) == ["start", "decided", "delta", "done"]
    assert events[1]["card"]["card_id"] == first["card_id"]
    assert events[1]["card"]["outcome"] == "confirmed"
    assert events[1]["card"]["result"]["isin"] == FIRST

    _script(monkeypatch, [advisor.AdvisorError("OpenRouter refused the call.")])
    events = _events(_decide(loaded, second["card_id"]))
    assert _kinds(events) == ["start", "decided", "error"]
    assert events[1]["card"]["card_id"] == second["card_id"]
    assert events[1]["card"]["outcome"] == "confirmed"

    stored = _stored_cards(loaded, conversation_id)
    assert [c["outcome"] for c in stored] == ["confirmed", "confirmed"]
    assert events[1]["card"] == stored[1], "the event is the card as stored"
    assert sorted(i["isin"] for i in loaded.get("/api/watchlist").json()) == [FIRST, SECOND]
    # The server's answer to a second press, unchanged: the decision is taken
    # once. The panel no longer offers the button that asked it.
    again = _decide(loaded, second["card_id"])
    assert again.status_code == 409
    assert "already confirmed" in again.json()["detail"]


def test_a_failure_after_the_decision_says_the_decision_is_saved(loaded, monkeypatch):
    _, (first, _) = _two_cards(loaded, monkeypatch)
    _script(monkeypatch, [advisor.AdvisorError("OpenRouter refused the call.")])

    events = _events(_decide(loaded, first["card_id"]))

    assert events[-1]["detail"] == (
        "OpenRouter refused the call. Your answer to the card is saved: only this "
        "reply to it is missing."
    )


def test_a_failure_on_a_question_says_nothing_about_a_card(loaded, monkeypatch):
    """A guard: the sentence about a decision belongs to a turn that answers
    one."""
    _script(monkeypatch, [advisor.AdvisorError("OpenRouter refused the call.")])
    events = _events(loaded.post("/api/chat", json={"content": "How am I doing?"}))
    assert events[-1]["detail"] == "OpenRouter refused the call."


# --- The turn after a decision ---------------------------------------------------------


def test_the_turn_after_a_decision_ends_on_the_apps_note(loaded, monkeypatch):
    """What was decided, what still waits, and what is asked: briefly, no
    second answer, no lookup run again. Without it the turn ended on the
    cards' tool results, which a model reads as its own tools answering in
    the middle of the answer it was writing, so it went on writing it."""
    _, (first, second) = _two_cards(loaded, monkeypatch)
    seen = _script(monkeypatch, [[("text", "Added.")]])

    _events(_decide(loaded, first["card_id"]))

    note = seen[0]["messages"][-1]
    assert note["role"] == "user"
    said = note["content"]
    assert said.startswith("THE READER HAS JUST ANSWERED A CARD")
    assert f'They accepted "{first["title"]}": it is on their watchlist now.' in said
    assert f'Still waiting for their answer, from the same reply: "{second["title"]}".' in said
    assert "do not run again the lookups" in said
    assert "running a tool again is for a new question" in said
    # The exchange the note follows is still the protocol's: the cards' calls,
    # then one tool turn each, the first confirmed and the second waiting.
    tool_turns = [m for m in seen[0]["messages"] if m["role"] == "tool"]
    assert [json.loads(m["content"])["outcome"] for m in tool_turns] == ["confirmed", "pending"]


def test_after_the_second_decision_the_request_ends_on_the_note_not_on_the_models_words(
    loaded, monkeypatch
):
    """The shape OpenRouter refused. After the first card's reply, deciding
    the second used to send a conversation ending on that reply: the model's
    own words, last."""
    _, (first, second) = _two_cards(loaded, monkeypatch)
    _script(monkeypatch, [[("text", "The first one is on your watchlist.")]])
    _events(_decide(loaded, first["card_id"]))

    seen = _script(monkeypatch, [[("text", "And the second.")]])
    _events(_decide(loaded, second["card_id"]))

    sent = seen[0]["messages"]
    assert sent[-2] == {"role": "assistant", "content": "The first one is on your watchlist."}
    assert sent[-1]["role"] == "user"
    assert f'They accepted "{second["title"]}"' in sent[-1]["content"]
    assert "Still waiting" not in sent[-1]["content"], "nothing else waits"


def test_a_rejection_is_said_and_not_proposed_again(loaded, monkeypatch):
    _, (first, _) = _two_cards(loaded, monkeypatch)
    seen = _script(monkeypatch, [[("text", "Fine.")]])

    _events(_decide(loaded, first["card_id"], "reject"))

    said = seen[0]["messages"][-1]["content"]
    assert f'They rejected "{first["title"]}": nothing was written.' in said
    assert "Do not propose it again unless they ask for it." in said


def test_the_turn_after_a_decision_is_asked_twice_at_most(loaded, monkeypatch):
    """The reader's bound (2026-10-08): one round with the tools, then one
    with none. A model that reads the note answers on the first; one that
    looks something up anyway gets its result and one round to write in."""
    _, (first, _) = _two_cards(loaded, monkeypatch)
    lookup = (
        "tool_call",
        advisor.ToolCall(id="call_9", name="search_catalogue", arguments='{"query": "example"}'),
    )
    seen = _script(monkeypatch, [[lookup], [lookup, ("text", "Added.")]])

    events = _events(_decide(loaded, first["card_id"]))

    assert _kinds(events)[-1] == "done"
    assert len(seen) == 2 == chat.DECISION_ROUNDS
    assert seen[0]["tools"] is not None, "the first round keeps the tools, and the cache with them"
    assert seen[1]["tools"] is None, "the second can only write"


def test_the_turn_after_a_decision_carries_no_deadline(loaded, monkeypatch):
    """A guard. The last-round notice says "propose it NOW"; the turn after a
    decision is told the opposite, and is never told both."""
    _, (first, _) = _two_cards(loaded, monkeypatch)
    lookup = (
        "tool_call",
        advisor.ToolCall(id="call_9", name="search_catalogue", arguments='{"query": "example"}'),
    )
    seen = _script(monkeypatch, [[lookup], [("text", "Added.")]])

    _events(_decide(loaded, first["card_id"]))

    for asked in seen:
        assert chat.LAST_TOOL_ROUND_NOTICE not in asked["system"]
        assert all(chat.LAST_TOOL_ROUND_NOTICE not in str(m.get("content")) for m in asked["messages"])


# --- No request ends on the model's own words --------------------------------------------


def _last_roles(seen: list[dict]) -> list[str]:
    return [asked["messages"][-1]["role"] for asked in seen]


def test_no_request_the_chat_sends_ends_on_the_models_own_words(loaded, monkeypatch):
    """Every shape of turn the reader's round went through, and one more: a
    question; a decision on a card; a decision after another card's reply; a
    question after that; and a decision on a card left waiting while a later
    question was answered. Each request ends on the reader's question, a tool
    result, or the app's note, never on the model."""
    conversation_id, (first, second) = _two_cards(loaded, monkeypatch)

    decided = _script(monkeypatch, [[("text", "Added.")]])
    _events(_decide(loaded, first["card_id"]))

    asked_later = _script(monkeypatch, [[("text", "Something else, answered.")]])
    _events(
        loaded.post(
            "/api/chat",
            json={"content": "Something else?", "conversation_id": conversation_id},
        )
    )

    decided_later = _script(monkeypatch, [[("text", "Added too.")]])
    _events(_decide(loaded, second["card_id"]))

    asked = decided + asked_later + decided_later
    assert len(asked) == 3
    assert "assistant" not in _last_roles(asked)


# --- A provider failure, said in words ---------------------------------------------------


@pytest.fixture
def openrouter(monkeypatch):
    """The real client over a transport answering with `openrouter.answer`, a
    (status, body) pair, or raising `openrouter.raises`; the public list of
    models holding the model asked, so a 400 is not taken for a model gone."""

    class Fake:
        answer: tuple = (400, READERS_400)
        raises: Exception | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        if Fake.raises is not None:
            raise Fake.raises
        status, body = Fake.answer
        return httpx.Response(status, json=body)

    def client():
        return advisor.sdk().OpenAI(
            base_url=advisor.OPENROUTER_BASE_URL,
            api_key="invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "call_llm", REAL_CALL_LLM)
    monkeypatch.setattr(advisor, "_client", client)
    monkeypatch.setattr(advisor, "_fetch_model_list", lambda: {OPUS})
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", OPUS)
    return Fake


def _reads_as_words(sentence: str) -> None:
    # chr(0x2014) is the em dash, kept out of the source so a count of dashes
    # in this repository does not find the test that forbids them.
    for raw in ("{", "}", "Error code", "AdvisorError", "LLM call failed", chr(0x2014)):
        assert raw not in sentence, f"{raw!r} in: {sentence}"


def _streamed_error(model: str = OPUS) -> None:
    """Ask the real `stream_llm` once; the caller expects it to raise."""
    pieces = list(REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}], model=model))
    raise AssertionError(f"no failure, the stream gave {pieces}")


def test_the_readers_400_reads_as_a_sentence_with_what_to_do(loaded, monkeypatch, openrouter):
    """The reader's own failure, on the turn after a decision: what it means,
    what they can do, OpenRouter's words last, and that the decision stands."""
    _, (first, _) = _two_cards(loaded, monkeypatch)
    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)

    events = _events(_decide(loaded, first["card_id"]))

    assert _kinds(events) == ["start", "decided", "error"]
    assert events[-1]["detail"] == (
        f"OpenRouter refused the call to {OPUS} with 400: the request the app built "
        "is not one it accepts, which is the app's fault and not your question's. "
        "Ask again; if it happens again, pick another model in the menu under the "
        'question. OpenRouter said: Server tool "openrouter:web_search" failed: '
        "invalid request (400). Your answer to the card is saved: only this reply to "
        "it is missing."
    )
    _reads_as_words(events[-1]["detail"])


@pytest.mark.parametrize(
    ("status", "means", "remedy"),
    [
        (
            401,
            "it does not accept the API key in backend/.env (OPENROUTER_API_KEY)",
            "Check the key on openrouter.ai, put the right one in backend/.env, and start the app again.",
        ),
        (402, "the account behind the API key has no credit left", "Add credit on openrouter.ai, then ask again."),
        (
            403,
            "a moderation flag, a guardrail or a permission on the key stopped it",
            "Rephrase it, or pick another model in the menu under the question.",
        ),
        (408, "the model took too long to answer", "Ask again in a moment."),
        (
            429,
            "too many requests are reaching it or the model's provider right now",
            "Wait a minute, then ask again.",
        ),
        (
            502,
            "the model is down, or sent back something OpenRouter could not read",
            "Ask again in a few minutes, or pick another model in the menu under the question.",
        ),
        (
            503,
            "no provider can serve this model right now",
            "Ask again in a few minutes, or pick another model in the menu under the question.",
        ),
    ],
)
def test_each_status_openrouter_documents_says_what_it_means_and_what_to_do(
    openrouter, status, means, remedy
):
    openrouter.answer = (status, {"error": {"code": status, "message": "Invented words."}})

    with pytest.raises(advisor.AdvisorError) as failed:
        _streamed_error()

    assert str(failed.value) == (
        f"OpenRouter refused the call to {OPUS} with {status}: {means}. {remedy} "
        "OpenRouter said: Invented words."
    )
    _reads_as_words(str(failed.value))


def test_a_status_it_does_not_document_still_says_what_to_do(openrouter):
    openrouter.answer = (418, {"error": {"code": 418, "message": "Invented words."}})

    with pytest.raises(advisor.AdvisorError) as failed:
        _streamed_error()

    assert str(failed.value) == (
        f"OpenRouter refused the call to {OPUS} with 418. Ask again; if it happens "
        "again, pick another model in the menu under the question. OpenRouter said: "
        "Invented words."
    )


def test_the_analysis_is_told_where_its_model_is_set(openrouter):
    """The analysis has no menu: its models are named in backend/.env."""
    openrouter.answer = (503, {"error": {"code": 503, "message": "Invented words."}})

    with pytest.raises(advisor.AdvisorError) as failed:
        REAL_CALL_LLM("system", "user", model=OPUS)

    assert "Ask again in a few minutes, or set another model in backend/.env." in str(failed.value)


def test_no_connection_says_to_check_the_computer_is_online(openrouter):
    openrouter.raises = httpx.ConnectError("no route to host")

    with pytest.raises(advisor.AdvisorError) as failed:
        _streamed_error()

    said = str(failed.value)
    assert said.startswith("OpenRouter could not be reached (")
    assert said.endswith("Check that this computer is online, then ask again.")
    _reads_as_words(said)


def test_a_timeout_says_to_ask_again(openrouter):
    openrouter.raises = httpx.ReadTimeout("timed out")

    with pytest.raises(advisor.AdvisorError) as failed:
        _streamed_error()

    said = str(failed.value)
    assert said.startswith("OpenRouter did not answer in time (")
    assert said.endswith("Ask again in a moment.")


def test_a_stream_that_breaks_midway_says_so(openrouter, monkeypatch):
    """A connection that drops after the answer started: the words already
    shown stay, and the sentence says what happened and what to do."""

    class Breaking(httpx.SyncByteStream):
        def __iter__(self):
            chunk = {
                "id": "gen-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": OPUS,
                "choices": [{"index": 0, "delta": {"content": "Hel"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            raise httpx.ReadError("connection reset")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Breaking(), headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(
        advisor,
        "_client",
        lambda: advisor.sdk().OpenAI(
            base_url=advisor.OPENROUTER_BASE_URL,
            api_key="invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        ),
    )
    pieces: list = []
    with pytest.raises(advisor.AdvisorError) as failed:
        for piece in REAL_STREAM_LLM("system", [{"role": "user", "content": "hi"}], model=OPUS):
            pieces.append(piece)

    assert pieces == [("text", "Hel")]
    said = str(failed.value)
    assert said.startswith("The connection to OpenRouter broke while the answer was being written (")
    assert said.endswith("Ask again.")
    _reads_as_words(said)
