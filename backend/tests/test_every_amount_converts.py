"""Every amount reaches a total in the base currency, whatever it was written in.

Until now only holdings went through `fx.Converter`. The cash register, real
assets, debts and the monthly cash flow summed their amounts as they were
stored, which was right only because every one of them was in EUR: a register
anchored at 1,250 dollars counted 1,250 euro into the net worth. The currency
has been required on every one of those rows since a7d2e94c10b8, so it can be
read — and these tests write rows in USD, which the API already accepts, and
check each total receives them converted.

The feed is fixed at 1.25 dollars per euro so every expected figure is round:
1,250 USD is 1,000 EUR.
"""

from __future__ import annotations

import datetime

import pytest

from app import advisor, fx
from app.database import SessionLocal

TODAY = datetime.date.today()
LAST_MONTH = (TODAY - datetime.timedelta(days=30)).isoformat()
LAST_WEEK = (TODAY - datetime.timedelta(days=7)).isoformat()


@pytest.fixture(autouse=True)
def dollars_at_one_twenty_five(monkeypatch):
    def fetch(base, start, end=None):
        assert base == "EUR"
        return {"2026-09-11": {"USD": 1.25}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)


def _account(client, name: str, amount: float, currency: str) -> int:
    iid = client.post("/api/institutions", json={"name": name}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": LAST_MONTH, "amount": amount, "currency": currency},
    )
    assert r.status_code == 201, r.text
    return iid


def test_an_account_held_in_dollars_reaches_every_total_in_euro(client):
    usd = _account(client, "Wise", 1250, "USD")
    _account(client, "Broker A", 500, "EUR")

    register = client.get(f"/api/institutions/{usd}/cash").json()
    summary = client.get("/api/dashboard/summary").json()
    allocation = client.get("/api/dashboard/allocation").json()
    series = client.get("/api/dashboard/net-worth-series").json()

    assert register["anchor_amount"] == 1000.0 and register["projected"] == 1000.0
    assert summary["cash_total"] == 1500.0 and summary["net_worth"] == 1500.0
    assert {s["asset_class"]: s["value"] for s in allocation["by_asset_class"]} == {"cash": 1500.0}
    assert series[-1]["financial"] == 1500.0


def test_what_moves_a_dollar_account_moves_it_in_euro(client):
    """Income, an expense and a transfer, each stated in USD, on top of a USD
    anchor — and the transfer lands in a euro account converted too."""
    usd = _account(client, "Wise", 1250, "USD")
    eur = _account(client, "Broker A", 0, "EUR")
    for path, body in (
        ("/api/income-sources", {"name": "Invoice", "amount": 250, "frequency": "one_off"}),
        ("/api/expenses", {"name": "Laptop", "amount": 125, "frequency": "one_off"}),
    ):
        r = client.post(
            path,
            json={**body, "currency": "USD", "institution_id": usd, "start_date": LAST_WEEK},
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/api/transfers",
        json={"date": LAST_WEEK, "from_institution_id": usd, "to_institution_id": eur,
              "amount": 500, "currency": "USD", "to_currency": "USD"},
    )
    assert r.status_code == 201, r.text

    wise = client.get(f"/api/institutions/{usd}/cash").json()
    broker_a = client.get(f"/api/institutions/{eur}/cash").json()

    assert (wise["income"], wise["expenses"], wise["transfers_out"]) == (200.0, 100.0, 400.0)
    assert wise["projected"] == 1000.0 + 200.0 - 100.0 - 400.0
    assert broker_a["transfers_in"] == 400.0 and broker_a["projected"] == 400.0
    assert client.get("/api/dashboard/summary").json()["cash_total"] == 1100.0


def test_a_house_and_a_mortgage_in_dollars_reach_the_net_worth_in_euro(client):
    house = client.post(
        "/api/real-assets", json={"name": "Austin house", "category": "real_estate", "currency": "USD"}
    ).json()["id"]
    client.post(f"/api/real-assets/{house}/valuations", json={"date": LAST_MONTH, "value": 250_000})
    loan = client.post(
        "/api/liabilities",
        json={"name": "Mortgage", "kind": "mortgage", "currency": "USD", "real_asset_id": house},
    ).json()["id"]
    client.post(f"/api/liabilities/{loan}/balances", json={"date": LAST_MONTH, "balance": 125_000})

    summary = client.get("/api/dashboard/summary").json()
    allocation = client.get("/api/dashboard/allocation").json()
    series = client.get("/api/dashboard/net-worth-series").json()

    assert (summary["real_total"], summary["liabilities_total"]) == (200_000.0, 100_000.0)
    assert summary["net_worth"] == 100_000.0
    assert allocation["by_real_category"] == [{"category": "real_estate", "value": 200_000.0}]
    assert (series[-1]["real"], series[-1]["liabilities"]) == (200_000.0, 100_000.0)


def test_the_monthly_cash_flow_is_summed_in_euro(client):
    for path, body in (
        ("/api/income-sources", {"name": "US salary", "kind": "active", "amount": 1250, "currency": "USD"}),
        ("/api/income-sources", {"name": "Rent in", "kind": "passive", "amount": 500, "currency": "EUR"}),
        ("/api/expenses", {"name": "US rent", "nature": "essential", "amount": 625, "currency": "USD"}),
    ):
        assert client.post(path, json={**body, "frequency": "monthly"}).status_code == 201

    flow = client.get("/api/dashboard/cashflow").json()

    assert (flow["monthly_income"], flow["active_income"], flow["passive_income"]) == (1500.0, 1000.0, 500.0)
    assert (flow["monthly_expenses"], flow["essential_expenses"]) == (500.0, 500.0)
    assert flow["monthly_net"] == 1000.0


def test_the_picture_the_model_reads_says_what_each_raw_figure_is_in(client):
    """The totals in the context are converted; the rows listed under them are
    what the reader typed. Printed side by side with no unit, "real 200000.00"
    above "Austin house: 250000.00" reads as a contradiction or, worse, as two
    numbers in the same money. So each typed figure carries its currency."""
    house = client.post(
        "/api/real-assets", json={"name": "Austin house", "category": "real_estate", "currency": "USD"}
    ).json()["id"]
    client.post(f"/api/real-assets/{house}/valuations", json={"date": LAST_MONTH, "value": 250_000})
    loan = client.post("/api/liabilities", json={"name": "Mortgage", "currency": "USD"}).json()["id"]
    client.post(f"/api/liabilities/{loan}/balances", json={"date": LAST_MONTH, "balance": 125_000})
    client.post("/api/income-sources", json={"name": "US salary", "amount": 1250, "currency": "USD", "frequency": "monthly"})
    client.post("/api/expenses", json={"name": "US rent", "amount": 625, "currency": "USD", "frequency": "monthly"})

    with SessionLocal() as db:
        picture = advisor.build_context(db)

    assert "real 200000.00" in picture
    assert f"Austin house [real_estate]: 250000.00 USD ({LAST_MONTH})" in picture
    assert f"Mortgage [n/a]: 125000.00 USD ({LAST_MONTH})" in picture
    assert "US salary [n/a/n/a] 1250.00 USD monthly" in picture
    assert "US rent [n/a/n/a] 625.00 USD monthly" in picture
