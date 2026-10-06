"""A transfer between accounts in two currencies is two sums.

500 dollars leave the dollar account; what reaches the euro account is what
the conversion made of them on the day, and that is a fixed sum. The transfer
kept one figure and the register put the same 500 dollars into the euro
account, restated at the rate of every reading — a balance that drifted with
the dollar, where the bank statement shows a number that never moves.

The feed below publishes 1.25 dollars to the euro on the day of the transfer
and 1.00 today, so the wrong day's rate cannot pass for rounding: 500 dollars
are 400.00 euro on their day and 500.00 today.
"""

from __future__ import annotations

import datetime

import pytest

from app import fx

TODAY = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
MOVED = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()


@pytest.fixture()
def feed(monkeypatch) -> list[tuple]:
    asked: list[tuple] = []

    def fetch(base, start, end=None):
        asked.append((base, start, end))
        return {DAY: {"USD": 1.25}, MOVED: {"USD": 1.10}, TODAY: {"USD": 1.00}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def _accounts(client) -> tuple[int, int]:
    wise = client.post("/api/institutions", json={"name": "Wise"}).json()["id"]
    broker_a = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    for iid, currency in ((wise, "USD"), (broker_a, "EUR")):
        r = client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR_DAY, "amount": 1000, "currency": currency},
        )
        assert r.status_code == 201, r.text
    return wise, broker_a


def _transfer(client, wise, broker_a, **fields):
    return client.post(
        "/api/transfers",
        json={
            "date": DAY, "from_institution_id": wise, "to_institution_id": broker_a,
            "amount": 500, "currency": "USD", "to_currency": "EUR", **fields,
        },
    )


def test_what_arrived_is_fixed_at_the_rate_of_the_transfers_day(client, feed):
    wise, broker_a = _accounts(client)

    r = _transfer(client, wise, broker_a)

    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["amount"], t["currency"]) == (500.0, "USD")
    assert (t["to_amount"], t["to_currency"], t["fx_as_of"]) == (400.0, "EUR", DAY)
    # The source loses its dollars, converted at today's rate like every
    # dollar it holds; the destination gains the euro it was credited.
    source = client.get(f"/api/institutions/{wise}/cash").json()
    destination = client.get(f"/api/institutions/{broker_a}/cash").json()
    assert (source["transfers_out"], source["projected"]) == (500.0, 500.0)
    assert (destination["transfers_in"], destination["projected"]) == (400.0, 1400.0)


def test_moving_the_date_works_the_arrival_out_again_at_the_new_days_rate(client, feed):
    wise, broker_a = _accounts(client)
    tid = _transfer(client, wise, broker_a).json()["id"]

    # `to_amount: null` is the gesture the form makes for an arrival the app
    # worked out: a credit the reader typed comes back into its box and this
    # one is left empty, so that changing the date works it out again
    # (CashFlow.tsx, startEdit). Said rather than left out, because an edit no
    # longer touches what it did not mention — see `crud._update`.
    r = client.put(
        f"/api/transfers/{tid}",
        json={"date": MOVED, "from_institution_id": wise, "to_institution_id": broker_a,
              "amount": 500, "currency": "USD", "to_currency": "EUR", "to_amount": None},
    )

    assert r.status_code == 200, r.text
    assert (r.json()["to_amount"], r.json()["fx_as_of"]) == (454.55, MOVED)

    # Corrected with the statement: the typed figure stands, and no longer
    # claims the ECB day it replaced.
    r = client.put(
        f"/api/transfers/{tid}",
        json={"date": MOVED, "from_institution_id": wise, "to_institution_id": broker_a,
              "amount": 500, "currency": "USD", "to_currency": "EUR", "to_amount": 451.2},
    )
    assert (r.json()["to_amount"], r.json()["fx_as_of"]) == (451.2, None)


def test_the_figure_on_the_statement_is_kept_as_typed(client, feed):
    """The bank's rate is not the ECB's, and its spread is real money: the
    amount the destination was credited wins, and says it was not derived."""
    wise, broker_a = _accounts(client)

    t = _transfer(client, wise, broker_a, to_amount=396.8).json()

    assert (t["to_amount"], t["fx_as_of"]) == (396.8, None)
    assert client.get(f"/api/institutions/{broker_a}/cash").json()["transfers_in"] == 396.8


def test_without_a_final_rate_for_the_day_the_arrival_has_to_be_stated(client, monkeypatch):
    """Today, before the ECB publishes: yesterday's rate is the one in force,
    and a sum fixed at it would keep yesterday's rate for good. Refused, with
    the one figure that settles it asked for."""
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {YESTERDAY: {"USD": 1.25}}
    )
    wise, broker_a = _accounts(client)

    refused = _transfer(client, wise, broker_a, date=TODAY)

    assert refused.status_code == 422, refused.text
    assert "State the amount that arrived" in refused.json()["detail"]
    assert client.get("/api/transfers").json() == []

    stated = _transfer(client, wise, broker_a, date=TODAY, to_amount=402.1)
    assert stated.status_code == 201, stated.text
    assert (stated.json()["to_amount"], stated.json()["fx_as_of"]) == (402.1, None)


def test_a_transfer_in_one_currency_is_one_sum_and_asks_no_rate(client, feed):
    """Every transfer the reader has. The arrival is the amount itself, not a
    conversion of it, and nothing is asked of the feed."""
    wise, broker_a = _accounts(client)
    euro = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]

    t = client.post(
        "/api/transfers",
        json={"date": DAY, "from_institution_id": broker_a, "to_institution_id": euro,
              "amount": 123.456, "currency": "EUR", "to_currency": "EUR"},
    ).json()

    assert (t["to_amount"], t["to_currency"], t["fx_as_of"]) == (123.456, "EUR", None)
    assert feed == []


def test_the_destinations_currency_is_stated_like_every_other(client, feed):
    wise, broker_a = _accounts(client)
    body = {"date": DAY, "from_institution_id": wise, "to_institution_id": broker_a,
            "amount": 500, "currency": "USD"}

    missing = client.post("/api/transfers", json=body)
    assert missing.status_code == 422
    assert [e["loc"][-1] for e in missing.json()["detail"]] == ["to_currency"]

    blank = client.post("/api/transfers", json={**body, "to_currency": " "})
    assert blank.status_code == 422 and "say which currency" in blank.text
