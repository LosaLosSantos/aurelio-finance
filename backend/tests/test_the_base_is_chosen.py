"""The reader chooses the base, and choosing it rewrites nothing they recorded.

Changing the base moves every total — the history's too — because it is the
same wealth in another unit. What it must never move is a stored amount: each
row keeps the currency it was written in, and a sum fixed on its day (what a
purchase debited, what a transfer delivered) was worked out then and is not
worked out again. So the proof is on the rows themselves: every table that
holds a recorded figure, read before the change and after it, identical.

The feeds for the two bases agree (one euro is 1.25 dollars), so every total in
dollars is its euro figure times 1.25.
"""

from __future__ import annotations

import datetime

import anyio
import pytest
from mcp.client import Client
from sqlalchemy import text

from app import analytics, fx, models
from app.database import READ_ONLY, SessionLocal, engine
from app.mcp_server import build_server

TODAY = datetime.date.today().isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
BOUGHT = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
PLAN_START = (datetime.date.today() + datetime.timedelta(days=40)).isoformat()

RATES = {
    "EUR": {"USD": 1.25, "GBP": 0.8, "CHF": 0.9},
    "USD": {"EUR": 0.8, "GBP": 0.64, "CHF": 0.72},
}
# Stores that are not money a reader recorded: rates and settings change with
# the base by design, and the price cache is the market's.
NOT_RECORDS = {"fx_rates", "settings", "price_cache", "alembic_version"}


class Feed:
    """The ECB for two bases that agree, with a switch to take either off line."""

    def __init__(self):
        self.asked: list[tuple] = []
        self.offline: set[str] = set()

    def fetch(self, base, start, end=None):
        self.asked.append((base, start, end))
        if base in self.offline or "*" in self.offline:
            raise fx.FxError("feed down")
        days = [ANCHOR_DAY, BOUGHT, TODAY]
        first = max((d for d in days if d <= start), default=days[0])
        return {d: dict(RATES[base]) for d in days if d >= first and (end is None or d <= end)}


@pytest.fixture()
def feed(monkeypatch) -> Feed:
    f = Feed()
    monkeypatch.setattr(fx, "_fetch_rates", f.fetch)
    return f


def _made(r) -> int:
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _wealth(client) -> dict:
    """Every kind of recorded figure, in more than one currency, including the
    two sums fixed on their day."""
    broker_a = _made(client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}))
    wise = _made(client.post("/api/institutions", json={"name": "Wise", "type": "bank"}))
    for iid, amount, currency in ((broker_a, 1000, "EUR"), (wise, 500, "USD")):
        _made(client.post(f"/api/institutions/{iid}/cash-anchors",
                          json={"date": ANCHOR_DAY, "amount": amount, "currency": currency}))
    sid = _made(client.post(f"/api/institutions/{broker_a}/snapshots", json={"date": ANCHOR_DAY}))
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={"asset_name": "Vanguard All-World", "asset_class": "equity", "symbol": "VWCE.MI",
                            "quantity": 10, "unit_price": 80, "currency": "EUR"}))
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={"asset_name": "UK lump", "asset_class": "other", "value": 100, "currency": "GBP"}))
    buy = client.post("/api/transactions", json={
        "kind": "buy", "date": BOUGHT, "institution_id": broker_a, "asset_name": "Apple", "symbol": "AAPL",
        "quantity": 1, "unit_price": 100, "currency": "EUR", "price_currency": "USD"}).json()
    transfer = client.post("/api/transfers", json={
        "date": BOUGHT, "from_institution_id": wise, "to_institution_id": broker_a,
        "amount": 250, "currency": "USD", "to_currency": "EUR"}).json()
    assert (buy["amount"], buy["fx_as_of"]) == (80.0, BOUGHT)
    assert (transfer["to_amount"], transfer["fx_as_of"]) == (200.0, BOUGHT)
    house = _made(client.post("/api/real-assets", json={"name": "House", "category": "real_estate", "currency": "EUR"}))
    _made(client.post(f"/api/real-assets/{house}/valuations", json={"date": ANCHOR_DAY, "value": 200_000}))
    loan = _made(client.post("/api/liabilities", json={"name": "Loan", "currency": "CHF"}))
    _made(client.post(f"/api/liabilities/{loan}/balances", json={"date": ANCHOR_DAY, "balance": 9_000}))
    _made(client.post("/api/income-sources", json={"name": "Salary", "amount": 2000, "currency": "EUR",
                                                   "frequency": "monthly", "institution_id": broker_a}))
    _made(client.post("/api/goals", json={"name": "House", "currency": "EUR", "target_amount": 50_000}))
    _made(client.post("/api/accumulation-plans", json={
        "name": "PAC", "amount": 300, "currency": "EUR", "frequency": "monthly", "start_date": PLAN_START,
        "source_institution_id": broker_a, "targets": [{"symbol": "VWCE.MI", "institution_id": broker_a}]}))
    with SessionLocal() as db:
        db.merge(models.PriceCache(symbol="VWCE.MI", price=100.0, currency="EUR", as_of=TODAY))
        db.commit()
    return {"broker_a": broker_a, "wise": wise}


