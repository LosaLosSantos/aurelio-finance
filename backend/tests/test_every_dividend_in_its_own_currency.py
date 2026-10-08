"""Every dividend is recorded, in the currency it was paid in (brief AF).

Three things, each measured on Yahoo's public data on 2026-10-05 before any
code was written.

**The currency.** yfinance 1.4.1 keeps a dividend's currency as a second
column whenever any event names one, and `.dividends` is then a DataFrame,
which `_fetch_dividends` used to iterate as (column, Series) pairs: a
`TypeError`, so the ticker's whole history was skipped, at every start. No real
listing was found naming one (52 tickers, Vietnam included, the case yfinance's
own comment names), and an unnamed amount is the listing's: the Vanguard
All-World fund's dividend of 2026-09-17 in dollars (VWRD.L) over the same in
euros (VWRL.MI) is 1.1486, the ECB's EUR/USD that day 1.1481. So a named
currency is the only one that is not the listing's, and it is recorded as
named, converted like any other amount. One event that cannot be read is said
on its own ex-date; it does not take the rest of the history with it.

**A share's policy is its history.** A share has no
Accumulating or Distributing to choose: it pays or it does not. A stated
policy is still obeyed (a fund's, the reader's or the catalogue's), but an
empty one no longer means "never": the holding's own dividend history decides,
and whatever Yahoo lists after the situation date is recorded. The "Stocks &
ETF" bucket files every new row as `equity`, so the class cannot tell a share
from a fund typed by hand, and both follow their history. Crypto pays none and
is not asked.

**The whole history once, then a window.** `.dividends` downloads a ticker's
whole daily price history to read its dividends: 14,363,983 bytes for the 22
tickers §16 adds, every day. A daily request from the situation's date lost no
dividend over 460 checks on 26 tickers, at 73,933 bytes for the same 22. So a
ticker is asked for its whole history the first time it is followed, which is
what gives its line the last dividend Yahoo lists, and from then on for a
window that reaches back to the earliest situation that needs it.

Yahoo is faked where the app meets it: `prices._fetch_dividends` for the rules,
and `yfinance.Ticker` itself where the currency is read. Tickers are invented.
"""

from __future__ import annotations

import datetime
import threading

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import crud, dated, fx, models, prices
from app.database import SessionLocal
from app.main import app

# The real helper, taken before conftest's `offline` replaces it in every test.
# The tests of the currency run it against a faked yfinance.
REAL_FETCH_DIVIDENDS = prices._fetch_dividends

ANCHOR = "2026-01-01"
DAY = "2026-04-01"
NEXT_DAY = "2026-04-02"


# --- Fakes and helpers ---------------------------------------------------------


class Yahoo:
    """What `prices._fetch_dividends` answers, per ticker: a list of dividends,
    None for an answer that never came, an exception for a fetch that failed,
    each given back as the window it is. Every ask is recorded with the range
    it asked for."""

    def __init__(self) -> None:
        self.answers: dict[str, object] = {}
        self.asked: list[tuple[str, str]] = []

    def fetch(self, symbol: str, period: str = "max"):
        self.asked.append((symbol, period))
        answer = self.answers.get(symbol, [])
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return prices.DividendWindow(answered=False)
        return prices.DividendWindow(answered=True, dividends=answer)


@pytest.fixture()
def yahoo(monkeypatch) -> Yahoo:
    fake = Yahoo()
    monkeypatch.setattr(prices, "_fetch_dividends", fake.fetch)
    return fake


@pytest.fixture()
def on(monkeypatch):
    """`on(day)`: the reader's calendar reads `day` from here on."""

    def today_is(day: str) -> None:
        monkeypatch.setattr(dated, "today", lambda: day)

    return today_is


def paid(date: str, dps: float, currency: str | None = None) -> dict:
    """One dividend as `_fetch_dividends` answers it."""
    return {"date": date, "dps": dps} | ({"currency": currency} if currency else {})


