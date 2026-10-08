"""Yahoo is asked about a ticker's dividends once a day, not at every start.

Brief W part 3 measured it on 2026-09-30: every start of the app, with no click,
sent Yahoo the ticker of every distributing holding for its dividend history,
and two catch-ups in a row asked twice. Nothing new is learned by asking twice
in one day, since an ex-date is a day, and the reader wants it once a day.

So the catch-up keeps the day's ANSWER, one row per ticker in `settings`, and
every later catch-up that day works from it: a dividend whose write waited for
its rate, a holding added in the afternoon, the same fund at a second account,
a situation dated in the past. A stamp saying only "asked today" could serve
none of them without asking again.

Only an answer is kept. yfinance does not raise when no answer comes back: it
leaves `.dividends` as None, which `_fetch_dividends` used to turn into the
same `[]` as a fund that pays nothing (measured 2026-09-30 on yfinance 1.4.1,
network refused). A check nobody answered, or one that failed, is not kept,
and the next catch-up asks again.

Yahoo is faked where the app meets it, `prices._fetch_dividends`, and every ask
is counted: the count is what this file is about. The reader's day is moved
with `dated.today`, the app's one spelling of today.
"""

from __future__ import annotations

import threading
import types

import pandas as pd
import pytest

from app import crud, dated, fx, models, pac, prices
from app.database import SessionLocal

ANCHOR = "2026-01-01"
EX = "2026-03-20"
DAY = "2026-04-01"
NEXT_DAY = "2026-04-02"
TICKER = "VWRL.MI"

# The real helper, taken before conftest's `offline` replaces it in every test.
# The one test that runs it fakes yfinance itself instead.
REAL_FETCH_DIVIDENDS = prices._fetch_dividends


class Yahoo:
    """What `prices._fetch_dividends` gets back, per ticker: a list of
    (ex_date, per_share) for an answer, None for an answer that never came, an
    exception for a fetch that failed, each given back as the window it is.
    Every ask is recorded, whatever range it asked for (brief AF's window is
    that file's question, not this one's)."""

    def __init__(self) -> None:
        self.answers: dict[str, object] = {}
        self.asked: list[str] = []

    def fetch(self, symbol: str, period: str = "max"):
        self.asked.append(symbol)
        answer = self.answers[symbol]
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return prices.DividendWindow(answered=False)
        return prices.DividendWindow(
            answered=True, dividends=[{"date": day, "dps": dps} for day, dps in answer]
        )


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


def _hold(client, sid: int, symbol: str, qty: float = 10, currency: str = "EUR") -> None:
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": f"{symbol}, distributing",
            "asset_class": "fund_etf",
            "symbol": symbol,
            "quantity": qty,
            "unit_price": 100,
            "distribution_policy": "dist",
            "currency": currency,
        },
    )
    assert r.status_code == 201, r.text


def _distributing(
    client, symbol: str = TICKER, *, account: str = "Broker A", anchor: str = ANCHOR, qty: float = 10
) -> tuple[int, int]:
    """An account whose situation on `anchor` holds `qty` of one distributing
    fund. No cash anchor, so a dividend is recorded in the unit it was paid in
    and no exchange rate is involved."""
    iid = client.post("/api/institutions", json={"name": account, "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": anchor}).json()["id"]
    _hold(client, sid, symbol, qty)
    return iid, sid


def _catch_up(client) -> dict:
    out = client.post("/api/transactions/catch-up")
    assert out.status_code == 200, out.text
    return out.json()


# --- Once a day ---------------------------------------------------------------


def test_two_catch_ups_on_one_day_ask_yahoo_once(client, yahoo, on):
    """The finding the brief was written for, as W part 3 measured it: two
    catch-ups in a row, two asks. The second one records nothing new either."""
    _distributing(client)
    yahoo.answers[TICKER] = [(EX, 0.5)]
    on(DAY)

    assert len(_catch_up(client)["created"]) == 1
    assert _catch_up(client)["created"] == []
    assert yahoo.asked == [TICKER]


