"""The web search, run by the app as a request of its own.

Brief AM (2026-10-09). The chat used to declare OpenRouter's search on every
request it sent (brief AG), and OpenRouter ran the search inside the chat's own
call. Brief AL's paid probe P1 (2026-10-08) found what that cost: on a request
that declares the search, OpenRouter keeps only the end-of-request cache
marker, so no turn read the one before it from the cache, and every question
to Opus paid for its whole prompt again. So the search is a tool of the app's
now (`tools.SEARCH_WEB`), no request of the chat declares OpenRouter's, and
this module runs a search when the chat's model asks for one.

One search is one request to OpenRouter, with the reader's key, carrying the
query and nothing else: no picture, no records, no question, no conversation.
Still a request to a MODEL, because OpenRouter runs its search only on behalf
of one: its pages (read 2026-10-09) give the web plugin and the `:online`
suffix as deprecated, and no endpoint runs a server tool alone. So a small
model is told to run exactly one search with the query it is given, and what
the app keeps is what OpenRouter hands back from the search itself: the pages,
as `url_citation` annotations, each with an excerpt. The model's own words are
not read.

The model is Claude Haiku 5.5. Anthropic's, because Anthropic already receives
the whole conversation from the chat, so no company that does not already see
the reader's questions sees their queries (Exa, which runs the search, already
did); the cheapest of that family by a factor of ten ($0.10 and $0.50 per
million tokens on OpenRouter's list, 2026-10-09); and it reads nothing but the
query, so a search can carry nothing of the reader that the chat's model did
not put in it.

Measured before the rest was built (brief AM's P1, paid, 2026-10-09): three
queries, one search each, five pages each with excerpts of 128 to 627
characters, 3.5 to 4.4 seconds and $0.0073 to $0.0074 a search, of which
$0.007 is Exa's fee and the rest Haiku's tokens; the key was charged what each
answer reported. No answer carries the query the model searched for, so what
the reader is shown is the query the app sent.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from app import advisor

SEARCH_MODEL = "anthropic/claude-haiku-5.5"

# Exa, five pages a search, each excerpt at most a thousand characters of Exa's
# highlights (the passages of a page closest to the query). Exa because it
# hands back every page it found with an excerpt, which is what the reader is
# shown and the chat's model reads (brief AG's probe, 2026-10-06), at $0.007 a
# search, which is what the key was charged in brief AM's P1. A thousand
# characters is what brief AG passed on between rounds, and the model cited
# figures from it.
#
# One search a request, asked twice over: `max_uses` in the tool, and the
# request's `max_tool_calls`, OpenRouter's own budget of server-tool steps (30
# unless set). Brief AG saw two searches run in one batch under `max_uses: 1`,
# so how many ran is read from each answer (`Search.ran`), never assumed.
# `parallel_tool_calls` is not sent: no endpoint of the model lists it.
SERVER_TOOL = {
    "type": "openrouter:web_search",
    "parameters": {"engine": "exa", "max_results": 5, "max_uses": 1, "max_characters": 1000},
}

INSTRUCTION = (
    "You run one web search for an app. Call the web search exactly once, with "
    "the user's message as the query, word for word. Then reply with the single "
    "word: done."
)

# Room for the call and the one word after it, with the reasoning Haiku 5.5
# does by default kept low (it used none in P1). A ceiling: at $0.50 per
# million, $0.0005.
MAX_TOKENS = 1024

# How long a search may take before the app gives up on it. And no retry: a
# retried search is a second search, paid for, that nobody asked for.
TIMEOUT_SECONDS = 30

# How long a page's title may be, as kept and shown. A title is a label for a
# link; brief AG's probe's longest was 55 characters.
_TITLE_CHARS = 200


@dataclass(frozen=True)
class WebPage:
    """One page a search found: its address, its title and an excerpt of what
    it says, as OpenRouter hands it over in a `url_citation` annotation."""

    url: str
    title: str
    excerpt: str


@dataclass(frozen=True)
class Search:
    """One search, as it went.

    `ran` is how many searches the request ran: what OpenRouter's answer says,
    and when it says nothing, one if pages came back and none if they did not.
    `usage` is what the request read and cost, None when no answer came back,
    and then what it cost is not known. `failure` says why no answer could be
    read, None when one could."""

    query: str
    pages: tuple[WebPage, ...] = ()
    ran: int = 0
    usage: advisor.Usage | None = None
    failure: str | None = None


def request(query: str) -> dict:
    """The request one search sends, as `chat.completions.create` takes it:
    the instruction and the query, the search, and nothing else."""
    return {
        "model": SEARCH_MODEL,
        "messages": [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": query},
        ],
        "tools": [SERVER_TOOL],
        "max_tokens": MAX_TOKENS,
        # Not parameters the SDK knows, so they travel in extra_body, which it
        # merges into the request as it is.
        "extra_body": {"max_tool_calls": 1, "reasoning": {"effort": "low"}},
    }


def _page(annotation) -> WebPage | None:
    """The page one annotation names, or None when it is not a `url_citation`
    or its address is not http or https.

    What is kept here becomes a link the reader can press, so the scheme is
    checked where it enters: an address a page or a model made up as
    `javascript:` is not a page, and neither is anything else a browser would
    run or hand to another program. A page with no title is named by its host,
    which is what its link would show anyway."""
    found = annotation if isinstance(annotation, dict) else annotation.model_dump()
    if found.get("type") != "url_citation":
        return None
    cited = found.get("url_citation") or {}
    url = str(cited.get("url") or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    title = " ".join(str(cited.get("title") or "").split())[:_TITLE_CHARS]
    return WebPage(
        url=url,
        title=title or parts.netloc,
        excerpt=str(cited.get("content") or "").strip(),
    )


def _pages(completion) -> tuple[WebPage, ...]:
    """Every page the answer names, once each, in the order it names them."""
    choice = completion.choices[0] if completion.choices else None
    message = getattr(choice, "message", None)
    seen: set[str] = set()
    pages = []
    for annotation in getattr(message, "annotations", None) or ():
        page = _page(annotation)
        if page is not None and page.url not in seen:
            seen.add(page.url)
            pages.append(page)
    return tuple(pages)


def _failed(error: Exception) -> str:
    """Why a search got no answer, in words the chat's model and the reader
    both read."""
    openai = advisor.sdk()
    if isinstance(error, openai.APITimeoutError):
        return f"it took longer than {TIMEOUT_SECONDS} seconds"
    if isinstance(error, openai.APIConnectionError):
        return "OpenRouter could not be reached"
    if isinstance(error, openai.APIStatusError):
        body = error.body if isinstance(error.body, dict) else {}
        said = str(body.get("message") or error.message).strip().rstrip(".")
        return f"OpenRouter refused it with {error.status_code}: {said}"
    if isinstance(error, advisor.AdvisorError):
        return str(error).rstrip(".")
    return f"it failed before an answer came back ({type(error).__name__})"


def search(query: str) -> Search:
    """Run one web search for `query` and say how it went. Never raises: a
    search that could not run is a `Search` whose `failure` says why."""
    try:
        client = advisor._client().with_options(max_retries=0, timeout=TIMEOUT_SECONDS)
        completion = client.chat.completions.create(**request(query))
    except Exception as exc:
        return Search(query=query, failure=_failed(exc))
    reported = getattr(completion, "usage", None)
    usage = advisor._usage(reported) if reported else None
    # OpenRouter's documented answer to a provider failing partway: a 200 whose
    # body holds an `error` object (see `advisor._failed_partway`).
    broke = getattr(completion, "error", None)
    if broke:
        said = broke.get("message") if isinstance(broke, dict) else getattr(broke, "message", None)
        return Search(
            query=query,
            usage=usage,
            failure="the provider failed partway" + (f": {said}" if said else ""),
        )
    pages = _pages(completion)
    counted = usage.searches if usage is not None else None
    return Search(
        query=query,
        pages=pages,
        ran=counted if counted is not None else (1 if pages else 0),
        usage=usage,
    )


def outcome(found: Search) -> dict:
    """What the chat's model reads back from one search: the pages it found,
    each with its title, its address and its excerpt; or why there are none.

    A search that got no answer, or whose answer says no search ran, is told
    as one that did not run, and never as one that found nothing: "nothing
    found" is a claim about the web, and nobody asked the web anything (the
    reader's rule, through the reviewer, 2026-10-09)."""
    if found.failure is not None:
        return {
            "ok": False,
            "error": (
                f'The search for "{found.query}" got no answer ({found.failure}), '
                "so this says nothing about what the web holds."
            ),
        }
    if found.ran < 1:
        return {
            "ok": False,
            "error": (
                f'The search for "{found.query}" did not run: OpenRouter reported no '
                "search, so this says nothing about what the web holds."
            ),
        }
    return {
        "ok": True,
        "result": {
            "query": found.query,
            "pages": [
                {"title": page.title, "url": page.url, "excerpt": page.excerpt}
                for page in found.pages
            ],
        },
    }
