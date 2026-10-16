"""The chat corrects and deletes a transfer as the Cash flow form does.

Brief AP, item 3 (2026-10-12). Brief AN gave the chat `record_transfer`, and a
transfer it or the reader recorded could then be corrected or deleted only on
the Cash flow page. `change_transfer` is that page's form: a correction is
the PUT the form sends for a transfer opened and changed (`TransferSection`'s
`startEdit`, then `submit`: both sides, the amount, both currencies as stored,
and what arrived only when it was typed from a statement, else empty for the
app to work out again at the rate of the transfer's day), through
`crud.update_transfer`; a deletion is its DELETE. The card shows the diff and
what it moves: each account's cash today, and from which days it changes
(`cash_moves`), with the form's refusals in words. The page's Delete asks with
the same words.

For each, the records after the card is confirmed equal, field by field, the
records after the form's request on the same starting records. Every account
and figure is invented; the feed publishes 1.25 dollars to the euro thirty
days ago, 1.60 twenty days ago and 1.00 today, so the wrong day's rate cannot
pass for rounding.
"""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest
from conftest import _empty_every_table

from app import advisor, fx, tools

TODAY = datetime.date.today().isoformat()
DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
NEW_DAY = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
LATER_ANCHOR = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
BEFORE_LATER = (datetime.date.today() - datetime.timedelta(days=11)).isoformat()


@pytest.fixture()
def feed(monkeypatch):
    def fetch(base, start, end=None):
        return {DAY: {"USD": 1.25}, NEW_DAY: {"USD": 1.60}, TODAY: {"USD": 1.00}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)


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
    call = advisor.ToolCall(id="call_1", name="change_transfer", arguments=json.dumps(arguments))
    _script(monkeypatch, [[("tool_call", call)]])
    return _events(client.post("/api/chat", json={"content": "please"}))


def _draw(client, monkeypatch, **arguments) -> dict:
    events = _asks(client, monkeypatch, **arguments)
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert cards, [e for e in events if e["kind"] == "tool"]
    return cards[0]


def _refused(client, monkeypatch, **arguments) -> str:
    events = _asks(client, monkeypatch, **arguments)
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    return refused["detail"]


def _decide(client, monkeypatch, card: dict, decision: str = "confirm"):
    _script(monkeypatch, [[("text", "Done.")]])
    return client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": decision})


def _setup(client) -> dict:
    """Two euro accounts and a dollar one, each with a balance sixty days ago,
    and a transfer of thirty days ago between the euro ones."""
    ids = {}
    for name, currency, amount in (
        ("Euro Bank", "EUR", 1000.0),
        ("Euro Broker", "EUR", 500.0),
        ("Dollar Bank", "USD", 1000.0),
    ):
        iid = client.post("/api/institutions", json={"name": name}).json()["id"]
        made = client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR_DAY, "amount": amount, "currency": currency},
        )
        assert made.status_code == 201, made.text
        ids[name] = iid
    _transfer(client, from_institution_id=ids["Euro Bank"], to_institution_id=ids["Euro Broker"])
    return ids


