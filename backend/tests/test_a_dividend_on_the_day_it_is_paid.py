"""A dividend is dated on the day Yahoo says it is paid, where Yahoo says it.

Brief AZ, the reader's D3 (2026-10-16). Measured that day on 40 public
tickers: Yahoo's quote names a payment date for every US share (7 of 7, 14 to
24 days after the ex-date) and every US-listed ADR (5 of 5, 28 to 69 days),
for one dividend, the latest or the next; for nothing listed elsewhere and no
fund. So for a listing with no exchange suffix the catch-up asks the quote
once for each new dividend, and dates the row on that day: the cash counts
the money from the day it arrives, and a balance typed between the ex-date
and the payment no longer swallows it. A day still ahead waits, said once; a
day the quote names for another dividend, or one before the ex-date, is not
used; nobody answering is recorded as before.

Yahoo is faked where the app meets it (`_fetch_dividends`, `_fetch_payment_
day`); the reader's day with `dated.today`. The tickers are invented.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import dated, models, prices
from app.database import SessionLocal

TICKER = "XUSD"  # a listing with no exchange suffix, as a US one is written
EX = "2026-09-15"
PAID = "2026-10-01"

# The real helper, taken before conftest's `offline` replaces it in every test.
REAL_FETCH_PAYMENT_DAY = prices._fetch_payment_day


class Yahoo:
    def __init__(self) -> None:
        self.listed = [(EX, 0.53)]
        self.payment: prices.PaymentDay | Exception = prices.PaymentDay(EX, PAID)
        self.quotes_asked: list[str] = []

    def dividends(self, symbol: str, period: str = "max"):
        events = [{"date": day, "dps": dps} for day, dps in self.listed] if symbol in (TICKER, "XDIV.MI") else []
        return prices.DividendWindow(answered=True, dividends=events)

    def payment_day(self, symbol: str) -> prices.PaymentDay:
        self.quotes_asked.append(symbol)
        if isinstance(self.payment, Exception):
            raise self.payment
        return self.payment


@pytest.fixture()
def yahoo(monkeypatch) -> Yahoo:
    fake = Yahoo()
    monkeypatch.setattr(prices, "_fetch_dividends", fake.dividends)
    monkeypatch.setattr(prices, "_fetch_payment_day", fake.payment_day)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "USD")
    return fake


@pytest.fixture()
def on(monkeypatch):
    def today_is(day: str) -> None:
        monkeypatch.setattr(dated, "today", lambda: day)

    today_is("2026-10-05")
    return today_is


def _account(client, *, symbol: str = TICKER, balance: str | None = None) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-09-01"}).json()["id"]
    r = client.post(f"/api/snapshots/{sid}/holdings",
                    json={"asset_name": "Example US Share", "asset_class": "equity", "symbol": symbol,
                          "quantity": 10, "unit_price": 60, "currency": "USD"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/institutions/{iid}/cash-anchors",
                    json={"date": "2026-09-01", "amount": 1000.0, "currency": "USD"})
    assert r.status_code == 201, r.text
    if balance:
        r = client.post(f"/api/institutions/{iid}/cash-anchors",
                        json={"date": balance, "amount": 1000.0, "currency": "USD"})
        assert r.status_code == 201, r.text
    return iid


def _catch_up(client) -> dict:
    r = client.post("/api/transactions/catch-up")
    assert r.status_code == 200, r.text
    return r.json()


def _dividends(client) -> list[tuple]:
    return sorted(
        (t["date"], t["amount"], t.get("ex_date"), t["note"])
        for t in client.get("/api/transactions").json()
        if t["kind"] == "dividend"
    )


def _cash(client, iid: int) -> float:
    (cash,) = [c for c in client.get("/api/cash/positions").json() if c["institution_id"] == iid]
    return round(cash["projected"], 2)


def test_a_dividend_paid_already_is_dated_on_its_payment_day(client, yahoo, on):
    iid = _account(client)
    result = _catch_up(client)
    assert [(t["date"], t["ex_date"]) for t in result["created"]] == [(PAID, EX)]
    assert result.get("waiting") == []
    assert _dividends(client) == [(
        PAID, 5.3, EX,
        "Auto-recorded from market data: a dividend of 0.53 USD per share, on its payment date as Yahoo lists it",
    )]
    assert yahoo.quotes_asked == [TICKER]
    on("2026-10-06")
    assert _catch_up(client)["created"] == []
    assert yahoo.quotes_asked == [TICKER]
    assert _cash(client, iid) == 1005.3


def test_a_balance_typed_between_the_ex_date_and_the_payment_does_not_swallow_it(client, yahoo, on):
    """The third defect for such a listing: the balance of 25 September holds
    nothing paid on 1 October. Yahoo's day decides, nothing is asked, and the
    cash that follows counts it."""
    iid = _account(client, balance="2026-09-25")
    result = _catch_up(client)
    assert ([(t["date"], t["ex_date"]) for t in result["created"]], result["questions"]) == ([(PAID, EX)], [])
    assert _cash(client, iid) == 1005.3


def test_a_payment_day_still_ahead_waits_and_is_said_once(client, yahoo, on):
    on("2026-09-20")
    _account(client)
    result = _catch_up(client)
    assert result["created"] == []
    assert result["waiting"] == [{
        "institution_id": result["waiting"][0]["institution_id"], "institution_name": "Broker A",
        "symbol": TICKER, "ex_date": EX, "paid_on": PAID, "dps": 0.53, "currency": "USD",
    }]
    again = _catch_up(client)
    assert (again["created"], again["waiting"]) == ([], [])
    on("2026-09-30")
    assert _catch_up(client)["created"] == []
    on(PAID)
    assert [(t["date"], t["ex_date"]) for t in _catch_up(client)["created"]] == [(PAID, EX)]
    assert yahoo.quotes_asked == [TICKER]


def test_a_day_named_for_another_dividend_is_not_used(client, yahoo, on):
    """The quote names one dividend: here the next one (an ADR's shape seen
    that day named an older one). The dividend of 15 September keeps its
    ex-date, and the quote is not asked again for it."""
    yahoo.payment = prices.PaymentDay("2026-12-01", "2026-12-15")
    _account(client)
    assert [(t["date"], t["ex_date"]) for t in _catch_up(client)["created"]] == [(EX, EX)]
    with SessionLocal() as db:
        kept = {k: v for k, v in db.execute(select(models.Setting.key, models.Setting.value))
                if k.startswith("dividend_paid:")}
    assert kept == {f"dividend_paid:{TICKER}:{EX}": ""}


def test_a_day_before_the_ex_date_is_not_that_dividend_s(client, yahoo, on):
    """A Swiss share's quote named a payment a year before its ex-date."""
    yahoo.payment = prices.PaymentDay(EX, "2025-09-30")
    _account(client)
    assert [t["date"] for t in _catch_up(client)["created"]] == [EX]


