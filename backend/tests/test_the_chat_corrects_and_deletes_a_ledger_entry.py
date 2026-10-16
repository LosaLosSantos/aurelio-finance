"""The chat corrects and deletes a ledger entry as the ledger form does.

Brief AO, item 2 (2026-10-11). In the reader's second test round (2026-10-08)
the chat was asked to correct the last ledger entry and to delete it, and had
no tool for either. `change_ledger_entry` corrects an entry through the PUT the
ledger form on the Portfolio page sends (`Portfolio.tsx`: every box the form
fills, the ticker upper case, the amount back only when the stored one could
only have come from a statement, else empty, "work it out"), and deletes one
through the function the form's Delete calls, which leaves a PAC's occurrence
or a dividend's day settled (tests/test_a_deleted_entry_stays_deleted.py).
The entry is named by what the reader sees: its day, its kind, its instrument
and, when two match, its amount.

For each write the records after the card equal, field by field, the records
after the form's request on the same starting records. And each card says
what it moves, read by the functions the pages read (the cash register, the
projection): the account's cash today, the units, their average cost; or
that the account's latest balance or situation already holds the entry.

Yahoo is faked (every weekday at 48.00 and 52.00; one dividend of 0.30 a
share), the reader's today pinned. Every name and figure here is invented.
"""

from __future__ import annotations

import datetime
import json

import pytest
from conftest import _empty_every_table
from sqlalchemy import select

from app import advisor, crud, dated, models, prices, schemas
from app.database import SessionLocal

CLOSES = {"XWLD.MI": 48.0, "XBND.MI": 52.0}


@pytest.fixture()
def market(monkeypatch):
    def fetch(symbol, start, end):
        out, day = [], start
        while day < end:
            if day.weekday() < 5:
                out.append((day.isoformat(), CLOSES[symbol]))
            day += datetime.timedelta(days=1)
        return out

    monkeypatch.setattr(prices, "_fetch_close_window", fetch)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda symbol, since: prices.DividendWindow(
            answered=True,
            dividends=[{"date": "2026-09-23", "dps": 0.30}] if symbol == "XDIV.MI" else [],
        ),
    )

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
    call = advisor.ToolCall(id="call_1", name="change_ledger_entry", arguments=json.dumps(arguments))
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


def _catch_up(client) -> list[tuple]:
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    return [(t["kind"], t["plan_occurrence"] or t["date"], t["symbol"], t["quantity"], t["amount"])
            for t in r.json()["created"]]


def _records(client) -> dict:
    """The ledger and the plans as the pages read them, the occurrences settled
    without a buy and the dividends remembered as deleted, without the ids and
    the moments each row was made."""

    def kept(rows):
        return [{k: v for k, v in r.items() if k not in ("id", "created_at")} for r in rows]

    plans = client.get("/api/accumulation-plans").json()
    for p in plans:
        p["targets"] = kept(p["targets"])
    with SessionLocal() as db:
        unfilled = sorted(
            (u.plan_id, u.occurrence, crud.deleted_from_the_ledger(u.reason))
            for u in db.scalars(select(models.PlanUnfilledOccurrence))
        )
        remembered = sorted(
            k for k in db.scalars(select(models.Setting.key)) if k.startswith("dividend_deleted:")
        )
    return {"ledger": kept(client.get("/api/transactions").json()), "plans": kept(plans),
            "unfilled": unfilled, "remembered": remembered}


def _row(client, kind: str, day: str, symbol: str | None = None) -> dict:
    (t,) = [t for t in client.get("/api/transactions").json()
            if t["kind"] == kind and t["date"] == day and (symbol is None or t["symbol"] == symbol)]
    return t


# --- The records every scenario starts from ------------------------------------------------


def _broker(client, name="Broker A", day="2026-06-30", cash=10000.0) -> int:
    iid = client.post("/api/institutions", json={"name": name, "type": "broker"}).json()["id"]
    r = client.post(f"/api/institutions/{iid}/cash-anchors", json={"date": day, "amount": cash, "currency": "EUR"})
    assert r.status_code == 201, r.text
    return iid


