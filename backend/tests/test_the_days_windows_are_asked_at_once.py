"""The day's first catch-up asks Yahoo for its dividend windows at once.

The catch-up the page posts at every load asked Yahoo for each followed
ticker's dividend window one after another, inside the loop that writes, and
Yahoo takes about a second for each whatever its size: brief AF measured 44.7 s
for 22 tickers, and the banner waited for all of them. Now the windows are
asked before the loop (`pac._ask_at_once`): on the catch-up's own thread until
one comes back answered, then at most eight at a time (`pac._WINDOWS_AT_ONCE`,
the reader's D1), and the loop writes what each comes to as before, in the
same order and the same rows (shown on 2026-10-23 by dumps of the code before
and after, on the same faked answers).

Why one must answer first, on the catch-up's own thread: yfinance keeps every
ticker's time zone in an SQLite file, each thread on a connection of its own,
and while that file is being created a new connection can be refused,
"database is locked" (measured with Yahoo faked under yfinance: windows lost
in 13 of 30 trials on a fresh file, 0 of 30 on one that exists). yfinance reads
the time zone before it asks anything, so an answered window means the file
exists; a blank symbol, or one shaped like an ISIN Yahoo does not know, fails
before that read and proves nothing.

Yahoo is faked under the real yfinance where the question is the time
(`tests/yahoo_chart.py`), and at `prices._fetch_dividends` where it is the
app's. Every symbol and name is invented.
"""

from __future__ import annotations

import datetime
import threading
import time

from sqlalchemy import event, select

from app import dated, database, models, pac, prices
from app.database import SessionLocal
from tests.yahoo_chart import Listing, install

TODAY = "2026-10-23"
SITUATION = "2026-10-01"
EX = "2026-10-12"

# The real helper, taken before conftest's `offline` replaces it in every test.
REAL_FETCH_DIVIDENDS = prices._fetch_dividends


def _account(client, symbols: list[str], name: str = "Broker Zeta") -> int:
    """An account whose situation of SITUATION holds 10 units of each symbol,
    no policy stated, so each follows its own dividend history. No cash anchor:
    a dividend is recorded in the unit it was paid in."""
    iid = client.post("/api/institutions", json={"name": name, "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": SITUATION}).json()["id"]
    for k, symbol in enumerate(symbols):
        r = client.post(f"/api/snapshots/{sid}/holdings", json={
            "asset_name": f"Invented share {k + 1}", "asset_class": "equity", "symbol": symbol,
            "quantity": 10, "unit_price": 100, "currency": "EUR"})
        assert r.status_code == 201, r.text
    return iid


def _catch_up(client) -> dict:
    out = client.post("/api/transactions/catch-up")
    assert out.status_code == 200, out.text
    return out.json()


class Yahoo:
    """`prices._fetch_dividends`, faked: per symbol a list of (ex-date, per
    share) for an answer, None for an answer that never came, an exception for
    a fetch that fails. Each ask is kept with its thread and its times, and the
    most asks ever in flight at once."""

    def __init__(self, monkeypatch, answers: dict, delay: float = 0.05) -> None:
        self.answers = answers
        self.delay = delay
        self.asks: list[dict] = []
        self.lock = threading.Lock()
        self.in_flight = 0
        self.most_in_flight = 0
        self.hold = None  # a Barrier the first asks of the pool's threads wait at
        self.held = 0
        monkeypatch.setattr(prices, "_fetch_dividends", self.fetch)

    def fetch(self, symbol: str, period: str = "max"):
        thread = threading.current_thread().name
        with self.lock:
            self.in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self.in_flight)
            wait = self.hold is not None and thread.startswith(pac._WINDOW_THREADS) and self.held < self.hold.parties
            if wait:
                self.held += 1
            started = time.perf_counter()
        try:
            if wait:
                self.hold.wait()
            time.sleep(self.delay)
            answer = self.answers[symbol]
            if isinstance(answer, Exception):
                raise answer
            if answer is None:
                return prices.DividendWindow(answered=False)
            return prices.DividendWindow(
                answered=True, dividends=[{"date": day, "dps": dps} for day, dps in answer]
            )
        finally:
            with self.lock:
                self.in_flight -= 1
                self.asks.append({"symbol": symbol, "thread": thread, "started": started,
                                  "ended": time.perf_counter()})

    def ordered(self) -> list[dict]:
        return sorted(self.asks, key=lambda a: a["started"])