def test_the_next_day_asks_again_and_hears_what_is_new(client, yahoo, on):
    """A day is the reader's calendar date. The first catch-up of the next day
    asks again, and an ex-date Yahoo listed overnight is recorded."""
    _distributing(client)
    yahoo.answers[TICKER] = [(EX, 0.5)]
    on(DAY)
    _catch_up(client)
    _catch_up(client)

    yahoo.answers[TICKER] = [(EX, 0.5), (NEXT_DAY, 0.6)]
    on(NEXT_DAY)
    created = _catch_up(client)["created"]

    assert [(t["date"], t["unit_price"]) for t in created] == [(NEXT_DAY, 0.6)]
    assert yahoo.asked == [TICKER, TICKER]


def test_yesterdays_answer_is_not_used_today_even_when_nobody_answers(client, yahoo, on):
    """An answer serves the day it was given and no other. The next day, a
    check nobody answered records nothing, as it always did, even for a holding
    yesterday's answer could have served."""
    _distributing(client, account="Broker A")
    yahoo.answers[TICKER] = [(EX, 0.5)]
    on(DAY)
    assert len(_catch_up(client)["created"]) == 1

    _distributing(client, account="Broker B")
    yahoo.answers[TICKER] = None
    on(NEXT_DAY)

    assert _catch_up(client) == {"created": [], "skipped": []}
    assert yahoo.asked == [TICKER, TICKER]


# --- A check that did not happen does not count --------------------------------


def test_a_check_nobody_answered_is_asked_again_and_says_nothing(client, yahoo, on):
    """No network, Yahoo down, or a ticker Yahoo does not know: yfinance says
    all three the same way, None, without raising. Not kept, so the next
    catch-up asks again. And said nowhere, as before: decided in review on
    2026-09-30, since the next start retries by itself (under STILL OPEN)."""
    _distributing(client)
    on(DAY)
    yahoo.answers[TICKER] = None

    assert _catch_up(client) == {"created": [], "skipped": []}

    yahoo.answers[TICKER] = [(EX, 0.5)]
    assert len(_catch_up(client)["created"]) == 1
    assert _catch_up(client)["created"] == []
    assert yahoo.asked == [TICKER, TICKER]


def test_a_check_that_failed_is_reported_as_before_and_asked_again(client, yahoo, on):
    """A fetch that raises (a rate limit, an answer that cannot be read) is a
    skip with the same words as before, and is not kept either."""
    _distributing(client)
    on(DAY)
    yahoo.answers[TICKER] = RuntimeError("Too Many Requests")

    out = _catch_up(client)
    assert out["created"] == []
    assert [(s["label"], s["reason"]) for s in out["skipped"]] == [
        (TICKER, f"Dividend history fetch failed for '{TICKER}': Too Many Requests")
    ]

    yahoo.answers[TICKER] = [(EX, 0.5)]
    assert len(_catch_up(client)["created"]) == 1
    assert _catch_up(client)["created"] == []
    assert yahoo.asked == [TICKER, TICKER]


# --- What the day's answer serves ------------------------------------------------


def test_a_ticker_added_after_the_check_is_asked_at_once_and_alone(client, yahoo, on):
    """The reader adds a distributing holding in the afternoon. Its ticker has
    not been asked about today, so it is asked at once, its first request of
    the day, and its dividends are recorded at once. The ticker that already
    answered is not asked again."""
    _, sid = _distributing(client)
    yahoo.answers.update({TICKER: [(EX, 0.5)], "ENEL.MI": [(EX, 0.3)]})
    on(DAY)
    _catch_up(client)

    _hold(client, sid, "ENEL.MI")
    created = _catch_up(client)["created"]

    assert [(t["symbol"], t["date"], t["amount"]) for t in created] == [("ENEL.MI", EX, 3.0)]
    assert yahoo.asked == [TICKER, "ENEL.MI"]