def _entry(client, **body) -> dict:
    r = client.post("/api/transactions", json={"currency": "EUR", "price_currency": "EUR", "amount": None, **body})
    assert r.status_code == 201, r.text
    return r.json()


def _hand_buy(client, iid: int) -> dict:
    """10 units at 47.00 and 1.50 of fees: 471.50, worked out."""
    return _entry(client, kind="buy", date="2026-09-10", institution_id=iid,
                  asset_name="Example World UCITS ETF", symbol="XWLD.MI",
                  quantity=10, unit_price=47.0, fees=1.5)


def _stated_buy(client, iid: int) -> dict:
    """5 units at 52.00, the account debited 262.40 by the statement."""
    return _entry(client, kind="buy", date="2026-09-12", institution_id=iid,
                  asset_name="Example Bond UCITS ETF", symbol="XBND.MI",
                  quantity=5, unit_price=52.0, amount=262.4)


def _closed(client, iid: int) -> dict:
    """A bond fund photographed at 750.00 on 1 July, closed for 800.00."""
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-07-01"}).json()["id"]
    held = client.post(f"/api/snapshots/{sid}/holdings",
                       json={"asset_name": "Old Bond Fund", "asset_class": "bond", "value": 750.0, "currency": "EUR"})
    assert held.status_code == 201, held.text
    return _entry(client, kind="close", date="2026-09-25", institution_id=iid,
                  asset_name="Old Bond Fund", symbol=None, amount=800.0, price_currency=None)


def _holder(client) -> int:
    """20 units of a distributing share on 1 September; the catch-up records
    its dividend of 23 September, 20 x 0.30 = 6.00."""
    iid = _broker(client)
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-09-01"}).json()["id"]
    r = client.post(f"/api/snapshots/{sid}/holdings",
                    json={"asset_name": "Example Dividend Share", "asset_class": "equity", "symbol": "XDIV.MI",
                          "quantity": 20, "unit_price": 10, "currency": "EUR", "distribution_policy": "dist"})
    assert r.status_code == 201, r.text
    assert _catch_up(client) == [("dividend", "2026-09-23", "XDIV.MI", 20.0, 6.0)]
    return iid


def _pac(client, *, two_funds: bool = False) -> int:
    """300.00 a month from 15 July at 48.00 (6 units each time, 36.00
    carried by 11 October); or 500.00 at 70/30 on 20 July, 7 units at 48.00
    and 3 at 52.00, 8.00 carried."""
    iid = _broker(client)
    targets = [("XWLD.MI", 70), ("XBND.MI", 30)] if two_funds else [("XWLD.MI", 1)]
    r = client.post(
        "/api/accumulation-plans",
        json={"name": "Example PAC", "amount": 500.0 if two_funds else 300.0, "currency": "EUR",
              "frequency": "monthly", "execution": "whole_units", "source_institution_id": iid,
              "start_date": "2026-07-20" if two_funds else "2026-07-15", "end_date": None,
              "targets": [{"symbol": s, "isin": None, "asset_name": s, "institution_id": iid, "weight": w}
                          for s, w in targets]},
    )
    assert r.status_code == 201, r.text
    _catch_up(client)
    return iid


def _form_body(row: dict, **typed) -> dict:
    """What the ledger form PUTs for an entry opened and saved (`startEdit`,
    then `submit`), with what the reader typed; `amount` is the debit box,
    given by each test as the form would fill it."""
    if row["kind"] == "close":
        body = {"kind": "close", "date": row["date"], "institution_id": row["institution_id"],
                "asset_name": row["asset_name"].strip(),
                "symbol": (row["symbol"] or "").strip().upper() or None,
                "amount": row["amount"], "currency": row["currency"]}
    else:
        body = {"kind": row["kind"], "date": row["date"], "institution_id": row["institution_id"],
                "asset_name": row["asset_name"].strip(), "symbol": (row["symbol"] or "").strip().upper(),
                "quantity": row["quantity"], "unit_price": row["unit_price"],
                "fees": row["fees"] if row["fees"] else 0, "currency": row["currency"],
                "price_currency": row["price_currency"] or row["currency"]}
    return {**body, **typed}


