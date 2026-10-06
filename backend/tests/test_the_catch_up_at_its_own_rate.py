"""The catch-up converts at the rate of the day it records, never today's.

A plan's contribution is in its account's currency, and the fund it buys is
priced in its listing's. The catch-up used to read both as euro: 250 set
against a 100-dollar share bought two units whatever the dollar was worth. An
occurrence caught up three months late happened three months ago — the units
it buys and the sum it takes out of the account are those of the close it
buys at, at that day's rate. The same holds for a dividend, on its ex-date.

The feed below publishes 1.25 dollars to the euro on the day that is recorded
and 1.00 today, so the wrong day's rate cannot pass for rounding: a 100-dollar
share is 80.00 euro on its day and 100.00 today, and 250 euro buys three of
the first and two of the second.
"""

from __future__ import annotations

import datetime

import pytest

from app import crud, fx, models, pac, prices
from app.database import SessionLocal

TODAY = datetime.date.today()
CLOSE_DAY = (TODAY - datetime.timedelta(days=91)).isoformat()
ANCHOR_DAY = (TODAY - datetime.timedelta(days=150)).isoformat()


@pytest.fixture()
def feed(monkeypatch) -> list[tuple]:
    asked: list[tuple] = []

    def fetch(base, start, end=None):
        asked.append((base, start, end))
        return {
            CLOSE_DAY: {"USD": 1.25},
            TODAY.isoformat(): {"USD": 1.00},
        }

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def _account(client, cash: float = 1000.0) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": ANCHOR_DAY, "amount": cash, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    return iid


def _plan(client, iid: int, symbol: str = "VTI", **extra) -> int:
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "PAC America",
            "amount": 250,
            "currency": "EUR",
            # Annual, so the one occurrence due is the one three months ago.
            "frequency": "annual",
            "start_date": CLOSE_DAY,
            "source_institution_id": iid,
            "targets": [{"symbol": symbol, "asset_name": "Total Market", "institution_id": iid}],
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _closes_at(monkeypatch, price: float, listing: str | None) -> None:
    monkeypatch.setattr(
        prices,
        "get_price_on",
        lambda symbol, on: {"symbol": symbol, "price": price, "as_of": on.isoformat()},
    )
    if listing is not None:
        monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: listing)


def _run() -> dict:
    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=TODAY)
        return {
            "created": [
                (t.quantity, t.amount, t.currency, t.price_currency, t.fx_as_of, t.estimated)
                for t in out["created"]
            ],
            "skipped": [s["reason"] for s in out["skipped"]],
        }


def _carried(plan_id: int) -> float:
    with SessionLocal() as db:
        return db.get(models.AccumulationPlan, plan_id).carried_remainder


# --- The plan ---------------------------------------------------------------


def test_an_occurrence_three_months_late_buys_at_its_close_days_rate(client, feed, monkeypatch):
    iid = _account(client)
    plan_id = _plan(client, iid)
    _closes_at(monkeypatch, 100.0, listing="USD")

    out = _run()

    # 250 euro against 80.00 a share on that day: three units, 240.00 out of
    # the account, 10.00 carried. Today's rate would have bought two for 200.
    assert out == {"created": [(3, 240.0, "EUR", "USD", CLOSE_DAY, True)], "skipped": []}
    assert _carried(plan_id) == 10.0
    assert client.get(f"/api/institutions/{iid}/cash").json()["projected"] == 760.0


def test_a_fractional_plan_invests_its_contribution_at_that_days_rate(client, feed, monkeypatch):
    iid = _account(client)
    _plan(client, iid, execution="fractional")
    _closes_at(monkeypatch, 100.0, listing="USD")

    ((quantity, amount, *_),) = _run()["created"]

    assert abs(quantity - 250 / 80.0) < 1e-9  # 3.125, not the 2.5 of today's rate
    assert amount == 250.0


def test_without_that_days_rate_the_occurrence_waits_and_nothing_is_written(
    client, monkeypatch
):
    """The same answer as a missing price: skipped, retried, and not a trace
    left — no buy, no unfilled record, the carried change untouched. Today's
    rate is not a stand-in for the rate that was missing."""
    iid = _account(client)
    plan_id = _plan(client, iid)
    _closes_at(monkeypatch, 100.0, listing="USD")

    def offline(base, start, end=None):
        raise fx.FxError("feed down")

    monkeypatch.setattr(fx, "_fetch_rates", offline)
    out = _run()

    assert out["created"] == []
    assert out["skipped"] == [f"VTI: no exchange rate from USD to EUR is known for {CLOSE_DAY}"]
    with SessionLocal() as db:
        assert db.query(models.Transaction).count() == 0
        assert crud.get_plan_occurrences_settled(db, plan_id) == set()
    assert _carried(plan_id) == 0.0

    # The feed answers again, and the occurrence runs as if it never waited.
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {CLOSE_DAY: {"USD": 1.25}}
    )
    assert _run() == {"created": [(3, 240.0, "EUR", "USD", CLOSE_DAY, True)], "skipped": []}
    assert _carried(plan_id) == 10.0