def test_one_fund_at_two_accounts_is_asked_about_once(client, yahoo, on):
    """Within one catch-up a ticker is asked at most once, however many
    accounts hold it. Each account is credited for its own units."""
    broker_a, _ = _distributing(client, account="Broker A", qty=10)
    broker_b, _ = _distributing(client, account="Broker B", qty=4)
    yahoo.answers[TICKER] = [(EX, 0.5)]
    on(DAY)

    created = _catch_up(client)["created"]

    assert sorted((t["institution_id"], t["amount"]) for t in created) == sorted(
        [(broker_a, 5.0), (broker_b, 2.0)]
    )
    assert yahoo.asked == [TICKER]


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("Too Many Requests")], ids=["nobody answered", "fetch failed"]
)
def test_a_fund_at_two_accounts_with_no_answer_is_asked_once_per_catch_up(
    client, yahoo, on, failure
):
    """Within one catch-up the outcome is reused whatever it is, so an outage
    costs one request per ticker, not one per account. Nothing is kept, so a
    kept answer cannot be what spares the second request. Each account reports
    what it reported before: a skip line each for a fetch that failed, nothing
    for a check nobody answered."""
    _distributing(client, account="Broker A")
    _distributing(client, account="Broker B")
    yahoo.answers[TICKER] = failure
    on(DAY)

    out = _catch_up(client)

    assert out["created"] == []
    said = [] if failure is None else [
        (TICKER, f"Dividend history fetch failed for '{TICKER}': Too Many Requests")
    ] * 2
    assert [(s["label"], s["reason"]) for s in out["skipped"]] == said
    assert yahoo.asked == [TICKER]


def test_the_same_fund_entered_elsewhere_later_that_day_is_served_by_its_answer(
    client, yahoo, on
):
    """The same fund at a second account, entered after the day's check, in a
    situation dated before the first one's. It is recorded at once and with no
    request, INCLUDING the dividend the first account's cut left out: the day's
    answer is Yahoo's whole history, never one holding's slice of it, because
    a situation dated in the past needs older dividends. What it writes is what
    a fresh answer writes, down to the note."""
    broker_a, _ = _distributing(client, account="Broker A", anchor="2026-03-01", qty=10)
    yahoo.answers[TICKER] = [("2026-02-10", 0.4), (EX, 0.5)]
    on(DAY)
    (first,) = _catch_up(client)["created"]
    assert (first["institution_id"], first["date"]) == (broker_a, EX)

    broker_b, _ = _distributing(client, account="Broker B", anchor=ANCHOR, qty=4)
    created = _catch_up(client)["created"]

    assert sorted((t["institution_id"], t["date"], t["amount"]) for t in created) == [
        (broker_b, "2026-02-10", 1.6),
        (broker_b, EX, 2.0),
    ]
    (again,) = [t for t in created if t["date"] == EX]
    assert again["note"] == first["note"] == (
        "Auto-recorded from market data: a dividend of 0.5 EUR per share"
    )
    assert yahoo.asked == [TICKER]


def test_a_dividend_waiting_for_its_rate_is_written_without_asking_again(
    client, yahoo, on, monkeypatch
):
    """A dollar dividend into a euro account, on a day the rate feed is down:
    skipped, and written by the next catch-up once the rate is there, exactly
    as `test_a_dividend_without_its_ex_dates_rate_waits` pins. This pins that
    the next catch-up writes it from the day's answer rather than by asking
    Yahoo again, which a stamp alone could not do."""
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": ANCHOR, "amount": 1000.0, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": ANCHOR}).json()["id"]
    _hold(client, sid, "VYM", qty=100, currency="USD")
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {"VYM": {"price": 120.0, "as_of": ANCHOR, "currency": "USD"}})
    yahoo.answers["VYM"] = [(EX, 1.0)]
    on(DAY)

    def feed_down(base, start, end=None):
        raise fx.FxError("feed down")

    monkeypatch.setattr(fx, "_fetch_rates", feed_down)
    out = _catch_up(client)
    assert out["created"] == []
    assert [(s["label"], s["occurrence"]) for s in out["skipped"]] == [("VYM", EX)]

    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {EX: {"USD": 1.25}})
    (tx,) = _catch_up(client)["created"]

    assert (tx["institution_id"], tx["amount"], tx["fx_as_of"]) == (iid, 80.0, EX)
    assert yahoo.asked == ["VYM"]


def test_an_ex_date_on_the_anchor_date_is_left_to_the_anchor(client, yahoo, on):
    """The cut `get_dividends_since` made, strictly after the anchor, is now
    made on the day's answer: a situation taken on an ex-date already accounts
    for that day. Passes before the change too, on purpose: it guards the cut
    while it moves."""
    _distributing(client, anchor=EX)
    yahoo.answers[TICKER] = [(EX, 0.5), ("2026-03-27", 0.6)]
    on(DAY)

    created = _catch_up(client)["created"]

    assert [t["date"] for t in created] == ["2026-03-27"]


