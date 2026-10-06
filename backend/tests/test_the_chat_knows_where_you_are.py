"""The chat knows where you are — and nothing else learns it.

The reader moves around the app, and the chat moves with them. A question
travels with the page it was asked from: named, never numbered, kept on the
question so a later
turn still knows where an earlier one was asked, and carrying what that screen
shows only when the picture does not already hold it.

Half of this file is about what the page must NOT reach. The analyzer's
sub-agents must never see the person, and a screen is the person's; an outside
assistant through MCP is not looking at the app at all; and a card writes what
it names and never "whatever is on screen". Each of those is pinned here as
code — a signature, an import, a prompt captured at the boundary — because an
intention is not something a test can fail on.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app import advisor, chain, chat, schemas, screen, tools
from app.database import SessionLocal
from tests.test_chat import _decide, _events, _fake_stream, _kinds, _wants

APP = pathlib.Path(chat.__file__).parent


def _ask(client, content: str, page: dict | None = None, conversation_id: int | None = None):
    body: dict = {"content": content, "conversation_id": conversation_id}
    if page is not None:
        body["page"] = page
    return client.post("/api/chat", json=body)


def _institution(client, name: str) -> int:
    return client.post("/api/institutions", json={"name": name}).json()["id"]


def _situation(client, iid: int, date: str, *holdings: dict) -> int:
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": date}).json()["id"]
    for h in holdings:
        r = client.post(f"/api/snapshots/{sid}/holdings", json={"currency": "EUR", **h})
        assert r.status_code == 201, r.text
    return sid


GOLD = {"asset_name": "Gold bar", "asset_class": "commodity", "value": 400}
VWCE = {"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
        "symbol": "VWCE.MI", "quantity": 10, "unit_price": 150}


def _question(seen_round: dict, index: int = -1) -> str:
    """The content of a user turn as the model received it, counted from the
    end of the conversation — the picture and its acknowledgement excluded."""
    users = [m for m in seen_round["messages"][2:] if m["role"] == "user"]
    return users[index]["content"]


def _stored_question(client, cid: int, index: int = -1) -> dict:
    msgs = client.get(f"/api/chat/conversations/{cid}").json()["messages"]
    return [m for m in msgs if m["role"] == "user"][index]


# --- What the model reads ------------------------------------------------------


def test_a_question_sent_without_a_page_reaches_the_model_as_its_words_alone(
    client, monkeypatch
):
    """Everything asked before this existed, and anything that sends no page,
    reads exactly as it did: no tag, no block, nothing claimed about a screen."""
    seen = _fake_stream(monkeypatch)
    cid = _events(_ask(client, "hi"))[0]["conversation_id"]

    assert _question(seen[0]) == "hi"
    assert _stored_question(client, cid)["blocks"] == [{"kind": "text", "text": "hi"}]


def test_an_account_page_names_the_account_and_points_at_its_lines(client, monkeypatch):
    """The reader on Broker B's page asks about "this number". The picture holds
    two cash registers; the note says which one is in front of them, by the
    name the picture itself prints — never by the id the frontend sent."""
    _institution(client, "Broker A")
    rid = _institution(client, "Broker B")
    seen = _fake_stream(monkeypatch)
    cid = _events(
        _ask(client, "perché questo numero è così basso?",
             page={"kind": "account", "institution_id": rid})
    )[0]["conversation_id"]

    asked = _question(seen[0])
    assert asked.startswith("<screen>\nRecords → Wealth → Broker B\n")
    assert "the 'Broker B' line of the picture's cash register" in asked
    assert "marked '@ Broker B'" in asked
    assert asked.endswith("</screen>\n\nperché questo numero è così basso?")
    assert "institution_id" not in asked

    stored = _stored_question(client, cid)
    assert stored["blocks"] == [
        {"kind": "page", "label": "Records → Wealth → Broker B"},
        {"kind": "text", "text": "perché questo numero è così basso?"},
    ]


def test_each_question_remembers_where_it_was_asked(client, monkeypatch):
    """Turn one on Broker B, turn two on Broker A. If the page were only ever
    "now", the history would read as two questions about Broker A. Each question
    keeps its own; only the one being answered carries the full note."""
    fid = _institution(client, "Broker A")
    rid = _institution(client, "Broker B")
    _fake_stream(monkeypatch, pieces=("It is your Broker B cash.",))
    cid = _events(
        _ask(client, "cos'è questo?", page={"kind": "account", "institution_id": rid})
    )[0]["conversation_id"]

    seen = _fake_stream(monkeypatch)
    _events(_ask(client, "e questo?", page={"kind": "account", "institution_id": fid},
                 conversation_id=cid))

    assert _question(seen[0], 0) == "<screen>Records → Wealth → Broker B</screen>\n\ncos'è questo?"
    now = _question(seen[0], 1)
    assert now.startswith("<screen>\nRecords → Wealth → Broker A\n")
    assert now.endswith("e questo?")


def test_a_situation_the_picture_does_not_hold_travels_with_its_question_and_no_other(
    client, monkeypatch
):
    """The situation of 10 January is on screen and nowhere in the picture —
    the picture reads Broker A from its situation in force today. A pointer to it
    would point at nothing the model can read, so its rows travel, as typed.
    On the next question, from somewhere else, only the label goes back."""
    fid = _institution(client, "Broker A")
    old = _situation(client, fid, "2026-01-10", GOLD, VWCE)
    _situation(client, fid, "2026-02-10", VWCE)

    seen = _fake_stream(monkeypatch, pieces=("There was a gold bar.",))
    cid = _events(
        _ask(client, "cosa c'era qui?",
             page={"kind": "situation", "institution_id": fid, "snapshot_id": old})
    )[0]["conversation_id"]

    assert "Gold bar" not in seen[0]["messages"][0]["content"], "the picture held it after all"
    asked = _question(seen[0])
    assert asked.startswith("<screen>\nRecords → Wealth → Broker A → situation of 2026-01-10\n")
    assert "it is NOT the one Broker A is read from today, which is the situation of 2026-02-10" in asked
    assert "- Gold bar [commodity]: 400.00 EUR; cost unknown" in asked
    assert "- Vanguard All-World [fund_etf] VWCE.MI: qty 10 x 150.00 = 1500.00 EUR; cost unknown" in asked

    seen = _fake_stream(monkeypatch)
    _events(_ask(client, "e adesso?", page={"kind": "dashboard"}, conversation_id=cid))
    assert _question(seen[0], 0) == (
        "<screen>Records → Wealth → Broker A → situation of 2026-01-10</screen>\n\ncosa c'era qui?"
    )
    for m in seen[0]["messages"]:
        if m["role"] == "user":
            assert "- Gold bar" not in m["content"], "a past screen's rows were sent again"


def test_the_dashboard_says_its_history_is_not_in_front_of_the_model(client, monkeypatch):
    """The chart is a point per event date and the picture carries none of
    them. Saying so is what turns "why did it drop in July?" into rule 2 rather
    than a figure borrowed from today's totals."""
    seen = _fake_stream(monkeypatch)
    _events(_ask(client, "perché è sceso a luglio?", page={"kind": "dashboard"}))
    asked = _question(seen[0])
    assert asked.startswith("<screen>\nDashboard\n")
    assert "The chart's points are NOT in the picture" in asked


