"""The chat writes income and expenses as the Cash flow page writes them.

Brief AN, items 1 and 2 (2026-10-10). In the reader's second test round
(2026-10-08) the chat was asked to add an expense and an income, and to change
an income from a date (a raise), and could do none of it. `write_flow` makes
each change the page's form makes, through the schema it posts and the crud
function its request calls, behind a card: add a line; correct one recorded
wrong from the start; change one from a day, which ends the line on record
and starts a new one, both or neither; end one; delete one.

The proof that it is the form's write and not a second path: for each action,
the records after the card is confirmed equal, field by field, the records
after the request the form sends on the same starting records
(`CashFlow.tsx`: every field it has a box for, a blank one as null, never the
note). And the cards say, in the reader's terms, what the record's two dates
mean: the first payment's day is the day it repeats on, and the payments up to
the account's latest balance are already in it (the record's bullets on
"start" meaning two things, and on a start read as the day a line was
entered).

Every name and figure here is invented. The model is faked at
`advisor.stream_llm`; the tool is the real one.
"""

from __future__ import annotations

import json

import pytest
from conftest import _empty_every_table

from app import advisor, chat, crud, tools
from app.database import SessionLocal

TODAY_ANCHOR = "2026-09-30"


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        seen.append({"system": system_prompt, "messages": list(messages), "tools": tools})
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        yield from rounds[len(seen) - 1]

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def _flow(**arguments) -> tuple:
    return ("tool_call", advisor.ToolCall(id="call_1", name="write_flow", arguments=json.dumps(arguments)))


def _setup(client) -> dict:
    """Two accounts, one with a balance on record, an income and an expense on
    it: the records every scenario starts from."""
    bank = client.post("/api/institutions", json={"name": "Example Bank"}).json()["id"]
    other = client.post("/api/institutions", json={"name": "Second Bank"}).json()["id"]
    anchored = client.post(
        f"/api/institutions/{bank}/cash-anchors",
        json={"date": TODAY_ANCHOR, "amount": 2000.0, "currency": "EUR"},
    )
    assert anchored.status_code == 201, anchored.text
    salary = client.post(
        "/api/income-sources",
        json={
            "name": "Salary", "kind": "active", "category": "salary", "amount": 2000.0,
            "currency": "EUR", "frequency": "monthly", "institution_id": bank,
            "start_date": "2026-01-27", "end_date": None,
        },
    ).json()["id"]
    rent = client.post(
        "/api/expenses",
        json={
            "name": "Rent", "nature": "essential", "category": "housing", "amount": 800.0,
            "currency": "EUR", "frequency": "monthly", "institution_id": bank,
            "start_date": "2026-01-05", "end_date": None,
        },
    ).json()["id"]
    return {"bank": bank, "other": other, "salary": salary, "rent": rent}


def _rows(client) -> dict:
    """Every income and expense as the page reads them, without the id and the
    moment each row was made."""

    def kept(rows):
        return [{k: v for k, v in r.items() if k not in ("id", "created_at")} for r in rows]

    return {
        "income": kept(client.get("/api/income-sources").json()),
        "expenses": kept(client.get("/api/expenses").json()),
    }


def _draw(client, monkeypatch, **arguments) -> dict:
    _script(monkeypatch, [[("text", "Here it is:"), _flow(**arguments)]])
    events = _events(client.post("/api/chat", json={"content": "please"}))
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert cards, [e for e in events if e["kind"] == "tool"]
    return cards[0]


def _confirm(client, monkeypatch, card: dict):
    _script(monkeypatch, [[("text", "Done.")]])
    return client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})


def _form_edit(row: dict, tag: str, **changed) -> dict:
    """What the Cash flow form PUTs for a row the reader opened and changed:
    `toDraft` then `toPayload`, every box it has, a blank one as null, no note."""
    body = {
        "name": row["name"].strip(),
        "category": row["category"] or None,
        "amount": row["amount"],
        "currency": row["currency"],
        "frequency": row["frequency"] or None,
        "institution_id": row["institution_id"],
        "start_date": row["start_date"] or None,
        "end_date": row["end_date"] or None,
        tag: row[tag] or None,
    }
    return {**body, **changed}


