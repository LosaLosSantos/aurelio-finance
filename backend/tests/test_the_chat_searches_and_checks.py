"""The chat proposes only what a source verifies: cards for shares, and up to
three in one answer.

Brief AG (2026-10-06). The reader asked for a chat that goes and looks ("Io
voglio che il mio bot sia in grado di fare ricerca!!"), and decided: the whole
web, with its sources in view, and up to three cards when they ask for
several, never one unasked. The web finds and a card verifies: a fund is named
by an ISIN the catalogue holds, a share by the exact symbol Yahoo lists, and
nothing else gets a card. These tests pin the cards. The search itself became
a tool of the app with brief AM (2026-10-09), and its tests are in
tests/test_the_web_is_a_tool_of_the_app.py.

Where a turn is involved they go through the real `stream_llm` and the real
openai client over a faked transport: the rules are about the bytes of the
request and of the stream.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import httpx
import pandas as pd
import pytest
from alembic import command
from alembic.config import Config

from app import advisor, catalogue, chat, crud, database, prices, tools
from app.database import SessionLocal

REAL_STREAM_LLM = advisor.stream_llm

OPUS = "anthropic/claude-opus-5.5"
PAGE = {"kind": "portfolio"}


# --- OpenRouter, scripted ---------------------------------------------------------


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _usage() -> dict:
    """The chunk a streamed call ends with."""
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [],
        "usage": {
            "prompt_tokens": 11865,
            "completion_tokens": 40,
            "total_tokens": 11905,
            "prompt_tokens_details": {"cached_tokens": 11861, "cache_write_tokens": 0},
            "cost": 0.0087282,
        },
    }


def _sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _says(text: str) -> bytes:
    return _sse(_chunk({"content": text}), _chunk({}, "stop"), _usage())


def _call_at(index: int, name: str, arguments: dict) -> dict:
    """One call's chunk, at its own index, for a round that asks for several."""
    return _chunk(
        {
            "tool_calls": [
                {
                    "index": index,
                    "id": f"toolu_{name}_{index}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
        }
    )


@pytest.fixture
def openrouter(monkeypatch):
    """The real client over a transport that answers each call with the next
    entry of `openrouter.script` and keeps every request body in `asked`."""

    class Fake:
        script: list = []
        asked: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        Fake.asked.append(json.loads(request.content))
        assert Fake.script, "a call past the script"
        return httpx.Response(
            200, content=Fake.script.pop(0), headers={"content-type": "text/event-stream"}
        )

    def client():
        return advisor.sdk().OpenAI(
            base_url=advisor.OPENROUTER_BASE_URL,
            api_key="invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "_client", client)
    Fake.script, Fake.asked = [], []
    return Fake


def _events(text: str) -> list[dict]:
    """Every frame of an SSE answer, as the events it carried."""
    out = []
    for frame in text.split("\n\n"):
        data = [line[len("data: "):] for line in frame.split("\n") if line.startswith("data: ")]
        if data:
            out.append(json.loads(data[0]))
    return out


def _ask(client, content: str, model: str, conversation_id: int | None = None) -> list[dict]:
    response = client.post(
        "/api/chat",
        json={"content": content, "conversation_id": conversation_id, "model": model, "page": PAGE},
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["kind"] == "done", events[-1]
    return events


# --- Cards for shares, and up to three --------------------------------------------
#
# Every instrument here is invented: a share Yahoo is faked to list, and funds
# with made-up ISINs in a made-up registry.

# Kept before the `offline` fixture refuses it, for the one test that reads a
# faked yfinance frame through it.
REAL_FETCH_LOOKUP = prices._fetch_lookup

WHY = {
    "reason": "It would add a European industrial name to a portfolio of funds only.",
    "based_on": "You said you want a few single shares beside your ETFs.",
    "unknowns": "I do not know how much single-share risk you are willing to carry.",
}

ACME = {
    "symbol": "ACME.MI",
    "name": "Acme Industrie",
    "quote_type": "equity",
    "exchange": "MIL",
    "price": 12.3,
}

FUNDS = ["XA0000000011", "XA0000000029", "XA0000000037", "XA0000000045"]
REGISTRY = pd.DataFrame(
    [
        {
            "name": f"Example Equity Fund {n} UCITS ETF (Acc)",
            "ticker": f"EXF{n}", "dividends": "Accumulating", "ter": 0.1 + n / 100,
            "size": 1000 + n, "replication": "Full replication",
            "domicile_country": "Ireland", "currency": "EUR",
            "number_of_holdings": 100, "hedged": False,
        }
        for n in range(1, 5)
    ],
    index=pd.Index(FUNDS, name="isin"),
)


@pytest.fixture
def yahoo(monkeypatch):
    """Yahoo's lookup, scripted: `yahoo.lists` maps a query to the rows it
    returns (none by default), `yahoo.silent` makes every lookup fail as an
    outage does, and `yahoo.asked` keeps every query."""

    class Fake:
        lists: dict = {}
        silent = False
        asked: list[str] = []

    def lookup(query, count):
        Fake.asked.append(query)
        if Fake.silent:
            raise ConnectionError("Yahoo is down")
        return [dict(row) for row in Fake.lists.get(query.upper(), [])]

    monkeypatch.setattr(prices, "_fetch_lookup", lookup)
    Fake.lists, Fake.silent, Fake.asked = {"ACME.MI": [ACME]}, False, []
    return Fake


@pytest.fixture
def registry(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: REGISTRY)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


def _suggest(db, **arguments) -> dict:
    call = advisor.ToolCall(
        id="toolu_1", name="suggest_instrument", arguments=json.dumps(arguments)
    )
    return tools.answer(db, call)


def _accept(db, card: dict) -> dict:
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


def test_a_share_yahoo_lists_is_put_up_and_kept_by_its_symbol(client, yahoo):
    """The card shows what Yahoo says, asked when it is drawn: the name, the
    symbol, that it is a share, and the exchange as Yahoo names it. Accepted,
    the watchlist keeps no ISIN, the symbol as the identity, Yahoo's name and
    the three sentences."""
    with SessionLocal() as db:
        card = _suggest(db, symbol="acme.mi", **WHY)["card"]
        assert card["title"] == "watch: Acme Industrie, ACME.MI · share · MIL"
        assert card["verb"] == "Add to watchlist"
        assert "gives no ISIN" in card["consequence"]
        assert crud.get_watchlist_items(db) == [], "nothing is written before the reader says yes"
        done = _accept(db, card)
        db.commit()
    assert done["ok"], done
    (line,) = client.get("/api/watchlist").json()
    assert (line["isin"], line["symbol"], line["name"]) == (None, "ACME.MI", "Acme Industrie")
    assert (line["reason"], line["based_on"], line["unknowns"]) == (
        WHY["reason"],
        WHY["based_on"],
        WHY["unknowns"],
    )


def test_confirming_a_share_asks_yahoo_again_and_refuses_what_changed(client, yahoo):
    with SessionLocal() as db:
        card = _suggest(db, symbol="ACME.MI", **WHY)["card"]
        assert yahoo.asked == ["ACME.MI"]
        yahoo.lists["ACME.MI"] = [{**ACME, "name": "Acme Holding"}]
        done = _accept(db, card)
    assert done["ok"] is False and done.get("stale") is True
    assert len(yahoo.asked) == 2


def test_a_silent_yahoo_at_confirmation_writes_nothing(client, yahoo):
    with SessionLocal() as db:
        card = _suggest(db, symbol="ACME.MI", **WHY)["card"]
        yahoo.silent = True
        done = _accept(db, card)
        assert done["ok"] is False
        assert "did not answer" in done["error"]
        assert crud.get_watchlist_items(db) == []


@pytest.mark.parametrize(
    "lists, symbol, said",
    [
        # Yahoo lists nothing under it.
        ({}, "ZZZZ.MI", "Yahoo lists nothing under 'ZZZZ.MI'"),
        # A fund listed in the US, the case the reader will meet on the web.
        (
            {"EXUS": [{"symbol": "EXUS", "name": "Example US 500 Fund", "quote_type": "etf", "exchange": "PCX"}]},
            "EXUS",
            "as a fund, not a share",
        ),
        # Typed equity by Yahoo, a fund by its name (VOOY, 2026-10-06).
        (
            {"EXIN": [{"symbol": "EXIN", "name": "Example Income ETF", "quote_type": "equity", "exchange": "PCX"}]},
            "EXIN",
            "as a fund, not a share",
        ),
        # A bond quoted under its ISIN on Stuttgart, typed equity, no name.
        (
            {"XS0000000009.SG": [{"symbol": "XS0000000009.SG", "name": None, "quote_type": "equity", "exchange": "STU"}]},
            "XS0000000009.SG",
            "is an ISIN",
        ),
        # A coin.
        (
            {"EXC-EUR": [{"symbol": "EXC-EUR", "name": "Example Coin EUR", "quote_type": "cryptocurrency", "exchange": "CCC"}]},
            "EXC-EUR",
            "as cryptocurrency, not as a share",
        ),
        # A share Yahoo gives no name for.
        (
            {"NONAME.MI": [{"symbol": "NONAME.MI", "name": None, "quote_type": "equity", "exchange": "MIL"}]},
            "NONAME.MI",
            "with no name",
        ),
    ],
)
def test_what_yahoo_cannot_vouch_for_as_a_share_gets_no_card(client, yahoo, lists, symbol, said):
    yahoo.lists = {**lists}
    with SessionLocal() as db:
        outcome = _suggest(db, symbol=symbol, **WHY)
    assert "card" not in outcome
    assert outcome["ok"] is False and said in outcome["error"], outcome["error"]


def test_a_silent_yahoo_draws_no_card_and_is_not_called_a_no(client, yahoo):
    yahoo.silent = True
    with SessionLocal() as db:
        outcome = _suggest(db, symbol="ACME.MI", **WHY)
    assert "card" not in outcome
    assert "did not answer just now" in outcome["error"]
    assert "says nothing about whether ACME.MI exists" in outcome["error"]


def test_a_share_already_on_the_watchlist_is_not_suggested_again(client, yahoo):
    with SessionLocal() as db:
        assert _accept(db, _suggest(db, symbol="ACME.MI", **WHY)["card"])["ok"]
        db.commit()
        outcome = _suggest(db, symbol="ACME.MI", **WHY)
    assert "already on the watchlist" in outcome["error"]


def test_a_suggestion_must_name_a_fund_or_a_share(client, yahoo):
    with SessionLocal() as db:
        outcome = _suggest(db, **WHY)
    assert "card" not in outcome
    assert "Name a fund by its ISIN, or a single share by its symbol" in outcome["error"]
    assert yahoo.asked == []


def test_a_missing_name_from_yahoo_is_no_name(monkeypatch):
    """A cell Yahoo left empty arrives as NaN, which used to become the name
    "nan" (VOOB, 2026-10-06)."""
    import yfinance

    class Lookup:
        def __init__(self, query, timeout=None):
            pass

        def get_all(self, count=8):
            return pd.DataFrame(
                [{"shortName": float("nan"), "quoteType": "equity", "exchange": "MIL", "regularMarketPrice": 1.0}],
                index=pd.Index(["NONAME.MI"], name="symbol"),
            )

    monkeypatch.setattr(yfinance, "Lookup", Lookup)
    (row,) = REAL_FETCH_LOOKUP("NONAME.MI", 8)
    assert row["name"] is None and row["quote_type"] == "equity"


# --- Up to three in one answer ----------------------------------------------------


def _suggests(*named: dict) -> bytes:
    """One round that asks for several suggestions at once."""
    calls = [
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": n,
                        "id": f"toolu_{n}",
                        "type": "function",
                        "function": {
                            "name": "suggest_instrument",
                            "arguments": json.dumps({**args, **WHY}),
                        },
                    }
                ]
            }
        )
        for n, args in enumerate(named)
    ]
    return _sse(*calls, _chunk({}, "tool_calls"), _usage())


