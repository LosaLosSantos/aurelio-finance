"""Prices refresh by themselves, once a day, and say how old they are.

In the reader's test round (2026-10-08) the cached closes were days old and
the chat said so: only the "Refresh market prices" button and the per-position
refresh ever asked. Brief AJ: the catch-up the app posts at every page load
brings each priced symbol's close up to date once a day. A ticker whose
dividends the catch-up asked about is priced from that same answer, which
carries the daily rows (measured 2026-10-08 on seven public tickers: one
request each); every other one is asked once, in one batch. And the picture
the chat and the analysis read gives a price its currency and its age.

Yahoo is faked: at its chart answer under the real yfinance for the window,
and at the app's helpers for the rest. Every symbol here is invented.
"""

from __future__ import annotations

import datetime
import json
import types

import pytest
from sqlalchemy import select

from app import advisor, crud, dated, models, prices
from app.database import SessionLocal

REAL_FETCH_DIVIDENDS = prices._fetch_dividends
TODAY = "2026-10-08"
ANCHOR = "2026-10-01"


# --- The window carries the price ------------------------------------------------------


def _stamp(day: str) -> int:
    return int(datetime.datetime.fromisoformat(day + "T07:00:00+00:00").timestamp())


def _chart(days: list[str], closes: list[float | None], currency: str, range_: str) -> dict:
    """Yahoo's chart answer, as yfinance 1.4.1 reads it: daily rows, a
    dividend on the third, the listing's currency in the metadata."""
    stamps = [_stamp(d) for d in days]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": currency, "symbol": "XGLO.L", "exchangeName": "LSE",
                        "instrumentType": "ETF", "firstTradeDate": _stamp("2020-01-02"),
                        "regularMarketTime": stamps[-1], "gmtoffset": 3600, "timezone": "BST",
                        "exchangeTimezoneName": "Europe/London", "regularMarketPrice": 104.0,
                        "chartPreviousClose": 99.0, "priceHint": 2, "dataGranularity": "1d",
                        "range": range_,
                        "validRanges": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"],
                    },
                    "timestamp": stamps,
                    "events": {"dividends": {str(stamps[2]): {"amount": 0.5, "date": stamps[2]}}},
                    "indicators": {
                        "quote": [{
                            "open": closes, "high": closes, "low": closes, "close": closes,
                            "volume": [1000 if c is not None else 0 for c in closes],
                        }],
                        "adjclose": [{"adjclose": closes}],
                    },
                }
            ],
            "error": None,
        }
    }


@pytest.fixture()
def chart(monkeypatch, tmp_path):
    """The real yfinance, answering every request with `chart.answer(range)`;
    `chart.asked` lists each request's range."""
    import yfinance as yf
    from yfinance import data as yfdata

    yf.set_tz_cache_location(str(tmp_path / "yf-cache"))

    class Fake:
        asked: list[str] = []
        answer = None

    def get(self, url, params=None, timeout=30):
        range_ = (params or {}).get("range", "1mo")
        Fake.asked.append(range_)
        body = Fake.answer(range_)
        return types.SimpleNamespace(
            status_code=200, url=url, text=json.dumps(body), json=lambda: body, headers={}
        )

    monkeypatch.setattr(yfdata.YfData, "get", get)
    monkeypatch.setattr(yfdata.YfData, "cache_get", get)
    monkeypatch.setattr(prices, "_fetch_dividends", REAL_FETCH_DIVIDENDS)
    Fake.asked = []
    return Fake


def test_the_window_brings_its_last_close_and_the_listings_currency(chart):
    """One answer, three facts: the dividends, as before; the last row that
    has a price, stepping over one that has none; and the currency, in its own
    case, GBp being pence. Asked for twice in all: the time zone, which
    yfinance learns once a ticker, and the window. Nothing for the price."""
    days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
    chart.answer = lambda r: _chart(days, [100.0, 101.0, 102.0, 103.0, None], "GBp", r)

    answer = prices._fetch_dividends("XGLO.L", "1mo")

    assert list(answer) == [{"date": "2026-10-05", "dps": 0.5}]
    assert answer.close == ("2026-10-06", 103.0)
    assert answer.currency == "GBp"
    assert chart.asked == ["1d", "1mo"]