def test_the_portfolio_page_says_nothing_on_it_is_selected(client, monkeypatch):
    """ "Should I sell?" on Portfolio is about the portfolio. A page that is
    about everything has to say it is, or its first row becomes the subject."""
    seen = _fake_stream(monkeypatch)
    _events(_ask(client, "dovrei vendere?", page={"kind": "portfolio"}))
    assert "nothing on it is selected: 'this' is not the first row" in _question(seen[0])


def test_an_analysis_page_points_at_the_tool_that_reads_it(client, monkeypatch):
    run_id = _one_run(monkeypatch)
    later = _one_run(monkeypatch)

    s = _resolve({"kind": "analysis", "run_id": run_id})
    assert s.label == f"Analysis run {run_id}"
    assert "It is not the latest, and nothing of it is in the picture." in s.note
    assert f"Call `read_analysis` with run_id={run_id}" in s.note

    s = _resolve({"kind": "analysis", "run_id": later})
    assert "It is the latest, so its opening lines are in the picture." in s.note


@pytest.mark.parametrize(
    "page, label",
    [
        ({"kind": "dashboard"}, "Dashboard"),
        ({"kind": "portfolio"}, "Portfolio"),
        ({"kind": "profile"}, "Profile"),
        ({"kind": "records", "section": "wealth"}, "Records → Wealth"),
        ({"kind": "records", "section": "real"}, "Records → Real assets"),
        ({"kind": "records", "section": "debts"}, "Records → Debts"),
        ({"kind": "records", "section": "cash"}, "Records → Cash flow"),
        ({"kind": "analyses"}, "Past analyses"),
    ],
)
def test_every_page_has_a_label_and_a_note_that_starts_with_it(client, page, label):
    s = _resolve(page)
    assert s.label == label
    assert s.note.startswith(label + "\n") and len(s.note) > len(label) + 1