def _caught_up_on(monkeypatch) -> dict:
    """The name of the thread the dividend catch-up runs on, once it has."""
    seen: dict = {}
    real = pac.execute_dividends

    def execute_dividends(db, as_of=None):
        seen["thread"] = threading.current_thread().name
        return real(db, as_of)

    monkeypatch.setattr(pac, "execute_dividends", execute_dividends)
    return seen


def _kept(prefix: str) -> dict[str, str]:
    with SessionLocal() as db:
        rows = db.scalars(select(models.Setting).where(models.Setting.key.startswith(prefix)))
        return {row.key.removeprefix(prefix): row.value for row in rows}


def _dividends() -> list[tuple[str, str, float]]:
    with SessionLocal() as db:
        rows = db.scalars(select(models.Transaction).where(models.Transaction.kind == "dividend"))
        return sorted((t.symbol, t.ex_date, t.amount) for t in rows)


# --- The time -------------------------------------------------------------------


def test_sixteen_windows_at_a_second_each_take_seconds_not_sixteen(client, monkeypatch, tmp_path):
    """The brief's figure, with the real yfinance under a fake that answers
    every window after a second: sixteen windows took sixteen seconds one after
    another; now one alone, then two rounds of eight. Every window answered and
    every dividend written, so the time is not a failure's."""
    fake = install(monkeypatch, tmp_path, delay=1.0)
    monkeypatch.setattr(prices, "_fetch_dividends", REAL_FETCH_DIVIDENDS)
    symbols = [f"ZZW{k:02d}.XF" for k in range(1, 17)]
    days = [d.isoformat() for d in (datetime.date(2026, 9, 1) + datetime.timedelta(days=n) for n in range(53))
            if d.weekday() < 5]
    for symbol in symbols:
        fake.listings[symbol] = Listing(closes={d: 100.0 for d in days}, dividends={EX: 0.25})
    _account(client, symbols)
    monkeypatch.setattr(dated, "today", lambda: TODAY)

    started = time.perf_counter()
    created = _catch_up(client)["created"]
    took = time.perf_counter() - started

    assert sorted(t["symbol"] for t in created) == symbols
    assert len([p for _, p in fake.asked if "events" in p]) == 16
    assert took < 8, f"16 windows at a second each took {took:.1f} s"


# --- Who asks, and how many at once ------------------------------------------


def test_windows_are_asked_on_the_catch_ups_thread_until_one_answers_then_eight_at_once(client, monkeypatch):
    """A blank symbol (refused before yfinance runs), one whose fetch fails and
    one Yahoo says nothing of come first: none proves yfinance has opened its
    time-zone file, so each is asked on the catch-up's own thread, and the
    next too, until one answers. Then the other eleven, on the pool's threads,
    eight at once and never more; each window asked once in the catch-up.
    Each of the three failures is said as before, and takes no other ticker
    with it."""
    answering = [f"ZZA{k:02d}.XF" for k in range(1, 13)]
    first = ["   ", "ZZDROP.XF", "ZZNONE.XF"]
    yahoo = Yahoo(monkeypatch, {"ZZDROP.XF": RuntimeError("connection dropped"), "ZZNONE.XF": None,
                                **{s: [(EX, 0.25)] for s in answering}})
    yahoo.hold = threading.Barrier(pac._WINDOWS_AT_ONCE, timeout=10)
    _account(client, [*first, *answering])
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    caught_up = _caught_up_on(monkeypatch)

    out = _catch_up(client)

    asks = yahoo.ordered()
    on_its_thread = [a for a in asks if a["thread"] == caught_up["thread"]]
    pooled = [a for a in asks if a["thread"].startswith(pac._WINDOW_THREADS)]
    assert [a["symbol"] for a in on_its_thread] == ["ZZDROP.XF", "ZZNONE.XF", "ZZA01.XF"]
    assert sorted(a["symbol"] for a in pooled) == answering[1:]
    assert len(on_its_thread) + len(pooled) == len(asks) == 14
    assert all(p["started"] >= on_its_thread[-1]["ended"] for p in pooled)
    assert yahoo.most_in_flight == pac._WINDOWS_AT_ONCE
    assert [(s["label"], s["reason"]) for s in out["skipped"]] == [
        ("   ", "Empty symbol"),
        ("ZZDROP.XF", "Dividend history fetch failed for 'ZZDROP.XF': connection dropped"),
    ]
    assert _dividends() == [(s, EX, 2.5) for s in answering]