def test_a_cut_of_the_window_keeps_what_it_carried(monkeypatch):
    """`get_dividends_since` keeps the dividends after the day it is asked for,
    and the price with them."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    monkeypatch.setattr(
        prices,
        "_fetch_dividends",
        lambda symbol, period="max": prices.Dividends(
            [{"date": "2026-09-20", "dps": 0.4}, {"date": "2026-10-05", "dps": 0.5}],
            close=("2026-10-07", 50.0),
            currency="EUR",
        ),
    )

    answer = prices.get_dividends_since("XSHR.DE", datetime.date(2026, 10, 1))

    assert list(answer) == [{"date": "2026-10-05", "dps": 0.5}]
    assert (answer.close, answer.currency) == (("2026-10-07", 50.0), "EUR")


def test_a_yfinance_that_keeps_no_rows_costs_only_the_shortcut(monkeypatch):
    """Its internals are read defensively: a Ticker without them still gives
    its dividends, and no price."""
    import yfinance

    monkeypatch.setattr(prices, "_fetch_dividends", REAL_FETCH_DIVIDENDS)
    monkeypatch.setattr(
        yfinance,
        "Ticker",
        lambda symbol: types.SimpleNamespace(get_dividends=lambda period="max": __import__("pandas").Series([], dtype=float)),
    )

    answer = prices._fetch_dividends("XSHR.DE", "1mo")

    assert list(answer) == [] and answer.close is None and answer.currency is None


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
    """Yahoo, faked at the app's helpers: the window answers with a close for
    the share; the batch answers for whatever it is asked; each ask kept."""

    class Fake:
        windows: list[str] = []
        batches: list[list[str]] = []
        currencies: list[str] = []
        batch_fails = False
        closes: dict = {}

    def window(symbol, period="max"):
        Fake.windows.append(symbol)
        return prices.Dividends([], close=("2026-10-07", 50.0), currency="EUR")

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
    Fake.closes = {"XACC.DE": (80.0, "2026-10-07"), "XCOIN-EUR": (2000.0, "2026-10-08")}
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


def test_the_catch_up_refreshes_each_price_once_and_asks_no_ticker_twice(client, held, yahoo):
    _catch_up(client)

    assert _cached() == {
        "XACC.DE": (80.0, "2026-10-07", "EUR"),
        "XCOIN-EUR": (2000.0, "2026-10-08", "EUR"),
        "XSHR.DE": (50.0, "2026-10-07", "EUR"),
    }
    assert yahoo.windows == ["XSHR.DE"], "the share's window, once"
    assert yahoo.batches == [["XACC.DE", "XCOIN-EUR"]], "the others, in one batch; not the share"
    assert yahoo.currencies == ["XCOIN-EUR"], "only the currency the cache had never learnt"


def test_a_second_start_the_same_day_asks_nothing(client, held, yahoo):
    _catch_up(client)
    _catch_up(client)

    assert yahoo.windows == ["XSHR.DE"]
    assert yahoo.batches == [["XACC.DE", "XCOIN-EUR"]]


def test_the_next_day_asks_again(client, held, yahoo, monkeypatch):
    _catch_up(client)
    monkeypatch.setattr(dated, "today", lambda: "2026-10-09")

    _catch_up(client)

    assert yahoo.windows == ["XSHR.DE", "XSHR.DE"]
    assert yahoo.batches == [["XACC.DE", "XCOIN-EUR"], ["XACC.DE", "XCOIN-EUR"]]


def test_a_market_that_does_not_answer_leaves_each_price_with_its_date(client, held, yahoo):
    """The ledger part of the catch-up stands, and a price nobody refreshed
    keeps the day it is of, which the picture and the pages show."""
    yahoo.batch_fails = True

    out = _catch_up(client)

    assert out["skipped"] == [], "a price not refreshed is no line in the banner"
    cached = _cached()
    assert cached["XSHR.DE"] == (50.0, "2026-10-07", "EUR"), "the window's still counts"
    assert cached["XACC.DE"] == (40.0, "2026-10-02", "EUR")
    assert "XCOIN-EUR" not in cached


def test_a_symbol_yahoo_prices_nothing_for_is_not_asked_again_that_day(client, held, yahoo, monkeypatch):
    """A delisted ticker, one typed wrong: Yahoo prices the others in the
    same batch and nothing for it. Asked once that day, not at every page
    load (seen in the browser on a copy of the test database), and again the
    next day."""
    yahoo.closes = {"XACC.DE": (80.0, "2026-10-07")}

    _catch_up(client)
    _catch_up(client)

    assert yahoo.batches == [["XACC.DE", "XCOIN-EUR"]]
    monkeypatch.setattr(dated, "today", lambda: "2026-10-09")
    _catch_up(client)
    assert yahoo.batches[-1] == ["XACC.DE", "XCOIN-EUR"]


def test_a_batch_that_priced_nothing_is_tried_at_the_next_load(client, held, yahoo):
    """Nothing priced at all is a market that did not answer: the next page
    load asks again."""
    yahoo.closes = {}

    _catch_up(client)
    _catch_up(client)

    assert yahoo.batches == [["XACC.DE", "XCOIN-EUR"], ["XACC.DE", "XCOIN-EUR"]]


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