def test_a_listing_whose_currency_nobody_can_tell_is_not_bought_as_the_plans(
    client, feed, monkeypatch
):
    """A price with no currency is not a price in euro. Priced as the plan's,
    a 100-dollar share would buy two units for 200.00 again."""
    iid = _account(client)
    plan_id = _plan(client, iid)
    _closes_at(monkeypatch, 100.0, listing=None)  # the market cannot say

    out = _run()

    assert out["created"] == []
    assert "the currency VTI trades in is not known yet" in out["skipped"][0]
    with SessionLocal() as db:
        assert crud.get_plan_occurrences_settled(db, plan_id) == set()


def test_a_plan_with_nothing_due_does_not_ask_what_it_trades_in(client, feed, monkeypatch):
    """The catch-up runs at every app start. A plan whose occurrences are all
    done has no price to set against a budget, so it neither asks the market
    for its listing's currency nor reports that it could not find out."""
    iid = _account(client)
    _plan(client, iid)
    _closes_at(monkeypatch, 100.0, listing="USD")
    assert len(_run()["created"]) == 1

    asked: list[str] = []
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: asked.append(symbol))
    assert _run() == {"created": [], "skipped": []}
    assert asked == []


def test_a_euro_plan_buying_a_euro_fund_reads_no_rate(client, feed, monkeypatch):
    """Every plan the reader has. Nothing to convert, so nothing is asked of
    the feed and the figures are the ones the catch-up has always written."""
    iid = _account(client)
    _plan(client, iid, symbol="VWCE.MI")
    _closes_at(monkeypatch, 83.0, listing="EUR")

    assert _run() == {"created": [(3, 249.0, "EUR", "EUR", None, True)], "skipped": []}
    assert feed == []


# --- The dividend -----------------------------------------------------------


EX_DAY = CLOSE_DAY


def _dollar_dividend(client, monkeypatch) -> int:
    """100 shares of a dollar fund held in a euro account, paying one dollar
    a share on an ex-date three months ago."""
    iid = _account(client)
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": ANCHOR_DAY}
    ).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Vanguard High Dividend",
            "asset_class": "fund_etf",
            "symbol": "VYM",
            "quantity": 100,
            "unit_price": 120,
            "distribution_policy": "dist",
            "currency": "USD",
        },
    )
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        db.merge(models.PriceCache(symbol="VYM", price=120.0, currency="USD", as_of=TODAY.isoformat()))
        db.commit()
    monkeypatch.setattr(
        prices, "get_dividends_since", lambda sym, since: [{"date": EX_DAY, "dps": 1.0}]
    )
    return iid


def test_a_dollar_dividend_is_gross_and_converted_and_the_statement_corrects_both(
    client, feed, monkeypatch
):
    """Two flags on one row, for two different approximations. `estimated`
    says the figure is the market's GROSS — the withholding estimate reads it
    to find what is still untaxed. `fx_as_of` says it was converted at the
    ECB's rate of the ex-date. The credit on the statement is net AND at the
    broker's rate, so typing it in retires both, and the withholding stops
    being applied to money that already had it taken."""
    iid = _dollar_dividend(client, monkeypatch)
    r = client.put(
        "/api/settings/tax",
        json={"country": None, "capital_gains_rate": None, "dividend_withholding_rate": 26},
    )
    assert r.status_code == 200, r.text

    (tx,) = client.post("/api/transactions/catch-up").json()["created"]
    # 100 dollars gross on the ex-date, at 1.25: 80.00 euro into the euro
    # account. At today's rate it would have been 100.00.
    assert (tx["amount"], tx["currency"], tx["price_currency"]) == (80.0, "EUR", "USD")
    assert (tx["estimated"], tx["fx_as_of"]) == (True, EX_DAY)

    before = client.get("/api/dashboard/portfolio").json()
    assert before["total_dividends_estimated"] == 80.0
    assert before["tax_estimate"]["dividend_withholding"] == pytest.approx(20.8)  # 26% of 80

    corrected = client.put(
        f"/api/transactions/{tx['id']}",
        json={
            "kind": "dividend",
            "date": tx["date"],
            "institution_id": iid,
            "asset_name": tx["asset_name"],
            "symbol": "VYM",
            "quantity": 100,
            "unit_price": 1.0,
            "amount": 58.9,  # the net credit, at the broker's own rate
            "currency": "EUR",
            "price_currency": "USD",
        },
    ).json()
    assert (corrected["amount"], corrected["estimated"], corrected["fx_as_of"]) == (58.9, False, None)

    after = client.get("/api/dashboard/portfolio").json()
    assert after["total_dividends"] == 58.9
    assert after["total_dividends_estimated"] == 0.0
    assert after["tax_estimate"]["dividend_withholding"] == 0.0
    assert after["tax_estimate"]["dividends_recorded_net"] == 58.9


def test_a_dividend_without_its_ex_dates_rate_waits(client, monkeypatch):
    iid = _dollar_dividend(client, monkeypatch)

    def offline(base, start, end=None):
        raise fx.FxError("feed down")

    monkeypatch.setattr(fx, "_fetch_rates", offline)
    out = client.post("/api/transactions/catch-up").json()
    assert out["created"] == []
    assert [(s["label"], s["occurrence"]) for s in out["skipped"]] == [("VYM", EX_DAY)]
    assert client.get("/api/transactions").json() == []

    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {EX_DAY: {"USD": 1.25}}
    )
    (tx,) = client.post("/api/transactions/catch-up").json()["created"]
    assert (tx["institution_id"], tx["amount"], tx["fx_as_of"]) == (iid, 80.0, EX_DAY)
