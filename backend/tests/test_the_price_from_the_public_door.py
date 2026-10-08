"""The dividends come through yfinance's public door, and every price from the batch.

Brief AJ took a followed ticker's last close and its listing's currency from
the dividend answer by reading yfinance's internals
(`_lazy_load_price_history()._history_cache`, `_history_metadata`) and carried
them in a list with two attributes added. Brief AK measured the public calls
on 2026-10-08, on 18 public tickers none of which is the reader's, every
request counted:

- `get_dividends(period)` gives the dividends exactly, in one chart request.
- `history(period, actions=True, auto_adjust=False)` gives the dividends and
  the closes in one request too, but it moved the one dividend of 1,464 dated
  on a day with no price row (KO's of 2001-09-12, New York shut) to the
  session before, and it drops a currency Yahoo names; and its
  `history_metadata` asked Yahoo again, 36 times of 36, for the currency.

So the dividends stay on `get_dividends`, given back as a `DividendWindow`
that says whether Yahoo answered at all, and a followed ticker is priced in
the batch like every other symbol.

Yahoo is faked under the real yfinance where its reading is the question
(`tests/yahoo_chart.py`), and at the app's helpers elsewhere. Every symbol here
is invented.
"""

from __future__ import annotations

import datetime

import pytest

from app import dated, models, prices
from app.database import SessionLocal
from tests.yahoo_chart import Listing, install

REAL_FETCH_DIVIDENDS = prices._fetch_dividends
TODAY = "2026-10-08"


@pytest.fixture()
def yahoo_chart(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "_fetch_dividends", REAL_FETCH_DIVIDENDS)
    return install(monkeypatch, tmp_path)


class _Watched:
    """A real yfinance Ticker, every attribute the app reads off it noted."""

    def __init__(self, inner, read: list[str]) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_read", read)

    def __getattr__(self, name):
        self._read.append(name)
        return getattr(self._inner, name)


def test_the_window_reads_nothing_but_yfinances_public_answer(yahoo_chart, monkeypatch):
    """One chart request a window, once the time zone is known, and nothing of
    yfinance's read but `get_dividends`. Before: the window also opened
    yfinance's price history to take the close it had kept."""
    import yfinance

    yahoo_chart.listings["XGLO.L"] = Listing(
        closes={"2026-10-01": 100.0, "2026-10-02": 101.0, "2026-10-05": 102.0, "2026-10-06": 103.0},
        dividends={"2026-10-05": 0.5},
        currency="GBp",
        timezone="Europe/London",
    )
    read: list[str] = []
    real = yfinance.Ticker
    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: _Watched(real(symbol), read))

    window = REAL_FETCH_DIVIDENDS("XGLO.L", "1mo")

    assert read == ["get_dividends"], "nothing of yfinance's but its public call"
    assert window == prices.DividendWindow(answered=True, dividends=[{"date": "2026-10-05", "dps": 0.5}])
    assert [params.get("range") for _, params in yahoo_chart.asked] == ["1d", "1mo"], (
        "the time zone, the first time a ticker is seen; then the window, one request"
    )


def test_a_cut_of_the_window_keeps_whether_yahoo_answered(monkeypatch):
    """`get_dividends_since` keeps the dividends after the day it is asked
    for, and a window nobody answered stays one: it is not a ticker that pays
    nothing."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    windows = {
        "XSHR.DE": prices.DividendWindow(
            answered=True,
            dividends=[{"date": "2026-09-20", "dps": 0.4}, {"date": "2026-10-05", "dps": 0.5}],
        ),
        "XGONE.DE": prices.DividendWindow(answered=False),
    }
    monkeypatch.setattr(prices, "_fetch_dividends", lambda symbol, period="max": windows[symbol])
    since = datetime.date(2026, 10, 1)

    assert prices.get_dividends_since("XSHR.DE", since) == prices.DividendWindow(
        answered=True, dividends=[{"date": "2026-10-05", "dps": 0.5}]
    )
    assert prices.get_dividends_since("XGONE.DE", since) == prices.DividendWindow(answered=False)


def test_an_answer_that_never_came_lists_nothing():
    """The type says what it is: an answer, and what it lists, which cannot
    grow once read; a window nobody answered listing dividends is refused."""
    window = prices.DividendWindow(answered=True, dividends=[{"date": "2026-10-05", "dps": 0.5}])

    assert window.dividends == ({"date": "2026-10-05", "dps": 0.5},)
    assert prices.DividendWindow(answered=False).dividends == ()
    with pytest.raises(ValueError):
        prices.DividendWindow(answered=False, dividends=[{"date": "2026-10-05", "dps": 0.5}])


# --- The catch-up: a followed ticker is priced in the batch ------------------------------


ANCHOR = "2026-10-01"


@pytest.fixture()
def share(client, monkeypatch):
    """One account whose situation of ANCHOR holds a share with no policy, so
    the catch-up follows its dividends; never priced before."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": ANCHOR}).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "XSHR.DE, held", "asset_class": "equity", "symbol": "XSHR.DE",
            "quantity": 10, "unit_price": 100, "currency": "EUR",
        },
    )
    assert r.status_code == 201, r.text
    return iid


def test_a_followed_ticker_is_priced_in_the_batch_whatever_its_dividends_said(client, share, monkeypatch):
    """Yahoo said nothing about the share's dividends this time, and its price
    is still asked, in the batch: the price no longer hangs on the dividend
    answer. Before: a window that failed kept its ticker out of the batch for
    that run, and the price stayed as old as it was."""
    windows: list[str] = []
    batches: list[list[str]] = []

    def window(symbol, period="max"):
        windows.append(symbol)
        return prices.DividendWindow(answered=False)

    def batch(symbols):
        batches.append(list(symbols))
        return {"XSHR.DE": (50.0, "2026-10-07")}

    monkeypatch.setattr(prices, "_fetch_dividends", window)
    monkeypatch.setattr(prices, "_fetch_recent_closes", batch)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")

    assert client.post("/api/transactions/catch-up").status_code == 200

    assert windows == ["XSHR.DE"]
    assert batches == [["XSHR.DE"]]
    with SessionLocal() as db:
        row = db.get(models.PriceCache, "XSHR.DE")
        assert (row.price, row.as_of, row.currency) == (50.0, "2026-10-07", "EUR")
