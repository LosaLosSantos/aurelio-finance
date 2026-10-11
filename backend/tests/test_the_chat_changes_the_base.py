"""The chat changes the base currency as the Profile page's Save changes it.

Brief AN, item 7 (2026-10-10). In the reader's second test round the chat was
asked to change the base currency and could not. `change_base_currency` goes
through `crud.change_base`, the function the settings request calls since
this brief (the request's own checks moved into it, its statuses and
sentences unchanged): a code the ECB's feed does not quote is refused, and the
new base's rates are stored before the setting changes, or nothing changes.
It asks the feed while it writes, so it runs as the analysis runs, on the
stream and outside the confirmation's unit of work, said as one step.

The card says what changes (every figure shown), what does not (nothing
stored is rewritten) and that the ECB's feed is asked. The feeds here are
invented and agree: one euro is 1.25 dollars.
"""

from __future__ import annotations

import datetime
import json

import pytest
from conftest import _empty_every_table
from sqlalchemy import text

from app import advisor, chat, crud, fx
from app.database import SessionLocal, engine

TODAY = datetime.date.today().isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
RATES = {"EUR": {"USD": 1.25, "GBP": 0.8}, "USD": {"EUR": 0.8, "GBP": 0.64}}


class Feed:
    def __init__(self):
        self.offline = False

    def fetch(self, base, start, end=None):
        if self.offline:
            raise fx.FxError("feed down")
        days = [ANCHOR_DAY, TODAY]
        first = max((d for d in days if d <= start), default=days[0])
        return {d: dict(RATES[base]) for d in days if d >= first and (end is None or d <= end)}


@pytest.fixture()
def feed(monkeypatch) -> Feed:
    f = Feed()
    monkeypatch.setattr(fx, "_fetch_rates", f.fetch)
    return f


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        yield from rounds.pop(0)

    monkeypatch.setattr(advisor, "stream_llm", fake)


def _asks(client, monkeypatch, currency: str) -> list[dict]:
    call = advisor.ToolCall(
        id="call_1", name="change_base_currency", arguments=json.dumps({"currency": currency})
    )
    _script(monkeypatch, [[("tool_call", call)]])
    return _events(client.post("/api/chat", json={"content": "show me everything in dollars"}))


def _draw(client, monkeypatch, currency: str = "USD") -> dict:
    events = _asks(client, monkeypatch, currency)
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert cards, [e for e in events if e["kind"] == "tool"]
    return cards[0]


def _confirm(client, monkeypatch, card: dict):
    _script(monkeypatch, [[("text", "Done.")]])
    return client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})


def _setup(client) -> None:
    """An account with a balance a month old, in euro, the base; the feed
    answered once already, as at any page load."""
    iid = client.post("/api/institutions", json={"name": "Example Bank"}).json()["id"]
    made = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": ANCHOR_DAY, "amount": 1000.0, "currency": "EUR"},
    )
    assert made.status_code == 201, made.text
    assert client.get("/api/settings/base-currency").json()["base_currency"] == "EUR"


def _stores() -> dict:
    """The setting and the rates stored against each base, as rows."""
    with engine.connect() as conn:
        setting = conn.execute(text("SELECT key, value FROM settings WHERE key = 'base_currency'")).all()
        rates = conn.execute(
            text("SELECT base, currency, as_of, rate FROM fx_rates ORDER BY base, currency, as_of")
        ).all()
    return {"setting": [tuple(r) for r in setting], "rates": [tuple(r) for r in rates]}


def test_the_cards_change_is_the_settings_requests(client, monkeypatch, feed):
    _setup(client)
    card = _draw(client, monkeypatch)
    events = _events(_confirm(client, monkeypatch, card))
    by_chat = _stores()
    assert [e["kind"] for e in events][:3] == ["start", "step", "decided"]

    _empty_every_table()
    _setup(client)
    saved = client.put("/api/settings/base-currency", json={"base_currency": "USD"})
    assert saved.status_code == 200, saved.text
    assert by_chat == _stores()
    assert by_chat["setting"] == [("base_currency", "USD")]