def _by_chat_and_by_form(client, monkeypatch, arguments: dict, form) -> dict:
    """The records after the card is confirmed, and after the form's request on
    the same starting records, which must be the same: returns them."""
    _setup(client)
    card = _draw(client, monkeypatch, **arguments)
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _rows(client)

    _empty_every_table()
    ids = _setup(client)
    form(client, ids)
    by_form = _rows(client)

    assert by_chat == by_form
    return by_chat


# --- The card's write is the form's ---------------------------------------------------


def test_an_expense_added_is_the_forms_add(client, monkeypatch):
    def form(client, ids):
        made = client.post(
            "/api/expenses",
            json={
                "name": "Gym", "category": "leisure", "amount": 45.0, "currency": "EUR",
                "frequency": "monthly", "institution_id": ids["bank"],
                "start_date": "2026-11-03", "end_date": None, "nature": "discretionary",
            },
        )
        assert made.status_code == 201, made.text

    rows = _by_chat_and_by_form(
        client,
        monkeypatch,
        {
            "action": "add", "side": "expense", "name": "Gym", "account": "Example Bank",
            "amount": 45, "first_payment": "2026-11-03", "nature": "discretionary",
            "category": "leisure",
        },
        form,
    )
    assert [r["name"] for r in rows["expenses"]] == ["Rent", "Gym"]


def test_an_income_added_takes_the_accounts_currency_as_the_form_proposes_it(client, monkeypatch):
    """No currency said: the form proposes the account's on the first
    payment's day, and the card proposes the same."""

    def form(client, ids):
        client.post(
            f"/api/institutions/{ids['other']}/cash-anchors",
            json={"date": "2026-08-31", "amount": 500.0, "currency": "USD"},
        )
        made = client.post(
            "/api/income-sources",
            json={
                "name": "Lessons", "category": "freelance", "amount": 300.0, "currency": "USD",
                "frequency": "monthly", "institution_id": ids["other"],
                "start_date": "2026-10-15", "end_date": None, "kind": "active",
            },
        )
        assert made.status_code == 201, made.text

    _setup(client)
    client.post(
        "/api/institutions/2/cash-anchors",
        json={"date": "2026-08-31", "amount": 500.0, "currency": "USD"},
    )
    card = _draw(
        client, monkeypatch, action="add", side="income", name="Lessons",
        account="Second Bank", amount=300, first_payment="2026-10-15", kind="active",
        category="freelance",
    )
    assert "300.00 USD" in card["title"]
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _rows(client)
    _empty_every_table()
    form(client, _setup(client))
    assert by_chat == _rows(client)


def test_a_line_corrected_is_the_forms_edit(client, monkeypatch):
    def form(client, ids):
        row = client.get(f"/api/expenses/{ids['rent']}").json()
        edited = client.put(f"/api/expenses/{ids['rent']}", json=_form_edit(row, "nature", amount=850.0))
        assert edited.status_code == 200, edited.text

    rows = _by_chat_and_by_form(
        client, monkeypatch,
        {"action": "correct", "side": "expense", "name": "Rent", "amount": 850},
        form,
    )
    assert [r["amount"] for r in rows["expenses"]] == [850.0]


