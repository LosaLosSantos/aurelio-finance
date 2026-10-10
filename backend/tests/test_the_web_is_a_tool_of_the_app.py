"""The web search is a tool of the app, run as a request of its own.

Brief AM (2026-10-09). Brief AG (2026-10-06) gave the chat the web through
OpenRouter's server tool, declared on every request of the chat, and brief AL's
paid probe P1 (2026-10-08) found what that cost: a request that declares it
keeps none of the cache's markers but the last, so no turn read the turn
before it. Now the chat's model calls `search_web`, a tool of the app's like
the others, and the app runs each search as a request of its own to OpenRouter
that carries the query and nothing else of the conversation (`websearch`).
Brief AM's own P1 (paid, 2026-10-09) measured that request before the rest
was built: one search each, five pages, $0.0073 a search, Exa's fee as
charged.

These pin:
- no request of the chat declares a search OpenRouter runs, and Anthropic's
  models are offered `search_web` beside the app's other tools;
- a search is one request that carries its query and nothing else, and its
  pages come back to the model as the tool's result, with their excerpts;
- the reader sees the pages as before, as links where the search ran;
- six searches a turn: a seventh is answered in words and the tools stay as
  they are; one round's searches run at the same time;
- a search whose answer reports no search did not run, and is never told as
  one that found nothing; one that got no answer says why, and is not asked
  again;
- the turn's cost is its rounds' and its searches', unknown when any is.

They go through the real `stream_llm`, the real `websearch.search` and the
real openai client over a faked transport: the rules are about the bytes of
the requests.
"""

from __future__ import annotations

import json
import re
import threading

import httpx
import pytest

from app import advisor, chat, crud, tools, websearch
from app.database import SessionLocal

REAL_STREAM_LLM = advisor.stream_llm

OPUS = "anthropic/claude-opus-5.5"
ANTHROPICS = [OPUS, "anthropic/claude-sonnet-4.6", "~anthropic/claude-sonnet-latest"]
OTHERS = ["qwen/qwen3.8-max-0902", "openai/gpt-6.1-sol-pro", "moonshotai/kimi-k3"]
PAGE = {"kind": "portfolio"}

QUESTION = "Che differenza c'è tra un ETF ad accumulazione e uno a distribuzione?"
QUERY = "UCITS ETF accumulating vs distributing difference"

# What each scripted round of the chat reports: read, written and paid like a
# round that reads the one before it.
ROUND_PROMPT, ROUND_CACHED, ROUND_COST = 12925, 12644, 0.01
SEARCH_COST = 0.0073


# --- A search's answer, shaped like those of brief AM's P1 --------------------------


def _cited(url: str, title: str, content: str = "An excerpt.") -> dict:
    return {
        "type": "url_citation",
        "url_citation": {
            "url": url,
            "title": title,
            "content": content,
            "start_index": 0,
            "end_index": 0,
        },
    }


def _answer(*annotations: dict, searches: int | None = 1, cost: float | None = SEARCH_COST) -> dict:
    usage: dict = {
        "prompt_tokens": 3213,
        "completion_tokens": 72,
        "total_tokens": 3285,
        "prompt_tokens_details": {"cached_tokens": 982, "cache_write_tokens": 2225},
    }
    if cost is not None:
        usage["cost"] = cost
    if searches is not None:
        usage["server_tool_use_details"] = {
            "web_search_requests": searches,
            "tool_calls_requested": searches,
            "tool_calls_executed": searches,
        }
    return {
        "id": "gen-search",
        "object": "chat.completion",
        "created": 1,
        "model": websearch.SEARCH_MODEL,
        "provider": "unknown",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "native_finish_reason": "stop",
                "message": {"role": "assistant", "content": "done", "annotations": list(annotations)},
            }
        ],
        "usage": usage,
    }


