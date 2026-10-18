"""A model the app is about to call is said before the call fails, wherever it
is set: which model, when, where it is set and how to change it.

Brief BB. OpenRouter's public list dates some models for removal, and the app
reads it once a day (`model_list`). The chat panel says, above the question
box, the model the next question goes to and the web search's when that model
searches; the analysis's card says the models a run would call. The reader's
choices, 2026-10-17: there (D1 (a)), from 30 days before the list's date (D2
(b)); a day already past, or a model the list lacks, always; "no longer
listed", never "gone", since a name that had left the list was seen still
answering (2026-09-24). OpenRouter names no successor for a dated model (P0),
so nothing is said in its place.

The list is faked as in `test_the_list_of_models_is_read_once_a_day.py`, with
the reader's day 2026-10-17; the models are the app's own and the dates
invented. No model is called: the three ways the app calls one are refused
and counted.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import advisor, model_list, tools
from app.database import SessionLocal
from app.main import app
from tests.test_the_list_of_models_is_read_once_a_day import (  # noqa: F401 (a fixture)
    OPUS,
    SONNET,
    _settled,
    the_list,
)

HAIKU = "anthropic/claude-haiku-5.5"
QWEN = "qwen/qwen3.8-max-0902"

SET_BY = "It is set by {} in backend/.env, where another model takes its place once the app starts again."
BUILT_IN = (
    "It is the app's built-in default (DEFAULT_MODEL in backend/app/advisor.py); "
    "OPENROUTER_MODEL in backend/.env sets another once the app starts again."
)
PICKED = "It is picked in the menu under the question, where another can be picked."
SEARCH_SET = "It is set in the app's code (SEARCH_MODEL in backend/app/websearch.py)."


def dated(model: str, day: str) -> str:
    return f"OpenRouter may retire {model} after {day}, the date its list of models gives."


@pytest.fixture(autouse=True)
def no_model_is_called(monkeypatch):
    """Saying it calls no model: every way the app calls one is refused, and
    counted."""
    called: list[str] = []

    def refuse(name):
        def call(*args, **kwargs):
            called.append(name)
            raise AssertionError(f"{name} was called")

        return call

    for name in ("call_llm", "call_round", "stream_llm"):
        monkeypatch.setattr(advisor, name, refuse(name))
    yield
    assert called == []


def _menu(the_list, dates: dict[str, str | None] | None = None) -> dict:
    """The menu as the panel gets it, after the app's start read the list
    with `dates` laid over the faked one."""
    the_list.dates.update(dates or {})
    with TestClient(app) as client:
        _settled()
        response = client.get("/api/chat/models")
    assert response.status_code == 200, response.text
    return response.json()


def _entry(menu: dict, slug: str) -> dict:
    return next(m for m in menu["models"] if m["slug"] == slug)


def _card(the_list, dates: dict[str, str | None] | None = None) -> dict:
    """The analysis's card as drawn, after the app's start read the list."""
    the_list.dates.update(dates or {})
    with TestClient(app):
        _settled()
        with SessionLocal() as db:
            drawn = tools.answer(db, advisor.ToolCall(id="call_1", name="run_analysis", arguments="{}"))
    return drawn["card"]


# --- The chat panel: the model a question goes to -------------------------------------


def test_a_dated_model_set_in_env_is_said_before_the_question(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", SONNET)

    menu = _menu(the_list)

    default = _entry(menu, SONNET)
    assert menu["default"] == SONNET
    assert default["warning"] == dated(SONNET, "2026-10-31") + " " + SET_BY.format("OPENROUTER_MODEL")
    assert default["searches"] is True
    assert menu["search_warning"] is None


def test_the_variable_in_force_for_the_chat_is_the_one_named(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", SONNET)
    monkeypatch.setenv("OPENROUTER_MODEL", OPUS)

    menu = _menu(the_list)

    assert _entry(menu, SONNET)["warning"] == dated(SONNET, "2026-10-31") + " " + SET_BY.format(
        "OPENROUTER_CHAT_MODEL"
    )


def test_a_model_set_in_env_that_the_list_lacks_is_said_with_its_dated_versions(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "qwen/qwen3.8-max")

    menu = _menu(the_list)

    assert _entry(menu, "qwen/qwen3.8-max")["warning"] == (
        "OpenRouter's list of models no longer has qwen/qwen3.8-max, so a call to it may be refused. "
        + SET_BY.format("OPENROUTER_CHAT_MODEL")
        + " OpenRouter still lists qwen/qwen3.8-max-0902, a dated version of it."
    )


def test_the_built_in_default_is_said_as_built_in(the_list, monkeypatch):
    # The analyst's variable naming the same model changes nothing for the
    # chat, which takes the built-in default: only that is named.
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", OPUS)

    menu = _menu(the_list, {OPUS: "2026-11-01"})

    assert menu["default"] == OPUS
    assert _entry(menu, OPUS)["warning"] == dated(OPUS, "2026-11-01") + " " + BUILT_IN


def test_a_model_picked_from_the_menu_is_said_as_a_pick(the_list):
    menu = _menu(the_list)

    assert _entry(menu, SONNET)["warning"] == dated(SONNET, "2026-10-31") + " " + PICKED
    assert _entry(menu, OPUS)["warning"] is None


def test_a_menu_model_the_list_lacks_is_said_as_a_pick_that_may_be_refused(the_list):
    menu = _menu(the_list)

    assert _entry(menu, "moonshotai/kimi-k2.6")["warning"] == (
        "OpenRouter's list of models no longer has moonshotai/kimi-k2.6, so a call to it may be "
        "refused. " + PICKED
    )


def test_a_date_is_said_from_30_days_before_it_and_shown_in_the_menu_from_the_first(the_list):
    assert model_list.WARN_DAYS == 30  # the reader's D2 (b), 2026-10-17

    menu = _menu(the_list, {SONNET: "2026-11-16", QWEN: "2026-11-17"})

    # 2026-11-16 is 30 days after 2026-10-17, and 2026-11-17 is 31.
    assert _entry(menu, SONNET)["warning"] == dated(SONNET, "2026-11-16") + " " + PICKED
    assert _entry(menu, QWEN)["warning"] is None
    assert _entry(menu, QWEN)["retires"] == "2026-11-17"


def test_a_day_already_past_is_said_whatever_the_day(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", SONNET)

    menu = _menu(the_list, {SONNET: "2026-10-10"})

    assert _entry(menu, SONNET)["warning"] == (
        "OpenRouter's list of models dated anthropic/claude-sonnet-4.6 for removal after "
        "2026-10-10, so it may stop serving it at any time. " + SET_BY.format("OPENROUTER_MODEL")
    )


def test_the_search_model_is_said_with_the_models_that_search(the_list):
    menu = _menu(the_list, {HAIKU: "2026-10-20"})

    assert menu["search_warning"] == (
        "The web searches run on anthropic/claude-haiku-5.5, which OpenRouter may retire after "
        "2026-10-20. " + SEARCH_SET
    )
    assert _entry(menu, OPUS)["searches"] is True
    assert _entry(menu, "openai/gpt-6.1-sol-pro")["searches"] is False


def test_a_search_model_the_list_lacks_is_said(the_list):
    del the_list.dates[HAIKU]

    menu = _menu(the_list)

    assert menu["search_warning"] == (
        "The web searches run on anthropic/claude-haiku-5.5, which OpenRouter's list of models no "
        "longer has, so a search may be refused. " + SEARCH_SET
    )


def test_without_a_list_today_nothing_is_said(the_list, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENROUTER_MODEL", SONNET)

    menu = _menu(the_list)

    assert the_list.asked == 0
    assert all(m["warning"] is None for m in menu["models"])
    assert menu["search_warning"] is None


# --- The analysis's card: the models a run would call ------------------------------------


def test_the_analysis_card_says_a_dated_role_model_and_where_it_is_set(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", SONNET)

    card = _card(the_list)

    assert card["warning"] == dated(SONNET, "2026-10-31") + " " + SET_BY.format("OPENROUTER_ANALYST_MODEL")


def test_one_model_in_both_seats_is_said_once(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", SONNET)

    card = _card(the_list)

    assert card["warning"] == dated(SONNET, "2026-10-31") + " " + SET_BY.format("OPENROUTER_MODEL")


def test_one_model_set_for_each_seat_names_both_variables(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", SONNET)
    monkeypatch.setenv("OPENROUTER_CONFIDANT_MODEL", SONNET)

    card = _card(the_list)

    assert card["warning"] == dated(SONNET, "2026-10-31") + " " + SET_BY.format(
        "OPENROUTER_ANALYST_MODEL and OPENROUTER_CONFIDANT_MODEL"
    )


def test_one_model_from_a_variable_and_built_in_says_both(the_list, monkeypatch):
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", OPUS)

    card = _card(the_list, {OPUS: "2026-11-01"})

    assert card["warning"] == (
        dated(OPUS, "2026-11-01") + " " + SET_BY.format("OPENROUTER_ANALYST_MODEL") + " " + BUILT_IN
    )


def test_the_analysis_card_says_the_search_model_when_the_analyst_searches(the_list, monkeypatch):
    card = _card(the_list, {HAIKU: "2026-10-20"})
    assert card["warning"] == (
        "The web searches run on anthropic/claude-haiku-5.5, which OpenRouter may retire after "
        "2026-10-20. " + SEARCH_SET
    )

    # An analyst that does not search does not say the search's model.
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", QWEN)
    assert _card(the_list)["warning"] == ""


def test_the_analysis_card_says_nothing_when_nothing_is_dated(the_list):
    card = _card(the_list)

    assert card["warning"] == ""
    assert "OpenRouter may retire" not in card["consequence"]


def test_the_analysis_card_says_nothing_without_a_list_today(the_list, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENROUTER_MODEL", SONNET)

    assert _card(the_list)["warning"] == ""
    assert the_list.asked == 0