def _account(client, name: str = "Broker A", cash_in: str | None = None) -> int:
    iid = client.post("/api/institutions", json={"name": name, "type": "broker"}).json()["id"]
    if cash_in is not None:
        r = client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": ANCHOR, "amount": 1000.0, "currency": cash_in},
        )
        assert r.status_code == 201, r.text
    return iid


def _hold(
    client,
    iid: int,
    symbol: str,
    *,
    asset_class: str = "equity",
    policy: str | None = None,
    anchor: str = ANCHOR,
    qty: float = 10,
    currency: str = "USD",
) -> int:
    """A situation of `iid` dated `anchor` holding `qty` units of `symbol`."""
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": anchor}).json()["id"]
    body = {
        "asset_name": f"{symbol}, held",
        "asset_class": asset_class,
        "symbol": symbol,
        "quantity": qty,
        "unit_price": 100,
        "currency": currency,
    }
    if policy is not None:
        body["distribution_policy"] = policy
    r = client.post(f"/api/snapshots/{sid}/holdings", json=body)
    assert r.status_code == 201, r.text
    return sid


def _listed_in(symbol: str, currency: str) -> None:
    """What pricing the listing once taught the price cache."""
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {symbol: {"price": 100.0, "as_of": ANCHOR, "currency": currency}})


def _catch_up(client) -> dict:
    out = client.post("/api/transactions/catch-up")
    assert out.status_code == 200, out.text
    return out.json()


def _dividends() -> list[tuple]:
    with SessionLocal() as db:
        return [
            (t.date, t.symbol, t.quantity, t.unit_price, t.price_currency, t.amount, t.currency, t.fx_as_of)
            for t in db.scalars(
                select(models.Transaction)
                .where(models.Transaction.kind == "dividend")
                .order_by(models.Transaction.date, models.Transaction.id)
            )
        ]


# --- The currency: read through yfinance itself ------------------------------------


class _Ticker:
    """A yfinance Ticker whose dividends are `frame`, whatever range is asked.
    `.dividends` too, which is what the app read before this brief."""

    def __init__(self, frame, calls: list[str]) -> None:
        self._frame = frame
        self._calls = calls

    def get_dividends(self, period: str = "max"):
        self._calls.append(period)
        return self._frame

    @property
    def dividends(self):
        return self.get_dividends("max")


def _two_columns(*events: tuple) -> pd.DataFrame:
    """Dividends as yfinance 1.4.1 keeps them when Yahoo names a currency on
    any event: the amount and the currency, by ex-date in the exchange's zone.
    Shown on 2026-09-30 with Yahoo's chart answer itself faked, not built by
    hand: the shape `_fetch_dividends` failed on."""
    index = pd.DatetimeIndex([d for d, _, _ in events]).tz_localize("America/New_York")
    return pd.DataFrame(
        {"Dividends": [a for _, a, _ in events], "currency": [c for _, _, c in events]}, index=index
    ).rename_axis("Date")


@pytest.fixture()
def yfinance_answers(monkeypatch):
    """`yfinance_answers(frame)`: every Ticker the app builds answers `frame`;
    returns the list of ranges asked, one entry per ask."""
    import yfinance

    monkeypatch.setattr(prices, "_fetch_dividends", REAL_FETCH_DIVIDENDS)
    calls: list[str] = []

    def answer(frame) -> list[str]:
        monkeypatch.setattr(yfinance, "Ticker", lambda symbol: _Ticker(frame, calls))
        return calls

    return answer


@pytest.fixture()
def rates(monkeypatch):
    """`rates(table)`: the ECB answers `table` ({day: {currency: per euro}}),
    or refuses when it is None."""

    def answer(table) -> None:
        def fetch(base, start, end=None):
            if table is None:
                raise fx.FxError("feed down")
            return table

        monkeypatch.setattr(fx, "_fetch_rates", fetch)

    return answer


