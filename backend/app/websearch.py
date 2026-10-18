"""Bounded web retrieval through GitHub Copilot SDK's isolated web-fetch tool."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from app import advisor, copilot_provider

SEARCH_MODEL = "claude-haiku-5.5"
_TITLE_CHARS = 200


@dataclass(frozen=True)
class WebPage:
    """One fetched source page shown to the reader and the answering model."""

    url: str
    title: str
    excerpt: str


@dataclass(frozen=True)
class Search:
    """One search, including its sources, token usage, and any failure."""

    query: str
    pages: tuple[WebPage, ...] = ()
    ran: int = 0
    usage: advisor.Usage | None = None
    failure: str | None = None


def _page(found: dict[str, str]) -> WebPage | None:
    """Validate a model-returned source before it becomes a clickable link."""
    url = str(found.get("url") or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    title = " ".join(str(found.get("title") or "").split())[:_TITLE_CHARS]
    return WebPage(
        url=url,
        title=title or parts.netloc,
        excerpt=str(found.get("excerpt") or "").strip(),
    )


def search(query: str) -> Search:
    """Run one Copilot-backed web search. Failures are data, never exceptions."""
    try:
        result = copilot_provider.search_web(query, SEARCH_MODEL)
    except copilot_provider.CopilotError as exc:
        return Search(query=query, failure=str(exc).rstrip("."))

    seen: set[str] = set()
    pages: list[WebPage] = []
    for found in result.pages:
        page = _page(found)
        if page is not None and page.url not in seen:
            seen.add(page.url)
            pages.append(page)
    usage = advisor.Usage(
        prompt_tokens=result.usage.input_tokens,
        cached_tokens=result.usage.cached_tokens,
        cost=None,
        searches=1,
    )
    return Search(query=query, pages=tuple(pages), ran=1, usage=usage)


def outcome(found: Search) -> dict:
    """What the chat model reads back from one search."""
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
                f'The search for "{found.query}" did not run, so this says nothing '
                "about what the web holds."
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
