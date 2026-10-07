"""Every amount the app works out for a ledger entry is in cents.

`crud._transaction_columns` rounded the cash figure only when it converted it
at a rate (`if fx_day is not None`). In the price's own currency it stored the
float product, so a dividend or a plan's buy kept a fraction of a cent (seen
in brief AF's browser check, 2026-10-05, on a dividend in the account's own
currency). Since brief AI every path is rounded: the same currency, pence into
pounds, and a rate, the fees included. An amount the reader states is kept as
stated, and a row stored before is not rewritten: an edit that leaves its
amount to be worked out puts it in cents. Every name and amount here is
invented.
"""

from __future__ import annotations

import datetime

from app import models, pac, prices
from app.database import SessionLocal


def _bank(client) -> int:
    r = client.post("/api/institutions", json={"name": "Banca Alfa"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _entry(client, bank: int, **fields) -> dict:
    body = {"institution_id": bank, "asset_name": "Fondo Alfa", "symbol": "ALFA.MI",
            "date": "2026-05-04", "currency": "EUR", "price_currency": "EUR", **fields}
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_dividend_in_the_account_s_own_currency_is_credited_in_cents(client):
    # 30 x 0.352345 is 10.570350000000001 as a double.
    row = _entry(client, _bank(client), kind="dividend", quantity=30, unit_price=0.352345)
    assert row["amount"] == 10.57
    assert row["fx_as_of"] is None


def test_a_buy_in_the_account_s_own_currency_is_debited_in_cents(client):
    row = _entry(client, _bank(client), kind="buy", quantity=13, unit_price=7.019)
    assert row["amount"] == 91.25


def test_the_fees_do_not_leave_the_amount_off_a_cent(client):
    # 0.10 + 0.20 is 0.30000000000000004 as a double.
    row = _entry(client, _bank(client), kind="buy", quantity=1, unit_price=0.10, fees=0.20)
    assert row["amount"] == 0.3


def test_pence_into_pounds_is_a_figure_in_pence_too(client):
    row = _entry(client, _bank(client), kind="buy", symbol="ALFA.L", quantity=7,
                 unit_price=101.3, currency="GBP", price_currency="GBp")
    assert row["amount"] == 7.09
    assert row["fx_as_of"] is None, "a minor unit is not a rate"


def test_an_amount_the_reader_states_is_kept_as_stated(client):
    row = _entry(client, _bank(client), kind="dividend", quantity=30, unit_price=0.352345,
                 amount=10.5703)
    assert row["amount"] == 10.5703


def test_a_plan_buy_is_debited_in_cents_and_carries_the_rest(client, monkeypatch):
    bank = _bank(client)
    monkeypatch.setattr(
        prices, "get_price_on",
        lambda symbol, on: {"symbol": symbol, "price": 7.019, "as_of": on.isoformat()},
    )
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    r = client.post("/api/accumulation-plans", json={
        "name": "Piano Alfa", "amount": 100, "currency": "EUR", "frequency": "monthly",
        "start_date": "2026-05-04", "source_institution_id": bank,
        "targets": [{"symbol": "ALFA.MI", "asset_name": "Fondo Alfa", "institution_id": bank}],
    })
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=datetime.date(2026, 5, 10))
        assert len(out["created"]) == 1
        plan = db.get(models.AccumulationPlan, r.json()["id"])
        carried = plan.carried_remainder
    buy = client.get("/api/transactions").json()[0]
    # 14 x 7.019 is 98.266.
    assert (buy["quantity"], buy["amount"]) == (14.0, 98.27)
    assert carried == 1.73  # what the stored amount left of the 100


def test_a_row_stored_before_is_not_rewritten_until_it_is_edited(client):
    bank = _bank(client)
    with SessionLocal() as db:
        old = models.Transaction(
            kind="dividend", date="2026-05-04", institution_id=bank, asset_name="Fondo Alfa",
            symbol="ALFA.MI", quantity=30, unit_price=0.352345, fees=0.0,
            amount=10.570350000000001, currency="EUR", price_currency="EUR", estimated=True,
        )
        db.add(old)
        db.commit()
        tx_id = old.id

    assert client.get(f"/api/transactions/{tx_id}").json()["amount"] == 10.570350000000001

    # The pencil, the amount box left empty: the app works it out again.
    r = client.put(f"/api/transactions/{tx_id}", json={
        "kind": "dividend", "date": "2026-05-04", "institution_id": bank,
        "asset_name": "Fondo Alfa", "symbol": "ALFA.MI", "quantity": 30,
        "unit_price": 0.352345, "fees": 0, "currency": "EUR", "price_currency": "EUR",
        "amount": None,
    })
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 10.57
