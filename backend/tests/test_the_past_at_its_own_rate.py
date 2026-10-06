"""A point of the history is converted at the rate of its own day.

The net worth series used to convert every point at the latest rate, so a
past point was that day's amounts restated at today's rate, and the past moved
every time the rate did. A rate is a price, and this series already refuses to
price the past with today's quotes — so each point is now converted with the
rates in force on its date, read from the one history `fx.rates_on_days`
keeps, and says which ECB day that was.

The feed below publishes two very different rates, 1.25 dollars to the euro
a month ago and 1.00 today, so a point converted at the wrong day's rate is off
by a quarter and cannot pass for a rounding difference.
"""

from __future__ import annotations

import datetime

import pytest

from app import analytics, fx
from app.database import SessionLocal

from tests.test_no_n_plus_one import _counting_queries

TODAY = datetime.date.today().isoformat()
LAST_MONTH = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()


@pytest.fixture()
def two_rates(monkeypatch) -> list[tuple]:
    asked: list[tuple] = []

    def fetch(base, start, end=None):
        asked.append((base, start, end))
        return {LAST_MONTH: {"USD": 1.25}, TODAY: {"USD": 1.00}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def _dollars_a_month_ago(client) -> int:
    """An account, a situation, a house and a mortgage, all in USD and all
    dated a month ago."""
    iid = client.post("/api/institutions", json={"name": "Wise"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": LAST_MONTH, "amount": 1250, "currency": "USD"},
    )
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LAST_MONTH}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "A private fund", "asset_class": "other", "value": 500, "currency": "USD"},
    )
    house = client.post(
        "/api/real-assets", json={"name": "Austin house", "currency": "USD"}
    ).json()["id"]
    client.post(f"/api/real-assets/{house}/valuations", json={"date": LAST_MONTH, "value": 250_000})
    loan = client.post("/api/liabilities", json={"name": "Mortgage", "currency": "USD"}).json()["id"]
    client.post(f"/api/liabilities/{loan}/balances", json={"date": LAST_MONTH, "balance": 125_000})
    return iid


def test_each_point_is_converted_at_the_rate_of_its_own_day(client, two_rates):
    _dollars_a_month_ago(client)

    series = {p["date"]: p for p in client.get("/api/dashboard/net-worth-series").json()}

    then, now = series[LAST_MONTH], series[TODAY]
    # A month ago: 1.25 dollars to the euro.
    assert (then["financial"], then["real"], then["liabilities"]) == (1000.0 + 400.0, 200_000.0, 100_000.0)
    assert then["fx_as_of"] == LAST_MONTH
    # Today: the same dollars, at 1.00.
    assert (now["financial"], now["real"], now["liabilities"]) == (1250.0 + 500.0, 250_000.0, 125_000.0)
    assert now["fx_as_of"] == TODAY


def test_the_history_is_read_once_not_once_per_point(client, two_rates):
    """Every point asks for its own day's rates, and all of them are answered
    from one load. Counted on the table rather than on the feed: once the
    history is stored the feed is not asked again anyway, and a load per point
    is a pair of queries per point — the query-per-row shape this codebase
    keeps removing. So the reads of `fx_rates` must not grow with the points."""
    iid = _dollars_a_month_ago(client)
    client.get("/api/dashboard/net-worth-series")  # the history is stored now

    def reads_of_rates() -> int:
        with _counting_queries() as seen:
            client.get("/api/dashboard/net-worth-series")
        return sum("fx_rates" in q for q in seen)

    few = reads_of_rates()
    for days_ago in (25, 20, 15, 10, 5):
        d = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
        client.post(
            "/api/transfers",
            json={"date": d, "from_institution_id": iid, "amount": 1, "currency": "USD", "to_currency": "USD"},
        )
    many = reads_of_rates()

    assert len(client.get("/api/dashboard/net-worth-series").json()) == 7
    assert many == few, f"{few} reads of the rates for 2 points, {many} for 7"


def test_a_history_all_in_euro_never_asks_for_a_rate(client, two_rates):
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": LAST_MONTH, "amount": 1000, "currency": "EUR"},
    )

    series = client.get("/api/dashboard/net-worth-series").json()

    assert [p["financial"] for p in series] == [1000.0, 1000.0]
    assert [p["fx_as_of"] for p in series] == [None, None]
    assert two_rates == []


def test_the_register_asked_about_a_past_day_converts_at_that_day(client, two_rates):
    """The register answers "how much cash on this date", and the series asks
    it the same question for every point — so the two agree only if the
    register converts at that date too."""
    iid = _dollars_a_month_ago(client)

    then = client.get(f"/api/institutions/{iid}/cash", params={"as_of": LAST_MONTH}).json()
    now = client.get(f"/api/institutions/{iid}/cash").json()

    assert then["projected"] == 1000.0
    assert now["projected"] == 1250.0


def test_both_cash_projections_convert_at_the_same_day(client, two_rates):
    """The declared duplicate again, on the other axis. With one rate for every
    date, a copy that converted at today's rate and a copy that converted at
    the date's would agree; with two, they cannot."""
    iid = _dollars_a_month_ago(client)

    with SessionLocal() as db:
        fast = analytics._cash_totals_by_date(db, [LAST_MONTH, TODAY], [iid])
        reference = {
            d: analytics.compute_cash_position(db, iid, datetime.date.fromisoformat(d))["projected"]
            for d in (LAST_MONTH, TODAY)
        }

    assert fast == reference == {LAST_MONTH: 1000.0, TODAY: 1250.0}
