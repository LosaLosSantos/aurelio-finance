"""The chat changes a PAC's amount from its next occurrence, as the PAC form does.

Brief AO, item 1 (2026-10-11). In the reader's second test round (2026-10-08)
the chat was asked to change a PAC's amount from its next occurrence and had
no tool for it. `change_pac_amount` writes what the PAC form's Save writes
(`CashFlow.tsx`: the whole plan as it loads it, with the amount changed),
through the function the form's request calls; the router's check that every
account the plan names exists moved into it, so the two doors check alike.

The card says what the change does that the form leaves to the reader: the
first occurrence the new amount buys, and when that one is due already and
not bought yet (today's, a weekend's waiting for its session) it is bought
at the new amount, which the catch-up's reading of the amount when it buys
makes so; the carry on record goes to zero with the change (it always has,
`crud.update_accumulation_plan`), and that money never left the account's
cash. The schedule and the funds stay with the form.

Yahoo is faked at `prices._fetch_close_window`, every weekday at 48.00, and
the reader's today is pinned. Every name and figure here is invented.
"""

from __future__ import annotations

import datetime
import json

import pytest
from conftest import _empty_every_table

from app import advisor, crud, dated, prices
from app.database import SessionLocal

CLOSE = 48.0


@pytest.fixture()
def market(monkeypatch):
    """A listing that trades on weekdays at 48.00, and the reader's today,
    pinned by `on`."""

    def fetch(symbol, start, end):
        out, day = [], start
        while day < end:
            if day.weekday() < 5:
                out.append((day.isoformat(), CLOSE))
            day += datetime.timedelta(days=1)
        return out

    monkeypatch.setattr(prices, "_fetch_close_window", fetch)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")

    def on(day: str) -> None:
        monkeypatch.setattr(dated, "today", lambda: day)

    on("2026-10-11")
    return on


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
    call = advisor.ToolCall(id="call_1", name="change_pac_amount", arguments=json.dumps(arguments))
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
    (said,) = [e for e in events if e["kind"] == "tool"]
    return said["detail"]


def _confirm(client, monkeypatch, card: dict):
    _script(monkeypatch, [[("text", "Done.")]])
    return client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})


def _catch_up(client) -> list[dict]:
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    return [
        (t["plan_occurrence"], t["date"], t["quantity"], t["amount"])
        for t in r.json()["created"]
        if t["plan_occurrence"]
    ]


def _setup(client, *, start="2026-07-15", amount=300.0, execution="whole_units") -> dict:
    """An account with a balance before the plan, and a plan on it caught up
    to the reader's today: 300.00 a month at 48.00 buys 6 units each time,
    and leaves 12.00, 24.00 and 36.00 carried."""
    broker = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    anchored = client.post(
        f"/api/institutions/{broker}/cash-anchors",
        json={"date": "2026-06-30", "amount": 10000.0, "currency": "EUR"},
    )
    assert anchored.status_code == 201, anchored.text
    made = client.post(
        "/api/accumulation-plans",
        json={
            "name": "Example PAC", "amount": amount, "currency": "EUR", "frequency": "monthly",
            "execution": execution, "source_institution_id": broker, "start_date": start,
            "end_date": None,
            "targets": [
                {"symbol": "XWLD.MI", "isin": None, "asset_name": "Example World UCITS ETF",
                 "institution_id": broker, "weight": 1},
            ],
        },
    )
    assert made.status_code == 201, made.text
    _catch_up(client)
    return {"broker": broker, "plan": made.json()["id"]}


def _form_body(plan: dict, **changed) -> dict:
    """What the PAC form PUTs for a plan the reader opened and changed
    (`CashFlow.tsx`, `startEdit` then `submit`): a blank frequency and fill
    model as the form's defaults, no note."""
    body = {
        "name": plan["name"].strip(),
        "amount": plan["amount"],
        "currency": plan["currency"],
        "frequency": plan["frequency"] or "monthly",
        "execution": plan["execution"] or "whole_units",
        "source_institution_id": plan["source_institution_id"],
        "start_date": plan["start_date"] or None,
        "end_date": plan["end_date"] or None,
        "targets": [
            {
                "symbol": t["symbol"].strip(),
                "isin": (t["isin"] or "").strip().upper() or None,
                "asset_name": (t["asset_name"] or "").strip() or None,
                "institution_id": t["institution_id"],
                "weight": t["weight"] if t["weight"] > 0 else 1,
            }
            for t in plan["targets"]
        ],
    }
    return {**body, **changed}


def _records(client) -> dict:
    """The plans and the ledger as the pages read them, without the ids and
    the moments each row was made."""

    def kept(rows):
        return [{k: v for k, v in r.items() if k not in ("id", "created_at")} for r in rows]

    plans = client.get("/api/accumulation-plans").json()
    for p in plans:
        p["targets"] = kept(p["targets"])
    return {"plans": kept(plans), "ledger": kept(client.get("/api/transactions").json())}