def test_a_dividend_named_in_another_currency_is_recorded_in_it_and_converted(
    client, yfinance_answers, rates, on
):
    """A dollar listing whose March dividend Yahoo names in euros, into a dollar
    account. The euro dividend is recorded as paid, 2.0 EUR a share, and
    converted at its ex-date's rate (1.25): 25.00 USD for 10 shares. The
    February one names nothing, so it is the listing's, as every real answer
    measured was: 10.00 USD with nothing to convert.

    Before: yfinance's two columns raised a TypeError in `_fetch_dividends`,
    and the whole history was one skip line."""
    iid = _account(client, cash_in="USD")
    _hold(client, iid, "ADRX", policy="dist")
    _listed_in("ADRX", "USD")
    yfinance_answers(_two_columns(("2026-02-10", 1.0, ""), ("2026-03-20", 2.0, "EUR")))
    rates({"2026-03-20": {"USD": 1.25}})
    on(DAY)

    out = _catch_up(client)

    assert out["skipped"] == []
    assert _dividends() == [
        ("2026-02-10", "ADRX", 10.0, 1.0, "USD", 10.0, "USD", None),
        ("2026-03-20", "ADRX", 10.0, 2.0, "EUR", 25.0, "USD", "2026-03-20"),
    ]
    notes = sorted(t["note"] for t in out["created"])
    assert notes == [
        "Auto-recorded from market data: a dividend of 1.0 USD per share",
        "Auto-recorded from market data: a dividend of 2.0 EUR per share",
    ]


def test_one_event_that_cannot_be_read_does_not_take_the_history_with_it(
    client, yfinance_answers, on
):
    """Of three dividends, one amount is not a number and one currency is not
    a code. The third is recorded; each of the other two is said on its own
    ex-date, so the reader knows which to enter from the statement.

    Before: one TypeError for the whole history, said once, nothing recorded."""
    iid = _account(client)
    _hold(client, iid, "ADRX", policy="dist")
    _listed_in("ADRX", "USD")
    yfinance_answers(
        _two_columns(("2026-02-10", 1.0, ""), ("2026-03-20", "n/a", "EUR"), ("2026-03-27", 1.5, "US$"))
    )
    on(DAY)

    out = _catch_up(client)

    assert _dividends() == [("2026-02-10", "ADRX", 10.0, 1.0, "USD", 10.0, "USD", None)]
    assert [(s["label"], s["occurrence"]) for s in out["skipped"]] == [
        ("ADRX", "2026-03-20"),
        ("ADRX", "2026-03-27"),
    ]
    reasons = [s["reason"] for s in out["skipped"]]
    assert "its amount 'n/a' is not a number" in reasons[0]
    assert "its currency 'US$' is not a currency code" in reasons[1]
    assert all("enter it from your statement" in r for r in reasons)


def test_a_named_currency_is_kept_with_the_days_answer(client, yfinance_answers, rates, on):
    """Brief X's rule with a named currency: the euro dividend waits while the
    ECB has no rate for its day, and the next catch-up writes it from the
    day's kept answer, still in euros, without asking Yahoo again."""
    iid = _account(client, cash_in="USD")
    _hold(client, iid, "ADRX", policy="dist")
    _listed_in("ADRX", "USD")
    asked = yfinance_answers(_two_columns(("2026-03-20", 2.0, "EUR")))
    on(DAY)

    rates(None)
    first = _catch_up(client)
    assert first["created"] == []
    assert [(s["label"], s["occurrence"]) for s in first["skipped"]] == [("ADRX", "2026-03-20")]

    rates({"2026-03-20": {"USD": 1.25}})
    (tx,) = _catch_up(client)["created"]

    assert (tx["price_currency"], tx["unit_price"], tx["amount"], tx["currency"]) == ("EUR", 2.0, 25.0, "USD")
    assert asked == ["max"]


@pytest.mark.parametrize(
    "named, expected",
    [("", None), (float("nan"), None), ("GBp", "GBp"), ("EUR", "EUR")],
    ids=["empty", "missing", "pence", "euro"],
)
def test_what_a_dividend_names_is_read_as_it_is_written(monkeypatch, named, expected):
    """One level down: an empty or missing currency names none (the listing's
    is used); a named one is kept as written, case included, because GBp is
    pence and GBP pounds."""
    import yfinance

    frame = _two_columns(("2026-03-20", 0.5, named), ("2026-06-20", 0.6, "EUR"))
    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: _Ticker(frame, []))

    first, _ = REAL_FETCH_DIVIDENDS("ADRX").dividends

    assert first == ({"date": "2026-03-20", "dps": 0.5} | ({"currency": expected} if expected else {}))


