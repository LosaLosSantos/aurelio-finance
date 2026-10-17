"""A dividend the app estimated is corrected, never added beside, through the chat.

Brief AO, item 4 (2026-10-11), the reader's answer of 2026-10-10. The
catch-up records a dividend on its ex-date at the market's gross figure,
marked estimated, to be corrected with the broker's credit; a second row
typed for the same dividend was counted twice by the cash, the dividends
collected and the tax panel (measured by brief AI on a copy of the test
database). The ledger form offers the correction of every still-estimated
dividend of the same account and ticker dated on or before the one typed
(`sameDividend.estimatedDividends`), and never refuses, since a special
dividend is real. The chat's `record_transaction` was a second door to the
double count (the record's bullet of 2026-10-07): it now refuses such a
dividend, names the one on record, points to its correction
(`change_ledger_entry`) and says that a genuine second dividend is entered on
the form, which offers the correction first.

Yahoo's dividend answer is faked, the reader's today pinned. Every name and
figure here is invented.
"""

from __future__ import annotations

import json

import pytest

from app import advisor, dated, prices

SAID = (
    "XDIV.MI at Broker A already has a dividend the app recorded on 2026-09-23: 6.00 EUR, the "
    "market's gross figure, still estimated. If this is that dividend, correct it with their "
    "figures through `change_ledger_entry`, since a second row would count it twice. A genuine "
    "second dividend, such as a special one, is entered on the ledger form on the Portfolio "
    "page, which offers the same correction first."
)


@pytest.fixture()
def market(monkeypatch):
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda symbol, since: prices.DividendWindow(
            answered=True,
            dividends=[{"date": "2026-09-23", "dps": 0.30}] if symbol == "XDIV.MI" else [],
        ),
    )
    monkeypatch.setattr(dated, "today", lambda: "2026-10-11")


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        yield from rounds.pop(0)

    monkeypatch.setattr(advisor, "stream_llm", fake)


def _asks(client, monkeypatch, **arguments) -> list[dict]:
    body = {"kind": "dividend", "asset_name": "Example Dividend Share", "symbol": "XDIV.MI",
            "quantity": 20, "unit_price": 0.22, "currency": "EUR", "price_currency": "EUR",
            "institution": "Broker A", **arguments}
    call = advisor.ToolCall(id="call_1", name="record_transaction", arguments=json.dumps(body))
    _script(monkeypatch, [[("tool_call", call)]])
    return _events(client.post("/api/chat", json={"content": "please"}))


def _cards(events) -> list[dict]:
    return [e["card"] for e in events if e["kind"] == "card"]


def _said(events) -> str:
    (tool,) = [e for e in events if e["kind"] == "tool"]
    return tool["detail"]


def _account(client, name: str) -> int:
    iid = client.post("/api/institutions", json={"name": name, "type": "broker"}).json()["id"]
    r = client.post(f"/api/institutions/{iid}/cash-anchors", json={"date": "2026-06-30", "amount": 1000.0, "currency": "EUR"})
    assert r.status_code == 201, r.text
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-09-01"}).json()["id"]
    held = client.post(f"/api/snapshots/{sid}/holdings",
                       json={"asset_name": "Example Dividend Share", "asset_class": "equity", "symbol": "XDIV.MI",
                             "quantity": 20, "unit_price": 10, "currency": "EUR", "distribution_policy": "dist"})
    assert held.status_code == 201, held.text
    return iid


def _recorded(client) -> int:
    """Broker A holds 20 units; the catch-up records their dividend of 23
    September, 6.00, estimated."""
    iid = _account(client, "Broker A")
    created = client.post("/api/transactions/catch-up").json()["created"]
    assert [(t["date"], t["amount"], t["estimated"]) for t in created] == [("2026-09-23", 6.0, True)]
    return iid


def _dividends(client) -> list[tuple]:
    return [(t["date"], t["amount"]) for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]


