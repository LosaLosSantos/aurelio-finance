"""Prices refresh by themselves, once a day, and say how old they are.

In the reader's test round (2026-10-08) the cached closes were days old and
the chat said so: only the "Refresh market prices" button and the per-position
refresh ever asked. Brief AJ: the catch-up the app posts at every page load
brings each priced symbol's close up to date once a day, all of them in one
batch; since brief AK a followed ticker too, whose price no longer comes from
its dividend answer (test_the_price_from_the_public_door.py says why). And the
picture the chat and the analysis read gives a price its currency and its age.

Yahoo is faked at the app's helpers. Every symbol here is invented.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import advisor, crud, dated, models, prices
from app.database import SessionLocal

TODAY = "2026-10-08"
ANCHOR = "2026-10-01"


# --- The catch-up refreshes them --------------------------------------------------------


@pytest.fixture()
def held(client, monkeypatch):
    """One account whose situation of ANCHOR holds a share with no policy (its
    dividends are followed, so the window asks about it), an accumulating
    fund and a coin (neither asked), each priced six days ago."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": ANCHOR}).json()["id"]
    for symbol, asset_class, policy in (
        ("XSHR.DE", "equity", None),
        ("XACC.DE", "fund_etf", "acc"),
        ("XCOIN-EUR", "crypto", None),
    ):
        body = {
            "asset_name": f"{symbol}, held", "asset_class": asset_class, "symbol": symbol,
            "quantity": 10, "unit_price": 100, "currency": "EUR",
        }
        if policy:
            body["distribution_policy"] = policy
        assert client.post(f"/api/snapshots/{sid}/holdings", json=body).status_code == 201
    with SessionLocal() as db:
        crud.upsert_price_caches(
            db,
            {s: {"price": 40.0, "as_of": "2026-10-02", "currency": "EUR"} for s in ("XSHR.DE", "XACC.DE")},
        )
        for row in db.scalars(select(models.PriceCache)):
            row.fetched_at = "2026-10-02T17:00:00+00:00"
        db.commit()
    return iid


@pytest.fixture()
def yahoo(monkeypatch):
    """Yahoo, faked at the app's helpers: the share's dividend window lists
    none; the batch answers for whatever it is asked; each ask kept."""

    class Fake:
        windows: list[str] = []
        batches: list[list[str]] = []
        currencies: list[str] = []
        batch_fails = False
        closes: dict = {}

    def window(symbol, period="max"):
        Fake.windows.append(symbol)
        return prices.DividendWindow(answered=True)

    def batch(symbols):
        Fake.batches.append(list(symbols))
        if Fake.batch_fails:
            raise RuntimeError("no route to host")
        return {s: Fake.closes[s] for s in symbols if s in Fake.closes}

    def currency(symbol):
        Fake.currencies.append(symbol)
        return "EUR"

    monkeypatch.setattr(prices, "_fetch_dividends", window)
    monkeypatch.setattr(prices, "_fetch_recent_closes", batch)
    monkeypatch.setattr(prices, "_fetch_currency", currency)
    Fake.windows, Fake.batches, Fake.currencies, Fake.batch_fails = [], [], [], False
    Fake.closes = {
        "XACC.DE": (80.0, "2026-10-07"),
        "XCOIN-EUR": (2000.0, "2026-10-08"),
        "XSHR.DE": (50.0, "2026-10-07"),
    }
    return Fake


def _cached() -> dict[str, tuple]:
    with SessionLocal() as db:
        return {
            r.symbol: (r.price, r.as_of, r.currency)
            for r in db.scalars(select(models.PriceCache).order_by(models.PriceCache.symbol))
        }


def _catch_up(client) -> dict:
    out = client.post("/api/transactions/catch-up")
    assert out.status_code == 200, out.text
    return out.json()


EVERY = ["XACC.DE", "XCOIN-EUR", "XSHR.DE"]


def test_the_catch_up_refreshes_every_price_once_in_one_batch(client, held, yahoo):
    """The share's dividends and every price, the share's included: one
    window and one batch. Before brief AK the share was priced from its
    window and left out of the batch."""
    _catch_up(client)

    assert _cached() == {
        "XACC.DE": (80.0, "2026-10-07", "EUR"),
        "XCOIN-EUR": (2000.0, "2026-10-08", "EUR"),
        "XSHR.DE": (50.0, "2026-10-07", "EUR"),
    }
    assert yahoo.windows == ["XSHR.DE"], "the share's dividends, once"
    assert yahoo.batches == [EVERY], "every price in one batch, the share's too"
    assert yahoo.currencies == ["XCOIN-EUR"], "only the currency the cache had never learnt"


