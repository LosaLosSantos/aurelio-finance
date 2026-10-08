"""The chat searches the web, and proposes only what a source verifies.

Brief AG (2026-10-06). The reader asked for a chat that goes and looks ("Io
voglio che il mio bot sia in grado di fare ricerca!!"), and decided: the whole
web, with its sources in view. The search is OpenRouter's server tool,
`openrouter:web_search`: the model asks for it inside a request, OpenRouter
runs it, and what comes back to the app is the pages it found, one
`url_citation` annotation each. Measured on the wire before this was built
(a paid probe, 2026-10-06), and these tests pin what that showed:

- the tool goes to Anthropic's models only, the line brief AD drew for the
  cache, with the engine and the caps the probe settled;
- a turn stops offering it after six searches, counted by the app between
  rounds, because OpenRouter's own cap did not hold within one batch;
- the pages are kept where the search ran, as links, and nothing that is not
  a web address becomes one;
- a round that ended on the app's tools never read its pages (OpenRouter ran
  the search after it), so they are passed on to the next round.

They go through the real `stream_llm` and the real openai client over a faked
transport: the rules are about the bytes of the request and of the stream.
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
SONNET = "anthropic/claude-sonnet-4.6"
OTHERS = ["qwen/qwen3.8-max-0902", "openai/gpt-6.1-sol-pro", "moonshotai/kimi-k3"]
PAGE = {"kind": "portfolio"}
WEB = {
    "type": "openrouter:web_search",
    "parameters": {"engine": "exa", "max_results": 5, "max_uses": 3},
}


# --- OpenRouter, scripted ---------------------------------------------------------


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _usage(searches: int | None = None) -> dict:
    """The chunk a streamed call ends with. A call that searched says how many
    times in `server_tool_use_details`, the name it arrived under in the probe
    (not the `server_tool_use` OpenRouter's docs give)."""
    usage = {
        "prompt_tokens": 11865,
        "completion_tokens": 40,
        "total_tokens": 11905,
        "prompt_tokens_details": {"cached_tokens": 11861, "cache_write_tokens": 0},
        "cost": 0.0087282,
    }
    if searches is not None:
        usage["server_tool_use_details"] = {
            "web_search_requests": searches,
            "tool_calls_requested": searches,
            "tool_calls_executed": searches,
        }
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [],
        "usage": usage,
    }


def _found(url: str, title: str, content: str = "An excerpt.") -> dict:
    """One page a search found, as the probe saw it arrive."""
    return _chunk(
        {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": url,
                        "title": title,
                        "content": content,
                        "start_index": 0,
                        "end_index": 0,
                    },
                }
            ]
        }
    )


def _sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _says(text: str, *before, searches: int | None = None) -> bytes:
    return _sse(*before, _chunk({"content": text}), _chunk({}, "stop"), _usage(searches))


