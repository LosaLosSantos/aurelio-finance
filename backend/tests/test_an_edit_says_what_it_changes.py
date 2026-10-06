"""An edit writes the columns it named, and leaves the rest of the row alone.

`crud._update` used to be a full replace of every settable column, which is
what a `*Create` describes — a row has to start complete. On an edit that same
payload is a lie: a form with no box for `cash_institution_id` sends no key,
pydantic parses the absence as None, and the replace writes that None over the
account that actually paid for the buy. Nothing complains, the net worth does
not move, and there is no box to type the fact back into.

The rule that replaced it is one sentence — **a request writes what it said** —
and it lives in one place, `crud._update`, which is what the first test here
holds it to. The other two say what the sentence means, per shape rather than
per field: resend a row unchanged with one key left out and the row does not
move; send that key as `null` and it empties.

The danger in the obvious fix is the opposite one, and it is why the second
half exists: if a form emptied a box by sending NOTHING, a partial update would
silently stop clearing, and an edit that works today would quietly do nothing.
All thirteen forms that PUT were read before this was written, and none of them
does that — every box that can be emptied sends an explicit `null`
(`Portfolio.tsx`, `Wealth.tsx`, `CashFlow.tsx`, `Debts.tsx`, `Goals.tsx`,
`RealAssets.tsx`, `listEditor.ts`, `DatedAmountEditor.tsx`). The fourteenth
resource, a situation, has no edit form at all.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app import crud

TODAY = "2026-02-02"
EARLIER = "2026-01-01"

# Three columns where an empty box does not mean "nothing": it means "work it
# out". A ledger entry's `amount` and a transfer's `to_amount` are the cash the
# account moved by, computed from the figures beside them at the rate of their
# own day; a holding's `value` is quantity x unit price. Emptying one is how
# the forms ASK for that, so the generic pair below cannot say it comes back a
# null — and what each DOES come back as is asserted, one test each:
# `amount` and `value` at the bottom of this file, `to_amount` in
# test_a_transfer_across_two_currencies.py, where the rate it is worked out at
# is the subject.
WORKED_OUT = {"amount", "to_amount", "value"}


# --- One complete example of every editable resource -----------------------
#
# Complete meaning every optional field filled in, so that anything an edit
# fails to preserve shows up as a None — and self-consistent, so that resending
# the same body must leave the row exactly as it was. Each builder returns the
# URL of the row, the body it was created with, and the row as it came back —
# read from the create rather than fetched, because two of the fourteen have no
# GET of their own.


def _institution(client, name="Broker B"):
    return client.post("/api/institutions", json={"name": name}).json()["id"]


def institution(client):
    body = {"name": "Broker A", "type": "broker", "notes": "the old account"}
    made = client.post("/api/institutions", json=body).json()
    return f"/api/institutions/{made['id']}", body, made


def snapshot(client):
    iid = _institution(client)
    body = {"date": EARLIER, "note": "read off the app"}
    made = client.post(f"/api/institutions/{iid}/snapshots", json=body).json()
    return f"/api/snapshots/{made['id']}", body, made


def holding(client):
    iid = _institution(client)
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": EARLIER}
    ).json()["id"]
    body = {
        "asset_name": "Vanguard FTSE All-World",
        "asset_class": "fund_etf",
        "symbol": "VWCE.MI",
        "isin": "IE00BK5BQT80",
        "quantity": 10.0,
        "unit_price": 30.0,
        "value": 300.0,
        "cost_basis": 280.0,
        "cost_estimated": True,
        "currency": "EUR",
        "distribution_policy": "acc",
    }
    made = client.post(f"/api/snapshots/{sid}/holdings", json=body).json()
    return f"/api/holdings/{made['id']}", body, made


def real_asset(client):
    body = {
        "name": "Milan flat",
        "category": "real_estate",
        "currency": "EUR",
        "acquisition_date": EARLIER,
        "acquisition_value": 250000.0,
        "notes": "bought with the mortgage below",
    }
    made = client.post("/api/real-assets", json=body).json()
    return f"/api/real-assets/{made['id']}", body, made


def real_asset_valuation(client):
    aid = client.post(
        "/api/real-assets", json={"name": "Milan flat", "currency": "EUR"}
    ).json()["id"]
    body = {"date": EARLIER, "value": 260000.0, "note": "agency estimate"}
    made = client.post(f"/api/real-assets/{aid}/valuations", json=body).json()
    return f"/api/real-asset-valuations/{made['id']}", body, made


def _cash_flow_body(tag_field: str, tag_value: str, iid: int) -> dict:
    return {
        "name": "Rent",
        tag_field: tag_value,
        "category": "housing",
        "amount": 1200.0,
        "currency": "EUR",
        "frequency": "monthly",
        "institution_id": iid,
        "start_date": EARLIER,
        "end_date": TODAY,
        "notes": "index-linked",
    }


def income_source(client):
    body = _cash_flow_body("kind", "active", _institution(client))
    made = client.post("/api/income-sources", json=body).json()
    return f"/api/income-sources/{made['id']}", body, made


def expense(client):
    body = _cash_flow_body("nature", "essential", _institution(client))
    made = client.post("/api/expenses", json=body).json()
    return f"/api/expenses/{made['id']}", body, made


def goal(client):
    body = {
        "name": "House deposit",
        "type": "target_amount",
        "currency": "EUR",
        "target_amount": 50000.0,
        "target_date": "2030-01-01",
        "current_amount": 12000.0,
        "monthly_contribution": 500.0,
        "notes": "two years of saving",
    }
    made = client.post("/api/goals", json=body).json()
    return f"/api/goals/{made['id']}", body, made


def cash_anchor(client):
    iid = _institution(client)
    body = {"date": EARLIER, "amount": 10000.0, "currency": "EUR", "note": "statement"}
    made = client.post(f"/api/institutions/{iid}/cash-anchors", json=body).json()
    return f"/api/cash-anchors/{made['id']}", body, made


def transfer(client):
    body = {
        "date": EARLIER,
        "from_institution_id": _institution(client, "Broker B"),
        "to_institution_id": _institution(client, "Broker A"),
        "amount": 500.0,
        "currency": "EUR",
        "to_amount": 500.0,
        "to_currency": "EUR",
        "note": "moved for the buy",
    }
    made = client.post("/api/transfers", json=body).json()
    return f"/api/transfers/{made['id']}", body, made


def transaction(client):
    body = {
        "kind": "buy",
        "date": TODAY,
        "institution_id": _institution(client, "Broker A"),
        "cash_institution_id": _institution(client, "Broker B"),
        "asset_name": "Vanguard FTSE All-World",
        "symbol": "VWCE.MI",
        "isin": "IE00BK5BQT80",
        "asset_class": "fund_etf",
        "quantity": 10.0,
        "unit_price": 30.0,
        "fees": 0.0,
        "amount": 300.0,
        "currency": "EUR",
        "price_currency": "EUR",
        "note": "bought on the phone",
    }
    made = client.post("/api/transactions", json=body).json()
    return f"/api/transactions/{made['id']}", body, made


def liability(client):
    aid = client.post(
        "/api/real-assets", json={"name": "Milan flat", "currency": "EUR"}
    ).json()["id"]
    body = {
        "name": "Home mortgage",
        "kind": "mortgage",
        "currency": "EUR",
        "interest_rate": 3.2,
        "real_asset_id": aid,
        "notes": "fixed for ten years",
    }
    made = client.post("/api/liabilities", json=body).json()
    return f"/api/liabilities/{made['id']}", body, made


def liability_balance(client):
    lid = client.post(
        "/api/liabilities", json={"name": "Home mortgage", "currency": "EUR"}
    ).json()["id"]
    body = {"date": EARLIER, "balance": 180000.0, "note": "after the January payment"}
    made = client.post(f"/api/liabilities/{lid}/balances", json=body).json()
    return f"/api/liability-balances/{made['id']}", body, made


def accumulation_plan(client):
    iid = _institution(client)
    body = {
        "name": "PAC All-World",
        "amount": 500.0,
        "currency": "EUR",
        "frequency": "monthly",
        "execution": "whole_units",
        "start_date": EARLIER,
        "end_date": "2030-01-01",
        "source_institution_id": iid,
        "notes": "raise it next year",
        "targets": [
            {
                "symbol": "VWCE.MI",
                "isin": "IE00BK5BQT80",
                "asset_name": "Vanguard FTSE All-World",
                "institution_id": iid,
                "weight": 1.0,
            }
        ],
    }
    made = client.post("/api/accumulation-plans", json=body).json()
    return f"/api/accumulation-plans/{made['id']}", body, made


# Keyed by the crud function each one goes through, so that the coverage check
# below can be about crud rather than about this file's own imagination.
EDITABLE = {
    "update_institution": institution,
    "update_snapshot": snapshot,
    "update_holding": holding,
    "update_real_asset": real_asset,
    "update_real_asset_valuation": real_asset_valuation,
    "update_income_source": income_source,
    "update_expense": expense,
    "update_goal": goal,
    "update_cash_anchor": cash_anchor,
    "update_transfer": transfer,
    "update_transaction": transaction,
    "update_liability": liability,
    "update_liability_balance": liability_balance,
    "update_accumulation_plan": accumulation_plan,
}
RESOURCES = sorted(EDITABLE)


def _updates_in_crud() -> set[str]:
    """Every `update_*` in crud.py that is handed a `*Create` payload.

    Read out of the source rather than listed, for the reason `_columns` exists
    at all: a list written by hand is a line somebody forgets. A fifteenth
    editable resource fails this file on the day it is added, not on the day it
    destroys something.
    """
    tree = ast.parse(pathlib.Path(crud.__file__).read_text(encoding="utf-8"))
    return {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and fn.name.startswith("update_")
        and any(
            isinstance(a.annotation, ast.Attribute)
            and a.annotation.attr.endswith("Create")
            for a in fn.args.args
        )
    }


def _facts(row: dict) -> dict:
    """A row as a reader would see it, without the identities the database
    hands out to CHILD rows.

    A plan's targets ARE its composition, so an edit that names them replaces
    them wholesale and the replacements are new rows with new ids. The
    composition is the fact under test; which row numbers carry it is not.
    """
    if isinstance(row, dict):
        return {k: _facts(v) for k, v in row.items() if k not in {"id", "position"}}
    if isinstance(row, list):
        return [_facts(v) for v in row]
    return row


# --- The rule lives in one place -------------------------------------------


def test_every_editable_resource_is_covered_here():
    """The two tests below are only worth having if they look at everything.

    Both directions: a resource crud can update and this file does not build is
    a hole, and a name here that crud no longer has is a test measuring
    nothing.
    """
    assert set(EDITABLE) == _updates_in_crud()


def test_no_update_writes_a_payload_of_its_own():
    """One place, the way the allow-list is one place.

    The failure this replaced was thirteen hand-written field-by-field copies
    (`_columns`), and the fix must not walk back into it: an update that built
    its own payload and handed it to `_apply` would be free to decide on its
    own what an absent key means. So every `update_*` goes through `_update`,
    and `_update` is the only thing that reads `model_fields_set`.

    `update_accumulation_plan` touches its row before delegating — it zeroes a
    carried remainder that no longer means what it meant — which is why this
    asks that `_update` is reached, not that nothing else happens.
    """
    tree = ast.parse(pathlib.Path(crud.__file__).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in _updates_in_crud()):
            continue
        called = {
            n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_update" in called, f"{fn.name} does not go through _update"
        assert "_apply" not in called, (
            f"{fn.name} writes its own payload: which columns one request may "
            f"touch is _update's decision, in one place"
        )


# --- What the rule means ---------------------------------------------------


@pytest.mark.parametrize("resource", RESOURCES)
def test_an_edit_leaves_alone_the_columns_it_did_not_mention(client, resource):
    """Resend a row exactly as it stands, with one key left out. Nothing moves.

    This is the defect, per shape: the ledger form has no box for
    `cash_institution_id`, an asset class or a note, so it sends none of the
    three, and each edit used to write a None over all of them. Measured before
    the fix, on the row this test builds: 300.00 of spending moved from the
    funding account to the holding one, and `fund_etf` became nothing.

    A key the request cannot leave out is answered 422 by the schema — a buy
    with no ticker, a balance with no date — and there is nothing to preserve
    about a field that must always be stated, so those are skipped rather than
    asserted about.
    """
    url, body, before = EDITABLE[resource](client)

    preserved = []
    for field in sorted(body):
        without = {k: v for k, v in body.items() if k != field}
        answer = client.put(url, json=without)
        if answer.status_code == 422:
            continue  # the schema refuses the row without it; nothing to keep
        assert answer.status_code == 200, answer.text
        assert _facts(answer.json()) == _facts(before), (
            f"{resource}: leaving {field} out of the body changed the row"
        )
        preserved.append(field)

    assert preserved, f"{resource}: no field of it can be left out at all"


@pytest.mark.parametrize("resource", RESOURCES)
def test_an_edit_empties_the_columns_it_sends_empty(client, resource):
    """The other half, and the reason the fix is not simply "merge".

    A reader who deletes the text in a note means it. Told apart from the
    absence above by the key being there with a `null` under it, which is the
    gesture every form in this app already makes for an emptied box — so a
    partial update does not quietly stop clearing what clearing used to work
    on.
    """
    url, body, _ = EDITABLE[resource](client)

    cleared = []
    for field in sorted(body):
        if field in WORKED_OUT:
            continue
        answer = client.put(url, json={**body, field: None})
        if answer.status_code == 422:
            continue  # the column may not be empty at all
        assert answer.status_code == 200, answer.text
        assert answer.json()[field] in (None, []), (
            f"{resource}: sending {field} as null did not empty it"
        )
        cleared.append(field)
        client.put(url, json=body)  # put it back for the next field

    assert cleared, f"{resource}: no field of it can be emptied at all"


# --- The shapes the generic pair cannot state ------------------------------


def test_an_edited_buy_still_comes_out_of_the_account_that_paid(client):
    """The reproduction, end to end, in the cash the reader reads.

    A buy of 300.00 held at Broker A and funded from Broker B, then one edit that
    changes the quantity and sends exactly what the ledger form owns. Before
    the fix the funding account was handed its 300.00 back and the holding one
    was charged instead — 9,700/5,000 became 10,000/4,700 — with the net worth
    unchanged, so nothing anywhere complained.
    """
    broker_b = _institution(client, "Broker B")
    broker_a = _institution(client, "Broker A")
    for iid, amount in ((broker_b, 10_000.0), (broker_a, 5_000.0)):
        client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": EARLIER, "amount": amount, "currency": "EUR"},
        )
    tx = client.post(
        "/api/transactions",
        json={
            "kind": "buy", "date": TODAY, "institution_id": broker_a,
            "cash_institution_id": broker_b, "asset_name": "Vanguard FTSE All-World",
            "symbol": "VWCE.MI", "isin": "IE00BK5BQT80", "asset_class": "fund_etf",
            "quantity": 10, "unit_price": 30, "fees": 0, "amount": 300.0,
            "currency": "EUR", "price_currency": "EUR", "note": "bought on the phone",
        },
    ).json()

    def cash() -> dict[str, float]:
        return {
            row["institution_name"]: round(row["projected"], 2)
            for row in client.get("/api/cash/positions").json()
        }

    assert cash() == {"Broker B": 9_700.0, "Broker A": 5_000.0}

    # Portfolio.tsx, the buy branch: no cash institution, no ISIN, no class,
    # no note — the form has no box for any of them.
    edited = client.put(
        f"/api/transactions/{tx['id']}",
        json={
            "kind": "buy", "date": TODAY, "institution_id": broker_a,
            "asset_name": "Vanguard FTSE All-World", "symbol": "VWCE.MI",
            "quantity": 11, "unit_price": 30, "fees": 0,
            "currency": "EUR", "price_currency": "EUR", "amount": None,
        },
    )
    assert edited.status_code == 200, edited.text
    after = edited.json()
    assert after["cash_institution_id"] == broker_b
    assert (after["asset_class"], after["isin"]) == ("fund_etf", "IE00BK5BQT80")
    assert after["note"] == "bought on the phone"
    assert after["amount"] == 330.0  # the one figure the edit did ask about
    assert cash() == {"Broker B": 9_670.0, "Broker A": 5_000.0}


def test_a_worked_out_figure_is_worked_out_again_only_when_it_is_asked_for(client):
    """`amount` empty means "work it out"; `amount` absent means "not my subject".

    Two gestures with two meanings, on the one column where an empty box is
    already a request rather than a blank. The form makes the first one on
    every save, which is what keeps the cash figure in step with the quantity;
    the second is what protects a figure copied off a statement from an edit
    that was about something else.
    """
    iid = _institution(client, "Broker A")
    buy = client.post(
        "/api/transactions",
        json={
            "kind": "buy", "date": TODAY, "institution_id": iid,
            "asset_name": "Vanguard FTSE All-World", "symbol": "VWCE.MI",
            "quantity": 10, "unit_price": 30, "fees": 0, "amount": 307.42,
            "currency": "EUR", "price_currency": "EUR",
        },
    ).json()
    assert buy["amount"] == 307.42  # the figure on the statement, fees and all

    body = {
        "kind": "buy", "date": TODAY, "institution_id": iid,
        "asset_name": "Vanguard FTSE All-World", "symbol": "VWCE.MI",
        "quantity": 10, "unit_price": 30, "fees": 0,
        "currency": "EUR", "price_currency": "EUR", "note": "from the contract note",
    }
    assert client.put(f"/api/transactions/{buy['id']}", json=body).json()["amount"] == 307.42
    assert client.put(
        f"/api/transactions/{buy['id']}", json={**body, "amount": None}
    ).json()["amount"] == 300.0


def test_a_holdings_value_is_worked_out_only_when_there_is_something_to_work_it_out_from(
    client,
):
    """The same two gestures on a holding, and the case that is NOT like a buy.

    On a row with units, an empty `value` box asks for quantity x unit price —
    which is what the qty-mode form sends on every save (`Wealth.tsx`), and
    what keeps the figure in step with an edited quantity. Left out, the stored
    figure stands.

    On an OPAQUE row there is nothing to work it out from: no quantity, no unit
    price, and the value IS the fact. So emptying it empties it, rather than
    quietly reappearing as a zero. That asymmetry with a ledger entry's
    `amount` — which always has a quantity and a price to fall back on — is why
    `_update` leaves an unmentioned column alone instead of re-deriving every
    worked-out one: re-deriving this row's value would have destroyed it.
    """
    iid = _institution(client)
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": EARLIER}
    ).json()["id"]
    priced = {
        "asset_name": "Vanguard FTSE All-World", "symbol": "VWCE.MI",
        "quantity": 10.0, "unit_price": 30.0, "value": 300.0, "currency": "EUR",
    }
    row = client.post(f"/api/snapshots/{sid}/holdings", json=priced).json()
    url = f"/api/holdings/{row['id']}"

    asked = client.put(url, json={**priced, "quantity": 11.0, "value": None})
    assert asked.status_code == 200, asked.text
    assert asked.json()["value"] == 330.0

    left_out = {k: v for k, v in priced.items() if k != "value"}
    assert client.put(url, json={**left_out, "quantity": 12.0}).json()["value"] == 330.0

    opaque = {"asset_name": "Gold bar", "value": 400.0, "currency": "EUR"}
    bar = client.post(f"/api/snapshots/{sid}/holdings", json=opaque).json()
    emptied = client.put(f"/api/holdings/{bar['id']}", json={**opaque, "value": None})
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["value"] is None


def test_a_plan_keeps_the_targets_an_edit_did_not_name(client):
    """A plan's targets are children, and the rule reaches them unchanged.

    Named, they are replaced wholesale — a half-updated composition would leave
    a stale target the next execution keeps buying. Not named, they stay: a
    request that did not mention them is not a request to empty the plan, which
    is what a full replace made of it.
    """
    url, body, _ = accumulation_plan(client)

    kept = client.put(url, json={k: v for k, v in body.items() if k != "targets"})
    assert kept.status_code == 200, kept.text
    assert [t["symbol"] for t in kept.json()["targets"]] == ["VWCE.MI"]

    replaced = client.put(
        url,
        json={
            **body,
            "targets": [
                {**body["targets"][0], "symbol": "SWDA.MI", "asset_name": "iShares World"}
            ],
        },
    )
    assert [t["symbol"] for t in replaced.json()["targets"]] == ["SWDA.MI"]


def test_an_edit_that_never_mentioned_the_plan_keeps_its_carried_remainder(client):
    """The remainder is zeroed by a change of contribution, not by an edit.

    It belongs to the OLD contribution, so a new amount or a new fill model
    starts it again. Reading that from the payload rather than from what the
    request LEAVES the plan with threw it away on every edit that did not
    happen to restate the execution — the same defect one level up.
    """
    from app.database import SessionLocal
    from app import models

    url, body, _ = accumulation_plan(client)
    plan_id = int(url.rsplit("/", 1)[1])
    with SessionLocal() as db:
        db.get(models.AccumulationPlan, plan_id).carried_remainder = 42.0
        db.commit()

    client.put(url, json={k: v for k, v in body.items() if k != "execution"})
    with SessionLocal() as db:
        assert db.get(models.AccumulationPlan, plan_id).carried_remainder == 42.0

    client.put(url, json={**body, "amount": 600.0})
    with SessionLocal() as db:
        assert db.get(models.AccumulationPlan, plan_id).carried_remainder == 0.0