def _records() -> dict[str, list[tuple]]:
    """Every row of every table a reader records figures in, as stored."""
    with engine.connect() as conn:
        tables = [
            r[0] for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'instruments_fts%'"))
            if r[0] not in NOT_RECORDS
        ]
        return {t: [tuple(row) for row in conn.execute(text(f'SELECT * FROM "{t}" ORDER BY rowid'))] for t in tables}


def _read_everything(client) -> dict:
    for path in ("/api/dashboard/summary", "/api/dashboard/net-worth-series", "/api/dashboard/portfolio",
                 "/api/dashboard/allocation", "/api/dashboard/cashflow", "/api/cash/positions"):
        assert client.get(path).status_code == 200, path
    client.post("/api/transactions/catch-up")
    return client.get("/api/dashboard/summary").json()


def test_the_base_comes_with_the_currencies_it_can_become(client, feed):
    body = client.get("/api/settings/base-currency").json()
    assert body == {"base_currency": "EUR", "available": ["CHF", "EUR", "GBP", "USD"]}


def test_changing_the_base_moves_every_total_and_rewrites_no_recorded_amount(client, feed):
    _wealth(client)
    in_euro = _read_everything(client)
    before = _records()

    r = client.put("/api/settings/base-currency", json={"base_currency": "usd"})
    assert r.status_code == 200, r.text
    assert r.json()["base_currency"] == "USD"
    in_dollars = _read_everything(client)
    after_dollars = _records()

    client.put("/api/settings/base-currency", json={"base_currency": "EUR"})
    back_in_euro = _read_everything(client)
    after_euro = _records()

    assert after_dollars == before
    assert after_euro == before
    # The same wealth in another unit, and back.
    assert in_dollars["base_currency"] == "USD"
    assert in_dollars["net_worth"] == pytest.approx(in_euro["net_worth"] * 1.25)
    assert back_in_euro["net_worth"] == pytest.approx(in_euro["net_worth"])


def test_a_sum_fixed_under_one_base_is_the_same_under_another(client, feed):
    """New fixed sums do not depend on the unit the totals are read in either:
    the same transfer recorded under a dollar base delivers what it delivered
    under the euro."""
    ids = _wealth(client)
    client.put("/api/settings/base-currency", json={"base_currency": "USD"})

    transfer = client.post("/api/transfers", json={
        "date": BOUGHT, "from_institution_id": ids["wise"], "to_institution_id": ids["broker_a"],
        "amount": 250, "currency": "USD", "to_currency": "EUR"}).json()
    buy = client.post("/api/transactions", json={
        "kind": "buy", "date": BOUGHT, "institution_id": ids["broker_a"], "asset_name": "Apple",
        "symbol": "AAPL", "quantity": 1, "unit_price": 100, "currency": "EUR", "price_currency": "USD"}).json()

    assert (transfer["to_amount"], buy["amount"]) == (200.0, 80.0)