# --- §16: an empty policy is decided by the holding's history ------------------------


def test_a_share_with_no_policy_is_asked_and_what_it_paid_is_recorded(client, yahoo, on):
    """The reader's case: a share carries no policy, because a share has none to
    choose. Its dividends after the situation are recorded."""
    iid = _account(client)
    _hold(client, iid, "ACME")
    yahoo.answers["ACME"] = [paid("2025-12-15", 0.4), paid("2026-02-14", 0.5), paid("2026-03-20", 0.5)]
    on(DAY)

    created = _catch_up(client)["created"]

    assert [(t["symbol"], t["date"], t["amount"]) for t in created] == [
        ("ACME", "2026-02-14", 5.0),
        ("ACME", "2026-03-20", 5.0),
    ]
    assert yahoo.asked == [("ACME", "max")]


def test_a_share_that_never_paid_is_asked_and_records_nothing(client, yahoo, on):
    """Asked all the same, because a share that starts paying is followed the
    day Yahoo lists its first dividend; nothing is recorded, nothing is said."""
    iid = _account(client)
    _hold(client, iid, "QUIET")
    yahoo.answers["QUIET"] = []
    on(DAY)

    assert _catch_up(client) == {"created": [], "skipped": []}
    assert yahoo.asked == [("QUIET", "max")]


def test_a_fund_typed_with_no_policy_follows_its_history_too(client, yahoo, on):
    """An ETF typed into "Stocks & ETF" is filed as `equity`, and one a PAC
    carried into a situation as `fund_etf`: either way, with no policy, its
    history decides, so a distributing fund nobody marked is no longer lost."""
    iid = _account(client)
    _hold(client, iid, "HANDETF.MI", asset_class="fund_etf", currency="EUR")
    yahoo.answers["HANDETF.MI"] = [paid("2026-03-20", 0.3)]
    on(DAY)

    (tx,) = _catch_up(client)["created"]

    assert (tx["symbol"], tx["amount"]) == ("HANDETF.MI", 3.0)


@pytest.mark.parametrize("policy, recorded", [("acc", 0), ("dist", 1)])
def test_a_stated_policy_is_kept(client, yahoo, on, policy, recorded):
    """A fund keeps the policy the reader or the catalogue gave it: an
    accumulating one is never asked, even with dividends listed for its
    ticker; a distributing one is asked as before."""
    iid = _account(client)
    _hold(client, iid, "FUNDX.MI", asset_class="fund_etf", policy=policy, currency="EUR")
    yahoo.answers["FUNDX.MI"] = [paid("2026-03-20", 0.3)]
    on(DAY)

    assert len(_catch_up(client)["created"]) == recorded
    assert yahoo.asked == ([] if policy == "acc" else [("FUNDX.MI", "max")])


def test_crypto_with_no_policy_is_never_asked(client, yahoo, on):
    """A coin pays no dividend, so asking Yahoo every day would cost a request
    for nothing."""
    iid = _account(client)
    _hold(client, iid, "TOKEN-EUR", asset_class="crypto", currency="EUR")
    on(DAY)

    assert _catch_up(client) == {"created": [], "skipped": []}
    assert yahoo.asked == []


def test_a_share_is_asked_once_a_day(client, yahoo, on):
    """Brief X's rule holds for a share as for a distributing fund: two
    catch-ups on one day ask once, and the next day asks again."""
    iid = _account(client)
    _hold(client, iid, "ACME")
    yahoo.answers["ACME"] = [paid("2026-03-20", 0.5)]
    on(DAY)
    assert len(_catch_up(client)["created"]) == 1
    assert _catch_up(client)["created"] == []
    assert [s for s, _ in yahoo.asked] == ["ACME"]

    on(NEXT_DAY)
    _catch_up(client)
    assert [s for s, _ in yahoo.asked] == ["ACME", "ACME"]


