"""A day whose close is not there — and what a sum fixed on that day does.

Measured on 2026-09-17 in Milan: Yahoo's daily history for VWCE.MI held a row
for the 16th with no prices in it, and still held it at 20:18 with the 17th's
session already closed at 167.64. ENI.MI's 16th, by contrast, was empty at
10:06 and filled by 11:55. The same shape appears twice: as a NaN row in one
query window and as no row at all in another, because yfinance drops a row
whose prices are all NaN and whose volume is zero, and the volume it reports
for the most recent bar is not always zero.

Both shapes used to reach the plan as a budget too small to buy a unit — a
message about money, for something that has nothing to do with money — and one
of them (the dropped row) bought the PREVIOUS session's close, dated that
session: a purchase on a day it did not happen, in a debit that is never
restated.

The rule these tests pin:

- a sum fixed on a day takes THAT day's close, or waits;
- only a session that has ENDED is evidence about an earlier day. Today's own
  row is an open session, and an open session proves nothing;
- after three ended sessions have each published a close and the asked day
  still has none, it is treated as a day that symbol did not trade, and the
  first ended session after it is used — priced, dated and converted together;
- while it waits, NOTHING is written: no transaction, no unfilled occurrence,
  no carried remainder. The occurrence comes back on the next run.
"""

from __future__ import annotations

import datetime

import pytest

from app import crud, dated, fx, models, pac, prices
from app.database import SessionLocal
from sqlalchemy import select

OCC = datetime.date(2026, 9, 16)
ANCHOR = "2026-09-01"


@pytest.fixture()
def market(monkeypatch):
    """Yahoo's rows, as a dict of day -> close (None = a row with no prices, a
    day absent = no row at all). The fake honours the window it is asked for,
    so a caller that never looks past the asked day sees no later session."""

    def rows_are(days: dict[str, float | None], *, today: datetime.date):
        def fetch(symbol, start, end):
            return sorted(
                (day, close)
                for day, close in days.items()
                if start.isoformat() <= day < end.isoformat()
            )

        monkeypatch.setattr(prices, "_fetch_close_window", fetch)
        monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
        monkeypatch.setattr(dated, "today", lambda: today.isoformat())

    return rows_are


def _plan(client, *, start: datetime.date = OCC, execution: str = "whole_units") -> tuple[int, int]:
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    assert (
        client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR, "amount": 2000.0, "currency": "EUR"},
        ).status_code
        == 201
    )
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "PAC All-World",
            "amount": 500,
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": start.isoformat(),
            "source_institution_id": iid,
            "execution": execution,
            "targets": [
                {"symbol": "VWCE.MI", "asset_name": "VWCE", "institution_id": iid}
            ],
        },
    )
    assert r.status_code == 201, r.text
    return iid, r.json()["id"]


def _run(client) -> dict:
    out = client.post("/api/transactions/catch-up")
    assert out.status_code == 200, out.text
    return out.json()


def _written(plan_id: int) -> dict:
    """Everything the catch-up could have left behind for a plan."""
    with SessionLocal() as db:
        return {
            "transactions": [
                (t.date, t.quantity, t.unit_price, t.amount)
                for t in db.scalars(select(models.Transaction))
            ],
            "unfilled": [
                u.occurrence for u in db.scalars(select(models.PlanUnfilledOccurrence))
            ],
            "carried": db.get(models.AccumulationPlan, plan_id).carried_remainder,
        }


NOTHING = {"transactions": [], "unfilled": [], "carried": 0.0}


# --- Waiting -----------------------------------------------------------------


def test_a_close_that_has_not_arrived_is_not_a_budget_too_small(client, market):
    """The message the reader actually sees. 500 EUR buys three units of a 165
    EUR fund, so "cannot buy a whole unit" sends them to check a plan that is
    configured correctly."""
    market({"2026-09-14": 164.9, "2026-09-15": 165.38, "2026-09-16": None}, today=datetime.date(2026, 9, 17))
    _, plan_id = _plan(client)

    out = _run(client)

    (skip,) = out["skipped"]
    assert out["created"] == []
    assert "2026-09-16" in skip["reason"]
    assert "close" in skip["reason"].lower()
    assert "whole unit" not in skip["reason"]
    assert _written(plan_id) == NOTHING


def test_the_asked_day_absent_from_the_window_waits_the_same_way(client, market):
    """The other shape of the same fact: no row at all, rather than an empty
    one. It must not become "the last close on or before", which is the
    previous session's, dated then."""
    market({"2026-09-14": 164.9, "2026-09-15": 165.38}, today=datetime.date(2026, 9, 17))
    _, plan_id = _plan(client)

    out = _run(client)

    (skip,) = out["skipped"]
    assert out["created"] == []
    assert "2026-09-16" in skip["reason"]
    assert _written(plan_id) == NOTHING


