"""OpenRouter's public list of models is read once a day, and the chat's menu
says what it says of each model.

The list dates some models for removal ("the date after which the model may
be removed", its API reference): on 2026-10-17, 17 of its 470 entries, 3 to 75
days ahead. Until brief BB the app read it only after OpenRouter had refused a
call. Now it reads it once a reader's day, in the background, with no key and
nothing of the reader's in the request, and the menu says each model's date
beside its name, and whether the list still has it.

The list is faked where the app meets it, `advisor._fetch_model_list`, and every
ask is counted; the reader's day is moved with `dated.today`. One test runs the
real helper with httpx's transport captured instead, to read what is sent.
The models are the menu's own and the dates invented.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import advisor, dated, model_list, models
from app.database import SessionLocal
from app.main import app
from tests.test_a_model_that_is_gone import GONE, _chat_error, openrouter  # noqa: F401 (a fixture)

# The real helper, taken before conftest's `offline` replaces it in every test.
REAL_FETCH_MODEL_LIST = advisor._fetch_model_list

DAY, NEXT_DAY = "2026-10-17", "2026-10-18"
OPUS = "anthropic/claude-opus-5.5"
SONNET = "anthropic/claude-sonnet-4.6"
KIMI_K26 = "moonshotai/kimi-k2.6"

# The list as faked: the menu's models but one, Sonnet 4.6 dated.
LISTED = {
    OPUS: None,
    SONNET: "2026-10-31",
    "openai/gpt-6.1-sol-pro": None,
    "qwen/qwen3.8-max-0902": None,
    "moonshotai/kimi-k3": None,
    "anthropic/claude-haiku-5.5": None,
}


class OpenRouterList:
    """What `advisor._fetch_model_list` answers: `dates`, unless it `fails`;
    held on `hold` when one is set, for a read that takes its time. Every ask
    is counted."""

    def __init__(self) -> None:
        self.dates: dict[str, str | None] = dict(LISTED)
        self.asked = 0
        self.fails: Exception | None = None
        self.hold: threading.Event | None = None

    def fetch(self) -> dict[str, str | None]:
        self.asked += 1
        if self.hold is not None:
            self.hold.wait(timeout=5)
        if self.fails is not None:
            raise self.fails
        return dict(self.dates)


@pytest.fixture()
def the_list(monkeypatch) -> OpenRouterList:
    """The list faked, a key set (there is no read without one), the four
    variables empty, and the reader's day `DAY`. Asked for before `client`, so
    the read the app starts with meets the fake."""
    fake = OpenRouterList()
    monkeypatch.setattr(advisor, "_fetch_model_list", fake.fetch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "invalid")
    for var in advisor.MODEL_VARIABLES:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(dated, "today", lambda: DAY)
    return fake


def _settled() -> None:
    """Wait for every read of the list this process has started."""
    for thread in threading.enumerate():
        if thread.name == model_list.THREAD_NAME:
            thread.join(timeout=5)


def _menu(client) -> dict[str, dict]:
    response = client.get("/api/chat/models")
    assert response.status_code == 200, response.text
    return {entry["slug"]: entry for entry in response.json()["models"]}


def _says_nothing(menu: dict[str, dict]) -> None:
    for entry in menu.values():
        assert entry["retires"] is None and entry["listed"] is None, entry


# --- The menu says it ------------------------------------------------------------


def test_a_model_the_list_dates_reads_its_date_in_the_menu(the_list, client):
    _settled()
    menu = _menu(client)

    assert menu[SONNET]["retires"] == "2026-10-31"
    assert menu[SONNET]["listed"] is True
    assert menu[OPUS]["retires"] is None
    assert menu[OPUS]["listed"] is True
    assert the_list.asked == 1


def test_a_model_the_list_lacks_stays_offered_and_marked(the_list, client, monkeypatch):
    # Not hidden: a name that had left the list was seen still answering
    # (2026-09-24), so the list's say-so alone takes no choice away.
    monkeypatch.setenv("OPENROUTER_ANALYST_MODEL", "qwen/qwen3.8-max")
    _settled()
    menu = _menu(client)

    assert menu[KIMI_K26]["listed"] is False
    assert menu[KIMI_K26]["retires"] is None
    assert menu["qwen/qwen3.8-max"]["listed"] is False
    assert menu["qwen/qwen3.8-max"]["note"] == "your analyst model"


def test_a_routing_variant_reads_what_the_list_says_of_its_model(the_list, client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", SONNET + ":nitro")
    _settled()
    body = client.get("/api/chat/models").json()

    assert body["default"] == SONNET + ":nitro"
    first = body["models"][0]
    assert first["slug"] == SONNET + ":nitro"
    assert first["retires"] == "2026-10-31" and first["listed"] is True


def test_a_date_that_is_not_one_is_no_date(the_list):
    the_list.dates[OPUS] = "soon"
    with TestClient(app) as client:
        _settled()
        menu = _menu(client)

    assert menu[OPUS]["retires"] is None and menu[OPUS]["listed"] is True
    assert menu[SONNET]["retires"] == "2026-10-31"


# --- Once a day --------------------------------------------------------------------


def test_the_list_is_asked_once_a_day(the_list, monkeypatch):
    with TestClient(app) as client:
        _settled()
        _menu(client)
        _menu(client)
        assert the_list.asked == 1

    # Started again the same day: the day is claimed in `settings`, and the
    # read kept there is the day's.
    model_list._forget()
    with TestClient(app) as client:
        _settled()
        assert _menu(client)[SONNET]["retires"] == "2026-10-31"
        assert the_list.asked == 1

        # The next day, the app still running: its first request starts the
        # day's read.
        monkeypatch.setattr(dated, "today", lambda: NEXT_DAY)
        _menu(client)
        _settled()
        assert _menu(client)[SONNET]["retires"] == "2026-10-31"
        assert the_list.asked == 2
    with SessionLocal() as db:
        assert db.get(models.Setting, model_list.ASKED_ON).value == NEXT_DAY


def test_a_new_days_first_request_is_answered_without_waiting_for_its_read(the_list, client, monkeypatch):
    _settled()
    assert _menu(client)[SONNET]["retires"] == "2026-10-31"

    monkeypatch.setattr(dated, "today", lambda: NEXT_DAY)
    # Yesterday's read is not today's: nothing is said until today's is back.
    _says_nothing(_menu(client))
    _settled()
    assert _menu(client)[SONNET]["retires"] == "2026-10-31"
    assert the_list.asked == 2


def test_an_outage_is_said_nowhere_and_not_asked_again_that_day(the_list, monkeypatch, caplog):
    the_list.fails = httpx.ConnectError("no route to host")
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            _settled()
            _says_nothing(_menu(client))
            _says_nothing(_menu(client))
        model_list._forget()
        with TestClient(app) as client:  # started again, the same day
            _settled()
            _says_nothing(_menu(client))
    assert the_list.asked == 1
    said = [r.getMessage() for r in caplog.records]
    assert not [s for s in said if "OpenRouter" in s or "no route to host" in s], said

    # The next day asks again, and what it reads is said.
    the_list.fails = None
    monkeypatch.setattr(dated, "today", lambda: NEXT_DAY)
    with TestClient(app) as client:
        _settled()
        assert _menu(client)[SONNET]["retires"] == "2026-10-31"
    assert the_list.asked == 2


def test_a_body_that_is_not_the_list_is_an_outage(the_list):
    the_list.fails = KeyError("data")
    with TestClient(app) as client:
        _settled()
        _says_nothing(_menu(client))
    assert the_list.asked == 1


def test_a_read_kept_from_another_day_is_not_used(the_list):
    with SessionLocal() as db:
        db.add(models.Setting(key=model_list.ASKED_ON, value="2026-10-16"))
        kept = {"day": "2026-10-16", "models": {SONNET: "2026-10-20"}}
        db.add(models.Setting(key=model_list.KEPT, value=json.dumps(kept)))
        db.commit()
    the_list.fails = httpx.ConnectError("no route to host")

    with TestClient(app) as client:
        _settled()
        _says_nothing(_menu(client))
    assert the_list.asked == 1


def test_the_menu_answers_while_the_read_is_held(the_list):
    the_list.hold = threading.Event()
    try:
        with TestClient(app) as client:
            started = time.perf_counter()
            menu = _menu(client)
            took = time.perf_counter() - started
            _says_nothing(menu)
            assert took < 1.0, f"the menu waited {took:.2f}s for the list"
            the_list.hold.set()
            _settled()
            assert _menu(client)[SONNET]["retires"] == "2026-10-31"
    finally:
        the_list.hold.set()
    assert the_list.asked == 1


def test_without_a_key_the_list_is_never_asked(the_list, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with TestClient(app) as client:
        _settled()
        _says_nothing(_menu(client))
        _says_nothing(_menu(client))
    assert the_list.asked == 0


def test_building_the_demo_reads_no_list(monkeypatch, tmp_path):
    """The demo calls no model, so it reads no list of them. `start.ps1 -Demo`
    builds it in a process of its own before the server starts: a read begun
    there would claim the day in the demo's `settings` and could die with that
    process, leaving the server nothing to say that day. The build runs as
    `test_demo_data.py` runs it, every outside connection refused, with a key."""
    from tests.test_demo_data import _command

    monkeypatch.setenv("OPENROUTER_API_KEY", "invalid")
    path = tmp_path / "demo.db"

    built = _command("--path", str(path))

    assert built.returncode == 0, built.stderr
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        kept = {key for (key,) in con.execute("select key from settings")}
    finally:
        con.close()
    assert model_list.ASKED_ON not in kept and model_list.KEPT not in kept


# --- After a refusal -----------------------------------------------------------------


def test_the_read_after_a_refusal_is_the_days_copy(the_list, openrouter, monkeypatch):
    # No key in the environment (the fake client carries its own): the app
    # reads nothing at its start, so the one ask is the refusal's, as
    # `2ba7466` has it.
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with TestClient(app) as client:
        sentence = _chat_error(client)
        assert sentence.startswith(f"The model {GONE} is no longer served by OpenRouter"), sentence
        assert the_list.asked == 1
        menu = _menu(client)
        assert menu[SONNET]["retires"] == "2026-10-31"
        assert menu[GONE]["listed"] is False
    _settled()
    assert the_list.asked == 1

    # Kept as the day's in `settings`, so a start the same day asks nothing.
    model_list._forget()
    monkeypatch.setenv("OPENROUTER_API_KEY", "invalid")
    with TestClient(app) as client:
        _settled()
        assert _menu(client)[SONNET]["retires"] == "2026-10-31"
    assert the_list.asked == 1


# --- What is sent -------------------------------------------------------------------


def test_nothing_of_the_readers_is_in_the_request(monkeypatch):
    """The real helper, with httpx's transport captured: what it sends is one
    GET of the list's address and httpx's own five headers. A planted key and a
    planted value in each of the four variables appear nowhere in it."""
    planted = {
        "OPENROUTER_API_KEY": "sk-or-v1-planted-key-0123456789",
        "OPENROUTER_MODEL": "planted/the-default-model",
        "OPENROUTER_CHAT_MODEL": "planted/the-chat-model",
        "OPENROUTER_ANALYST_MODEL": "planted/the-analyst-model",
        "OPENROUTER_CONFIDANT_MODEL": "planted/the-confidant-model",
    }
    for var, value in planted.items():
        monkeypatch.setenv(var, value)
    sent: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        sent.append(request)
        body = {"data": [{"id": "planted/the-default-model", "expiration_date": "2026-10-31"}]}
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
    monkeypatch.setattr(advisor, "_fetch_model_list", REAL_FETCH_MODEL_LIST)
    monkeypatch.setattr(dated, "today", lambda: DAY)

    model_list.start_if_due()
    _settled()

    assert len(sent) == 1
    request = sent[0]
    assert request.method == "GET"
    assert str(request.url) == advisor.MODEL_LIST_URL == "https://openrouter.ai/api/v1/models"
    assert request.url.query == b""
    assert request.content == b""
    assert sorted(request.headers.keys()) == ["accept", "accept-encoding", "connection", "host", "user-agent"]
    assert request.headers["user-agent"].startswith("python-httpx/")
    everything = str(request.url) + "".join(f"{k}{v}" for k, v in request.headers.items())
    for var, value in planted.items():
        assert value not in everything, var
    # And what came back is the day's read.
    with SessionLocal() as db:
        assert model_list.known(db).retires("planted/the-default-model") == "2026-10-31"