# --- The card's write is the form's -------------------------------------------------


def test_a_new_amount_is_the_pac_forms_save_and_the_next_occurrence_buys_with_it(
    client, monkeypatch, market
):
    """The records after the card equal the records after the form's PUT on
    the same starting records, and so does what the next occurrence buys."""
    _setup(client)
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _records(client)
    market("2026-10-16")
    bought_by_chat = _catch_up(client)

    _empty_every_table()
    market("2026-10-11")
    ids = _setup(client)
    plan = client.get(f"/api/accumulation-plans/{ids['plan']}").json()
    saved = client.put(f"/api/accumulation-plans/{ids['plan']}", json=_form_body(plan, amount=250.0))
    assert saved.status_code == 200, saved.text
    assert _records(client) == by_chat
    market("2026-10-16")
    assert _catch_up(client) == bought_by_chat == [("2026-10-15", "2026-10-15", 5.0, 240.0)]

    (after,) = by_chat["plans"]
    assert after["amount"] == 250.0 and after["carried_remainder"] == 0.0


def test_the_accounts_a_plan_names_are_checked_by_the_function_both_doors_call(client, market):
    """The router's check moved into `crud`: the form's requests answer as
    they did, a 404 naming the account, and the card meets the same check."""
    ids = _setup(client)
    plan = client.get(f"/api/accumulation-plans/{ids['plan']}").json()
    missing = client.put(
        f"/api/accumulation-plans/{ids['plan']}", json=_form_body(plan, source_institution_id=99)
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Institution 99 not found"
    gone = client.put("/api/accumulation-plans/42", json=_form_body(plan))
    assert gone.status_code == 404 and gone.json()["detail"] == "Accumulation plan 42 not found"

    from app import schemas

    with SessionLocal() as db, pytest.raises(crud.InstitutionMissing, match="Institution 99 not found"):
        crud.update_accumulation_plan(
            db, ids["plan"], schemas.AccumulationPlanWrite(**_form_body(plan, source_institution_id=99))
        )


# --- What the card says -----------------------------------------------------------------


def test_the_card_names_the_first_occurrence_and_what_happens_to_the_carry(client, monkeypatch, market):
    _setup(client)
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    assert card["confirmation"] == "diff"
    assert card["title"] == "change PAC amount: Example PAC, 300.00 → 250.00 EUR from 2026-10-15"
    assert card["diff"] == [
        {"field": "Amount per occurrence", "now": "300.00 EUR", "proposed": "250.00 EUR"},
        {"field": "Carried", "now": "36.00 EUR", "proposed": "0.00 EUR"},
    ]
    said = card["consequence"]
    assert said.startswith(
        "From its occurrence of 2026-10-15 on, each occurrence of Example PAC buys with 250.00 EUR."
    )
    assert "due and not bought" not in said and "today's" not in said
    assert "The occurrences already bought keep their buys." in said
    assert (
        "The 36.00 EUR carried now (what whole units could not place) goes to zero with "
        "the change, as a change of amount on the PAC's form does: that money never left "
        "Broker A's cash, and it stays there."
    ) in said
    assert (
        "Its frequency, the day of its first buy and its funds stay as they are: they change "
        "on the PAC's form, in Portfolio"
    ) in said


def test_an_occurrence_on_its_own_day_is_bought_after_its_close_at_the_new_amount(
    client, monkeypatch, market
):
    _setup(client)
    market("2026-10-15")
    assert _catch_up(client) == []
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    assert (
        "That occurrence is today's: the first start after today's close buys it with the "
        "new amount."
    ) in card["consequence"]
    assert _confirm(client, monkeypatch, card).status_code == 200
    market("2026-10-16")
    assert _catch_up(client) == [("2026-10-15", "2026-10-15", 5.0, 240.0)]


def test_a_weekends_occurrence_waiting_for_its_session_is_bought_at_the_new_amount(
    client, monkeypatch, market
):
    """A plan on Sunday the 4th, asked about on Monday the 5th: its session
    has not ended, so the occurrence is due and not bought yet."""
    market("2026-10-05")
    _setup(client, start="2026-10-04")
    assert _catch_up(client) == []
    card = _draw(client, monkeypatch, plan="Example PAC", amount=500)
    assert card["title"].endswith("from 2026-10-04")
    assert (
        "That occurrence is due and not bought yet (it waits for its close, or for the market "
        "to answer), so the next start buys it with the new amount."
    ) in card["consequence"]
    assert _confirm(client, monkeypatch, card).status_code == 200
    market("2026-10-06")
    assert _catch_up(client) == [("2026-10-04", "2026-10-05", 10.0, 480.0)]


def test_a_fractional_plan_carries_nothing_and_the_card_says_so(client, monkeypatch, market):
    _setup(client, execution="fractional")
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    assert card["diff"] == [
        {"field": "Amount per occurrence", "now": "300.00 EUR", "proposed": "250.00 EUR"},
    ]
    assert "A fractional plan invests exactly its amount, so it carries nothing." in card["consequence"]


def test_the_word_over_a_confirmed_card_and_what_it_wrote(client, monkeypatch, market):
    _setup(client)
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    decided = _events(_confirm(client, monkeypatch, card))
    (said,) = [e["card"] for e in decided if e["kind"] == "decided"]
    assert said["done"] == "Changed"
    assert [(r["label"], r["value"]) for r in said["receipt"]] == [
        ("Each occurrence buys with", "250.0"),
        ("From the occurrence of", "2026-10-15"),
        ("Carried now", "0.0"),
    ]


# --- Refused, stale, rejected ------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments, said",
    [
        ({"plan": "Example PAC", "amount": 300}, "Example PAC buys with 300.00 EUR already: nothing would change."),
        ({"plan": "Other PAC", "amount": 250}, "There is no PAC called 'Other PAC'. On record: Example PAC."),
    ],
    ids=["same amount", "unknown plan"],
)
def test_a_card_that_cannot_be_what_was_asked_is_refused_in_words(
    client, monkeypatch, market, arguments, said
):
    _setup(client)
    assert said in _refused(client, monkeypatch, **arguments)