def test_an_open_session_is_not_evidence_that_the_day_before_was_closed(client, market):
    """The trap, and it is the exact situation of 2026-09-17 at 10:06: the 16th
    empty, the 17th present — but the 17th was that morning's session, still
    trading. Reading it as "the market has moved on" buys the 16th at an
    intraday price of the 17th, which is not a close at all, and fixes a debit
    on it."""
    market(
        {"2026-09-15": 165.38, "2026-09-16": None, "2026-09-17": 167.21},
        today=datetime.date(2026, 9, 17),
    )
    _, plan_id = _plan(client)

    out = _run(client)

    (skip,) = out["skipped"]
    assert out["created"] == []
    assert "167.21" not in skip["reason"]
    assert _written(plan_id) == NOTHING


def test_two_ended_sessions_are_not_enough_to_give_up_on_a_day(client, market):
    """Measured on 2026-09-17: a late close arrived the next morning, before
    any later session had ended. The threshold sits above that, so a close that
    is merely slow is never overtaken by the rule meant for one that never
    comes."""
    market(
        {
            "2026-09-15": 165.38,
            "2026-09-16": None,
            "2026-09-17": 167.64,
            "2026-09-18": 168.10,
        },
        today=datetime.date(2026, 9, 21),
    )
    _, plan_id = _plan(client)

    out = _run(client)

    assert out["created"] == []
    assert _written(plan_id) == NOTHING


def test_an_occurrence_waiting_is_retried_and_not_recorded_as_run(client, market):
    """The behaviour that was already right, and the one this must not break.
    An occurrence that ran and bought nothing records itself so it is never
    retried with fresh money; an occurrence that could not be PRICED never ran
    at all, and comes back untouched."""
    market({"2026-09-15": 165.38, "2026-09-16": None}, today=datetime.date(2026, 9, 17))
    _, plan_id = _plan(client)

    first = _run(client)
    second = _run(client)

    assert [s["reason"] for s in first["skipped"]] == [s["reason"] for s in second["skipped"]]
    assert _written(plan_id) == NOTHING


# --- Giving up ---------------------------------------------------------------


def test_a_close_that_never_arrives_is_given_up_after_three_ended_sessions(client, market):
    """VWCE.MI has days whose close never arrived: 2025-10-24 and 2026-03-06,
    still empty months later. Waiting for one of those forever leaves the
    contribution uninvested for good, and says so only in a skip message."""
    market(
        {
            "2026-09-15": 165.38,
            "2026-09-16": None,
            "2026-09-17": 167.64,
            "2026-09-18": 168.10,
            "2026-09-21": 169.20,
        },
        today=datetime.date(2026, 9, 22),
    )
    _, plan_id = _plan(client)

    out = _run(client)

    # The FIRST ended session after the day, not the last one and not the one
    # before it: 500 EUR at 167.64 is two units, 335.28 out of the account.
    assert [(t["date"], t["quantity"], t["unit_price"], t["amount"]) for t in out["created"]] == [
        ("2026-09-17", 2.0, 167.64, 335.28)
    ]
    assert _written(plan_id)["carried"] == round(500 - 335.28, 2)


def test_a_day_the_market_did_not_trade_buys_the_session_after_it(client, market):
    """A Saturday occurrence. The close before it is Friday's, and using it
    dates the purchase — and the debit, and its rate — before the day the money
    was due. A standing order cannot be filled before it exists."""
    market(
        {
            "2026-09-18": 168.10,
            "2026-09-21": 169.20,
            "2026-09-22": 170.40,
            "2026-09-23": 171.00,
        },
        today=datetime.date(2026, 9, 24),
    )
    _, plan_id = _plan(client, start=datetime.date(2026, 9, 19))

    out = _run(client)

    assert [(t["date"], t["unit_price"]) for t in out["created"]] == [("2026-09-21", 169.20)]


# --- What the price endpoint says --------------------------------------------


def test_the_quote_says_that_day_has_no_close_rather_than_an_empty_price(client, market):
    """It used to answer 200 with a null price: the form's price box stayed
    empty and explained nothing, which reads like a broken ticker. A wrong
    ticker is 502 and an unreachable market is 503; this is neither."""
    market({"2026-09-15": 165.38, "2026-09-16": None}, today=datetime.date(2026, 9, 17))

    r = client.get("/api/prices/quote", params={"symbol": "VWCE.MI", "on": "2026-09-16"})

    assert r.status_code == 404, r.text
    assert "2026-09-16" in r.json()["detail"]
    assert "close" in r.json()["detail"].lower()


def test_the_quote_still_answers_a_day_that_has_its_close(client, market):
    market({"2026-09-15": 165.38, "2026-09-16": 166.10}, today=datetime.date(2026, 9, 17))

    r = client.get("/api/prices/quote", params={"symbol": "VWCE.MI", "on": "2026-09-16"})

    assert r.status_code == 200, r.text
    assert (r.json()["price"], r.json()["as_of"]) == (166.10, "2026-09-16")


def test_the_latest_close_skips_a_row_whose_prices_never_arrived(client, market):
    """The other reader of the same rows: "what is it worth now". Here the
    previous real close IS the right answer — a valuation is not fixed on a
    day — but a NaN reached the price cache and the holdings through it."""
    market(
        {"2026-09-15": 165.38, "2026-09-16": None},
        today=datetime.date(2026, 9, 17),
    )

    quote = prices.get_quote("VWCE.MI", "EUR")

    assert (quote["price"], quote["as_of"]) == (165.38, "2026-09-15")