def test_a_second_start_the_same_day_asks_nothing(client, held, yahoo):
    _catch_up(client)
    _catch_up(client)

    assert yahoo.windows == ["XSHR.DE"]
    assert yahoo.batches == [EVERY]


def test_the_next_day_asks_again(client, held, yahoo, monkeypatch):
    _catch_up(client)
    monkeypatch.setattr(dated, "today", lambda: "2026-10-09")

    _catch_up(client)

    assert yahoo.windows == ["XSHR.DE", "XSHR.DE"]
    assert yahoo.batches == [EVERY, EVERY]


def test_a_market_that_does_not_answer_leaves_each_price_with_its_date(client, held, yahoo):
    """The ledger part of the catch-up stands, and a price nobody refreshed
    keeps the day it is of, which the picture and the pages show."""
    yahoo.batch_fails = True

    out = _catch_up(client)

    assert out["skipped"] == [], "a price not refreshed is no line in the banner"
    cached = _cached()
    assert cached["XSHR.DE"] == (40.0, "2026-10-02", "EUR")
    assert cached["XACC.DE"] == (40.0, "2026-10-02", "EUR")
    assert "XCOIN-EUR" not in cached


def test_a_symbol_yahoo_prices_nothing_for_is_not_asked_again_that_day(client, held, yahoo, monkeypatch):
    """A delisted ticker, one typed wrong: Yahoo prices the others in the
    same batch and nothing for it. Asked once that day, not at every page
    load (seen in the browser on a copy of the test database), and again the
    next day."""
    yahoo.closes = {"XACC.DE": (80.0, "2026-10-07"), "XSHR.DE": (50.0, "2026-10-07")}

    _catch_up(client)
    _catch_up(client)

    assert yahoo.batches == [EVERY]
    monkeypatch.setattr(dated, "today", lambda: "2026-10-09")
    _catch_up(client)
    assert yahoo.batches[-1] == EVERY


def test_a_batch_that_priced_nothing_is_tried_at_the_next_load(client, held, yahoo):
    """Nothing priced at all is a market that did not answer: the next page
    load asks again."""
    yahoo.closes = {}

    _catch_up(client)
    _catch_up(client)

    assert yahoo.batches == [EVERY, EVERY]


def test_writing_a_price_keeps_a_currency_already_learnt():
    """A guard on the upsert: a quote without a currency does not erase one."""
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {"XSHR.DE": {"price": 40.0, "as_of": "2026-10-02", "currency": "EUR"}})
        crud.upsert_price_caches(db, {"XSHR.DE": {"price": 41.0, "as_of": "2026-10-05"}})
        row = db.get(models.PriceCache, "XSHR.DE")
        assert (row.price, row.as_of, row.currency) == (41.0, "2026-10-05", "EUR")


# --- The picture says what a price is in, and how old it is ---------------------------


def test_the_picture_gives_a_price_its_currency_and_its_age(client, monkeypatch):
    """What the chat and the analysis read. A dollar price with no unit was
    written as one in the reader's round; a date was left for the model to
    count from. Ten units of a dollar listing bought at 100 USD, the dollar at
    1.25 to the euro: an average cost of 80.00 EUR, beside a price of 336.67
    USD six days old."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    monkeypatch.setattr(advisor.fx, "_fetch_rates", lambda base, start, end=None: {"2026-10-01": {"USD": 1.25}, "2026-10-02": {"USD": 1.25}})
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": ANCHOR}).json()["id"]
    assert client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Example US share", "asset_class": "equity", "symbol": "XUSD",
            "quantity": 10, "unit_price": 100, "currency": "USD",
        },
    ).status_code == 201
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {"XUSD": {"price": 336.67, "as_of": "2026-10-02", "currency": "USD"}})

    with SessionLocal() as db:
        picture = advisor.build_context(db)

    line = next(l for l in picture.splitlines() if l.startswith("- Example US share"))
    assert "avg cost 80.00 EUR" in line, line
    assert "price 336.67 USD as of 2026-10-02, 6 days before today" in line, line
    assert "(market prices as of 2026-10-02, 6 days before today)" in picture