def test_the_card_says_what_changes_what_does_not_and_that_the_feed_is_asked(client, monkeypatch, feed):
    _setup(client)
    card = _draw(client, monkeypatch)
    assert card["confirmation"] == "diff"
    assert card["title"] == "base currency: EUR → USD"
    assert card["diff"] == [{"field": "Base currency", "now": "EUR", "proposed": "USD"}]
    said = card["consequence"]
    assert "Every total and figure the app shows is shown in USD from then on" in said
    assert "Nothing stored is rewritten: every amount keeps the currency it was recorded in" in said
    assert f"asks the ECB's feed for its rates against USD from {ANCHOR_DAY} to today" in said
    assert "if the feed does not answer, nothing changes" in said


def test_the_step_says_the_rates_were_stored_and_the_base_moved(client, monkeypatch, feed):
    _setup(client)
    card = _draw(client, monkeypatch)
    events = _events(_confirm(client, monkeypatch, card))
    (step,) = [e for e in events if e["kind"] == "step"]
    assert step["label"] == "The ECB's rates against USD fetched and stored, and the base changed"
    (decided,) = [e["card"] for e in events if e["kind"] == "decided"]
    assert decided["outcome"] == "confirmed" and decided["done"] == "Base changed"
    assert decided["result"] == {"base_currency": "USD", "was": "EUR"}


def test_a_feed_that_does_not_answer_changes_nothing_and_says_so(client, monkeypatch, feed):
    """The card stays waiting: nothing about it was wrong, the feed was down."""
    _setup(client)
    card = _draw(client, monkeypatch)
    before = _stores()
    feed.offline = True
    events = _events(_confirm(client, monkeypatch, card))
    assert events[-1]["kind"] == "error"
    assert "could not be fetched, so the base is still EUR" in events[-1]["detail"]
    assert _stores() == before
    with SessionLocal() as db:
        assert crud.find_chat_card(db, card["card_id"])[1]["outcome"] == "pending"


@pytest.mark.parametrize(
    "currency, said",
    [
        ("XYZ", "XYZ is not a currency the ECB rate feed quotes"),
        ("EUR", "EUR is the base already: nothing would change."),
    ],
)
def test_a_base_that_cannot_be_chosen_is_refused_in_words(client, monkeypatch, feed, currency, said):
    _setup(client)
    events = _asks(client, monkeypatch, currency)
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert said in refused["detail"]


def test_a_card_whose_base_changed_meanwhile_is_stale(client, monkeypatch, feed):
    """Another window changed the base after the card was drawn."""
    _setup(client)
    card = _draw(client, monkeypatch, "USD")
    assert client.put("/api/settings/base-currency", json={"base_currency": "USD"}).status_code == 200
    events = _events(_confirm(client, monkeypatch, card))
    assert events[-1]["kind"] == "error"
    assert "no longer what would happen" in events[-1]["detail"]
    with SessionLocal() as db:
        assert crud.find_chat_card(db, card["card_id"])[1]["outcome"] == "stale"


def test_the_settings_request_keeps_its_statuses(client, feed):
    """The checks moved into `crud.change_base`; the request answers as it did."""
    _setup(client)
    refused = client.put("/api/settings/base-currency", json={"base_currency": "XYZ"})
    assert refused.status_code == 422
    assert "XYZ is not a currency the ECB rate feed quotes" in refused.json()["detail"]
    feed.offline = True
    down = client.put("/api/settings/base-currency", json={"base_currency": "USD"})
    assert down.status_code == 503
    assert client.get("/api/settings/base-currency").json()["base_currency"] == "EUR"


def test_the_prompt_names_the_base_card():
    assert "`change_base_currency`: the currency every total is shown in" in chat.SYSTEM_PROMPT
