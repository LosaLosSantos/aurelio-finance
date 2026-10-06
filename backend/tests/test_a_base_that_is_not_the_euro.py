"""The base is the database's, and a base that is not the euro gives right totals.

Every test before this one ran in euro, which proves the constant still works
and nothing else. Here the reader's database says USD — written into `settings`
by hand, the way the setting will be kept — and the same wealth is read twice:
once in the euro, once in the dollar. The feeds for the two bases agree with
each other (one euro is 1.25 dollars, one pound is 1.25 euro), so every total in
dollars is its euro total times 1.25, exactly, and each expected figure below is
worked out by hand from what the rows say.

The wealth: a euro account holding 1,000; a dollar account holding 500; a
photograph with 10 units of a euro fund bought at 80 and quoted today at 100,
and a lump of 100 pounds; a house worth 200,000 euro and a loan of 40,000 euro;
a salary of 2,000 euro a month credited nowhere in particular.
"""

from __future__ import annotations

import datetime

import pytest

from app import advisor, fx, models, prices
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

# The same two days, as each base's feed publishes them.
RATES = {
    "EUR": {"USD": 1.25, "GBP": 0.8},
    "USD": {"EUR": 0.8, "GBP": 0.64},
}


@pytest.fixture()
def feed(monkeypatch) -> list[str]:
    """Answers for whichever base asks, and records which bases asked."""
    asked: list[str] = []

    def fetch(base, start, end=None):
        asked.append(base)
        return {ANCHOR_DAY: dict(RATES[base]), TODAY: dict(RATES[base])}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def _base(currency: str | None) -> None:
    with SessionLocal() as db:
        row = db.get(models.Setting, "base_currency")
        if currency is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(models.Setting(key="base_currency", value=currency))
        else:
            row.value = currency
        db.commit()


def _made(r) -> int:
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _wealth(client) -> dict:
    broker_a = _made(client.post("/api/institutions", json={"name": "Broker A", "type": "bank"}))
    wise = _made(client.post("/api/institutions", json={"name": "Wise", "type": "bank"}))
    broker = _made(client.post("/api/institutions", json={"name": "Broker", "type": "broker"}))
    for iid, amount, currency in ((broker_a, 1000, "EUR"), (wise, 500, "USD")):
        _made(client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR_DAY, "amount": amount, "currency": currency},
        ))
    sid = _made(client.post(
        f"/api/institutions/{broker}/snapshots", json={"date": ANCHOR_DAY}
    ))
    fund = _made(client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "equity", "symbol": "VWCE.MI",
              "quantity": 10, "unit_price": 80, "currency": "EUR"},
    ))
    _made(client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "UK lump", "asset_class": "other", "value": 100, "currency": "GBP"},
    ))
    with SessionLocal() as db:
        db.merge(models.PriceCache(symbol="VWCE.MI", price=100.0, currency="EUR", as_of=TODAY))
        db.commit()
    house = _made(client.post("/api/real-assets", json={"name": "House", "category": "real_estate", "currency": "EUR"}))
    _made(client.post(f"/api/real-assets/{house}/valuations", json={"date": ANCHOR_DAY, "value": 200_000}))
    loan = _made(client.post("/api/liabilities", json={"name": "Loan", "currency": "EUR"}))
    _made(client.post(f"/api/liabilities/{loan}/balances", json={"date": ANCHOR_DAY, "balance": 40_000}))
    _made(client.post(
        "/api/income-sources",
        json={"name": "Salary", "kind": "active", "amount": 2000, "currency": "EUR", "frequency": "monthly"},
    ))
    return {"broker_a": broker_a, "wise": wise, "snapshot": sid, "fund": fund}


def _readings(client, ids: dict) -> dict:
    summary = client.get("/api/dashboard/summary").json()
    portfolio = client.get("/api/dashboard/portfolio").json()
    series = client.get("/api/dashboard/net-worth-series").json()
    cash = {c["institution_name"]: c for c in client.get("/api/cash/positions").json()}
    snapshot = client.get(f"/api/snapshots/{ids['snapshot']}").json()
    holding = client.get(f"/api/holdings/{ids['fund']}").json()
    allocation = client.get("/api/dashboard/allocation").json()
    cashflow = client.get("/api/dashboard/cashflow").json()
    return {
        "bases": {
            summary["base_currency"], portfolio["base_currency"], series[-1]["base_currency"],
            cash["Broker A"]["base_currency"], snapshot["base_currency"], holding["base_currency"],
            allocation["base_currency"], cashflow["base_currency"],
        },
        "net_worth": summary["net_worth"],
        "cash_total": summary["cash_total"],
        "investments_total": summary["investments_total"],
        "real_total": summary["real_total"],
        "liabilities_total": summary["liabilities_total"],
        "total_book": portfolio["total_book"],
        "total_market": portfolio["total_market"],
        "series_today": series[-1]["net_worth"],
        "broker_a_cash": cash["Broker A"]["projected"],
        "wise_cash": cash["Wise"]["projected"],
        "snapshot": snapshot["value_base"],
        "fund_holding": holding["value_base"],
        "financial_allocation": allocation["financial_total"],
        "monthly_income": cashflow["monthly_income"],
    }