def test_an_income_changed_from_a_day_is_the_forms_two_saves(client, monkeypatch):
    """A raise from 27 November: the line on record ends with its October
    payment, and a new line starts on 27 November with the new figure. The
    form makes it in two saves; the card in one, both or neither."""

    def form(client, ids):
        row = client.get(f"/api/income-sources/{ids['salary']}").json()
        ended = client.put(
            f"/api/income-sources/{ids['salary']}", json=_form_edit(row, "kind", end_date="2026-10-27")
        )
        assert ended.status_code == 200, ended.text
        started = client.post(
            "/api/income-sources",
            json=_form_edit(row, "kind", amount=2300.0, start_date="2026-11-27", end_date=None),
        )
        assert started.status_code == 201, started.text

    rows = _by_chat_and_by_form(
        client, monkeypatch,
        {"action": "change_from", "side": "income", "name": "Salary", "amount": 2300,
         "first_payment": "2026-11-27"},
        form,
    )
    assert [(r["amount"], r["start_date"], r["end_date"]) for r in rows["income"]] == [
        (2000.0, "2026-01-27", "2026-10-27"),
        (2300.0, "2026-11-27", None),
    ]


def test_a_line_ended_is_the_forms_edit_of_its_last_payment(client, monkeypatch):
    def form(client, ids):
        row = client.get(f"/api/expenses/{ids['rent']}").json()
        client.put(f"/api/expenses/{ids['rent']}", json=_form_edit(row, "nature", end_date="2026-12-05"))

    rows = _by_chat_and_by_form(
        client, monkeypatch,
        {"action": "end", "side": "expense", "name": "Rent", "end": "2026-12-31"},
        form,
    )
    assert rows["expenses"][0]["end_date"] == "2026-12-05"


def test_a_line_deleted_is_the_forms_delete(client, monkeypatch):
    def form(client, ids):
        assert client.delete(f"/api/expenses/{ids['rent']}").status_code == 204

    rows = _by_chat_and_by_form(
        client, monkeypatch, {"action": "delete", "side": "expense", "name": "Rent"}, form
    )
    assert rows["expenses"] == []


def test_a_note_on_a_line_survives_a_card_as_it_survives_the_form(client, monkeypatch):
    """The form has no box for a note and never sends one; nor does a card."""
    ids = _setup(client)
    row = client.get(f"/api/expenses/{ids['rent']}").json()
    client.put(f"/api/expenses/{ids['rent']}", json={**_form_edit(row, "nature"), "notes": "an invented note"})
    card = _draw(client, monkeypatch, action="correct", side="expense", name="Rent", amount=900)
    _confirm(client, monkeypatch, card)
    assert client.get(f"/api/expenses/{ids['rent']}").json()["notes"] == "an invented note"


# --- What the cards say --------------------------------------------------------------


def test_an_add_is_light_and_says_the_payment_day_and_what_the_balance_holds(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="add", side="expense", name="Gym",
        account="Example Bank", amount=45, first_payment="2026-07-03",
    )
    assert card["confirmation"] == "light"
    assert card["title"] == "add expense: Gym, 45.00 EUR monthly · Example Bank"
    said = card["consequence"]
    assert "First paid on 2026-07-03, then on day 3 every month." in said
    assert (
        f"Payments dated up to {TODAY_ANCHOR}, the day of Example Bank's latest balance, "
        "are already in that balance; only those after it move its cash."
    ) in said
    assert "start" not in (card["title"] + said).lower()


def test_a_payment_day_past_the_28th_says_what_a_shorter_month_does(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="add", side="income", name="Bonus",
        account="Example Bank", amount=100, first_payment="2026-10-31", frequency="quarterly",
    )
    assert (
        "First paid on 2026-10-31, then on day 31 (the last day of a shorter month) "
        "every three months."
    ) in card["consequence"]


def test_a_line_on_no_account_says_it_moves_no_cash(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="add", side="expense", name="Gift", amount=50,
        first_payment="2026-12-20", frequency="one_off",
    )
    assert "Paid once, on 2026-12-20." in card["consequence"]
    assert "It is on no account, so it moves no account's cash" in card["consequence"]