def _transfer(client, **over) -> dict:
    body = {
        "date": DAY, "from_institution_id": None, "to_institution_id": None,
        "amount": 200.0, "currency": "EUR", "to_currency": "EUR", "to_amount": None,
    }
    body.update(over)
    made = client.post("/api/transfers", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def _form_save(client, transfer: dict, **changed) -> None:
    """The Cash flow form's Save for `transfer`, opened with ✎ and changed:
    every box as `startEdit` fills it, what arrived only when it was typed
    (no rate day, and not the same sum), then the boxes the reader changed.
    The same sum as `statedAmount.sameSum` reads it, which is `tools._same_sum`
    case for case (`test_one_currency_spelt_two_ways_is_one_sum` and its twin
    in `tests/statedAmount.test.ts`)."""
    typed = transfer["fx_as_of"] is None and not tools._same_sum(SimpleNamespace(**transfer))
    body = {
        "date": transfer["date"],
        "from_institution_id": transfer["from_institution_id"],
        "to_institution_id": transfer["to_institution_id"],
        "amount": transfer["amount"],
        "currency": transfer["currency"],
        "to_currency": transfer["to_currency"],
        "to_amount": transfer["to_amount"] if typed else None,
    }
    body.update(changed)
    saved = client.put(f"/api/transfers/{transfer['id']}", json=body)
    assert saved.status_code == 200, saved.text


def _rows(client) -> list[dict]:
    return [
        {k: v for k, v in t.items() if k not in ("id", "created_at")}
        for t in client.get("/api/transfers").json()
    ]


def _the_transfer(client, on: str = DAY) -> dict:
    (found,) = [t for t in client.get("/api/transfers").json() if t["date"] == on]
    return found


def _by_chat_and_by_form(client, monkeypatch, setup, arguments: dict, form) -> list[dict]:
    setup(client)
    card = _draw(client, monkeypatch, **arguments)
    assert _decide(client, monkeypatch, card).status_code == 200
    by_chat = _rows(client)

    _empty_every_table()
    form(client, setup(client))
    by_form = _rows(client)

    assert by_chat == by_form
    return by_chat


# --- Corrected, as the form's Save ---------------------------------------------------------


def test_a_corrected_amount_is_the_forms_save(client, monkeypatch):
    rows = _by_chat_and_by_form(
        client, monkeypatch, _setup,
        {"action": "correct", "date": DAY, "from_account": "Euro Bank", "to_account": "Euro Broker",
         "new_amount": 250},
        lambda client, ids: _form_save(client, _the_transfer(client), amount=250.0),
    )
    assert [(t["amount"], t["to_amount"], t["fx_as_of"]) for t in rows] == [(250.0, 250.0, None)]


def test_a_corrected_account_is_the_forms_save(client, monkeypatch):
    rows = _by_chat_and_by_form(
        client, monkeypatch, _setup,
        {"action": "correct", "date": DAY, "from_account": "Euro Bank", "to_account": "Euro Broker",
         "new_to_account": "Dollar Bank"},
        lambda client, ids: _form_save(client, _the_transfer(client), to_institution_id=ids["Dollar Bank"]),
    )
    assert len(rows) == 1


def _dollars_in(client) -> dict:
    ids = _setup(client)
    _transfer(
        client, date=DAY, from_institution_id=ids["Dollar Bank"], to_institution_id=ids["Euro Bank"],
        amount=500.0, currency="USD", to_currency="EUR",
    )
    return ids


def _dollar_transfer(client) -> dict:
    (found,) = [t for t in client.get("/api/transfers").json() if t["currency"] == "USD"]
    return found


def test_across_two_currencies_what_arrived_is_worked_out_again_as_the_form_does(
    client, monkeypatch, feed
):
    """Worked out at the rate of its day, so the form sends it back empty and
    the app works it out again from the new amount."""
    rows = _by_chat_and_by_form(
        client, monkeypatch, _dollars_in,
        {"action": "correct", "date": DAY, "from_account": "Dollar Bank", "to_account": "Euro Bank",
         "new_amount": 600},
        lambda client, ids: _form_save(client, _dollar_transfer(client), amount=600.0),
    )
    dollars = [t for t in rows if t["currency"] == "USD"]
    assert [(t["amount"], t["to_amount"], t["fx_as_of"]) for t in dollars] == [(600.0, 480.0, DAY)]


def test_a_corrected_day_works_what_arrived_out_at_that_days_rate(client, monkeypatch, feed):
    rows = _by_chat_and_by_form(
        client, monkeypatch, _dollars_in,
        {"action": "correct", "date": DAY, "from_account": "Dollar Bank", "to_account": "Euro Bank",
         "new_date": NEW_DAY},
        lambda client, ids: _form_save(client, _dollar_transfer(client), date=NEW_DAY),
    )
    dollars = [t for t in rows if t["currency"] == "USD"]
    assert [(t["date"], t["to_amount"], t["fx_as_of"]) for t in dollars] == [(NEW_DAY, 312.5, NEW_DAY)]


def test_the_card_says_what_arrived_is_worked_out_again(client, monkeypatch, feed):
    _dollars_in(client)
    card = _draw(
        client, monkeypatch, action="correct", date=DAY, from_account="Dollar Bank",
        to_account="Euro Bank", new_date=NEW_DAY,
    )
    assert {"field": "Reached", "now": "400.00 EUR", "proposed": "312.50 EUR"} in card["diff"]
    assert {
        "field": "What arrived is",
        "now": f"at the ECB rate of {DAY}",
        "proposed": f"at the ECB rate of {NEW_DAY}",
    } in card["diff"]
    assert f"What arrived is worked out again, at the ECB rate of {NEW_DAY}." in card["consequence"]


def _typed_in(client) -> dict:
    ids = _setup(client)
    _transfer(
        client, date=DAY, from_institution_id=ids["Dollar Bank"], to_institution_id=ids["Euro Bank"],
        amount=500.0, currency="USD", to_currency="EUR", to_amount=397.5,
    )
    return ids


def test_what_arrived_typed_from_a_statement_is_kept_as_the_form_keeps_it(client, monkeypatch, feed):
    rows = _by_chat_and_by_form(
        client, monkeypatch, _typed_in,
        {"action": "correct", "date": DAY, "from_account": "Dollar Bank", "to_account": "Euro Bank",
         "new_amount": 600},
        lambda client, ids: _form_save(client, _dollar_transfer(client), amount=600.0),
    )
    dollars = [t for t in rows if t["currency"] == "USD"]
    assert [(t["amount"], t["to_amount"], t["fx_as_of"]) for t in dollars] == [(600.0, 397.5, None)]


def test_the_card_says_a_typed_arrival_stays(client, monkeypatch, feed):
    _typed_in(client)
    card = _draw(
        client, monkeypatch, action="correct", date=DAY, from_account="Dollar Bank",
        to_account="Euro Bank", new_amount=600,
    )
    assert (
        "What arrived, 397.50 EUR, is a figure typed from a statement, so it stays as it is, as "
        "the Cash flow form keeps it: say the new figure if it changed."
    ) in card["consequence"]


def test_a_new_arrival_from_the_statement_is_the_forms_save(client, monkeypatch, feed):
    rows = _by_chat_and_by_form(
        client, monkeypatch, _typed_in,
        {"action": "correct", "date": DAY, "from_account": "Dollar Bank", "to_account": "Euro Bank",
         "new_arrived": 401},
        lambda client, ids: _form_save(client, _dollar_transfer(client), to_amount=401.0),
    )
    dollars = [t for t in rows if t["currency"] == "USD"]
    assert [(t["to_amount"], t["fx_as_of"]) for t in dollars] == [(401.0, None)]


# --- Deleted, as the form's Delete ---------------------------------------------------------


def test_a_deleted_transfer_is_the_forms_delete(client, monkeypatch):
    def form(client, ids):
        assert client.delete(f"/api/transfers/{_the_transfer(client)['id']}").status_code == 204

    rows = _by_chat_and_by_form(
        client, monkeypatch, _setup,
        {"action": "delete", "date": DAY, "from_account": "Euro Bank", "to_account": "Euro Broker"},
        form,
    )
    assert rows == []


# --- What the card says -------------------------------------------------------------------


def test_the_correction_card_shows_the_diff_and_each_accounts_cash_today(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="correct", date=DAY, from_account="Euro Bank",
        to_account="Euro Broker", new_amount=250,
    )
    assert card["confirmation"] == "diff"
    assert card["title"] == f"correct transfer: {DAY} Euro Bank to Euro Broker, 200.00 → 250.00 EUR"
    assert card["diff"] == [
        {"field": "Left", "now": "200.00 EUR", "proposed": "250.00 EUR"},
        {"field": "Reached", "now": "200.00 EUR", "proposed": "250.00 EUR"},
        {"field": "Cash at Euro Bank today", "now": "800.00 EUR", "proposed": "750.00 EUR"},
        {"field": "Cash at Euro Broker today", "now": "700.00 EUR", "proposed": "750.00 EUR"},
    ]
    assert card["consequence"] == (
        f"A correction: the transfer takes these figures. Euro Bank's cash changes from {DAY} on. "
        f"Euro Broker's cash changes from {DAY} on."
    )


def test_the_deletion_card_says_nothing_brings_it_back_and_what_it_moves(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank", to_account="Euro Broker",
    )
    assert card["title"] == f"delete transfer: {DAY} Euro Bank to Euro Broker: 200.00 EUR"
    assert card["diff"] == [
        {"field": "Transfer", "now": f"{DAY} Euro Bank to Euro Broker: 200.00 EUR", "proposed": "deleted"},
        {"field": "Cash at Euro Bank today", "now": "800.00 EUR", "proposed": "1000.00 EUR"},
        {"field": "Cash at Euro Broker today", "now": "700.00 EUR", "proposed": "500.00 EUR"},
    ]
    assert card["consequence"] == (
        f"It goes, and nothing brings it back. Euro Bank's cash changes from {DAY} on. "
        f"Euro Broker's cash changes from {DAY} on."
    )


def test_an_account_whose_later_balance_holds_it_says_which_days_change(client, monkeypatch):
    ids = _setup(client)
    client.post(
        f"/api/institutions/{ids['Euro Broker']}/cash-anchors",
        json={"date": LATER_ANCHOR, "amount": 700.0, "currency": "EUR"},
    )
    card = _draw(
        client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank", to_account="Euro Broker",
    )
    assert (
        f"Euro Broker's cash changes from {DAY} to {BEFORE_LATER}, and not today: its latest "
        f"balance, of {LATER_ANCHOR}, already holds it."
    ) in card["consequence"]
    assert "Cash at Euro Broker today" not in json.dumps(card["diff"])


def test_the_pages_delete_asks_with_the_cards_words_and_todays_figures(client, monkeypatch):
    """The Cash flow page's Delete asks with what `cash_moves` says, the
    figures the card shows in its diff said in words."""
    _setup(client)
    asked = client.get(f"/api/transfers/{_the_transfer(client)['id']}/deletion")
    assert asked.status_code == 200, asked.text
    assert asked.json() == {
        "said": (
            f"It goes, and nothing brings it back. Euro Bank's cash changes from {DAY} on: today "
            f"from 800.00 EUR to 1000.00 EUR. Euro Broker's cash changes from {DAY} on: today from "
            "700.00 EUR to 500.00 EUR."
        )
    }
    card = _draw(
        client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank", to_account="Euro Broker",
    )
    assert card["consequence"] == (
        f"It goes, and nothing brings it back. Euro Bank's cash changes from {DAY} on. "
        f"Euro Broker's cash changes from {DAY} on."
    )


def test_the_pages_delete_of_a_transfer_that_is_gone_is_404(client):
    """The route's own refusal, naming the transfer, not a path nobody serves."""
    gone = client.get("/api/transfers/999/deletion")
    assert gone.status_code == 404
    assert gone.json() == {"detail": "Transfer 999 not found"}


def test_a_transfer_from_outside_is_named_with_its_outside_side_empty(client, monkeypatch):
    ids = _setup(client)
    _transfer(client, date=NEW_DAY, to_institution_id=ids["Euro Bank"], amount=300.0)
    card = _draw(client, monkeypatch, action="delete", date=NEW_DAY, from_account=None, to_account="Euro Bank")
    assert card["title"] == f"delete transfer: {NEW_DAY} External to Euro Bank: 300.00 EUR"
    assert card["diff"][1:] == [
        {"field": "Cash at Euro Bank today", "now": "1100.00 EUR", "proposed": "800.00 EUR"},
    ]


def test_a_side_they_did_not_name_is_read_as_unsaid_when_nothing_outside_matches(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank", to_account=None)
    assert card["title"] == f"delete transfer: {DAY} Euro Bank to Euro Broker: 200.00 EUR"


# --- Refused in words -------------------------------------------------------------------


def test_a_transfer_not_on_record_is_refused_with_those_that_are(client, monkeypatch):
    _setup(client)
    said = _refused(
        client, monkeypatch, action="delete", date=NEW_DAY, from_account="Euro Bank", to_account="Euro Broker",
    )
    assert said.endswith(
        f"No transfer of {NEW_DAY} between those accounts is on record. On record: {DAY} Euro Bank "
        "to Euro Broker: 200.00 EUR."
    ), said


def test_one_account_on_both_sides_is_refused(client, monkeypatch):
    _setup(client)
    said = _refused(
        client, monkeypatch, action="correct", date=DAY, from_account="Euro Bank",
        to_account="Euro Broker", new_to_account="Euro Bank",
    )
    assert said.endswith("A transfer moves cash between two accounts: name two."), said


def test_a_day_with_no_final_rate_is_refused_with_the_forms_sentence(client, monkeypatch):
    """Today, before the ECB publishes: the form's own refusal."""
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {DAY: {"USD": 1.25}, yesterday: {"USD": 1.25}}
    )
    _dollars_in(client)
    said = _refused(
        client, monkeypatch, action="correct", date=DAY, from_account="Dollar Bank",
        to_account="Euro Bank", new_date=TODAY,
    )
    assert f"No final exchange rate from USD to EUR is known for {TODAY} yet" in said
    assert "State the amount that arrived" in said


def test_a_correction_that_changes_nothing_is_refused(client, monkeypatch):
    _setup(client)
    said = _refused(
        client, monkeypatch, action="correct", date=DAY, from_account="Euro Bank",
        to_account="Euro Broker", new_amount=200,
    )
    assert said.endswith(
        f"The transfer already says that: {DAY} Euro Bank to Euro Broker: 200.00 EUR. Nothing would change."
    ), said


def test_a_deletion_takes_no_new_values(client, monkeypatch):
    _setup(client)
    said = _refused(
        client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank",
        to_account="Euro Broker", new_amount=250,
    )
    assert "delete takes no new values." in said


# --- Stale and rejected -------------------------------------------------------------------


def test_a_card_is_stale_once_the_transfer_changes(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank", to_account="Euro Broker",
    )
    _form_save(client, _the_transfer(client), amount=300.0)
    assert _decide(client, monkeypatch, card).status_code == 409
    assert [t["amount"] for t in client.get("/api/transfers").json()] == [300.0]


def test_a_card_is_stale_once_an_accounts_cash_it_states_moves(client, monkeypatch):
    """Its figures are part of what it says: a balance added since makes them old."""
    ids = _setup(client)
    card = _draw(
        client, monkeypatch, action="correct", date=DAY, from_account="Euro Bank",
        to_account="Euro Broker", new_amount=250,
    )
    client.post(
        f"/api/institutions/{ids['Euro Bank']}/cash-anchors",
        json={"date": LATER_ANCHOR, "amount": 900.0, "currency": "EUR"},
    )
    assert _decide(client, monkeypatch, card).status_code == 409
    assert [t["amount"] for t in client.get("/api/transfers").json()] == [200.0]


def test_a_rejected_card_writes_nothing(client, monkeypatch):
    _setup(client)
    before = _rows(client)
    card = _draw(
        client, monkeypatch, action="delete", date=DAY, from_account="Euro Bank", to_account="Euro Broker",
    )
    assert _decide(client, monkeypatch, card, "reject").status_code == 200
    assert _rows(client) == before


# --- One currency spelt two ways (brief BA) ----------------------------------------------------


@pytest.mark.parametrize(
    "currency, to_currency, amount, to_amount, same",
    [
        ("EUR", "EUR", 200.0, 200.0, True),
        ("EUR", "EUR", 200.0, 199.0, False),
        ("EUR", "eur", 200.0, 200.0, True),
        ("GBP", "GBp", 12.34, 1234.0, True),
        ("GBp", "GBP", 1234.0, 12.34, True),
        ("EUR", "USD", 200.0, 200.0, False),
    ],
)
def test_one_currency_spelt_two_ways_is_one_sum(currency, to_currency, amount, to_amount, same):
    """The transfer cases of `tests/statedAmount.test.ts`, case for case:
    `crud._transfer_columns` works an arrival in "eur" or in pence out with
    the minor-unit step and no rate day, so the card must not read it as a
    figure typed from a statement."""
    t = SimpleNamespace(currency=currency, to_currency=to_currency, amount=amount, to_amount=to_amount)
    assert tools._same_sum(t) is same


def _spelt_small(client) -> dict:
    """Two euro accounts, and a transfer of thirty days ago whose destination
    side was typed "eur"."""
    ids = {}
    for name in ("Euro Bank", "Euro Broker"):
        iid = client.post("/api/institutions", json={"name": name}).json()["id"]
        made = client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR_DAY, "amount": 1000.0, "currency": "EUR"},
        )
        assert made.status_code == 201, made.text
        ids[name] = iid
    _transfer(client, from_institution_id=ids["Euro Bank"], to_institution_id=ids["Euro Broker"],
              to_currency="eur")
    return ids


def test_an_arrival_worked_out_in_eur_spelt_small_is_worked_out_again(client, monkeypatch):
    """Measured at 279acf8: the card read the stored 200 "eur" as typed and
    sent it back, so a corrected amount of 250 arrived as 200."""
    rows = _by_chat_and_by_form(
        client, monkeypatch, _spelt_small,
        {"action": "correct", "date": DAY, "from_account": "Euro Bank", "to_account": "Euro Broker",
         "new_amount": 250},
        lambda client, ids: _form_save(client, _the_transfer(client), amount=250.0),
    )
    assert [(t["amount"], t["to_amount"], t["to_currency"], t["fx_as_of"]) for t in rows] == [
        (250.0, 250.0, "eur", None)
    ]