def test_up_to_three_cards_and_never_four(registry, openrouter):
    openrouter.script = [_suggests(*({"isin": isin} for isin in FUNDS))]
    events = _ask(registry, "Consigliami quattro ETF", OPUS)

    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert [c["arguments"]["isin"] for c in cards] == FUNDS[:3]
    conv = registry.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
    blocks = conv["messages"][-1]["blocks"]
    assert [b["kind"] for b in blocks] == ["card", "card", "card", "tool"]
    refused = blocks[-1]
    assert refused["ok"] is False
    assert refused["detail"] == (
        f"3 suggestions are already up in this answer, the most one answer holds, "
        f"so this one for {FUNDS[3]} was not drawn."
    )
    assert len(openrouter.asked) == 1, "the answer ends on its cards"
    # Said on the live answer too, not only after a reload: the model never
    # gets a round to say why the fourth is missing.
    (tool,) = [e for e in events if e["kind"] == "tool"]
    assert tool == {"kind": "tool", "name": "suggest_instrument", "detail": refused["detail"]}


def test_a_tool_event_carries_a_failure_and_claims_no_success(registry, openrouter):
    openrouter.script = [
        _sse(
            _call_at(0, "read_analysis", {"run_id": 1}),
            _call_at(1, "search_catalogue", {"query": "Example Equity Fund"}),
            _chunk({}, "tool_calls"),
            _usage(),
        ),
        _says("Fatto."),
    ]
    events = _ask(registry, "Cerca", OPUS)
    failed, worked = [e for e in events if e["kind"] == "tool"]
    assert failed["name"] == "read_analysis"
    assert "There is no analysis run with id 1" in failed["detail"]
    assert worked == {"kind": "tool", "name": "search_catalogue", "detail": None}