def test_nobody_answering_records_it_on_its_ex_date(client, yahoo, on):
    yahoo.payment = OSError("Yahoo did not answer")
    _account(client)
    assert [t["date"] for t in _catch_up(client)["created"]] == [EX]


def test_a_listing_with_a_suffix_is_never_asked(client, yahoo, on):
    _account(client, symbol="XDIV.MI")
    assert [t["date"] for t in _catch_up(client)["created"]] == [EX]
    assert yahoo.quotes_asked == []


def test_one_listing_at_two_accounts_asks_once(client, yahoo, on):
    _account(client)
    iid = client.post("/api/institutions", json={"name": "Broker B", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-09-01"}).json()["id"]
    client.post(f"/api/snapshots/{sid}/holdings",
                json={"asset_name": "Example US Share", "asset_class": "equity", "symbol": TICKER,
                      "quantity": 4, "unit_price": 60, "currency": "USD"})
    created = _catch_up(client)["created"]
    assert sorted((t["date"], t["amount"]) for t in created) == [(PAID, 2.12), (PAID, 5.3)]
    assert yahoo.quotes_asked == [TICKER]


def test_the_quote_s_timestamps_are_read_in_utc(monkeypatch):
    """Yahoo names a day as its midnight in UTC: read in the machine's own
    zone, as `Ticker.calendar` does, it is the day before west of Greenwich."""
    import yfinance

    class Ticker:
        def __init__(self, symbol):
            pass

        def get_info(self):
            # KO's, 2026-10-16: ex-date 15 September, paid 1 October.
            return {"exDividendDate": 1789430400, "dividendDate": 1790812800}

    monkeypatch.setattr(yfinance, "Ticker", Ticker)
    monkeypatch.setattr(prices, "_fetch_payment_day", REAL_FETCH_PAYMENT_DAY)
    assert prices._fetch_payment_day("KO") == prices.PaymentDay("2026-09-15", "2026-10-01")
    # 23:30 in UTC on 14 September: the next day already east of Greenwich,
    # where this suite runs, so a day read in the machine's zone shows here.
    assert prices._utc_day(1789428600) == "2026-09-14"

    class Silent(Ticker):
        def get_info(self):
            return {"exDividendDate": 1789430400}

    monkeypatch.setattr(yfinance, "Ticker", Silent)
    assert prices._fetch_payment_day("SPY") == prices.PaymentDay()
