"""Yahoo's chart answer, faked under the real yfinance.

For the tests whose question is yfinance's own reading of an answer (which
column a close comes from, what `get_dividends` makes of an event), not the
app's reading of a result it is handed. Every request yfinance makes for a
chart goes through `YfData.get` or its memoised twin `cache_get`; both are
replaced, so nothing leaves the machine, and each request is kept with its
symbol and parameters.

A row stands at 07:00 UTC of its day: the same calendar day from Sydney to New
York, so yfinance dates it as written. Every symbol a test lists is invented.
"""

from __future__ import annotations

import datetime
import json
import types
from dataclasses import dataclass, field


def stamp(day: str) -> int:
    """A row's time: 07:00 UTC of `day`."""
    return int(datetime.datetime.fromisoformat(f"{day}T07:00:00+00:00").timestamp())


@dataclass
class Listing:
    """One symbol as Yahoo answers it: its daily closes (None for a row with no
    prices), the dividend-adjusted close where it differs from the close, its
    dividends by ex-date, and the listing's currency and time zone."""

    closes: dict[str, float | None]
    adjusted: dict[str, float] = field(default_factory=dict)
    dividends: dict[str, float] = field(default_factory=dict)
    currency: str = "EUR"
    timezone: str = "Europe/Berlin"

    def chart(self, symbol: str, params: dict) -> dict:
        """The answer to one request: the rows from period1 up to period2 when
        asked by dates, as Yahoo cuts them, and every row when asked by range."""
        lo, hi = params.get("period1"), params.get("period2")

        def within(day: str) -> bool:
            return lo is None or lo <= stamp(day) < (hi if hi is not None else float("inf"))

        days = [d for d in sorted(self.closes) if within(d)]
        closes = [self.closes[d] for d in days]
        meta = {
            "currency": self.currency, "symbol": symbol, "exchangeName": "XFAKE",
            "instrumentType": "EQUITY", "firstTradeDate": stamp("2020-01-02"),
            "regularMarketTime": stamp(days[-1]) if days else stamp("2020-01-02"),
            "gmtoffset": 0, "timezone": "UTC", "exchangeTimezoneName": self.timezone,
            "regularMarketPrice": next((c for c in reversed(closes) if c is not None), None),
            "chartPreviousClose": None, "priceHint": 2, "dataGranularity": "1d",
            "range": params.get("range", ""),
            "validRanges": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"],
        }
        result: dict = {"meta": meta}
        if days:
            result["timestamp"] = [stamp(d) for d in days]
            result["indicators"] = {
                "quote": [{
                    "open": closes, "high": closes, "low": closes, "close": closes,
                    "volume": [1000 if c is not None else 0 for c in closes],
                }],
                "adjclose": [{"adjclose": [self.adjusted.get(d, self.closes[d]) for d in days]}],
            }
        else:
            result["indicators"] = {"quote": [{}], "adjclose": [{}]}
        events = {
            str(stamp(d)): {"amount": amount, "date": stamp(d)}
            for d, amount in self.dividends.items()
            if within(d)
        }
        if events:
            result["events"] = {"dividends": events}
        return {"chart": {"result": [result], "error": None}}


class FakeYahoo:
    """The listings Yahoo knows, and every chart request asked of it as
    (symbol, parameters). A symbol it does not list is answered as Yahoo
    answers one: 404, "No data found"."""

    def __init__(self) -> None:
        self.listings: dict[str, Listing] = {}
        self.asked: list[tuple[str, dict]] = []

    def answer(self, url: str, params: dict):
        if "/v8/finance/chart/" not in url:
            raise AssertionError(f"the fake answers charts only, and was asked {url}")
        symbol = url.rsplit("/", 1)[-1]
        self.asked.append((symbol, dict(params)))
        listing = self.listings.get(symbol)
        if listing is None:
            status, body = 404, {
                "chart": {"result": None, "error": {
                    "code": "Not Found", "description": "No data found, symbol may be delisted",
                }}
            }
        else:
            status, body = 200, listing.chart(symbol, params)
        return types.SimpleNamespace(
            status_code=status, url=url, text=json.dumps(body), json=lambda: body, headers={}
        )


def install(monkeypatch, tmp_path) -> FakeYahoo:
    """The real yfinance from here on answers from a `FakeYahoo`, its time zone
    cache in `tmp_path` rather than the reader's own folder."""
    import yfinance as yf
    from yfinance import data as yfdata

    yf.set_tz_cache_location(str(tmp_path / "yf-cache"))
    fake = FakeYahoo()

    def get(self, url, params=None, timeout=30):
        return fake.answer(url, params or {})

    monkeypatch.setattr(yfdata.YfData, "get", get)
    monkeypatch.setattr(yfdata.YfData, "cache_get", get)
    return fake
