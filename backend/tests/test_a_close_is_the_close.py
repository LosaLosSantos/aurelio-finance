"""A close is the price a day traded at, never Yahoo's dividend-adjusted one.

yfinance's `history()` and `download()` default to `auto_adjust=True`, which
puts Yahoo's dividend-adjusted close where the close is: every session before
an ex-date reads lower by that dividend. Measured 2026-10-08 on public tickers
(brief AK), each on the session before an ex-date: the app's `get_price_on`
read KO's 2026-09-14 as 88.82 where the close was 89.35, ENI.MI's 2026-09-18 as
23.68 for 23.95, ISF.L's 2026-09-16 as 1046.1134 for 1046.20.

`get_price_on` is what a plan buys at. An occurrence priced once an ex-date of
its fund had passed (a plan entered with a past first buy, the app not opened
for days, a close waited for across an ex-date) was bought below its day's
price, and with whole units, more of them than the money could buy.

Yahoo is faked under the real yfinance (`tests/yahoo_chart.py`): which column
becomes "Close" is yfinance's own doing, so nothing above it can show this.
Every symbol here is invented; the 14th's close and adjusted close, and the
dividend of the 15th, are KO's as measured, the other prices invented.
"""

from __future__ import annotations

import datetime

import pytest

from app import dated, pac, prices
from app.database import SessionLocal
from tests.yahoo_chart import Listing, install

REAL_FETCH_CLOSE_WINDOW = prices._fetch_close_window
REAL_FETCH_RECENT_CLOSES = prices._fetch_recent_closes
REAL_FETCH_CURRENCY = prices._fetch_currency
TODAY = "2026-10-08"

# A week around an ex-date of 0.53 on Tuesday the 15th: the sessions before it
# carry the adjusted close beside the close, as Yahoo sends them.
WEEK = {
    "2026-09-09": 88.10, "2026-09-10": 88.60, "2026-09-11": 88.95,
    "2026-09-14": 89.35, "2026-09-15": 88.70, "2026-09-16": 88.90,
    "2026-09-17": 89.10, "2026-09-18": 89.40,
}
ADJUSTED = {"2026-09-09": 87.58, "2026-09-10": 88.07, "2026-09-11": 88.42, "2026-09-14": 88.82}


@pytest.fixture()
def yahoo_chart(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "_fetch_close_window", REAL_FETCH_CLOSE_WINDOW)
    monkeypatch.setattr(prices, "_fetch_recent_closes", REAL_FETCH_RECENT_CLOSES)
    monkeypatch.setattr(prices, "_fetch_currency", REAL_FETCH_CURRENCY)
    fake = install(monkeypatch, tmp_path)
    fake.listings["XDIV.DE"] = Listing(closes=WEEK, adjusted=ADJUSTED, dividends={"2026-09-15": 0.53})
    return fake


def test_a_dated_price_is_that_days_close(yahoo_chart):
    """What a plan buys at, on the session before an ex-date."""
    quote = prices.get_price_on("XDIV.DE", datetime.date(2026, 9, 14), datetime.date(2026, 10, 8))

    assert (quote["price"], quote["as_of"]) == (89.35, "2026-09-14")


def test_the_latest_close_is_the_close_on_an_ex_date_morning(yahoo_chart, monkeypatch):
    """The per-position refresh, before the session of an ex-date has opened:
    the day's row has no prices yet, and Yahoo already adjusts the session
    before it. The price is that session's close."""
    monkeypatch.setattr(dated, "today", lambda: "2026-09-15")
    yahoo_chart.listings["XDIV.DE"] = Listing(
        closes={**{d: c for d, c in WEEK.items() if d < "2026-09-15"}, "2026-09-15": None},
        adjusted=ADJUSTED,
        dividends={"2026-09-15": 0.53},
    )

    price, _, as_of = prices._fetch_recent_close("XDIV.DE")

    assert (price, as_of) == (89.35, "2026-09-14")


def test_the_batch_reads_the_close(yahoo_chart):
    """The daily refresh and the "Refresh market prices" button: the same
    morning, in one batch with a symbol that has no dividend."""
    yahoo_chart.listings["XDIV.DE"] = Listing(
        closes={d: c for d, c in WEEK.items() if d < "2026-09-15"},
        adjusted=ADJUSTED,
        dividends={"2026-09-15": 0.53},
    )
    yahoo_chart.listings["XACC.DE"] = Listing(closes={"2026-09-11": 50.0, "2026-09-14": 51.0})

    closes = prices._fetch_recent_closes(["XACC.DE", "XDIV.DE"])

    assert closes == {"XACC.DE": (51.0, "2026-09-14"), "XDIV.DE": (89.35, "2026-09-14")}


def test_a_plan_buys_at_its_days_close(client, yahoo_chart, monkeypatch):
    """A monthly plan of 800 EUR whose first buy, on the 14th, is priced on
    the 8th of the next month, the ex-date of the 15th long past: 8 units at
    89.35. At the adjusted 88.82 the same 800 bought 9."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "Example plan", "amount": 800, "currency": "EUR", "frequency": "monthly",
            "start_date": "2026-09-14", "source_institution_id": iid,
            "targets": [{"symbol": "XDIV.DE", "asset_name": "Example share", "institution_id": iid}],
        },
    )
    assert r.status_code == 201, r.text

    with SessionLocal() as db:
        out = pac.execute_due(db)
        assert out["skipped"] == []
        (buy,) = out["created"]
        assert (buy.date, buy.quantity, buy.unit_price) == ("2026-09-14", 8, 89.35)