@pytest.mark.parametrize(
    "stored",
    ["{", '{"on": "' + DAY + '"}', '["' + TICKER + '"]', '{"on": "' + DAY + '", "dividends": 7}'],
    ids=["truncated", "no dividends", "not an object", "dividends not a list"],
)
def test_a_stored_answer_that_cannot_be_read_is_asked_again_and_replaced(
    client, yahoo, on, stored
):
    """A value the catch-up cannot read, hand-edited or cut short, counts as
    not asked rather than breaking a route the app calls at every start, and
    the answer that replaces it is read back by the next catch-up."""
    _distributing(client)
    with SessionLocal() as db:
        db.add(models.Setting(key=pac._DIVIDENDS_ASKED.format(symbol=TICKER), value=stored))
        db.commit()
    yahoo.answers[TICKER] = [(EX, 0.5)]
    on(DAY)

    assert len(_catch_up(client)["created"]) == 1
    assert _catch_up(client)["created"] == []
    assert yahoo.asked == [TICKER]


def test_two_catch_ups_at_once_both_answer_and_the_answer_is_kept(client, monkeypatch, on):
    """Two tabs opened together start two catch-ups at once, and so does React's
    StrictMode on the development server, which runs the start-up effect twice.
    Both find no answer for the day, both ask, both store it. Each store is one
    statement that says "this row, whatever was there", so the second waits for
    the first and rewrites the same value instead of dying on the key: the
    lesson of the rates stored twice (dd8370b). Yahoo holds both callers until
    both are inside, the moment a read-then-insert would collide.

    Whether two catch-ups at once can record one dividend twice is not this
    file's question, and it is not asserted here."""
    _distributing(client)
    on(DAY)
    everyone_in = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    asked: list[str] = []

    def fetch(symbol: str, period: str = "max"):
        with lock:
            asked.append(symbol)
            held = len(asked) <= 2
        if held:
            everyone_in.wait()
        return prices.DividendWindow(answered=True, dividends=[{"date": EX, "dps": 0.5}])

    monkeypatch.setattr(prices, "_fetch_dividends", fetch)
    statuses: list[int] = []

    def run() -> None:
        response = client.post("/api/transactions/catch-up")
        with lock:
            statuses.append(response.status_code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a catch-up never came back"
    assert len(asked) == 2, "the catch-ups did not overlap, so nothing was tested"
    assert statuses == [200, 200]
    _catch_up(client)
    assert len(asked) == 2, "the answer both of them stored was not read back"


# --- The distinction, where yfinance makes it -----------------------------------


@pytest.mark.parametrize("case", ["no answer", "no dividend", "paid"])
def test_no_answer_is_told_apart_from_a_fund_that_pays_nothing(monkeypatch, case):
    """What the rule rests on, one level down. Measured 2026-09-30 on yfinance
    1.4.1 with the network refused: no answer leaves `.dividends` as None, and
    an answer listing no dividend is an empty Series. `_fetch_dividends` used
    to return `[]` for both, so an outage read as a fund that pays nothing;
    then None for the first, and since brief AK it says which in `answered`.
    Run against a faked yfinance, the way test_issuers.py runs the real
    adapters against a faked httpx. Asked by range since brief AF
    (`get_dividends(period)`, which `.dividends` is with "max")."""
    import yfinance

    index = pd.DatetimeIndex([EX, "2026-06-20"]).tz_localize("Europe/Rome")
    dividends = {
        "no answer": None,
        "no dividend": pd.Series([], dtype=float),
        # the zero is dropped, as it always was
        "paid": pd.Series([0.5, 0.0], index=index),
    }[case]
    monkeypatch.setattr(
        yfinance, "Ticker", lambda symbol: types.SimpleNamespace(get_dividends=lambda period="max": dividends)
    )
    expected = {
        "no answer": prices.DividendWindow(answered=False),
        "no dividend": prices.DividendWindow(answered=True),
        "paid": prices.DividendWindow(answered=True, dividends=[{"date": EX, "dps": 0.5}]),
    }[case]

    assert REAL_FETCH_DIVIDENDS(TICKER) == expected