def test_the_same_wealth_in_dollars_is_its_euro_figure_in_dollars(client, feed):
    ids = _wealth(client)

    in_euro = _readings(client, ids)
    _base("USD")
    in_dollars = _readings(client, ids)

    assert in_euro["bases"] == {"EUR"} and in_dollars["bases"] == {"USD"}
    # By hand, in dollars: cash 1,000 EUR = 1,250 and 500 USD = 500; the fund
    # at 10 x 100 EUR = 1,250 (cost 10 x 80 EUR = 1,000); the lump 100 GBP =
    # 125 EUR = 156.25; the house 250,000; the loan 50,000.
    assert in_dollars == {
        "bases": {"USD"},
        "net_worth": 1_750 + 1_406.25 + 250_000 - 50_000,
        "cash_total": 1_750.0,
        "investments_total": 1_406.25,
        "real_total": 250_000.0,
        "liabilities_total": 50_000.0,
        "total_book": 1_156.25,
        "total_market": 1_406.25,
        "series_today": 1_750 + 1_406.25 + 250_000 - 50_000,
        "broker_a_cash": 1_250.0,
        "wise_cash": 500.0,
        "snapshot": 1_156.25,
        "fund_holding": 1_000.0,
        "financial_allocation": 1_750 + 1_406.25,
        "monthly_income": 2_500.0,
    }
    # And every one of them is the euro figure in another unit — the same
    # wealth, not a different one.
    for key, dollars in in_dollars.items():
        if key != "bases":
            assert dollars == pytest.approx(in_euro[key] * 1.25), key


def test_a_dollar_base_asks_the_feed_for_dollar_rates_only(client, feed):
    """The store keeps each base's rows apart (228761b). A dollar reading that
    fell back on euro rows would read 1.25 dollars per euro as 1.25 euro per
    dollar."""
    _base("USD")
    ids = _wealth(client)
    client.get("/api/dashboard/summary")
    client.get("/api/dashboard/net-worth-series")
    buy = client.post(
        "/api/transactions",
        json={"kind": "buy", "date": TODAY, "institution_id": ids["broker_a"], "asset_name": "Apple",
              "symbol": "AAPL", "quantity": 1, "unit_price": 100, "currency": "EUR",
              "price_currency": "USD"},
    )
    composition = client.get("/api/dashboard/portfolio/composition").json()

    assert set(feed) == {"USD"}
    assert buy.json()["amount"] == 80.0
    assert composition["base_currency"] == "USD"


def test_a_database_that_never_chose_a_base_is_in_euro(client, feed):
    _base(None)
    ids = _wealth(client)
    assert _readings(client, ids)["bases"] == {"EUR"}
    with SessionLocal() as db:
        assert fx.base_currency(db) == "EUR"


def test_a_purchase_debits_the_same_sum_whatever_the_base(client, feed):
    """A fixed sum does not depend on the unit the totals are read in: 100
    dollars from a euro account is 80.00 euro through either base."""
    broker_a = _made(client.post("/api/institutions", json={"name": "Broker A"}))
    body = {"kind": "buy", "date": TODAY, "institution_id": broker_a, "asset_name": "Apple",
            "symbol": "AAPL", "quantity": 1, "unit_price": 100, "currency": "EUR",
            "price_currency": "USD"}

    via_euro = client.post("/api/transactions", json=body).json()
    _base("USD")
    via_dollar = client.post("/api/transactions", json={**body, "date": ANCHOR_DAY}).json()

    assert (via_euro["amount"], via_dollar["amount"]) == (80.0, 80.0)


def test_the_model_is_told_what_the_totals_are_in(client, feed):
    _base("USD")
    _wealth(client)
    with SessionLocal() as db:
        context = advisor.build_context(db)
        portfolio_context = advisor.build_portfolio_context(db)

    assert "Totals are in USD, the base currency." in context
    assert "Values are in USD, the base currency" in portfolio_context


def test_pence_are_pence_whatever_the_base(client, feed):
    """The minor-unit rule (fx._MINOR_EXACT) runs before the base is compared,
    so it holds for any base: 3,361 pence are 33.61 pounds, which in a pound
    base need no rate at all and in a dollar base are 33.61 / 0.64."""
    for base, expected in (("GBP", 33.61), ("USD", 33.61 / 0.64)):
        _base(base)
        with SessionLocal() as db:
            conv = fx.Converter(db, on=TODAY)
            assert conv.to_base(3361.0, "GBp") == pytest.approx(expected), base
            assert conv.from_base(expected, "GBp") == pytest.approx(3361.0), base
            assert conv.to_base(3361.0, "GBP") == pytest.approx(expected * 100), base


def test_a_position_born_in_the_ledger_is_photographed_in_the_base(client, feed, monkeypatch):
    """Starting a situation from the last one writes down every position the
    ledger created since — including one no photograph ever saw and nothing
    has priced. Its only figure is the projection's, which is in the base, so
    it is stored in the base: 2 units bought at 50 dollars are 100 dollars in a
    dollar base. Stored as euro, the same figure would be converted on the way
    in and read back as 80."""
    _base("USD")
    iid = _made(client.post("/api/institutions", json={"name": "Wise", "type": "broker"}))
    sid = _made(client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": ANCHOR_DAY}
    ))
    _made(client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Savings pot", "asset_class": "other", "value": 100, "currency": "USD"},
    ))
    bought = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    _made(client.post(
        "/api/transactions",
        json={"kind": "buy", "date": bought, "institution_id": iid, "asset_name": "Newco",
              "symbol": "NEWCO", "asset_class": "equity", "quantity": 2, "unit_price": 50,
              "currency": "USD", "price_currency": "USD"},
    ))
    monkeypatch.setattr(prices, "get_quotes", lambda symbols: {})

    r = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    )

    assert r.status_code == 201, r.text
    rows = {h["asset_name"]: h for h in client.get(f"/api/snapshots/{r.json()['id']}/holdings").json()}
    newco = rows["Newco"]
    assert (newco["currency"], newco["value"], newco["value_base"]) == ("USD", 100.0, 100.0)