# --- A page that is gone -------------------------------------------------------


def test_a_page_that_is_gone_answers_for_the_level_above_it(client, monkeypatch):
    """Deleted in another window while the reader was looking at it. One
    level up, the page it was opened from — and the question still goes."""
    fid = _institution(client, "Broker A")
    rid = _institution(client, "Broker B")
    sid = _situation(client, fid, "2026-01-10", GOLD)
    gone = _situation(client, fid, "2026-02-10", GOLD)
    client.delete(f"/api/snapshots/{gone}")
    client.delete(f"/api/institutions/{rid}")

    situation = {"kind": "situation", "institution_id": fid, "snapshot_id": gone}
    assert _resolve(situation).label == "Records → Wealth → Broker A"
    # A situation that belongs to another account is not this account's page.
    wrong = {"kind": "situation", "institution_id": rid, "snapshot_id": sid}
    assert _resolve(wrong).label == "Records → Wealth"
    assert _resolve({"kind": "account", "institution_id": rid}).label == "Records → Wealth"
    assert _resolve({"kind": "analysis", "run_id": 99}).label == "Past analyses"

    _fake_stream(monkeypatch)
    events = _events(_ask(client, "cosa c'era qui?", page=situation))
    assert _kinds(events) == ["start", "delta", "delta", "done"]


def _house_and_mortgage(client) -> tuple[int, int]:
    """A real asset valued twice and the debt that finances it, balanced twice
    — the picture carries only the newest of each."""
    aid = client.post(
        "/api/real-assets", json={"name": "Casa", "category": "real_estate", "currency": "EUR"}
    ).json()["id"]
    for date, value in (("2025-11-03", 198000), ("2026-06-01", 210000)):
        r = client.post(f"/api/real-assets/{aid}/valuations", json={"date": date, "value": value})
        assert r.status_code == 201, r.text
    lid = client.post(
        "/api/liabilities",
        json={"name": "Mutuo", "kind": "mortgage", "currency": "EUR", "interest_rate": 3.1,
              "real_asset_id": aid},
    ).json()["id"]
    for date, balance in (("2025-12-31", 150500), ("2026-06-30", 146200)):
        r = client.post(f"/api/liabilities/{lid}/balances", json={"date": date, "balance": balance})
        assert r.status_code == 201, r.text
    return aid, lid


def test_a_real_asset_page_carries_every_valuation_and_names_what_finances_it(
    client, monkeypatch
):
    """The picture has the house's newest valuation. The page has its history,
    and "how much has it gained?" is a question about the history — so the
    valuations travel, as typed, and the mortgage is pointed at by name."""
    aid, _ = _house_and_mortgage(client)
    seen = _fake_stream(monkeypatch)
    _events(_ask(client, "quanto è salita?", page={"kind": "real_asset", "real_asset_id": aid}))

    assert "2025-11-03" not in seen[0]["messages"][0]["content"], "the picture held it after all"
    asked = _question(seen[0])
    assert asked.startswith("<screen>\nRecords → Real assets → Casa\n")
    assert "- 2025-11-03: 198000.00 EUR\n- 2026-06-01: 210000.00 EUR" in asked
    assert "each a line of the picture's Debts: Mutuo" in asked


def test_a_debt_page_carries_every_balance(client, monkeypatch):
    _, lid = _house_and_mortgage(client)
    seen = _fake_stream(monkeypatch)
    _events(_ask(client, "quanto scende al mese?", page={"kind": "debt", "liability_id": lid}))

    assert "2025-12-31" not in seen[0]["messages"][0]["content"], "the picture held it after all"
    asked = _question(seen[0])
    assert asked.startswith("<screen>\nRecords → Debts → Mutuo\n")
    assert "- 2025-12-31: 150500.00 EUR\n- 2026-06-30: 146200.00 EUR" in asked