def _by_chat_and_by_form(client, monkeypatch, setup, arguments: dict, form) -> dict:
    """The records after the card, and after the form's request on the same
    starting records: equal, and returned."""
    setup(client)
    card = _draw(client, monkeypatch, **arguments)
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _records(client)

    _empty_every_table()
    setup(client)
    form(client)
    assert _records(client) == by_chat
    return by_chat


# --- The card's write is the form's -------------------------------------------------------


def test_a_buy_corrected_is_the_forms_edit(client, monkeypatch, market):
    def setup(client):
        _hand_buy(client, _broker(client))

    def form(client):
        row = _row(client, "buy", "2026-09-10")
        saved = client.put(f"/api/transactions/{row['id']}",
                           json=_form_body(row, unit_price=47.2, fees=3.0, amount=None))
        assert saved.status_code == 200, saved.text

    after = _by_chat_and_by_form(
        client, monkeypatch, setup,
        {"action": "correct", "date": "2026-09-10", "kind": "buy", "instrument": "XWLD.MI",
         "new_unit_price": 47.2, "new_fees": 3},
        form,
    )
    (row,) = after["ledger"]
    assert (row["unit_price"], row["fees"], row["amount"]) == (47.2, 3.0, 475.0)


def test_a_stated_amount_goes_back_as_the_form_sends_it(client, monkeypatch, market):
    """The debit box opens with a statement's figure, so a new quantity does
    not move it; the card sends it back the same way."""

    def setup(client):
        _stated_buy(client, _broker(client))

    def form(client):
        row = _row(client, "buy", "2026-09-12")
        client.put(f"/api/transactions/{row['id']}", json=_form_body(row, quantity=6, amount=262.4))

    after = _by_chat_and_by_form(
        client, monkeypatch, setup,
        {"action": "correct", "date": "2026-09-12", "kind": "buy", "instrument": "XBND.MI", "new_quantity": 6},
        form,
    )
    (row,) = after["ledger"]
    assert (row["quantity"], row["amount"]) == (6.0, 262.4)


def test_a_close_corrected_is_the_forms_edit_of_its_proceeds(client, monkeypatch, market):
    def setup(client):
        _closed(client, _broker(client))

    def form(client):
        row = _row(client, "close", "2026-09-25")
        client.put(f"/api/transactions/{row['id']}", json=_form_body(row, amount=812.3))

    after = _by_chat_and_by_form(
        client, monkeypatch, setup,
        {"action": "correct", "date": "2026-09-25", "kind": "close", "instrument": "Old Bond Fund",
         "new_amount": 812.3},
        form,
    )
    assert after["ledger"][0]["amount"] == 812.3


def test_a_dividend_corrected_is_the_forms_correct_this_one(client, monkeypatch, market):
    """"Correct this one" keeps the row's day and takes the credit typed in
    the debit box."""

    def form(client):
        row = _row(client, "dividend", "2026-09-23")
        client.put(f"/api/transactions/{row['id']}", json=_form_body(row, amount=4.41))

    after = _by_chat_and_by_form(
        client, monkeypatch, _holder,
        {"action": "correct", "date": "2026-09-23", "kind": "dividend", "instrument": "XDIV.MI",
         "new_amount": 4.41},
        form,
    )
    (row,) = after["ledger"]
    assert (row["date"], row["amount"], row["estimated"]) == ("2026-09-23", 4.41, False)
    assert _catch_up(client) == []


def test_an_entry_deleted_is_the_forms_delete(client, monkeypatch, market):
    def setup(client):
        _hand_buy(client, _broker(client))

    def form(client):
        assert client.delete(f"/api/transactions/{_row(client, 'buy', '2026-09-10')['id']}").status_code == 204

    after = _by_chat_and_by_form(
        client, monkeypatch, setup,
        {"action": "delete", "date": "2026-09-10", "kind": "buy", "instrument": "XWLD.MI"},
        form,
    )
    assert after["ledger"] == []