def test_two_catch_ups_at_once_record_a_shares_dividend_once(client, yahoo, on, monkeypatch):
    """Brief Y's rule holds for a share: both catch-ups held between "already
    recorded?" and the write, one row."""
    iid = _account(client)
    _hold(client, iid, "ACME")
    yahoo.answers["ACME"] = [paid("2026-03-20", 0.5)]
    on(DAY)
    everyone_in = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    checks: list[str] = []
    real = crud.get_dividend_dates_recorded

    def held(db, institution_id, symbol):
        recorded = real(db, institution_id, symbol)
        with lock:
            checks.append(symbol)
            first_two = len(checks) <= 2
        if first_two:
            everyone_in.wait()
        return recorded

    monkeypatch.setattr(crud, "get_dividend_dates_recorded", held)
    tab = TestClient(app, raise_server_exceptions=False)
    statuses: list[int] = []

    def run() -> None:
        response = tab.post("/api/transactions/catch-up")
        with lock:
            statuses.append(response.status_code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert statuses == [200, 200]
    assert len(checks) >= 2, "the catch-ups did not overlap, so nothing was tested"
    assert [(d, s, a) for d, s, _, _, _, a, _, _ in _dividends()] == [("2026-03-20", "ACME", 5.0)]


# --- The whole history once, then a window -------------------------------------------


def test_the_whole_history_is_asked_once_and_then_a_window_from_the_situation(client, yahoo, on):
    """The first time a ticker is followed, its whole history: that is what
    says when it last paid. From the next day, a window that reaches back to
    the situation, which is all the catch-up needs: here 8 days, Yahoo's
    "1mo"."""
    iid = _account(client)
    _hold(client, iid, "ACME", anchor="2026-03-25")
    yahoo.answers["ACME"] = [paid("2025-12-15", 0.4), paid("2026-03-27", 0.5)]
    on(DAY)
    assert [t["date"] for t in _catch_up(client)["created"]] == ["2026-03-27"]

    on(NEXT_DAY)
    yahoo.answers["ACME"] = [paid("2026-03-27", 0.5), paid(NEXT_DAY, 0.6)]
    assert [t["date"] for t in _catch_up(client)["created"]] == [NEXT_DAY]

    assert yahoo.asked == [("ACME", "max"), ("ACME", "1mo")]


def test_a_situation_older_than_the_days_window_asks_again_from_its_own_date(client, yahoo, on):
    """The day's answer covers the situations it was asked for. A second account
    holding the same share, entered later that day with an older situation,
    needs dividends the window does not reach: Yahoo is asked again, from that
    situation, and the older dividend is recorded for it."""
    broker_a = _account(client, "Broker A")
    _hold(client, broker_a, "ACME", anchor="2026-03-25")
    yahoo.answers["ACME"] = [paid("2026-02-14", 0.5), paid("2026-03-27", 0.5)]
    on(DAY)
    _catch_up(client)
    on(NEXT_DAY)
    _catch_up(client)

    broker_b = _account(client, "Broker B")
    _hold(client, broker_b, "ACME", anchor="2026-01-01", qty=4)
    created = _catch_up(client)["created"]

    assert sorted((t["institution_id"], t["date"], t["amount"]) for t in created) == [
        (broker_b, "2026-02-14", 2.0),
        (broker_b, "2026-03-27", 2.0),
    ]
    assert yahoo.asked == [("ACME", "max"), ("ACME", "1mo"), ("ACME", "6mo")]


def test_the_line_says_when_the_holding_last_paid(client, yahoo, on):
    """What the reader sees: a holding whose history decides carries the last
    dividend Yahoo lists, on Records and in Portfolio. A day whose window holds
    nothing new keeps the date the whole history gave; a share that never paid
    has none, and so does one never asked."""
    iid = _account(client)
    sid = _hold(client, iid, "ACME", anchor="2026-03-25")
    yahoo.answers["ACME"] = [paid("2025-12-15", 0.4), paid("2026-03-20", 0.5)]
    on(DAY)
    _catch_up(client)
    on(NEXT_DAY)
    yahoo.answers["ACME"] = []
    _catch_up(client)

    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fund, accumulating", "asset_class": "fund_etf", "symbol": "ACCX.MI",
              "quantity": 1, "unit_price": 100, "distribution_policy": "acc", "currency": "EUR"},
    )
    assert r.status_code == 201, r.text

    lines = {h["symbol"]: h["last_dividend"] for h in client.get(f"/api/snapshots/{sid}/holdings").json()}
    assert lines == {"ACME": "2026-03-20", "ACCX.MI": None}
    rows = {r["symbol"]: r["last_dividend"] for r in client.get("/api/dashboard/portfolio?live=false").json()["rows"]}
    assert rows == {"ACME": "2026-03-20", "ACCX.MI": None}