def test_a_change_from_a_day_shows_both_lines_and_keeps_the_past(client, monkeypatch):
    _setup(client)
    card = _draw(
        client, monkeypatch, action="change_from", side="income", name="Salary",
        amount=2300, first_payment="2026-11-27",
    )
    assert card["confirmation"] == "diff"
    assert card["title"] == "change income from 2026-11-27: Salary"
    assert card["diff"] == [
        {"field": "Last payment of the line on record", "now": None, "proposed": "2026-10-27"},
        {"field": "From 2026-11-27: amount", "now": "2000.00", "proposed": "2300.00"},
    ]
    said = card["consequence"]
    assert "keeps its payments up to its last one, on 2026-10-27, at the figures they had" in said
    assert "First paid on 2026-11-27, then on day 27 every month." in said
    assert "that is a correction of the whole line" in said
    assert "start" not in (card["title"] + said).lower()


def test_a_correction_says_it_moves_the_past(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="correct", side="expense", name="Rent", amount=850)
    assert card["confirmation"] == "diff"
    assert card["diff"] == [{"field": "Amount", "now": "800.00", "proposed": "850.00"}]
    assert "every payment it counts moves with them, the past ones too" in card["consequence"]
    assert "that is a change from that day" in card["consequence"]


def test_a_delete_shows_its_diff_and_says_nothing_brings_the_line_back(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", side="expense", name="Rent")
    assert card["confirmation"] == "diff"
    assert card["diff"][0]["proposed"] == "deleted"
    assert "Nothing brings the line back" in card["consequence"]
    assert "end it instead" in card["consequence"]


def test_an_end_names_the_last_payment(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="end", side="expense", name="Rent", end="2026-12-31")
    assert card["title"] == "end expense: Rent, last payment 2026-12-05"
    assert card["diff"] == [{"field": "Last payment", "now": None, "proposed": "2026-12-05"}]


def test_the_word_over_a_confirmed_card_says_what_it_did(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", side="expense", name="Rent")
    decided = _events(_confirm(client, monkeypatch, card))
    (said,) = [e["card"] for e in decided if e["kind"] == "decided"]
    assert said["done"] == "Deleted"


# --- Refused, stale, both or neither ------------------------------------------------------


@pytest.mark.parametrize(
    "arguments, said",
    [
        (
            {"action": "change_from", "side": "income", "name": "Salary", "amount": 2300,
             "first_payment": "2026-01-27"},
            "a change of the whole line: that is a correction",
        ),
        (
            {"action": "end", "side": "expense", "name": "Rent", "end": "2025-12-31"},
            "ending it before its first payment is deleting it",
        ),
        (
            {"action": "correct", "side": "expense", "name": "Gym", "amount": 50},
            "There is no expense called 'Gym'. On record: Rent.",
        ),
        (
            {"action": "add", "side": "income", "name": "Rent out", "amount": 500,
             "first_payment": "2026-11-01", "category": "housing"},
            "'housing' is not an income category",
        ),
        (
            {"action": "add", "side": "expense", "name": "Gym", "amount": 45,
             "first_payment": "2026-11-01", "kind": "active"},
            "kind is an income's",
        ),
    ],
    ids=["change on the first payment", "end before it starts", "unknown line", "category", "kind"],
)
def test_a_card_that_cannot_be_what_was_asked_is_refused_in_words(client, monkeypatch, arguments, said):
    _setup(client)
    _script(monkeypatch, [[_flow(**arguments)]])
    events = _events(client.post("/api/chat", json={"content": "please"}))
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert said in refused["detail"]


def test_two_lines_of_one_name_are_told_apart_by_their_first_payment(client, monkeypatch):
    ids = _setup(client)
    client.post(
        "/api/expenses",
        json={"name": "Rent", "nature": "essential", "category": "housing", "amount": 300.0,
              "currency": "EUR", "frequency": "monthly", "institution_id": ids["bank"],
              "start_date": "2026-02-10", "end_date": None},
    )
    _script(monkeypatch, [[_flow(action="correct", side="expense", name="Rent", amount=310)]])
    events = _events(client.post("/api/chat", json={"content": "please"}))
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert "2 expense lines are called 'Rent'" in refused["detail"]
    assert "Say which by its first payment (on_record_from)" in refused["detail"]

    card = _draw(
        client, monkeypatch, action="correct", side="expense", name="Rent",
        on_record_from="2026-02-10", amount=310,
    )
    assert card["diff"] == [{"field": "Amount", "now": "300.00", "proposed": "310.00"}]


def test_a_card_goes_stale_when_its_line_moves(client, monkeypatch):
    ids = _setup(client)
    card = _draw(client, monkeypatch, action="correct", side="expense", name="Rent", amount=850)
    row = client.get(f"/api/expenses/{ids['rent']}").json()
    client.put(f"/api/expenses/{ids['rent']}", json=_form_edit(row, "nature", amount=820.0))

    refused = _confirm(client, monkeypatch, card)
    assert refused.status_code == 409
    assert client.get(f"/api/expenses/{ids['rent']}").json()["amount"] == 820.0


def test_an_add_goes_stale_when_the_accounts_latest_balance_moves(client, monkeypatch):
    """Its card names that balance's day."""
    ids = _setup(client)
    card = _draw(
        client, monkeypatch, action="add", side="expense", name="Gym",
        account="Example Bank", amount=45, first_payment="2026-11-03",
    )
    client.post(
        f"/api/institutions/{ids['bank']}/cash-anchors",
        json={"date": "2026-10-05", "amount": 1500.0, "currency": "EUR"},
    )
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert [r["name"] for r in client.get("/api/expenses").json()] == ["Rent"]


def test_a_rejected_card_writes_nothing(client, monkeypatch):
    _setup(client)
    before = _rows(client)
    card = _draw(client, monkeypatch, action="delete", side="expense", name="Rent")
    _script(monkeypatch, [[("text", "Kept.")]])
    assert client.post(
        f"/api/chat/cards/{card['card_id']}", json={"decision": "reject"}
    ).status_code == 200
    assert _rows(client) == before


def test_a_change_from_a_day_writes_both_lines_or_neither(client, monkeypatch):
    """The new line fails to be written: the old line's end goes back too."""
    _setup(client)
    before = _rows(client)
    card = _draw(
        client, monkeypatch, action="change_from", side="income", name="Salary",
        amount=2300, first_payment="2026-11-27",
    )

    def no(db, data):
        raise RuntimeError("the disk went away")

    monkeypatch.setitem(
        tools._FLOW_SIDES,
        "income",
        tools._FlowSide(**{**tools._FLOW_SIDES["income"].__dict__, "create": no}),
    )
    refused = _confirm(client, monkeypatch, card)
    assert refused.status_code == 409 and "the disk went away" in refused.json()["detail"]
    assert _rows(client) == before


# --- What the chat reads ----------------------------------------------------------------


def test_the_picture_names_the_account_of_every_line(client):
    ids = _setup(client)
    client.post(
        "/api/expenses",
        json={"name": "Gift", "amount": 50.0, "currency": "EUR", "frequency": "one_off",
              "start_date": "2099-12-20"},
    )
    with SessionLocal() as db:
        picture = chat.build_chat_context(db)
    assert "Salary [active/salary] 2000.00 EUR monthly, credited to Example Bank, since 2026-01-27" in picture
    assert "Rent [essential/housing] 800.00 EUR monthly, paid from Example Bank, since 2026-01-05" in picture
    assert "Gift [n/a/n/a] 50.00 EUR one_off, on no account, from 2099-12-20" in picture
    assert ids


def test_the_prompt_says_what_write_flow_does_and_to_ask_which_change_is_meant():
    prompt = chat.SYSTEM_PROMPT
    assert "`write_flow`: their income and expenses, as the Cash flow page writes them" in prompt
    assert "when their words could be either, ask which" in prompt