def test_a_pac_buy_deleted_is_the_forms_delete_and_its_occurrence_stays_settled(client, monkeypatch, market):
    def form(client):
        row = _row(client, "buy", "2026-09-15")
        assert client.delete(f"/api/transactions/{row['id']}").status_code == 204

    after = _by_chat_and_by_form(
        client, monkeypatch, _pac,
        {"action": "delete", "date": "2026-09-15", "kind": "buy", "instrument": "XWLD.MI"},
        form,
    )
    assert after["unfilled"] == [(1, "2026-09-15", True)]
    assert after["plans"][0]["carried_remainder"] == 0.0
    assert _catch_up(client) == []


def test_a_dividend_deleted_is_the_forms_delete_and_is_not_recorded_again(client, monkeypatch, market):
    def form(client):
        client.delete(f"/api/transactions/{_row(client, 'dividend', '2026-09-23')['id']}")

    after = _by_chat_and_by_form(
        client, monkeypatch, _holder,
        {"action": "delete", "date": "2026-09-23", "kind": "dividend", "instrument": "XDIV.MI"},
        form,
    )
    assert after["ledger"] == [] and after["remembered"] == ["dividend_deleted:1:XDIV.MI:2026-09-23"]
    assert _catch_up(client) == []


# --- Named by what the reader sees -----------------------------------------------------------


def test_two_entries_alike_are_told_apart_by_their_amount(client, monkeypatch, market):
    iid = _broker(client)
    _hand_buy(client, iid)
    _entry(client, kind="buy", date="2026-09-10", institution_id=iid, asset_name="Example World UCITS ETF",
           symbol="XWLD.MI", quantity=2, unit_price=47.5)
    said = _refused(client, monkeypatch, action="delete", date="2026-09-10", kind="buy", instrument="XWLD.MI")
    assert (
        "2 entries match: 2026-09-10 buy 2 x XWLD.MI = 95.00 EUR; 2026-09-10 buy 10 x XWLD.MI = "
        "471.50 EUR. Say which by its amount, as the picture shows it."
    ) in said
    card = _draw(client, monkeypatch, action="delete", date="2026-09-10", kind="buy",
                 instrument="xwld.mi", amount=95)
    assert card["title"] == "delete buy: 2026-09-10 buy 2 x XWLD.MI = 95.00 EUR"


def test_an_entry_not_in_the_ledger_is_refused_with_what_that_day_holds(client, monkeypatch, market):
    _hand_buy(client, _broker(client))
    assert (
        "No sell of XWLD.MI on 2026-09-10 is in the ledger. On that day: 2026-09-10 buy 10 x "
        "XWLD.MI = 471.50 EUR."
    ) in _refused(client, monkeypatch, action="delete", date="2026-09-10", kind="sell", instrument="XWLD.MI")


def test_a_pac_buy_answers_to_its_occurrences_day_too(client, monkeypatch, market):
    """The occurrence of Saturday 15 August was bought on Monday the 17th;
    its line in the picture names both days."""
    _pac(client)
    card = _draw(client, monkeypatch, action="delete", date="2026-08-15", kind="buy", instrument="XWLD.MI")
    assert card["title"] == "delete buy: 2026-08-17 buy 6 x XWLD.MI = 288.00 EUR (estimated)"


# --- What the cards say ---------------------------------------------------------------------


def test_a_correction_shows_its_diff_and_what_it_moves(client, monkeypatch, market):
    _hand_buy(client, _broker(client))
    card = _draw(client, monkeypatch, action="correct", date="2026-09-10", kind="buy",
                 instrument="XWLD.MI", new_unit_price=47.2, new_fees=3)
    assert card["confirmation"] == "diff"
    assert card["title"] == "correct buy: 2026-09-10 XWLD.MI, 471.50 → 475.00 EUR"
    assert card["diff"] == [
        {"field": "Price", "now": "47.00 EUR", "proposed": "47.20 EUR"},
        {"field": "Fees", "now": "1.50 EUR", "proposed": "3.00 EUR"},
        {"field": "Amount", "now": "471.50 EUR", "proposed": "475.00 EUR"},
        {"field": "Cash at Broker A today", "now": "9528.50 EUR", "proposed": "9525.00 EUR"},
        {"field": "Average cost of XWLD.MI at Broker A", "now": "47.15 EUR", "proposed": "47.50 EUR"},
    ]
    assert card["consequence"] == "A correction: the entry takes these figures."