def test_one_card_per_instrument_in_an_answer(registry, openrouter):
    openrouter.script = [_suggests({"isin": FUNDS[0]}, {"isin": FUNDS[0].lower()})]
    events = _ask(registry, "Consigliami due ETF", OPUS)
    assert len([e for e in events if e["kind"] == "card"]) == 1
    conv = registry.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
    refused = conv["messages"][-1]["blocks"][-1]
    assert refused["kind"] == "tool" and refused["ok"] is False
    assert refused["detail"] == (
        f"This answer already has a card for {FUNDS[0]}: one card per instrument."
    )


def test_the_prompt_and_the_tool_say_up_to_three_and_what_gets_none():
    for text in (chat.SYSTEM_PROMPT, tools.REGISTRY["suggest_instrument"].description):
        assert "never more than one at a time" not in text.lower()
        assert "up to three" in text
    assert "not a single bond" in chat.SYSTEM_PROMPT
    assert "a single share" in chat.SYSTEM_PROMPT
    assert "Yahoo (a share)" in chat.WEB_RULES


# --- The migration ----------------------------------------------------------------


@pytest.fixture
def before_the_share_migration(tmp_path, start_on):
    """A file the real chain built up to the revision before `5a4336780500`,
    which the next `database.init_db()` starts on. Named by its revision and
    not as "one behind the head", because the head has moved since (brief AJ,
    `e62c6f6c8060`), and a start now runs this migration and the ones after it."""
    path = tmp_path / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, "e9346d9cfd3f")
    start_on(path)
    return path