def test_a_currency_the_feed_does_not_quote_cannot_be_the_base(client, feed):
    r = client.put("/api/settings/base-currency", json={"base_currency": "XYZ"})

    assert r.status_code == 422
    assert "not a currency the ECB rate feed quotes" in r.json()["detail"]
    assert client.get("/api/settings/base-currency").json()["base_currency"] == "EUR"


def test_no_base_is_chosen_before_its_rates_are_stored(client, feed):
    _wealth(client)
    client.get("/api/settings/base-currency")  # the euro rates are in
    feed.offline.add("USD")

    r = client.put("/api/settings/base-currency", json={"base_currency": "USD"})

    assert r.status_code == 503
    assert "the base is still EUR" in r.json()["detail"]
    assert client.get("/api/dashboard/summary").json()["base_currency"] == "EUR"
    with SessionLocal() as db:
        assert db.query(models.FxRate).filter(models.FxRate.base == "USD").count() == 0


def test_a_base_whose_older_days_cannot_be_stored_is_not_chosen(client, feed):
    """Today's rates are not enough. The history's oldest point is drawn at the
    rates of its own day, and a reader that cannot fetch would convert it with
    nothing: back to the euro, off line, with only today's euro rates kept, the
    change is refused and the dollar stays."""
    _wealth(client)
    assert client.put("/api/settings/base-currency", json={"base_currency": "USD"}).status_code == 200
    with SessionLocal() as db:
        db.query(models.FxRate).filter(models.FxRate.base == "EUR", models.FxRate.as_of < TODAY).delete()
        db.commit()
    feed.offline.add("*")

    r = client.put("/api/settings/base-currency", json={"base_currency": "EUR"})

    assert r.status_code == 503, r.text
    assert "the base is still USD" in r.json()["detail"]


def _mcp_positions() -> dict:
    server = build_server(engine.url.database)

    async def drive():
        async with Client(server, raise_exceptions=True) as c:
            return await c.call_tool("get_positions", {})

    result = anyio.run(drive)
    return result.structured_content


def test_a_reader_that_cannot_fetch_finds_the_new_bases_rates_already_stored(client, feed):
    """The MCP server opens the file read-only and never fetches. Right after a
    change of base it can only use what the change stored — and the change
    stores the new base's rates before it is made, so the reader converts
    instead of adding euro up as dollars."""
    _wealth(client)
    client.put("/api/settings/base-currency", json={"base_currency": "USD"})
    feed.offline.add("*")  # nothing more can be fetched by anyone

    positions = _mcp_positions()

    assert positions["base_currency"] == "USD"
    fund = next(p for p in positions["positions"] if p["symbol"] == "VWCE.MI")
    assert fund["book_value"] == pytest.approx(10 * 80 * 1.25)  # 1,000 dollars, not 800
    # And the history's oldest point, which needs the rates of its own day:
    # the change stored them from the oldest record on, not only today's.
    with SessionLocal() as db:
        db.info[READ_ONLY] = True
        oldest = analytics.compute_net_worth_series(db)[0]
    assert (oldest["date"], oldest["base_currency"], oldest["fx_as_of"]) == (ANCHOR_DAY, "USD", ANCHOR_DAY)


def test_without_that_the_reader_would_add_the_amounts_as_stored(client, feed):
    """The edge the change of base closes, shown open: the same setting written
    straight into the table, with no rates stored for it. The read-only reader
    has nothing to convert with and passes the euro through as dollars."""
    _wealth(client)
    feed.offline.add("*")
    with SessionLocal() as db:
        db.merge(models.Setting(key="base_currency", value="USD"))
        db.commit()

    fund = next(p for p in _mcp_positions()["positions"] if p["symbol"] == "VWCE.MI")

    assert fund["book_value"] == pytest.approx(800.0)