def test_a_pac_buy_corrected_says_it_keeps_its_occurrence_and_the_carry(client, monkeypatch, market):
    _pac(client)
    card = _draw(client, monkeypatch, action="correct", date="2026-09-15", kind="buy",
                 instrument="XWLD.MI", new_unit_price=48.95, new_fees=2.95)
    assert card["title"] == "correct buy: 2026-09-15 XWLD.MI, 288.00 → 296.65 EUR"
    assert card["diff"] == [
        {"field": "Price", "now": "48.00 EUR", "proposed": "48.95 EUR"},
        {"field": "Fees", "now": "0.00 EUR", "proposed": "2.95 EUR"},
        {"field": "Amount", "now": "288.00 EUR", "proposed": "296.65 EUR"},
        {"field": "Estimated", "now": "yes", "proposed": "no"},
        {"field": "Cash at Broker A today", "now": "9136.00 EUR", "proposed": "9127.35 EUR"},
        {"field": "Average cost of XWLD.MI at Broker A", "now": "48.00 EUR", "proposed": "48.48 EUR"},
    ]
    assert card["consequence"] == (
        "A correction: the entry takes these figures, and it is no longer marked estimated. "
        'It stays the buy of the PAC "Example PAC" for its occurrence of 2026-09-15, so the next '
        "start does not buy that occurrence again, and the plan's carry, 36.00 EUR, stays as it "
        "is: the plan's own reckoning of what whole units could not place at the estimate."
    )


def test_a_pac_buy_deleted_says_its_occurrence_is_not_bought_again_and_invites_the_correction(
    client, monkeypatch, market
):
    _pac(client)
    card = _draw(client, monkeypatch, action="delete", date="2026-09-15", kind="buy", instrument="XWLD.MI")
    assert card["diff"] == [
        {"field": "Entry", "now": "2026-09-15 buy 6 x XWLD.MI = 288.00 EUR (estimated)", "proposed": "deleted"},
        {"field": "Cash at Broker A today", "now": "9136.00 EUR", "proposed": "9424.00 EUR"},
        {"field": "XWLD.MI held at Broker A", "now": "18 units", "proposed": "12 units"},
        {"field": "Carried by Example PAC", "now": "36.00 EUR", "proposed": "0.00 EUR"},
    ]
    assert card["consequence"] == (
        "The entry goes, and nothing brings it back. "
        'The PAC "Example PAC" will not buy its occurrence of 2026-09-15 again. '
        "The plan's carry, 36.00 EUR, goes to zero, and that money stays in Broker A's cash. "
        "If your broker did buy it, correct the entry with the figures from your statement instead."
    )


def test_one_leg_deleted_says_its_occurrence_keeps_the_other(client, monkeypatch, market):
    market("2026-07-21")
    _pac(client, two_funds=True)
    card = _draw(client, monkeypatch, action="delete", date="2026-07-20", kind="buy", instrument="XBND.MI")
    assert (
        'Its occurrence of 2026-07-20 keeps its other buy (XWLD.MI), so the PAC "Example PAC" does '
        "not buy XBND.MI for it again."
    ) in card["consequence"]
    assert {"field": "Carried by Example PAC", "now": "8.00 EUR", "proposed": "0.00 EUR"} in card["diff"]


