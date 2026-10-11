"""The chat records a transfer and an account's balance as their forms do.

Brief AN, item 4 (2026-10-10): in the reader's second test round the chat was
asked to record a transfer between two of their accounts and to set an
account's cash balance on a day, and could do neither. `record_transfer` is
the Cash flow page's transfer: both accounts, both currencies, and what
reached the second account worked out at the ECB rate of the day by the
function that stores it, or the form's own refusal, in words, when that day
has no final rate. `set_cash_balance` is the account page's balance: a new day
is added, a day that has one is replaced with its diff, and the card says
that from that day the account holds that figure and that everything dated up
to it counts as already in it.

For each, the records after the card is confirmed equal, field by field, the
records after the request the form sends on the same starting records. Every
account and figure is invented; the feed publishes 1.25 dollars to the euro
thirty days ago and 1.00 today, so the wrong day's rate cannot pass for
rounding.
"""

from __future__ import annotations

import datetime
import json

import pytest
from conftest import _empty_every_table

from app import advisor, chat, fx

TODAY = datetime.date.today().isoformat()
DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
LATER_ANCHOR = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


@pytest.fixture()
def feed(monkeypatch):
    def fetch(base, start, end=None):
        return {DAY: {"USD": 1.25}, TODAY: {"USD": 1.00}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)


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


def _asks(client, monkeypatch, tool: str, **arguments) -> list[dict]:
    call = advisor.ToolCall(id="call_1", name=tool, arguments=json.dumps(arguments))
    _script(monkeypatch, [[("tool_call", call)]])
    return _events(client.post("/api/chat", json={"content": "please"}))


def _draw(client, monkeypatch, tool: str, **arguments) -> dict:
    events = _asks(client, monkeypatch, tool, **arguments)
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert cards, [e for e in events if e["kind"] == "tool"]
    return cards[0]


def _confirm(client, monkeypatch, card: dict):
    _script(monkeypatch, [[("text", "Done.")]])
    return client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})


def _setup(client) -> dict:
    """A euro account and a dollar account, each with a balance sixty days ago."""
    ids = {}
    for name, currency in (("Euro Bank", "EUR"), ("Dollar Bank", "USD")):
        iid = client.post("/api/institutions", json={"name": name}).json()["id"]
        made = client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR_DAY, "amount": 1000.0, "currency": currency},
        )
        assert made.status_code == 201, made.text
        ids[name] = iid
    return ids


def _rows(client) -> dict:
    def kept(rows):
        return [{k: v for k, v in r.items() if k not in ("id", "created_at")} for r in rows]

    return {
        "transfers": kept(client.get("/api/transfers").json()),
        "anchors": kept(client.get("/api/cash-anchors").json()),
    }


def _by_chat_and_by_form(client, monkeypatch, tool: str, arguments: dict, form) -> dict:
    _setup(client)
    card = _draw(client, monkeypatch, tool, **arguments)
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _rows(client)

    _empty_every_table()
    form(client, _setup(client))
    by_form = _rows(client)

    assert by_chat == by_form
    return by_chat


# --- A transfer ------------------------------------------------------------------------


def test_a_transfer_in_one_currency_is_the_forms(client, monkeypatch):
    def form(client, ids):
        made = client.post(
            "/api/transfers",
            json={
                "date": DAY, "from_institution_id": ids["Euro Bank"],
                "to_institution_id": ids["Dollar Bank"],
                "amount": 200.0, "currency": "EUR", "to_currency": "EUR", "to_amount": None,
            },
        )
        assert made.status_code == 201, made.text

    rows = _by_chat_and_by_form(
        client, monkeypatch, "record_transfer",
        {"date": DAY, "from_account": "Euro Bank", "to_account": "Dollar Bank",
         "amount": 200, "to_currency": "EUR"},
        form,
    )
    assert [(t["amount"], t["to_amount"], t["fx_as_of"]) for t in rows["transfers"]] == [
        (200.0, 200.0, None)
    ]