def test_a_real_asset_or_a_debt_that_is_gone_answers_for_its_list(client, monkeypatch):
    aid, lid = _house_and_mortgage(client)
    assert client.delete(f"/api/liabilities/{lid}").status_code == 204
    assert client.delete(f"/api/real-assets/{aid}").status_code == 204

    assert _resolve({"kind": "real_asset", "real_asset_id": aid}).label == "Records → Real assets"
    assert _resolve({"kind": "debt", "liability_id": lid}).label == "Records → Debts"
    _fake_stream(monkeypatch)
    start = _events(_ask(client, "e questo?", page={"kind": "debt", "liability_id": lid}))[0]
    assert start["page_label"] == "Records → Debts"


def test_the_start_frame_carries_the_label_the_question_was_stored_with(client, monkeypatch):
    """The panel prints where a question was asked under it while the answer
    is still streaming, and takes that from the server: resolved, so a page
    deleted in the meantime arrives already one level up, exactly as stored.
    A question sent without a page carries no label."""
    fid = _institution(client, "Broker A")
    gone = _situation(client, fid, "2026-02-10", GOLD)
    client.delete(f"/api/snapshots/{gone}")

    _fake_stream(monkeypatch)
    start = _events(_ask(client, "e qui?", page={
        "kind": "situation", "institution_id": fid, "snapshot_id": gone
    }))[0]
    assert start["kind"] == "start"
    assert start["page_label"] == "Records → Wealth → Broker A"
    assert _stored_question(client, start["conversation_id"])["blocks"][0] == {
        "kind": "page", "label": start["page_label"]
    }

    _fake_stream(monkeypatch)
    assert _events(_ask(client, "hi"))[0]["page_label"] is None


def test_a_page_of_an_unknown_kind_is_refused_before_anything_is_stored(client, monkeypatch):
    """The one refusal, and it is about the request, not the screen: a kind
    the backend does not know is a frontend that drifted, and a 422 says so
    instead of a note that quietly describes the Dashboard."""
    _fake_stream(monkeypatch)
    r = _ask(client, "hi", page={"kind": "hallway"})
    assert r.status_code == 422
    assert client.get("/api/chat/conversations").json() == []


# --- What the model is told the page means --------------------------------------


def test_the_prompt_makes_the_page_a_hint_about_the_referent_and_never_a_constraint(client):
    prompt = chat.SYSTEM_PROMPT
    assert "<screen> note. The APP writes it, not the reader" in prompt
    assert "It never narrows the question" in prompt
    assert "their words win" in prompt
    assert "Each note belongs to its own message" in prompt
    assert "that is rule 2" in prompt


# --- What the page must never reach --------------------------------------------


def test_the_screen_never_reaches_the_analyzer(client, monkeypatch):
    """THE rule, pinned where it would break. A conversation asked from an old
    situation — its rows in the chat's messages — and from Profile, then the
    analyzer confirmed. Every prompt the chain sends is captured at the
    boundary, and not one sentence the screen wrote is in any of them."""
    client.put(
        "/api/survey",
        json=[{"question_key": "self_narrative", "topic": "In your words",
               "question": "Tell us about yourself", "answer": "I panic when markets drop."}],
    )
    fid = _institution(client, "Broker A")
    old = _situation(client, fid, "2026-01-10", GOLD, VWCE)
    _situation(client, fid, "2026-02-10", VWCE)

    _fake_stream(monkeypatch, pieces=("There was a gold bar.",))
    cid = _events(
        _ask(client, "cosa c'era qui?",
             page={"kind": "situation", "institution_id": fid, "snapshot_id": old})
    )[0]["conversation_id"]
    _fake_stream(monkeypatch, rounds=[[("text", "Worth a look:"), _wants("run_analysis")]])
    events = _events(
        _ask(client, "analizzami", page={"kind": "profile"}, conversation_id=cid)
    )
    card = next(e["card"] for e in events if e["kind"] == "card")

    asked: list[str] = []

    def chain_call(system_prompt, user_content, model=None):
        asked.append(system_prompt + "\n" + user_content)
        text = "x"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += "\n\nVERDICT: FITS"
        return {"analysis": text, "model": "m", "cost": None}

    monkeypatch.setattr(advisor, "call_llm", chain_call)
    _fake_stream(monkeypatch, pieces=("Done.",))
    _events(_decide(client, card["card_id"], "confirm"))

    assert len(asked) == 3
    written_by_the_screen = (
        "<screen>", "Records → Wealth", "photograph of what was held there that day",
        "The Profile page", "situation of 2026-01-10", "- Gold bar",
    )
    for prompt in asked:
        for sentence in written_by_the_screen:
            assert sentence not in prompt, f"{sentence!r} reached a sub-agent"