def test_a_dividend_deleted_says_the_app_will_not_record_it_again(client, monkeypatch, market):
    _holder(client)
    card = _draw(client, monkeypatch, action="delete", date="2026-09-23", kind="dividend", instrument="XDIV.MI")
    assert card["diff"] == [
        {"field": "Entry", "now": "2026-09-23 dividend 20 x XDIV.MI = 6.00 EUR (estimated)", "proposed": "deleted"},
        {"field": "Cash at Broker A today", "now": "10006.00 EUR", "proposed": "10000.00 EUR"},
    ]
    assert card["consequence"] == (
        "The entry goes, and nothing brings it back. The app will not record the dividend of "
        "XDIV.MI with ex-date 2026-09-23 at Broker A again. If your broker paid it, correct it "
        "with the credit from your statement instead."
    )


def test_an_entry_the_latest_balance_and_situation_hold_moves_neither_and_the_card_says_why(
    client, monkeypatch, market
):
    """The copy of the test database has this shape: a plan's buy on the day
    of its account's latest balance and situation. The figures are invented."""
    iid = _broker(client, name="Broker B", day="2026-09-18", cash=4200.0)
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-09-18"}).json()["id"]
    client.post(f"/api/snapshots/{sid}/holdings",
                json={"asset_name": "Example Small Cap", "asset_class": "fund_etf", "symbol": "XSML.DE",
                      "quantity": 30, "unit_price": 8.5, "currency": "EUR"})
    _entry(client, kind="buy", date="2026-09-18", institution_id=iid, asset_name="Example Small Cap",
           symbol="XSML.DE", quantity=30, unit_price=8.5)
    card = _draw(client, monkeypatch, action="delete", date="2026-09-18", kind="buy", instrument="XSML.DE")
    assert card["diff"] == [
        {"field": "Entry", "now": "2026-09-18 buy 30 x XSML.DE = 255.00 EUR", "proposed": "deleted"},
    ]
    assert card["consequence"] == (
        "The entry goes, and nothing brings it back. Broker B's latest balance, of 2026-09-18, "
        "already holds it, so its cash today does not move. Its situation of 2026-09-18 at "
        "Broker B already holds its units, so they do not move."
    )


def test_a_stated_amount_that_stays_is_said(client, monkeypatch, market):
    _stated_buy(client, _broker(client))
    card = _draw(client, monkeypatch, action="correct", date="2026-09-12", kind="buy",
                 instrument="XBND.MI", new_quantity=6)
    assert card["diff"] == [
        {"field": "Units", "now": "5", "proposed": "6"},
        {"field": "XBND.MI held at Broker A", "now": "5 units", "proposed": "6 units"},
        {"field": "Average cost of XBND.MI at Broker A", "now": "52.48 EUR", "proposed": "43.73 EUR"},
    ]
    assert (
        "Its amount, 262.40 EUR, is one stated rather than worked out, so it stays as it is, as "
        "the ledger form keeps it: say the new amount if it changed."
    ) in card["consequence"]


def test_a_price_keeps_the_decimals_it_has(client, monkeypatch, market):
    iid = _broker(client)
    _entry(client, kind="buy", date="2026-09-10", institution_id=iid, asset_name="Example Small Cap",
           symbol="XSML.DE", quantity=10, unit_price=7.183)
    card = _draw(client, monkeypatch, action="correct", date="2026-09-10", kind="buy",
                 instrument="XSML.DE", new_unit_price=7.19)
    assert card["diff"][0] == {"field": "Price", "now": "7.183 EUR", "proposed": "7.19 EUR"}


# --- Refused --------------------------------------------------------------------------------


def test_a_dividend_the_app_recorded_moves_to_the_day_it_was_paid_and_keeps_its_ex_date(
    client, monkeypatch, market
):
    """Brief AZ: the row keeps its ex-date in a column of its own, so the card
    moves it to the day the broker credited it, and the next start does not
    record it again on the ex-date it left. Until then the card refused the
    move, the ex-date being the only key the catch-up had."""
    _holder(client)
    card = _draw(client, monkeypatch, action="correct", date="2026-09-23", kind="dividend",
                 instrument="XDIV.MI", new_date="2026-09-30", new_amount=4.41)
    assert {"field": "Day", "now": "2026-09-23", "proposed": "2026-09-30"} in card["diff"]
    assert (
        "Its ex-date stays 2026-09-23: the app finds this dividend by that day, whatever day it "
        "is dated."
    ) in card["consequence"]
    assert _confirm(client, monkeypatch, card).status_code == 200
    row = _row(client, "dividend", "2026-09-30", "XDIV.MI")
    assert (row["ex_date"], row["amount"], row["estimated"]) == ("2026-09-23", 4.41, False)
    assert _catch_up(client) == []
    market("2026-10-12")
    assert _catch_up(client) == []