def test_a_plan_with_no_occurrence_left_is_refused(client, monkeypatch, market):
    ids = _setup(client)
    plan = client.get(f"/api/accumulation-plans/{ids['plan']}").json()
    client.put(f"/api/accumulation-plans/{ids['plan']}", json=_form_body(plan, end_date="2026-09-30"))
    assert (
        "Example PAC has no occurrence left to buy (its last day is 2026-09-30): a new amount "
        "would buy nothing."
    ) in _refused(client, monkeypatch, plan="Example PAC", amount=250)


def test_two_plans_of_one_name_are_told_apart_by_their_first_buy(client, monkeypatch, market):
    ids = _setup(client)
    made = client.post(
        "/api/accumulation-plans",
        json={
            "name": "Example PAC", "amount": 100.0, "currency": "EUR", "frequency": "monthly",
            "execution": "whole_units", "source_institution_id": ids["broker"],
            "start_date": "2026-11-20", "end_date": None,
            "targets": [{"symbol": "XWLD.MI", "isin": None, "asset_name": None,
                         "institution_id": ids["broker"], "weight": 1}],
        },
    )
    assert made.status_code == 201, made.text
    assert (
        "2 PACs are called 'Example PAC': say which by the day of its first buy (first_buy)"
    ) in _refused(client, monkeypatch, plan="Example PAC", amount=250)
    card = _draw(client, monkeypatch, plan="Example PAC", amount=150, first_buy="2026-11-20")
    assert card["title"] == "change PAC amount: Example PAC, 100.00 → 150.00 EUR from 2026-11-20"


def test_a_card_goes_stale_when_the_catch_up_buys_the_occurrence_it_names(client, monkeypatch, market):
    """Drawn while the occurrence of the 15th waited for its close, confirmed
    after the catch-up bought it at the old amount: what the card said is no
    longer what would happen."""
    _setup(client)
    market("2026-10-15")
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    market("2026-10-16")
    # 300.00 and the 36.00 carried: 7 units.
    assert _catch_up(client) == [("2026-10-15", "2026-10-15", 7.0, 336.0)]
    refused = _confirm(client, monkeypatch, card)
    assert refused.status_code == 409
    (plan,) = client.get("/api/accumulation-plans").json()
    assert plan["amount"] == 300.0


def test_a_card_goes_stale_when_the_plan_moves_on_the_form(client, monkeypatch, market):
    ids = _setup(client)
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    plan = client.get(f"/api/accumulation-plans/{ids['plan']}").json()
    client.put(f"/api/accumulation-plans/{ids['plan']}", json=_form_body(plan, amount=280.0))
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert client.get(f"/api/accumulation-plans/{ids['plan']}").json()["amount"] == 280.0


def test_a_rejected_card_writes_nothing(client, monkeypatch, market):
    _setup(client)
    before = _records(client)
    card = _draw(client, monkeypatch, plan="Example PAC", amount=250)
    _script(monkeypatch, [[("text", "Kept.")]])
    assert client.post(
        f"/api/chat/cards/{card['card_id']}", json={"decision": "reject"}
    ).status_code == 200
    assert _records(client) == before