@pytest.mark.parametrize("day", ["2026-09-30", "2026-09-23"], ids=["payment day", "ex-date"])
def test_a_dividend_beside_an_estimated_one_is_refused_and_its_correction_named(client, monkeypatch, market, day):
    _recorded(client)
    events = _asks(client, monkeypatch, date=day)
    assert _cards(events) == []
    assert SAID in _said(events)
    assert _dividends(client) == [("2026-09-23", 6.0)]


def test_a_dividend_dated_before_it_cannot_be_the_same_one(client, monkeypatch, market):
    _recorded(client)
    assert _cards(_asks(client, monkeypatch, date="2026-09-20"))


def test_another_ticker_or_another_account_is_not_offered_the_correction(client, monkeypatch, market):
    _recorded(client)
    _account(client, "Broker B")
    assert _cards(_asks(client, monkeypatch, date="2026-09-30", institution="Broker B"))
    assert _cards(_asks(client, monkeypatch, date="2026-09-30", symbol="XOTH.MI", asset_name="Other Share"))


def test_once_corrected_a_second_dividend_is_a_genuine_one(client, monkeypatch, market):
    """A special dividend on top of one corrected with the broker's credit is
    the reader's to record: nothing estimated is left to correct."""
    _recorded(client)
    (row,) = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    corrected = client.put(
        f"/api/transactions/{row['id']}",
        json={"kind": "dividend", "date": row["date"], "institution_id": row["institution_id"],
              "asset_name": row["asset_name"], "symbol": row["symbol"], "quantity": row["quantity"],
              "unit_price": row["unit_price"], "fees": 0, "currency": "EUR", "price_currency": "EUR",
              "amount": 4.41},
    )
    assert corrected.status_code == 200, corrected.text
    assert _cards(_asks(client, monkeypatch, date="2026-09-30"))


def test_several_are_named_newest_first(client, monkeypatch, market):
    _account(client, "Broker A")
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda symbol, since: prices.DividendWindow(
            answered=True,
            dividends=[{"date": "2026-09-23", "dps": 0.30}, {"date": "2026-10-07", "dps": 0.25}],
        ),
    )
    client.post("/api/transactions/catch-up")
    said = _said(_asks(client, monkeypatch, date="2026-10-09"))
    assert (
        "XDIV.MI at Broker A already has dividends the app recorded, the market's gross figures, "
        "still estimated: 2026-10-07, 5.00 EUR; 2026-09-23, 6.00 EUR. If this is one of them, "
        "correct it"
    ) in said


def test_a_card_drawn_before_the_catch_up_records_the_dividend_is_refused_as_stale(
    client, monkeypatch, market
):
    """The card is drawn while nothing is on record; the catch-up records the
    estimated dividend before the reader confirms: confirming would add the
    second row, so the card is out of date."""
    _account(client, "Broker A")
    (card,) = _cards(_asks(client, monkeypatch, date="2026-09-30"))
    client.post("/api/transactions/catch-up")
    _script(monkeypatch, [[("text", "Done.")]])
    refused = client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})
    assert refused.status_code == 409
    assert _dividends(client) == [("2026-09-23", 6.0)]


def test_the_prompt_says_an_estimated_dividend_is_corrected_never_recorded_beside():
    from app import chat

    for prompt in (chat.system_prompt("claude-opus-5.5"), chat.SYSTEM_PROMPT):
        assert (
            "A dividend the app recorded at the market's figure, still estimated, is corrected with "
            "it when they report what they received, never recorded beside it"
        ) in prompt


def test_the_prompt_says_a_second_dividend_beside_it_is_entered_on_the_form():
    """Brief AO's paid run: the reply after the correction offered to record
    "un altro dividendo" as new, which the refusal above would stop. The
    prompt says where such a dividend is entered."""
    from app import chat

    for prompt in (chat.system_prompt("claude-opus-5.5"), chat.SYSTEM_PROMPT):
        assert (
            "and while it is on record, a second dividend of that position dated on or after it, "
            "such as a special one, is entered on the ledger form: no card records it, so offer "
            "the form and never a card."
        ) in prompt