def test_a_dividend_of_the_apps_with_no_ex_date_yet_moved_is_found_by_its_window(
    client, monkeypatch, market
):
    """One the reader corrected before rows kept their ex-date, moved on a
    day the market did not answer, so not given its ex-date first: the next
    catch-up finds it in its dividend's window, the only entry there, and
    gives it the ex-date rather than recording the dividend again."""
    _holder(client)
    with SessionLocal() as db:
        row = db.scalars(select(models.Transaction).where(models.Transaction.kind == "dividend")).one()
        row.ex_date, row.estimated = None, False
        db.commit()
    card = _draw(client, monkeypatch, action="correct", date="2026-09-23", kind="dividend",
                 instrument="XDIV.MI", new_date="2026-09-30", new_amount=4.41)
    assert "ex-date" not in card["consequence"]
    assert _confirm(client, monkeypatch, card).status_code == 200
    assert _catch_up(client) == []
    row = _row(client, "dividend", "2026-09-30", "XDIV.MI")
    assert (row["ex_date"], row["amount"]) == ("2026-09-23", 4.41)


def test_a_correction_that_changes_nothing_is_refused_and_an_estimate_confirmed_is_not(
    client, monkeypatch, market
):
    _hand_buy(client, _broker(client))
    assert (
        "The entry already says that: 2026-09-10 buy 10 x XWLD.MI = 471.50 EUR. Nothing would change."
    ) in _refused(client, monkeypatch, action="correct", date="2026-09-10", kind="buy",
                  instrument="XWLD.MI", new_fees=1.5)
    _empty_every_table()
    _pac(client)
    card = _draw(client, monkeypatch, action="correct", date="2026-09-15", kind="buy",
                 instrument="XWLD.MI", new_unit_price=48)
    assert card["diff"] == [{"field": "Estimated", "now": "yes", "proposed": "no"}]


def test_a_close_takes_no_units_price_or_fees(client, monkeypatch, market):
    _closed(client, _broker(client))
    assert "A close has its day and what came back, and no units, price or fees." in _refused(
        client, monkeypatch, action="correct", date="2026-09-25", kind="close",
        instrument="Old Bond Fund", new_fees=2,
    )


def test_an_entry_on_no_account_is_left_to_the_form(client, monkeypatch, market):
    with SessionLocal() as db:
        crud.create_transaction(db, schemas.TransactionCreate(
            kind="buy", date="2026-09-10", asset_name="Example World UCITS ETF", symbol="XWLD.MI",
            quantity=1, unit_price=47.0, currency="EUR", price_currency="EUR"))
    assert (
        "This entry names no account: the ledger form on the Portfolio page saves it once one is picked."
    ) in _refused(client, monkeypatch, action="correct", date="2026-09-10", kind="buy",
                  instrument="XWLD.MI", new_fees=1)


# --- Stale, rejected, done -------------------------------------------------------------------


def test_a_card_goes_stale_when_its_entry_moves_on_the_form(client, monkeypatch, market):
    _hand_buy(client, _broker(client))
    card = _draw(client, monkeypatch, action="correct", date="2026-09-10", kind="buy",
                 instrument="XWLD.MI", new_unit_price=47.2)
    row = _row(client, "buy", "2026-09-10")
    client.put(f"/api/transactions/{row['id']}", json=_form_body(row, unit_price=47.1, amount=None))
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert _row(client, "buy", "2026-09-10")["unit_price"] == 47.1