def test_a_transfer_across_two_currencies_is_the_forms_at_the_rate_of_its_day(
    client, monkeypatch, feed
):
    """No currency said: each side takes its account's, as the form proposes
    them; what arrived is worked out at the day's rate by the function that
    stores it, and the card says it before the confirmation."""

    def form(client, ids):
        made = client.post(
            "/api/transfers",
            json={
                "date": DAY, "from_institution_id": ids["Dollar Bank"],
                "to_institution_id": ids["Euro Bank"], "amount": 500.0, "currency": "USD",
                "to_currency": "EUR", "to_amount": None,
            },
        )
        assert made.status_code == 201, made.text

    _setup(client)
    card = _draw(
        client, monkeypatch, "record_transfer",
        date=DAY, from_account="Dollar Bank", to_account="Euro Bank", amount=500,
    )
    assert card["confirmation"] == "light"
    assert card["title"] == (
        f"transfer: 500.00 USD → 400.00 EUR (at the ECB rate of {DAY}), "
        f"Dollar Bank to Euro Bank, {DAY}"
    )
    assert card["consequence"] == (
        f"It lowers Dollar Bank's cash by 500.00 USD and raises Euro Bank's by 400.00 EUR "
        f"from {DAY}."
    )
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _rows(client)
    _empty_every_table()
    form(client, _setup(client))
    assert by_chat == _rows(client)
    assert by_chat["transfers"][0]["fx_as_of"] == DAY


def test_what_arrived_from_the_statement_is_kept_as_stated(client, monkeypatch, feed):
    def form(client, ids):
        client.post(
            "/api/transfers",
            json={
                "date": DAY, "from_institution_id": ids["Dollar Bank"],
                "to_institution_id": ids["Euro Bank"], "amount": 500.0, "currency": "USD",
                "to_currency": "EUR", "to_amount": 397.5,
            },
        )

    rows = _by_chat_and_by_form(
        client, monkeypatch, "record_transfer",
        {"date": DAY, "from_account": "Dollar Bank", "to_account": "Euro Bank",
         "amount": 500, "arrived": 397.5},
        form,
    )
    assert (rows["transfers"][0]["to_amount"], rows["transfers"][0]["fx_as_of"]) == (397.5, None)


def test_a_transfer_whose_day_has_no_final_rate_is_refused_with_the_forms_sentence(
    client, monkeypatch
):
    """Today, before the ECB publishes: yesterday's rate is the one in force,
    and a sum fixed at it would keep yesterday's rate for good."""
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {yesterday: {"USD": 1.25}})
    _setup(client)
    events = _asks(
        client, monkeypatch, "record_transfer",
        date=TODAY, from_account="Dollar Bank", to_account="Euro Bank", amount=500,
    )
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert f"No final exchange rate from USD to EUR is known for {TODAY} yet" in refused["detail"]
    assert "State the amount that arrived" in refused["detail"]


def test_a_transfer_already_in_a_balance_says_so(client, monkeypatch):
    ids = _setup(client)
    client.post(
        f"/api/institutions/{ids['Euro Bank']}/cash-anchors",
        json={"date": LATER_ANCHOR, "amount": 800.0, "currency": "EUR"},
    )
    card = _draw(
        client, monkeypatch, "record_transfer",
        date=DAY, from_account="Euro Bank", to_account="Dollar Bank", amount=100,
        to_currency="EUR",
    )
    assert (
        f"Euro Bank's latest balance, of {LATER_ANCHOR}, already holds it, so its cash "
        "today does not move."
    ) in card["consequence"]
    assert "Dollar Bank's latest balance" not in card["consequence"]


@pytest.mark.parametrize(
    "arguments, said",
    [
        ({"from_account": "Euro Bank", "to_account": "Euro Bank"}, "name two"),
        ({"from_account": "Euro Bank", "to_account": "Nowhere Bank"}, "There is no institution called 'Nowhere Bank'"),
    ],
)
def test_a_transfer_needs_two_accounts_on_record(client, monkeypatch, arguments, said):
    _setup(client)
    events = _asks(client, monkeypatch, "record_transfer", date=DAY, amount=100, **arguments)
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert said in refused["detail"]


def test_a_transfer_card_goes_stale_when_an_accounts_latest_balance_moves(client, monkeypatch):
    ids = _setup(client)
    card = _draw(
        client, monkeypatch, "record_transfer",
        date=DAY, from_account="Euro Bank", to_account="Dollar Bank", amount=100,
        to_currency="EUR",
    )
    client.post(
        f"/api/institutions/{ids['Euro Bank']}/cash-anchors",
        json={"date": LATER_ANCHOR, "amount": 800.0, "currency": "EUR"},
    )
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert client.get("/api/transfers").json() == []


# --- A balance on a day ------------------------------------------------------------------