def test_the_window_reaches_the_earliest_situation_so_a_dividend_waiting_for_its_rate_is_kept(
    client, yahoo, rates, on
):
    """One ticker at two accounts, one situation older than the other. A
    dollar dividend into the older one's euro account waits a day for its
    rate; the next day's window reaches back to the EARLIEST situation of the
    two, so the dividend is still in Yahoo's answer and is written then. A
    window sized for the newer one would leave it out for good."""
    broker_b = _account(client, "Broker B", cash_in="EUR")
    _hold(client, broker_b, "ACME", anchor="2026-01-01")
    broker_a = _account(client, "Broker A", cash_in="EUR")
    _hold(client, broker_a, "ACME", anchor="2026-03-25")
    _listed_in("ACME", "USD")
    yahoo.answers["ACME"] = [paid("2026-02-12", 0.5)]
    on(DAY)
    rates(None)
    out = _catch_up(client)
    assert [(s["label"], s["occurrence"]) for s in out["skipped"]] == [("ACME", "2026-02-12")]

    on(NEXT_DAY)
    rates({"2026-02-12": {"USD": 1.25}})
    (tx,) = _catch_up(client)["created"]

    assert (tx["institution_id"], tx["date"], tx["amount"]) == (broker_b, "2026-02-12", 4.0)
    assert yahoo.asked == [("ACME", "max"), ("ACME", "6mo")]


def test_a_newer_situation_does_not_hide_from_the_line_what_was_paid_since_the_last_answer(
    client, yahoo, on
):
    """The reader records a newer situation, dated after the day Yahoo last
    answered. A dividend paid in between belongs to that situation (it already
    accounts for it, so nothing is recorded), but it is still the last one the
    share paid: the window reaches back to the answer before it, not only to
    the situation, or the line would go on showing an older date."""
    iid = _account(client)
    _hold(client, iid, "ACME", anchor="2026-03-25")
    yahoo.answers["ACME"] = [paid("2025-12-15", 0.4)]
    on(DAY)
    _catch_up(client)

    sid = _hold(client, iid, "ACME", anchor="2026-04-10")
    yahoo.answers["ACME"] = [paid("2026-04-05", 0.5)]
    on("2026-04-12")
    assert _catch_up(client)["created"] == []

    lines = {h["symbol"]: h["last_dividend"] for h in client.get(f"/api/snapshots/{sid}/holdings").json()}
    assert lines == {"ACME": "2026-04-05"}


@pytest.mark.parametrize(
    "days_back, expected",
    [(0, "1mo"), (21, "1mo"), (22, "3mo"), (82, "3mo"), (83, "6mo"), (358, "1y"), (359, "2y"),
     (3645, "10y"), (3646, "max")],
)
def test_the_window_is_yahoos_smallest_range_that_reaches_a_week_before_the_situation(days_back, expected):
    """Yahoo answers by range ("1mo", "3mo", ...), and yfinance keeps a
    dividend's currency only through those (`history(start=...)` drops it).
    The week of margin covers a dividend stamped across midnight UTC and
    Yahoo's clock against the reader's; measured with it, nothing was lost."""
    today = datetime.date(2026, 10, 5)

    assert prices._dividend_range(today - datetime.timedelta(days=days_back), today) == expected
    assert prices._dividend_range(datetime.date.min, today) == "max"