def test_a_card_goes_stale_when_what_it_says_it_moves_moves(client, monkeypatch, market):
    """A balance recorded after the card was drawn holds the entry: deleting
    it would no longer move the cash the card says it moves."""
    iid = _broker(client)
    _hand_buy(client, iid)
    card = _draw(client, monkeypatch, action="delete", date="2026-09-10", kind="buy", instrument="XWLD.MI")
    client.post(f"/api/institutions/{iid}/cash-anchors", json={"date": "2026-10-01", "amount": 9000.0, "currency": "EUR"})
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert len(client.get("/api/transactions").json()) == 1


def test_a_rejected_card_writes_nothing(client, monkeypatch, market):
    _pac(client)
    before = _records(client)
    card = _draw(client, monkeypatch, action="delete", date="2026-09-15", kind="buy", instrument="XWLD.MI")
    _script(monkeypatch, [[("text", "Kept.")]])
    assert client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "reject"}).status_code == 200
    assert _records(client) == before


def test_the_word_over_a_confirmed_card_says_what_it_did(client, monkeypatch, market):
    _hand_buy(client, _broker(client))
    card = _draw(client, monkeypatch, action="correct", date="2026-09-10", kind="buy",
                 instrument="XWLD.MI", new_fees=3)
    (said,) = [e["card"] for e in _events(_confirm(client, monkeypatch, card)) if e["kind"] == "decided"]
    assert said["done"] == "Corrected"
    assert [(r["label"], r["value"]) for r in said["receipt"]] == [
        ("Now", "2026-09-10 buy 10 x XWLD.MI = 473.00 EUR"),
    ]
    card = _draw(client, monkeypatch, action="delete", date="2026-09-10", kind="buy", instrument="XWLD.MI")
    (said,) = [e["card"] for e in _events(_confirm(client, monkeypatch, card)) if e["kind"] == "decided"]
    assert said["done"] == "Deleted"
    assert [(r["label"], r["value"]) for r in said["receipt"]] == [
        ("Deleted", "2026-09-10 buy 10 x XWLD.MI = 473.00 EUR"),
    ]


# --- The form's rule for an amount it sends back ------------------------------------------------


def _tx(**over) -> models.Transaction:
    row = {"kind": "buy", "quantity": 10.0, "unit_price": 30.0, "fees": 0.0, "amount": 300.0,
           "currency": "EUR", "price_currency": "EUR", "fx_as_of": None}
    return models.Transaction(**{**row, **over})


@pytest.mark.parametrize(
    "over, stated",
    [
        ({}, False),
        ({"amount": 307.42}, True),
        ({"unit_price": 30.05, "amount": 10 * 30.05}, False),
        ({"unit_price": 30.05, "amount": 300.51}, True),
        ({"unit_price": 30.05, "amount": 300.504}, False),
        ({"unit_price": 30.05, "amount": 300.506}, True),
        ({"kind": "dividend", "quantity": 1, "unit_price": 0.125, "amount": 0.12}, False),
        ({"kind": "dividend", "quantity": 30, "unit_price": 0.352345, "amount": 10.57}, False),
        ({"kind": "dividend", "quantity": 30, "unit_price": 0.352345, "amount": 10.58}, True),
        ({"price_currency": "USD", "amount": 240, "fx_as_of": "2026-09-11"}, False),
        ({"price_currency": "USD", "amount": 241.13, "fx_as_of": None}, True),
        ({"price_currency": None, "amount": 300}, False),
        ({"price_currency": None, "amount": 307.42}, True),
        ({"kind": "close", "quantity": 0, "unit_price": 0, "amount": 412}, False),
        ({"kind": "dividend", "quantity": 100, "unit_price": 0.5, "amount": 50}, False),
        ({"kind": "dividend", "quantity": 100, "unit_price": 0.5, "amount": 43.75}, True),
    ],
)
def test_an_amount_is_a_statements_by_the_ledger_forms_own_rule(over, stated):
    """The cases of `tests/statedAmount.test.ts`, case for case: the card
    sends an amount back exactly when the form's debit box opens with it."""
    assert crud.amount_was_stated(_tx(**over)) is stated
