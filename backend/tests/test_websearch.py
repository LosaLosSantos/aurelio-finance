"""The bounded, record-free web retrieval result returned to the chat."""

from __future__ import annotations

from app import copilot_provider, websearch


def test_search_keeps_valid_unique_sources_and_copilot_usage(monkeypatch):
    seen: list[tuple[str, str]] = []

    def search(query: str, model: str) -> copilot_provider.WebResult:
        seen.append((query, model))
        return copilot_provider.WebResult(
            pages=(
                {"url": "https://example.com/report", "title": "  Annual   report  ", "excerpt": "Facts."},
                {"url": "javascript:alert(1)", "title": "Unsafe", "excerpt": "No."},
                {"url": "https://example.com/report", "title": "Duplicate", "excerpt": "No."},
            ),
            usage=copilot_provider.Usage(321, 45),
        )

    monkeypatch.setenv("COPILOT_SEARCH_MODEL", "claude-haiku-5.5")
    monkeypatch.setattr(copilot_provider, "search_web", search)

    found = websearch.search("example annual report")

    assert seen == [("example annual report", "claude-haiku-5.5")]
    assert found.pages == (
        websearch.WebPage("https://example.com/report", "Annual report", "Facts."),
    )
    assert found.ran == 1
    assert found.usage == websearch.advisor.Usage(321, 45, None, searches=1)
    assert websearch.outcome(found)["result"]["pages"] == [
        {"url": "https://example.com/report", "title": "Annual report", "excerpt": "Facts."}
    ]


def test_search_failure_is_returned_as_data(monkeypatch):
    def fail(query: str, model: str):
        raise copilot_provider.CopilotError("GitHub Copilot web search failed")

    monkeypatch.setattr(copilot_provider, "search_web", fail)

    found = websearch.search("latest rate decision")

    assert found.ran == 0 and found.pages == ()
    assert websearch.outcome(found) == {
        "ok": False,
        "error": (
            'The search for "latest rate decision" got no answer '
            "(GitHub Copilot web search failed), so this says nothing about what the web holds."
        ),
    }