def test_nothing_the_analyzer_or_an_outside_assistant_reads_has_a_way_in_for_a_page():
    """Enforced by shape rather than by care. The builders the chain and the
    MCP server read take a session and nothing else, and so does the chain;
    the tools answer a call and nothing else. Adding a `page` parameter to any
    of them is the change that would let a screen through, and it fails here."""
    for fn in (
        advisor.build_context,
        advisor.build_portfolio_context,
        advisor.build_person_context,
        chain.run_chain,
    ):
        assert list(inspect.signature(fn).parameters) == ["db"], fn.__qualname__
    assert list(inspect.signature(tools.answer).parameters) == ["db", "call"]
    assert list(inspect.signature(tools.settle).parameters) == [
        "db", "tool_name", "arguments", "fingerprint"
    ]


def test_only_the_chat_imports_the_screen():
    """The other half of the same guarantee. A module that cannot import this
    one cannot render a page into what it builds — the chain, the MCP server,
    the tools and the advisor included."""
    importers = []
    for path in sorted(APP.glob("**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(n in ("app.screen", "app.screen.Screen") for n in names):
                importers.append(path.relative_to(APP).as_posix())
    assert sorted(set(importers)) == ["chat.py"]


def test_the_screen_never_fills_in_what_a_card_writes(client, monkeypatch):
    """On Broker B's page, a buy that names no institution. The screen would
    make "Broker B" an easy guess, and it is exactly the guess that must not be
    made for the reader: the tool refuses and says what is missing, and no
    card appears. When the model does name Broker B, the card prints it and
    waits — the reader still writes."""
    rid = _institution(client, "Broker B")
    buy = (
        '{"kind": "buy", "asset_name": "Vanguard All-World", "symbol": "VWCE.MI", '
        '"quantity": 1, "unit_price": 150, "currency": "EUR", "price_currency": "EUR"}'
    )
    seen = _fake_stream(
        monkeypatch,
        rounds=[
            [_wants("record_transaction", arguments=buy)],
            [("text", "Which account paid for it?")],
        ],
    )
    events = _events(_ask(client, "ho comprato questo", page={"kind": "account", "institution_id": rid}))

    assert "card" not in _kinds(events)
    refusal = seen[1]["messages"][-1]["content"]
    assert '"ok": false' in refusal
    assert "A buy has to say where the position is held" in refusal

    named = buy[:-1] + ', "institution": "Broker B"}'
    _fake_stream(monkeypatch, rounds=[[("text", "Recording it:"), _wants("record_transaction", arguments=named)]])
    events = _events(_ask(client, "ho comprato questo", page={"kind": "account", "institution_id": rid}))
    card = next(e["card"] for e in events if e["kind"] == "card")
    assert "Broker B" in card["title"] and card["outcome"] == "pending"
    assert client.get("/api/transactions").json() == [], "the screen wrote before the reader did"


# --- helpers -------------------------------------------------------------------


def _resolve(page: dict) -> screen.Screen:
    parsed = schemas.ChatRequest(content="x", page=page).page
    with SessionLocal() as db:
        return screen.resolve(db, parsed)


def _one_run(monkeypatch) -> int:
    def fake(system_prompt, user_content, model=None):
        text = "x"
        if system_prompt == chain.CONFIDANT_SYSTEM_PROMPT:
            text += "\n\nVERDICT: FITS"
        return {"analysis": text, "model": "m", "cost": None}

    monkeypatch.setattr(advisor, "call_llm", fake)
    with SessionLocal() as db:
        walk = chain.run_chain(db)
        while True:
            try:
                next(walk)
            except StopIteration as done:
                return done.value.id