def _calls(name: str, arguments: dict, call_id: str, *after, searches: int | None = None) -> bytes:
    """A round that ends on one of the app's tools. Pages, when given, arrive
    after the call, which is where the probe found them: OpenRouter ran the
    search once the model's response had ended (S2, B5)."""
    tool = {
        "index": 2,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return _sse(_chunk({"tool_calls": [tool]}), *after, _chunk({}, "tool_calls"), _usage(searches))


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


def _reads_run_one(n: int, *after, searches: int | None = None) -> bytes:
    return _calls("read_analysis", {"run_id": 1}, f"toolu_{n}", *after, searches=searches)


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


def _web(body: dict) -> list[dict]:
    return [t for t in body.get("tools") or [] if t.get("type") != "function"]


def _functions(body: dict) -> list[str]:
    return [t["function"]["name"] for t in body.get("tools") or [] if t.get("type") == "function"]


def _text(message: dict) -> str | None:
    content = message.get("content")
    return content[0]["text"] if isinstance(content, list) else content


# --- Who is offered the web -------------------------------------------------------


@pytest.mark.parametrize("model", [OPUS, SONNET, "~anthropic/claude-sonnet-latest"])
def test_anthropics_models_are_offered_the_web_with_its_caps(client, openrouter, model):
    """Exa, five pages a search, three searches a request: the engine and the
    caps the probe settled (2026-10-06), beside the app's own nine tools."""
    openrouter.script = [_says("Ciao.")]
    _ask(client, "Ciao", model)
    (body,) = openrouter.asked
    assert _web(body) == [WEB]
    assert len(_functions(body)) == 9


@pytest.mark.parametrize("model", OTHERS)
def test_the_other_models_are_not(client, openrouter, model):
    """Unmeasured on the other families, so their requests carry the app's
    tools and nothing else, as before."""
    openrouter.script = [_says("Ciao.")]
    _ask(client, "Ciao", model)
    (body,) = openrouter.asked
    assert _web(body) == []
    assert len(_functions(body)) == 9


def test_the_search_count_is_read_where_openrouter_puts_it():
    class Reported:
        prompt_tokens = 25950
        prompt_tokens_details = None
        cost = 0.085376
        server_tool_use_details = {"web_search_requests": 2, "tool_calls_executed": 2}

    class Silent:
        prompt_tokens = 100
        prompt_tokens_details = None
        cost = 0.001

    assert advisor._usage(Reported()).searches == 2
    assert advisor._usage(Silent()).searches is None


# --- The cap a turn keeps ---------------------------------------------------------


def test_a_turn_stops_offering_the_web_after_six_searches(client, openrouter):
    """OpenRouter's `max_uses` did not hold within one batch (two searches ran
    under `max_uses: 1`, probe S2), so the cap that holds is the app's: it adds
    up what each round reports and, at six, asks the rest of the turn without
    the web. The app's own tools stay."""
    openrouter.script = [
        _reads_run_one(1, searches=4),
        _reads_run_one(2, searches=2),
        _says("Fatto."),
    ]
    _ask(client, "Cerca", OPUS)
    first, second, third = openrouter.asked
    assert _web(first) == [WEB] and _web(second) == [WEB]
    assert _web(third) == []
    assert len(_functions(third)) == 9


def test_a_turn_under_six_keeps_it(client, openrouter):
    openrouter.script = [
        _reads_run_one(1, searches=3),
        _reads_run_one(2, searches=2),
        _says("Fatto."),
    ]
    _ask(client, "Cerca", OPUS)
    assert all(_web(body) == [WEB] for body in openrouter.asked)


# --- The pages, as links ----------------------------------------------------------


def test_the_pages_a_search_found_are_kept_where_it_ran(client, openrouter):
    """In the order they arrived and where they arrived: before the words a
    round wrote from them. A page found twice is listed once, and anything that
    is not an http or https address is no link at all."""
    openrouter.script = [
        _says(
            "Lo 0,03% all'anno.",
            _found("https://investor.example/voo", "VOO fact sheet"),
            _found("https://www.sec.example/prospectus.htm", "Prospectus"),
            _found("https://investor.example/voo", "VOO fact sheet, again"),
            _found("javascript:alert(1)", "Not a page"),
            _found("ftp://files.example/report.pdf", "Not a web page either"),
            searches=1,
        )
    ]
    events = _ask(client, "Quanto costa VOO?", OPUS)

    sources = [e for e in events if e["kind"] == "source"]
    assert [(e["url"], e["title"]) for e in sources] == [
        ("https://investor.example/voo", "VOO fact sheet"),
        ("https://www.sec.example/prospectus.htm", "Prospectus"),
    ]
    conv = client.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
    blocks = conv["messages"][-1]["blocks"]
    assert [b["kind"] for b in blocks] == ["sources", "text"]
    assert blocks[0]["pages"] == [
        {"url": "https://investor.example/voo", "title": "VOO fact sheet"},
        {"url": "https://www.sec.example/prospectus.htm", "title": "Prospectus"},
    ]


def test_a_page_with_no_title_is_named_by_its_address(client, openrouter):
    openrouter.script = [_says("Ecco.", _found("https://www.example.org/a/b", ""), searches=1)]
    events = _ask(client, "Cerca", OPUS)
    (source,) = [e for e in events if e["kind"] == "source"]
    assert source["title"] == "www.example.org"


# --- What a later round reads -----------------------------------------------------


def test_pages_a_round_never_read_are_passed_on_to_the_next(client, openrouter):
    """The probe's finding (S2, B5): asked for searches and one of the app's
    tools in one response, OpenRouter runs the searches after that response,
    so the model never reads what they found. B3 passed them on as one
    message after the tool results, and the model cited them. Each excerpt is
    kept to a thousand characters."""
    long = "x" * 1500
    openrouter.script = [
        _reads_run_one(
            1,
            _found("https://investor.example/voo", "VOO fact sheet", "TER 0.03%"),
            _found("https://www.sec.example/prospectus.htm", "Prospectus", long),
            searches=2,
        ),
        _says("Lo 0,03% all'anno."),
    ]
    _ask(client, "Quanto costa VOO?", OPUS)
    second = openrouter.asked[1]["messages"]
    assert [m["role"] for m in second[-3:]] == ["assistant", "tool", "user"]
    passed = _text(second[-1])
    assert "https://investor.example/voo" in passed and "VOO fact sheet" in passed
    assert "TER 0.03%" in passed
    assert "x" * 1000 in passed and "x" * 1001 not in passed


def test_a_round_with_no_pages_passes_nothing_on(client, openrouter):
    openrouter.script = [_reads_run_one(1), _says("Fatto.")]
    _ask(client, "Leggi la run 1", OPUS)
    assert openrouter.asked[1]["messages"][-1]["role"] == "tool"


def test_the_last_round_notice_rides_with_the_pages(client, openrouter, monkeypatch):
    """On the round that carries the deadline, the pages and the notice are one
    message after the tool results, not two in a row."""
    monkeypatch.setattr(chat, "MAX_COMPLETIONS_PER_TURN", 3)
    openrouter.script = [
        _reads_run_one(1, _found("https://investor.example/voo", "VOO fact sheet"), searches=1),
        _reads_run_one(2),
        _says("Fatto."),
    ]
    _ask(client, "Cerca", OPUS)
    notice_round = openrouter.asked[1]["messages"]
    assert [m["role"] for m in notice_round[-3:]] == ["assistant", "tool", "user"]
    last = _text(notice_round[-1])
    assert "https://investor.example/voo" in last
    assert chat.LAST_TOOL_ROUND_NOTICE in last


def test_a_later_turn_gets_the_words_and_not_the_pages(client, openrouter):
    """Past turns travel as their words, like every other lookup (brief AB): a
    link the model wrote travels inside them, and the list of pages does not."""
    openrouter.script = [
        _says(
            "Secondo [Vanguard](https://investor.example/voo), lo 0,03%.",
            _found("https://investor.example/voo", "VOO fact sheet"),
            _found("https://www.sec.example/prospectus.htm", "Prospectus"),
            searches=1,
        ),
        _says("Prego."),
    ]
    first = _ask(client, "Quanto costa VOO?", OPUS)
    _ask(client, "Grazie", OPUS, first[0]["conversation_id"])
    history = json.dumps(openrouter.asked[1]["messages"])
    assert "https://investor.example/voo" in history  # inside the words
    assert "sec.example" not in history and "Prospectus" not in history


# --- The prompt -------------------------------------------------------------------


def test_the_web_rules_go_to_the_models_offered_the_web_and_no_other(client, openrouter):
    openrouter.script = [_says("Ciao."), _says("Ciao.")]
    _ask(client, "Ciao", OPUS)
    _ask(client, "Ciao", OTHERS[0])
    opus, other = openrouter.asked
    assert chat.WEB_RULES in _text(opus["messages"][0])
    assert _text(other["messages"][0]) == chat.SYSTEM_PROMPT
    assert "search the web" not in chat.SYSTEM_PROMPT


def test_the_web_rules_say_when_to_search_and_how_a_page_is_used():
    """When (advice, news, facts the records, the catalogue and Yahoo lack)
    and when not (what the picture or the catalogue answers); never the reader
    in a query; every claim from a page with its link, and a figure only with
    it; the web finds and a card verifies, so a fund the catalogue does not
    hold gets no card. Short, because the prompt goes out on every turn: 883
    characters when written."""
    rules = chat.WEB_RULES
    assert "news, recent performance" in rules
    assert "Never for what the picture or the catalogue answers" in rules
    assert "Never put their figures, names or anything else about them in a query" in rules
    assert "run it unasked" in rules
    assert "carries its link, as [title](url)" in rules
    assert "a figure from a page is stated with its link or not at all" in rules
    assert "The web finds; it does not verify" in rules
    assert "gets no card, and you say why" in rules
    assert len(rules) < 1000


def test_reading_is_no_longer_said_to_cost_nothing():
    """A search costs a little, so the sentence that said reading costs them
    no money goes; reading still needs no permission."""
    for prompt in (chat.SYSTEM_PROMPT, chat.system_prompt(OPUS)):
        assert "cost them no money" not in prompt
        assert "never ask whether to run one: run it" in prompt


def test_no_dash_in_what_the_chat_reads():
    """The reader, 2026-10-06: the chat's prompt and the tools' descriptions
    lose their em dashes, "since the model writes in the style it reads", and
    so do the readings that travel with every catalogue, lookup and
    look-through result. The one em dash and the one spaced en dash left are
    in `advisor.NO_DASHES`, which shows the two characters it forbids."""
    em, en = chr(0x2014), " " + chr(0x2013) + " "

    def clean(text: str) -> bool:
        return em not in text and en not in text

    for prompt in (chat.SYSTEM_PROMPT, chat.system_prompt(OPUS)):
        assert prompt.count(advisor.NO_DASHES) == 1
        assert clean(prompt.replace(advisor.NO_DASHES, ""))
    assert clean(chat.LAST_TOOL_ROUND_NOTICE) and clean(chat.PAGES_PASSED_ON)
    assert clean(json.dumps(tools.declarations(), ensure_ascii=False))
    for reading in (tools._READING, tools._CATALOGUE_READING, tools._LOOKUP_READING):
        assert all(clean(line) for line in reading)


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