def test_a_balance_on_a_new_day_is_the_forms_add(client, monkeypatch):
    def form(client, ids):
        made = client.post(
            f"/api/institutions/{ids['Dollar Bank']}/cash-anchors",
            json={"date": LATER_ANCHOR, "amount": 1500.0, "currency": "USD"},
        )
        assert made.status_code == 201, made.text

    rows = _by_chat_and_by_form(
        client, monkeypatch, "set_cash_balance",
        {"account": "Dollar Bank", "date": LATER_ANCHOR, "amount": 1500},
        form,
    )
    assert [(a["date"], a["amount"], a["currency"]) for a in rows["anchors"]][-1] == (
        LATER_ANCHOR, 1500.0, "USD"
    )


def test_a_new_balance_is_light_and_says_what_it_holds_from_that_day(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, "set_cash_balance", account="Euro Bank", date=LATER_ANCHOR, amount=1500
    )
    assert card["confirmation"] == "light"
    assert card["title"] == f"cash balance: Euro Bank held 1500.00 EUR on {LATER_ANCHOR}"
    assert card["consequence"] == (
        f"From {LATER_ANCHOR} Euro Bank holds 1500.00 EUR: the income, expenses, "
        f"transfers and ledger entries dated up to {LATER_ANCHOR} count as already in it, "
        "and only those after it move its cash."
    )


def test_a_balance_on_a_day_that_has_one_replaces_it_as_the_forms_edit(client, monkeypatch):
    """The day's balance is edited, its currency kept as stored."""

    def form(client, ids):
        anchor = client.get(f"/api/institutions/{ids['Dollar Bank']}/cash-anchors").json()[0]
        edited = client.put(
            f"/api/cash-anchors/{anchor['id']}",
            json={"date": ANCHOR_DAY, "amount": 1200.0, "currency": "USD"},
        )
        assert edited.status_code == 200, edited.text

    _setup(client)
    card = _draw(
        client, monkeypatch, "set_cash_balance", account="Dollar Bank", date=ANCHOR_DAY, amount=1200
    )
    assert card["confirmation"] == "diff"
    assert card["diff"] == [
        {"field": f"Balance on {ANCHOR_DAY}", "now": "1000.00 USD", "proposed": "1200.00 USD"}
    ]
    assert card["consequence"].startswith(
        f"This replaces the balance already on {ANCHOR_DAY}, which does not come back."
    )
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _rows(client)
    _empty_every_table()
    form(client, _setup(client))
    assert by_chat == _rows(client)


def test_a_balance_before_the_latest_says_the_latest_still_projects_today(client, monkeypatch):
    ids = _setup(client)
    client.post(
        f"/api/institutions/{ids['Euro Bank']}/cash-anchors",
        json={"date": LATER_ANCHOR, "amount": 800.0, "currency": "EUR"},
    )
    card = _draw(client, monkeypatch, "set_cash_balance", account="Euro Bank", date=DAY, amount=900)
    assert card["consequence"].endswith(
        f"Its balance of {LATER_ANCHOR}, after this day, stays the one its cash today is "
        "projected from."
    )


def test_a_balance_on_a_day_that_has_not_happened_is_refused(client, monkeypatch):
    _setup(client)
    events = _asks(
        client, monkeypatch, "set_cash_balance", account="Euro Bank", date=TOMORROW, amount=900
    )
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert "Those arguments do not fit set_cash_balance" in refused["detail"]


def test_a_balance_card_goes_stale_when_that_days_balance_moves(client, monkeypatch):
    ids = _setup(client)
    card = _draw(
        client, monkeypatch, "set_cash_balance", account="Euro Bank", date=ANCHOR_DAY, amount=1200
    )
    anchor = client.get(f"/api/institutions/{ids['Euro Bank']}/cash-anchors").json()[0]
    client.put(
        f"/api/cash-anchors/{anchor['id']}",
        json={"date": ANCHOR_DAY, "amount": 1100.0, "currency": "EUR"},
    )
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert client.get(f"/api/institutions/{ids['Euro Bank']}/cash-anchors").json()[0]["amount"] == 1100.0


def test_the_prompt_names_both_cash_cards():
    prompt = chat.SYSTEM_PROMPT
    assert "`record_transfer`: cash moved from one of their accounts to another" in prompt
    assert "`set_cash_balance`: what an account held on a day" in prompt