def test_when_no_window_answers_each_is_asked_on_the_catch_ups_thread_as_before(client, monkeypatch):
    """An outage: nothing answers and the market's canary is silent too. Every
    window is asked on the catch-up's own thread, one after another, as before
    brief BG; nothing is kept, nothing is said, and the next catch-up asks them
    all again. Passes before the change too: a guard."""
    symbols = [f"ZZOFF{k}.XF" for k in range(1, 5)]
    yahoo = Yahoo(monkeypatch, {s: None for s in symbols})
    monkeypatch.setattr(prices, "market_reachable", lambda: False)
    _account(client, symbols)
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    caught_up = _caught_up_on(monkeypatch)

    out = _catch_up(client)

    asks = yahoo.ordered()
    assert [(a["symbol"], a["thread"]) for a in asks] == [(s, caught_up["thread"]) for s in symbols]
    assert all(later["started"] >= earlier["ended"] for earlier, later in zip(asks, asks[1:]))
    assert (out["created"], out["skipped"]) == ([], [])
    assert _kept("dividends_") == {}

    _catch_up(client)
    assert [a["symbol"] for a in yahoo.ordered()] == symbols * 2


def test_no_thread_of_the_pool_touches_the_database(client, monkeypatch):
    """What a thread of the pool runs is Yahoo's window and nothing else: every
    statement of the catch-up is executed on its own thread, the reads that
    decide the windows and the writes of what they come to alike. Read at the
    engine, statement by statement, so a thread that borrowed the catch-up's
    own session would be caught too."""
    symbols = [f"ZZDB{k}.XF" for k in range(1, 7)]
    yahoo = Yahoo(monkeypatch, {s: [(EX, 0.25)] for s in symbols})
    _account(client, symbols)
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    caught_up = _caught_up_on(monkeypatch)
    statements: list[str] = []

    def executed(conn, cursor, statement, parameters, context, executemany):
        statements.append(threading.current_thread().name)

    event.listen(database.engine, "before_cursor_execute", executed)
    try:
        _catch_up(client)
    finally:
        event.remove(database.engine, "before_cursor_execute", executed)

    assert any(a["thread"].startswith(pac._WINDOW_THREADS) for a in yahoo.asks), "no window on the pool"
    assert caught_up["thread"] in statements
    assert not [t for t in statements if t.startswith(pac._WINDOW_THREADS)]


# --- Each outcome as before ---------------------------------------------------