def _slug(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")


def _two_pages(query: str) -> dict:
    """What a search finds unless a test says otherwise: two pages, named
    after its query."""
    return _answer(
        _cited(f"https://one.example/{_slug(query)}", f"One on {query}", f"First excerpt on {query}."),
        _cited(f"https://two.example/{_slug(query)}", f"Two on {query}", f"Second excerpt on {query}."),
    )


def _query(body: dict) -> str:
    return body["messages"][-1]["content"]


# --- The chat's rounds, scripted ----------------------------------------------------


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _usage_chunk() -> dict:
    return {
        "id": "gen-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [],
        "usage": {
            "prompt_tokens": ROUND_PROMPT,
            "completion_tokens": 40,
            "total_tokens": ROUND_PROMPT + 40,
            "prompt_tokens_details": {
                "cached_tokens": ROUND_CACHED,
                "cache_write_tokens": ROUND_PROMPT - ROUND_CACHED,
            },
            "cost": ROUND_COST,
        },
    }


def _sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _says(text: str) -> bytes:
    return _sse(_chunk({"content": text}), _chunk({}, "stop"), _usage_chunk())


def _call(index: int, name: str, arguments: dict) -> dict:
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


def _asks(*calls: dict) -> bytes:
    """A round that ends on the app's tools."""
    return _sse(*calls, _chunk({}, "tool_calls"), _usage_chunk())


def _searches_for(*queries: str) -> bytes:
    """A round that asks for one search per query, all at once."""
    return _asks(*(_call(n, "search_web", {"query": q}) for n, q in enumerate(queries)))


@pytest.fixture
def openrouter(monkeypatch):
    """The real client over a transport that tells the chat's requests from
    the searches' by their model. A request of the chat is answered with the
    next entry of `script` and kept in `asked`; a search is kept in `searched`
    and answered by `search(body)`, which finds two pages unless a test says
    otherwise.

    The client keeps the SDK's own retries, so a search that is asked twice
    after a failure shows up here as two requests: the search sets its own."""

    class Fake:
        script: list = []
        asked: list[dict] = []
        searched: list[dict] = []

        @staticmethod
        def search(body: dict) -> httpx.Response:
            return httpx.Response(200, json=_two_pages(_query(body)))

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == websearch.SEARCH_MODEL:
            Fake.searched.append(body)
            return Fake.search(body)
        Fake.asked.append(body)
        assert Fake.script, "a call past the script"
        return httpx.Response(
            200, content=Fake.script.pop(0), headers={"content-type": "text/event-stream"}
        )

    def client():
        return advisor.sdk().OpenAI(
            base_url=advisor.OPENROUTER_BASE_URL,
            api_key="invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(advisor, "stream_llm", REAL_STREAM_LLM)
    monkeypatch.setattr(advisor, "_client", client)
    Fake.script, Fake.asked, Fake.searched = [], [], []
    return Fake


def _events(text: str) -> list[dict]:
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


def _functions(body: dict) -> list[str]:
    return [t["function"]["name"] for t in body.get("tools") or [] if t.get("type") == "function"]


def _results(body: dict) -> list[dict]:
    """Every tool result a request carries, in order, as the model reads it."""
    return [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]


def _stored(events: list[dict]):
    """The answer as stored, with what it read and what it cost."""
    with SessionLocal() as db:
        conv = crud.get_chat_conversation(db, events[0]["conversation_id"])
        answer = [m for m in conv.messages if m.role == "assistant"][-1]
        return answer.prompt_tokens, answer.cached_tokens, answer.cost, json.loads(answer.blocks)


# --- No request of the chat declares a search -----------------------------------------


@pytest.mark.parametrize("model", ANTHROPICS)
def test_no_request_of_the_chat_declares_a_search_openrouter_runs(client, openrouter, model):
    """Anthropic's models are offered `search_web`, a function of the app's,
    after the app's other tools, on every round, and nothing OpenRouter would
    run inside the request."""
    openrouter.script = [_searches_for(QUERY), _says("Ecco la differenza.")]

    _ask(client, QUESTION, model)

    assert len(openrouter.asked) == 2
    for body in openrouter.asked:
        assert all(t["type"] == "function" for t in body["tools"])
        assert _functions(body) == [*tools.REGISTRY, tools.SEARCH_WEB]
        assert "openrouter:web_search" not in json.dumps(body)


@pytest.mark.parametrize("model", OTHERS)
def test_the_other_models_are_offered_the_apps_tools_and_no_search(client, openrouter, model):
    """Unmeasured on the other families, so their requests carry the app's
    nine tools and nothing else, as before."""
    openrouter.script = [_says("Ciao.")]

    _ask(client, "Ciao", model)

    (body,) = openrouter.asked
    assert _functions(body) == list(tools.REGISTRY)
    assert all(t["type"] == "function" for t in body["tools"])


# --- One search, one request, the query and nothing else ------------------------------


def test_a_search_is_one_request_that_carries_its_query_and_nothing_else(client, openrouter):
    """The request P1 measured, to the byte: Haiku 5.5, the fixed instruction,
    the query, OpenRouter's search on Exa capped at one, five pages of at most
    a thousand characters. No picture, no question, no conversation, no
    session, no cache."""
    openrouter.script = [_searches_for(QUERY), _says("Ecco la differenza.")]

    _ask(client, QUESTION, OPUS)

    (body,) = openrouter.searched
    assert body == {
        "model": "anthropic/claude-haiku-5.5",
        "messages": [
            {"role": "system", "content": websearch.INSTRUCTION},
            {"role": "user", "content": QUERY},
        ],
        "tools": [
            {
                "type": "openrouter:web_search",
                "parameters": {"engine": "exa", "max_results": 5, "max_uses": 1, "max_characters": 1000},
            }
        ],
        "max_tokens": 1024,
        "max_tool_calls": 1,
        "reasoning": {"effort": "low"},
    }
    sent = json.dumps(body, ensure_ascii=False)
    assert QUESTION not in sent
    assert "financial picture" not in sent and "Today is" not in sent


def test_the_model_reads_the_pages_with_their_excerpts_as_the_searchs_result(client, openrouter):
    """The round after the search reads its pages as the tool's result: no
    message of the app's passing them on, which brief AG needed when the
    search ran after the round that asked for it."""
    openrouter.script = [_searches_for(QUERY), _says("Ecco la differenza.")]

    _ask(client, QUESTION, OPUS)

    second = openrouter.asked[1]["messages"]
    assert [m["role"] for m in second[-2:]] == ["assistant", "tool"]
    slug = _slug(QUERY)
    assert _results(openrouter.asked[1]) == [
        {
            "ok": True,
            "result": {
                "query": QUERY,
                "pages": [
                    {"title": f"One on {QUERY}", "url": f"https://one.example/{slug}", "excerpt": f"First excerpt on {QUERY}."},
                    {"title": f"Two on {QUERY}", "url": f"https://two.example/{slug}", "excerpt": f"Second excerpt on {QUERY}."},
                ],
            },
        }
    ]


# --- The reader sees the pages, as before -----------------------------------------------


def test_the_reader_sees_the_pages_as_links_where_the_search_ran(client, openrouter):
    """Under the search's line and before the words written from them, in the
    order the search gave them. A page found twice is listed once, anything
    that is not an http or https address is no link at all, and a page with
    no title is named by its site."""
    openrouter.search = lambda body: httpx.Response(
        200,
        json=_answer(
            _cited("https://investor.example/voo", "VOO fact sheet"),
            _cited("https://www.sec.example/prospectus.htm", "Prospectus"),
            _cited("https://investor.example/voo", "VOO fact sheet, again"),
            _cited("javascript:alert(1)", "Not a page"),
            _cited("ftp://files.example/report.pdf", "Not a web page either"),
            _cited("https://www.example.org/a/b", ""),
        ),
    )
    openrouter.script = [_searches_for("VOO expense ratio"), _says("Lo 0,03% all'anno.")]

    events = _ask(client, "Quanto costa VOO?", OPUS)

    kinds = [e["kind"] for e in events]
    (tool,) = [e for e in events if e["kind"] == "tool"]
    assert tool == {"kind": "tool", "name": "search_web", "detail": None}
    assert kinds.index("tool") < kinds.index("source") < kinds.index("delta")
    pages = [
        ("https://investor.example/voo", "VOO fact sheet"),
        ("https://www.sec.example/prospectus.htm", "Prospectus"),
        ("https://www.example.org/a/b", "www.example.org"),
    ]
    assert [(e["url"], e["title"]) for e in events if e["kind"] == "source"] == pages
    *_, blocks = _stored(events)
    assert [b["kind"] for b in blocks] == ["tool", "sources", "text"]
    assert blocks[1]["pages"] == [{"url": url, "title": title} for url, title in pages]


def test_a_later_turn_gets_the_words_and_not_the_pages(client, openrouter):
    """Past turns travel as their words, like every other lookup (brief AB): a
    link the model wrote travels inside them, and the pages and excerpts it
    read do not."""
    openrouter.search = lambda body: httpx.Response(
        200,
        json=_answer(
            _cited("https://investor.example/voo", "VOO fact sheet", "TER 0.03%"),
            _cited("https://www.sec.example/prospectus.htm", "Prospectus", "A prospectus."),
        ),
    )
    openrouter.script = [
        _searches_for("VOO expense ratio"),
        _says("Secondo [Vanguard](https://investor.example/voo), lo 0,03%."),
        _says("Prego."),
    ]

    first = _ask(client, "Quanto costa VOO?", OPUS)
    _ask(client, "Grazie", OPUS, first[0]["conversation_id"])

    history = json.dumps(openrouter.asked[2]["messages"])
    assert "https://investor.example/voo" in history  # inside the words
    assert "sec.example" not in history and "Prospectus" not in history
    assert "TER 0.03%" not in history


# --- Six a turn, all of a round's at once ------------------------------------------------


def test_a_seventh_search_is_refused_in_words_and_the_tools_stay(client, openrouter):
    """Four searches in one round and three in the next: six run, the seventh
    is answered by the app in a sentence, and every round is offered the same
    tools, so none pays for its prefix again."""
    queries = [f"query {n}" for n in range(1, 8)]
    openrouter.script = [
        _searches_for(*queries[:4]),
        _searches_for(*queries[4:]),
        _says("Ecco cosa ho trovato."),
    ]

    events = _ask(client, "Cerca tutto quello che puoi", OPUS)

    assert sorted(_query(b) for b in openrouter.searched) == sorted(queries[:6])
    results = _results(openrouter.asked[2])
    assert [r["ok"] for r in results] == [True] * 6 + [False]
    assert results[-1] == {"ok": False, "error": chat.SEARCHES_SPENT}
    assert len({json.dumps(b["tools"]) for b in openrouter.asked}) == 1
    refused = [e for e in events if e["kind"] == "tool"][-1]
    assert refused == {"kind": "tool", "name": "search_web", "detail": chat.SEARCHES_SPENT}


def test_one_rounds_searches_run_at_the_same_time(client, openrouter):
    """Two searches asked at once are both on the wire before either is
    answered, and their results reach the model in the order it asked."""
    together = threading.Barrier(2, timeout=5)

    def search(body: dict) -> httpx.Response:
        together.wait()  # broken, and the search failed, if the other never comes
        return httpx.Response(200, json=_two_pages(_query(body)))

    openrouter.search = search
    openrouter.script = [_searches_for("first query", "second query"), _says("Fatto.")]

    events = _ask(client, "Cerca due cose", OPUS)

    assert [e["detail"] for e in events if e["kind"] == "tool"] == [None, None]
    assert [r["result"]["query"] for r in _results(openrouter.asked[1])] == [
        "first query",
        "second query",
    ]


def test_a_query_that_does_not_fit_is_told_why_and_never_sent(client, openrouter):
    """A query is words for a search engine, not a paragraph. One past the
    bound goes back to the model with the reason, nothing is sent, and it does
    not count among the turn's six."""
    openrouter.script = [_asks(_call(0, "search_web", {"query": "x" * 301})), _says("Riprovo.")]

    _ask(client, "Cerca", OPUS)

    assert openrouter.searched == []
    (result,) = _results(openrouter.asked[1])
    assert result["ok"] is False
    assert result["error"].startswith("Those arguments do not fit search_web")


# --- A search that did not run is not a search that found nothing ------------------------


@pytest.mark.parametrize("searches", [0, None])
def test_a_search_whose_answer_reports_no_search_did_not_run(client, openrouter, searches):
    """Said none, or said nothing and found nothing: the model reads that the
    search did not run, which says nothing about the web, and the reader sees
    it under the search's line. What the request cost is in the turn's."""
    openrouter.search = lambda body: httpx.Response(200, json=_answer(searches=searches))
    openrouter.script = [_searches_for(QUERY), _says("Non ho potuto cercare.")]

    events = _ask(client, QUESTION, OPUS)

    said = (
        f'The search for "{QUERY}" did not run: OpenRouter reported no search, so '
        "this says nothing about what the web holds."
    )
    assert _results(openrouter.asked[1]) == [{"ok": False, "error": said}]
    (tool,) = [e for e in events if e["kind"] == "tool"]
    assert tool["detail"] == said
    assert not [e for e in events if e["kind"] == "source"]
    _, _, cost, _ = _stored(events)
    assert cost == pytest.approx(2 * ROUND_COST + SEARCH_COST)


def test_pages_with_no_count_are_a_search_that_ran(client, openrouter):
    """An answer that says nothing about how many searches ran, but holds
    pages, ran one: the pages are what a search returns."""
    openrouter.search = lambda body: httpx.Response(
        200, json=_answer(_cited("https://one.example/a", "A page"), searches=None)
    )
    openrouter.script = [_searches_for(QUERY), _says("Ecco.")]

    _ask(client, QUESTION, OPUS)

    (result,) = _results(openrouter.asked[1])
    assert result["ok"] is True
    assert [p["url"] for p in result["result"]["pages"]] == ["https://one.example/a"]


def test_a_search_that_ran_and_found_nothing_says_so(client, openrouter):
    """The one case where "nothing found" is true: the answer says a search
    ran, and it returned no page."""
    openrouter.search = lambda body: httpx.Response(200, json=_answer(searches=1))
    openrouter.script = [_searches_for(QUERY), _says("Non ho trovato nulla.")]

    _ask(client, QUESTION, OPUS)

    assert _results(openrouter.asked[1]) == [{"ok": True, "result": {"query": QUERY, "pages": []}}]


def test_a_search_that_got_no_answer_says_why_and_is_not_asked_again(client, openrouter):
    """A refusal is told with OpenRouter's own words, once: the SDK would ask
    again by itself, and a search asked again is a second search, paid for."""
    openrouter.search = lambda body: httpx.Response(
        500, json={"error": {"message": "Internal error", "code": 500}}
    )
    openrouter.script = [_searches_for(QUERY), _says("La ricerca non ha risposto.")]

    _ask(client, QUESTION, OPUS)

    assert len(openrouter.searched) == 1
    assert _results(openrouter.asked[1]) == [
        {
            "ok": False,
            "error": (
                f'The search for "{QUERY}" got no answer (OpenRouter refused it with '
                "500: Internal error), so this says nothing about what the web holds."
            ),
        }
    ]


def test_a_search_waits_its_time_once(client, openrouter):
    """A search that does not answer in time is given up, and not asked again."""

    def slow(body: dict) -> httpx.Response:
        raise httpx.ReadTimeout("no answer")

    openrouter.search = slow
    openrouter.script = [_searches_for(QUERY), _says("La ricerca non ha risposto.")]

    _ask(client, QUESTION, OPUS)

    assert len(openrouter.searched) == 1
    (result,) = _results(openrouter.asked[1])
    assert result["error"] == (
        f'The search for "{QUERY}" got no answer (it took longer than '
        f"{websearch.TIMEOUT_SECONDS} seconds), so this says nothing about what the web holds."
    )


# --- What a turn costs ---------------------------------------------------------------------


def test_the_turns_cost_is_its_rounds_and_its_searches(client, openrouter):
    """Two rounds and two searches: the cost is all four. The tokens are the
    rounds' alone, since they show what the cache reads, and a search is
    another model's request that reads nothing from it."""
    openrouter.script = [_searches_for("first query", "second query"), _says("Fatto.")]

    events = _ask(client, "Cerca due cose", OPUS)

    prompt, cached, cost, _ = _stored(events)
    assert cost == pytest.approx(2 * ROUND_COST + 2 * SEARCH_COST)
    assert prompt == 2 * ROUND_PROMPT
    assert cached == 2 * ROUND_CACHED


def test_a_search_whose_cost_went_unsaid_makes_the_turns_cost_unknown(client, openrouter):
    """The reader's rule (2026-10-02): a price nobody said makes the turn's
    cost unknown, never smaller. The tokens keep their own rule."""
    openrouter.search = lambda body: httpx.Response(
        200, json=_answer(_cited("https://one.example/a", "A page"), cost=None)
    )
    openrouter.script = [_searches_for(QUERY), _says("Ecco.")]

    events = _ask(client, QUESTION, OPUS)

    prompt, _, cost, _ = _stored(events)
    assert cost is None
    assert prompt == 2 * ROUND_PROMPT


def test_a_search_that_got_no_answer_makes_the_turns_cost_unknown(client, openrouter):
    """No answer, no price: whether the search was charged is not known."""
    openrouter.search = lambda body: httpx.Response(
        500, json={"error": {"message": "Internal error", "code": 500}}
    )
    openrouter.script = [_searches_for(QUERY), _says("La ricerca non ha risposto.")]

    events = _ask(client, QUESTION, OPUS)

    _, _, cost, _ = _stored(events)
    assert cost is None


def test_the_search_count_is_read_where_openrouter_puts_it():
    """Under `server_tool_use_details`, where both paid probes found it (a
    stream on 2026-10-06, a search's answer on 2026-10-09), or under the
    `server_tool_use` OpenRouter's documentation names."""

    class Measured:
        prompt_tokens = 3213
        prompt_tokens_details = None
        cost = 0.007324545
        server_tool_use_details = {"web_search_requests": 1, "tool_calls_executed": 1}

    class Documented:
        prompt_tokens = 3213
        prompt_tokens_details = None
        cost = 0.007324545
        server_tool_use = {"web_search_requests": 2}

    class Silent:
        prompt_tokens = 100
        prompt_tokens_details = None
        cost = 0.001

    assert advisor._usage(Measured()).searches == 1
    assert advisor._usage(Documented()).searches == 2
    assert advisor._usage(Silent()).searches is None


# --- The prompt ------------------------------------------------------------------------


def test_the_web_rules_go_to_the_models_offered_the_web_and_no_other(client, openrouter):
    openrouter.script = [_says("Ciao."), _says("Ciao.")]
    _ask(client, "Ciao", OPUS)
    _ask(client, "Ciao", OTHERS[0])
    opus, other = openrouter.asked
    system = opus["messages"][0]["content"]
    assert chat.WEB_RULES in (system[0]["text"] if isinstance(system, list) else system)
    assert other["messages"][0]["content"] == chat.SYSTEM_PROMPT
    assert "search the web" not in chat.SYSTEM_PROMPT


def test_the_web_rules_say_when_to_search_and_how_a_page_is_used():
    """When (news, comparisons, what the records, the catalogue and Yahoo
    lack) and when not (what the picture or the catalogue answers); by which
    tool, unasked, several at once; never the reader in a query; every claim
    from a page with its link, and a figure only with it; the web finds and a
    card verifies. Short, because the prompt goes out on every turn."""
    rules = chat.WEB_RULES
    assert "`search_web`" in rules
    assert "news, recent performance" in rules
    assert "Never for what the picture or the catalogue answers" in rules
    assert "Never put their figures, names or anything else about them in a query" in rules
    assert "run it unasked, and several in one round when you need several" in rules
    assert "carries its link, as [title](url)" in rules
    assert "a figure from a page is stated with its link or not at all" in rules
    assert "The web finds; it does not verify" in rules
    assert "gets no card, and you say why" in rules
    assert len(rules) < 1000


def test_reading_is_no_longer_said_to_cost_nothing():
    """A search costs a little, so the sentence that said reading costs them
    no money is gone; reading still needs no permission."""
    for prompt in (chat.SYSTEM_PROMPT, chat.system_prompt(OPUS)):
        assert "cost them no money" not in prompt
        assert "never ask whether to run one: run it" in prompt


def test_no_dash_in_what_the_chat_reads():
    """The reader, 2026-10-06: what the chat reads loses its em dashes, "since
    the model writes in the style it reads". The search's declaration, its
    instruction and what it says when it did not run are new text the model
    reads, and the last also reaches the reader, under the search's line. The
    one em dash and the one spaced en dash left are in `advisor.NO_DASHES`,
    which shows the two characters it forbids."""
    em, en = chr(0x2014), " " + chr(0x2013) + " "

    def clean(text: str) -> bool:
        return em not in text and en not in text

    for prompt in (chat.SYSTEM_PROMPT, chat.system_prompt(OPUS)):
        assert prompt.count(advisor.NO_DASHES) == 1
        assert clean(prompt.replace(advisor.NO_DASHES, ""))
    assert clean(chat.LAST_TOOL_ROUND_NOTICE) and clean(chat.SEARCHES_SPENT)
    assert clean(websearch.INSTRUCTION)
    assert clean(json.dumps(tools.declarations() + tools.web_search(OPUS), ensure_ascii=False))
    for reading in (tools._READING, tools._CATALOGUE_READING, tools._LOOKUP_READING):
        assert all(clean(line) for line in reading)
    for found in (
        websearch.Search(query="q", failure="it took longer than 30 seconds"),
        websearch.Search(query="q"),
    ):
        assert clean(websearch.outcome(found)["error"])
