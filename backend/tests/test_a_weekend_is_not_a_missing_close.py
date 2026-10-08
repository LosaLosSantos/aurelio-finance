"""A weekend is not a missing close.

In the reader's test round (2026-10-08) a plan's occurrence fell on a Sunday,
and the catch-up skipped it with "2 session(s) have ended since ... After 3 it
is taken as a day ... did not trade": the three-session wait, written for a
weekday whose close may only be late, applied to a day no exchange has a
session on. Every weekend occurrence was bought days late, at the Monday
close it would get anyway.

Brief AJ: a Saturday or a Sunday with no close takes the first ENDED session
after it at once, for a symbol with no weekend row in the window Yahoo
returned; a weekday still waits; a symbol that trades on weekends (a coin) has
weekend rows, and its Saturday waits for its own close as before.

Yahoo is faked at `prices._fetch_close_window`, honouring the window it is
asked for. The symbols are invented.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from app import dated, models, prices
from app.database import SessionLocal

SAT, SUN, MON, TUE, WED, THU = (datetime.date(2026, 10, d) for d in (3, 4, 5, 6, 7, 8))

# An exchange listing: sessions Monday to Friday, none on weekends.
WEEKDAYS = {
    "2026-09-28": 100.0, "2026-09-29": 101.0, "2026-09-30": 102.0,
    "2026-10-01": 103.0, "2026-10-02": 104.0,
    "2026-10-05": 105.0, "2026-10-06": 106.0, "2026-10-07": 107.0, "2026-10-08": 108.0,
}


@pytest.fixture()
def market(monkeypatch):
    """`market(rows, today=...)`: Yahoo's rows as day -> close (None for a row
    with no prices, a day absent for no row), and the reader's today."""

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


# --- The rule --------------------------------------------------------------------------


@pytest.mark.parametrize("weekend_day", [SAT, SUN], ids=["saturday", "sunday"])
def test_a_weekend_day_takes_the_next_session_once_it_has_ended(market, weekend_day):
    """Monday has ended by Tuesday: a weekend occurrence is bought then, at
    Monday's close, dated Monday. The three-session rule bought it on
    Thursday, at the same close."""
    market(WEEKDAYS, today=TUE)

    quote = prices.get_price_on("XGLO.MI", weekend_day)

    assert (quote["price"], quote["as_of"]) == (105.0, "2026-10-05")


def test_before_the_next_session_has_ended_it_says_why_it_waits(market):
    market(WEEKDAYS, today=MON)

    with pytest.raises(prices.NoCloseYet) as waits:
        prices.get_price_on("XGLO.MI", SUN)

    assert str(waits.value) == (
        "2026-10-04 is a Sunday, when 'XGLO.MI' does not trade: it takes the close "
        "of the first session after it, which has not ended yet."
    )


def test_a_weekend_before_a_holiday_takes_the_first_session_that_traded(market):
    """No Monday row (a holiday): the first ended session is Tuesday's."""
    days = {d: c for d, c in WEEKDAYS.items() if d != "2026-10-05"}
    market(days, today=WED)

    quote = prices.get_price_on("XGLO.MI", SAT)

    assert (quote["price"], quote["as_of"]) == (106.0, "2026-10-06")


def test_a_weekday_without_a_close_still_waits_for_three_sessions(market):
    """A guard: a weekday's close can be late, and nothing tells late from
    never on the day, so the wait stands there."""
    days = {d: c for d, c in WEEKDAYS.items() if d != "2026-10-05"}
    market(days, today=THU)

    with pytest.raises(prices.NoCloseYet) as waits:
        prices.get_price_on("XGLO.MI", MON)

    assert "2 session(s) have ended since (2026-10-06, 2026-10-07)" in str(waits.value)


def test_a_coins_saturday_waits_for_its_own_close(market):
    """A symbol with weekend rows trades on weekends: its Saturday's close is
    late, not absent, and taking Sunday's would buy on a day it did not. The
    trap brief R named."""
    coin = {
        "2026-09-26": 50.0, "2026-09-27": 51.0, "2026-09-28": 52.0, "2026-09-29": 53.0,
        "2026-09-30": 54.0, "2026-10-01": 55.0, "2026-10-02": 56.0,
        "2026-10-04": 58.0, "2026-10-05": 59.0,
    }
    market(coin, today=TUE)

    with pytest.raises(prices.NoCloseYet):
        prices.get_price_on("XCOIN-EUR", SAT)


def test_a_coins_saturday_with_a_close_takes_it(market):
    """A guard: a day's own close always comes first."""
    coin = {d: 50.0 + i for i, d in enumerate(
        ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30",
         "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]
    )}
    market(coin, today=TUE)

    quote = prices.get_price_on("XCOIN-EUR", SAT)

    assert (quote["price"], quote["as_of"]) == (57.0, "2026-10-03")


# --- The reader's case: a plan on a Sunday -------------------------------------------


def _sunday_plan(client) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    assert client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": "2026-09-01", "amount": 2000.0, "currency": "EUR"},
    ).status_code == 201
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "Example plan",
            "amount": 300,
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": SUN.isoformat(),
            "source_institution_id": iid,
            "execution": "whole_units",
            "targets": [{"symbol": "XGLO.MI", "asset_name": "Example Global", "institution_id": iid}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_plan_on_a_sunday_buys_on_tuesday_at_mondays_close(client, market):
    """The reader's case. On Tuesday the Sunday occurrence is bought, two
    units at Monday's 105.00, dated Monday; under the old rule the catch-up
    skipped it until Thursday."""
    _sunday_plan(client)
    market(WEEKDAYS, today=TUE)

    out = client.post("/api/transactions/catch-up")

    assert out.status_code == 200, out.text
    assert not [s for s in out.json()["skipped"] if s.get("occurrence")], out.json()["skipped"]
    with SessionLocal() as db:
        bought = [(t.date, t.quantity, t.unit_price) for t in db.scalars(select(models.Transaction))]
    assert bought == [("2026-10-05", 2.0, 105.0)]


def test_on_monday_the_sunday_occurrence_waits_and_writes_nothing(client, market):
    """A guard: until Monday has ended there is no close to buy at, and the
    occurrence is retried, not recorded."""
    _sunday_plan(client)
    market(WEEKDAYS, today=MON)

    out = client.post("/api/transactions/catch-up").json()

    assert any("2026-10-04 is a Sunday" in s["reason"] for s in out["skipped"]), out["skipped"]
    with SessionLocal() as db:
        assert list(db.scalars(select(models.Transaction))) == []
        assert list(db.scalars(select(models.PlanUnfilledOccurrence))) == []