def test_on_the_pool_an_unknown_ticker_is_kept_for_the_day_and_one_that_raises_is_asked_again(client, monkeypatch):
    """The outcomes brief X and brief BE gave a window, now met on the pool's
    threads: while the market answers, a ticker Yahoo says nothing of is kept
    as such for the day (`dividends_unanswered:`) and not asked again; a fetch
    that fails is a skip line, kept nowhere, and asked again by the next
    catch-up; the others are recorded and their answers kept. Passes before the
    change too: a guard."""
    symbols = ["ZZB01.XF", "ZZB02.XF", "ZZNONE.XF", "ZZDROP.XF", "ZZB03.XF"]
    yahoo = Yahoo(monkeypatch, {"ZZNONE.XF": None, "ZZDROP.XF": RuntimeError("Too Many Requests"),
                                **{s: [(EX, 0.4)] for s in ("ZZB01.XF", "ZZB02.XF", "ZZB03.XF")}})
    monkeypatch.setattr(prices, "market_reachable", lambda: True)
    _account(client, symbols)
    monkeypatch.setattr(dated, "today", lambda: TODAY)

    out = _catch_up(client)

    assert [(s["label"], s["reason"]) for s in out["skipped"]] == [
        ("ZZDROP.XF", "Dividend history fetch failed for 'ZZDROP.XF': Too Many Requests"),
    ]
    assert _dividends() == [("ZZB01.XF", EX, 4.0), ("ZZB02.XF", EX, 4.0), ("ZZB03.XF", EX, 4.0)]
    assert _kept("dividends_unanswered:") == {"ZZNONE.XF": TODAY}
    assert sorted(_kept("dividends_asked:")) == ["ZZB01.XF", "ZZB02.XF", "ZZB03.XF"]

    yahoo.answers["ZZDROP.XF"] = [(EX, 0.4)]
    created = _catch_up(client)["created"]

    assert [(t["symbol"], t["amount"]) for t in created] == [("ZZDROP.XF", 4.0)]
    assert [a["symbol"] for a in yahoo.ordered()][len(symbols):] == ["ZZDROP.XF"]


def test_two_catch_ups_at_once_on_several_tickers_write_each_dividend_once(client, monkeypatch):
    """Brief Y's race with the pool in use: two catch-ups at once, both inside
    their windows together (each one's first, on its own thread, waits for the
    other), both asking and both writing. Each dividend is written once and
    each answer kept, as `_record_dividend`'s lock and the kept answer's upsert
    make it. Passes before the change too: a guard."""
    symbols = [f"ZZR{k}.XF" for k in range(1, 7)]
    yahoo = Yahoo(monkeypatch, {s: [(EX, 0.5)] for s in symbols})
    _account(client, symbols)
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    both_in = threading.Barrier(2, timeout=10)
    real = yahoo.fetch
    firsts: list[str] = []

    def fetch(symbol, period="max"):
        if symbol == symbols[0]:
            with yahoo.lock:
                firsts.append(threading.current_thread().name)
            both_in.wait()
        return real(symbol, period)

    monkeypatch.setattr(prices, "_fetch_dividends", fetch)
    statuses: list[int] = []

    def run() -> None:
        response = client.post("/api/transactions/catch-up")
        with yahoo.lock:
            statuses.append(response.status_code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a catch-up never came back"
    assert len(firsts) == 2, "the catch-ups did not overlap, so nothing was tested"
    assert statuses == [200, 200]
    assert _dividends() == [(s, EX, 5.0) for s in symbols]
    assert sorted(_kept("dividends_asked:")) == symbols


# --- The loop's own ask -----------------------------------------------------------


def test_a_window_asked_from_another_day_is_asked_again_by_the_loop(client, monkeypatch):
    """The loop takes a window from the ones asked at once only when it was
    asked from the day the loop would ask from now. Here it was not (another
    catch-up kept an answer in between, say): the loop asks Yahoo itself, from
    its own day, and keeps that answer, never the other window's."""
    yahoo = Yahoo(monkeypatch, {"ZZK.XF": [(EX, 0.3)]})
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    stale = prices.DividendWindow(answered=True, dividends=[{"date": "2026-09-15", "dps": 9.99}])
    asked = {"ZZK.XF": (datetime.date(2026, 9, 1), stale)}

    with SessionLocal() as db:
        window = pac._dividend_history(db, "ZZK.XF", TODAY, SITUATION, "2025-09-30", {}, asked)

    assert window.dividends == ({"date": EX, "dps": 0.3},)
    assert [a["symbol"] for a in yahoo.asks] == ["ZZK.XF"]
    kept = _kept("dividends_asked:")["ZZK.XF"]
    assert "9.99" not in kept and '"dps":0.3' in kept