def test_the_migration_keeps_every_line_and_lets_a_share_have_no_isin(before_the_share_migration):
    """The reader's `data.db` takes this at its next start: the app copies the
    file, then rebuilds `watchlist_items` with `isin` optional, every row
    copied as it was. Undone only while no line lacks an ISIN."""
    path = before_the_share_migration
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO watchlist_items (isin, symbol, name, reason, based_on, unknowns, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("XA0000000011", None, "Example Equity Fund 1", "Why.", "Because.", "Not known.",
             "2026-09-30T10:00:00"),
        )
        before = conn.execute("SELECT * FROM watchlist_items").fetchall()

    database.init_db()

    copies = list(
        path.parent.glob("data.db.bak-*-before-migration-e9346d9cfd3f-to-*")
    )
    assert len(copies) == 1, "the app copied the file before migrating it"
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("SELECT * FROM watchlist_items").fetchall() == before
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(watchlist_items)")}
        assert columns["isin"][3] == 0, "isin is no longer NOT NULL"
        assert columns["name"][3] == 1
        indexes = [row[1] for row in conn.execute("PRAGMA index_list(watchlist_items)")]
        assert "ix_watchlist_items_isin" in indexes
        conn.execute(
            "INSERT INTO watchlist_items (isin, symbol, name, reason, based_on, unknowns, added_at)"
            " VALUES (NULL, 'ACME.MI', 'Acme Industrie', 'Why.', 'Because.', 'Not known.',"
            " '2026-10-06T10:00:00')"
        )

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.raises(RuntimeError, match="name a share by its symbol"):
        command.downgrade(cfg, "e9346d9cfd3f")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DELETE FROM watchlist_items WHERE isin IS NULL")
    command.downgrade(cfg, "e9346d9cfd3f")
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(watchlist_items)")}
        assert columns["isin"][3] == 1
        assert conn.execute("SELECT * FROM watchlist_items").fetchall() == before
