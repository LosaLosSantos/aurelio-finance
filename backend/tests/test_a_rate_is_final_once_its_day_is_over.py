"""A day's rate is final once the feed has been asked after that day ended.

A reading of today converts at whatever rate is in force and says which day it
is; tomorrow it reads again. A debit fixed on a day does not read again, so the
rate written into it has to be the one the day ended with. The store answered
that question from `fetched_at`, which meant two things: when a day's rows were
written, and when the feed was last asked for days newer than the newest one
stored. A fetch backwards rewrote the first meaning and so faked the second,
and a store of a single day — every database migrated from 9a02bd4 — had its
newest day restamped by the first reading of the past. Measured on 2026-09-16
in the app, against the real feed: a PAC close of 2026-09-15 was debited at the
rate of 2026-09-11, 643.27 EUR where the day's own rate makes 646.23.

The feed below publishes 1.05, 1.10 and 1.20 dollars to the euro on three days,
and each test says how far it has published, so a rate of the wrong day cannot
pass for the right one: 120 dollars is 100.00 euro only at 1.20.
"""

from __future__ import annotations

import datetime

from app import dated, fx, models, pac, prices
from app.database import SessionLocal

UTC = datetime.timezone.utc
NOW = datetime.datetime.now(UTC)
TODAY = datetime.date.today()
EARLY = (TODAY - datetime.timedelta(days=90)).isoformat()
OLD = (TODAY - datetime.timedelta(days=5)).isoformat()
YESTERDAY = (TODAY - datetime.timedelta(days=1)).isoformat()


class Feed:
    """The ECB as frankfurter serves it: every day published so far, starting
    at the one in force on the day asked."""

    def __init__(self, monkeypatch, published: dict[str, float]):
        self.published = published
        self.until = max(published)
        self.asked: list[tuple] = []
        monkeypatch.setattr(fx, "_fetch_rates", self.fetch)

    def fetch(self, base, start, end=None):
        self.asked.append((start, end))
        days = sorted(d for d in self.published if d <= self.until)
        first = max((d for d in days if d <= start), default=None)
        return {
            d: {"USD": self.published[d]}
            for d in days
            if (d >= start or d == first) and (end is None or d <= end)
        }


def _asked_at(monkeypatch, moment: datetime.datetime, day: str) -> None:
    """Read `day` with the clock that stamps the store set to `moment` — the
    store then holds what the feed had published by then, stamped then."""
    stamp = moment.isoformat(timespec="seconds")
    with monkeypatch.context() as clock, SessionLocal() as db:
        clock.setattr(models, "_utcnow_iso", lambda: stamp)
        fx.rates_on(db, "EUR", day)


def test_a_store_of_one_day_asks_for_the_days_after_it_before_fixing_a_debit(client, monkeypatch):
    """Every database migrated from 9a02bd4 is this store: one day, written
    when the app last asked. The first reading of the past — the history's
    oldest point — fetches backwards up to that day and rewrites it, and the
    rewritten stamp said the feed had just been asked for newer days. It had
    not, and yesterday's debit took a rate five days old."""
    feed = Feed(monkeypatch, {EARLY: 1.05, OLD: 1.10, YESTERDAY: 1.20})
    feed.until = OLD
    _asked_at(monkeypatch, NOW - datetime.timedelta(days=3), OLD)
    feed.until = YESTERDAY

    with SessionLocal() as db:
        assert [r.as_of for r in db.query(models.FxRate)] == [OLD]  # one day
        fx.rates_on(db, "EUR", EARLY)  # a reading of the past
        assert fx.convert_on(db, 120.0, "USD", "EUR", YESTERDAY) == (100.0, YESTERDAY)


def test_a_day_is_known_only_to_a_feed_asked_after_it_ended(client, monkeypatch):
    """A reading of a past day — a point of the history — used to trust a
    store asked in the last 24 hours. Twenty-four hours says nothing about a
    day whose rate came out after the question: the store cannot know the hour
    the ECB published, only whether it asked once the day was over. Here it
    asked a second before midnight UTC, fresh by the clock for almost a day,
    and the day's own rate is out."""
    over = datetime.datetime.combine(NOW.date(), datetime.time(0), tzinfo=UTC)
    day = (NOW.date() - datetime.timedelta(days=1)).isoformat()  # ended at `over`
    feed = Feed(monkeypatch, {OLD: 1.10, day: 1.20})
    feed.until = OLD
    _asked_at(monkeypatch, over - datetime.timedelta(seconds=1), OLD)
    feed.until = day

    with SessionLocal() as db:
        assert fx.rates_on(db, "EUR", day)["USD"] == {"rate": 1.20, "as_of": day}
        assert fx.convert_on(db, 120.0, "USD", "EUR", day) == (100.0, day)


def test_a_debit_of_today_waits_for_todays_rate_and_a_reading_does_not(client, monkeypatch):
    """Before the ECB publishes, yesterday's rate is the one in force: right
    for a reading of today, which says which day it used and reads again. Wrong
    for a sum fixed today, which would keep yesterday's rate for good. Once the
    day's rate is out, the debit takes it — without waiting a day for the
    store to call itself stale."""
    feed = Feed(monkeypatch, {OLD: 1.10, YESTERDAY: 1.10, TODAY.isoformat(): 1.20})
    feed.until = YESTERDAY

    with SessionLocal() as db:
        today = fx.rates_on(db, "EUR", TODAY.isoformat())
        assert today["USD"] == {"rate": 1.10, "as_of": YESTERDAY}
        assert fx.convert_on(db, 120.0, "USD", "EUR", TODAY.isoformat()) == (None, None)

        feed.until = TODAY.isoformat()
        assert fx.convert_on(db, 120.0, "USD", "EUR", TODAY.isoformat()) == (100.0, TODAY.isoformat())


def test_a_day_inside_the_stored_history_is_final_without_asking(client, monkeypatch):
    """A Saturday between a stored Friday and a stored Monday had no rate of
    its own and never will: the history is contiguous, so the Friday is what
    it ended with. Nothing about when the feed was asked changes that — a
    migrated store has no record of it at all — and the feed is not needed."""
    friday = "2026-06-12"
    saturday, monday = "2026-06-13", "2026-06-15"

    def offline(base, start, end=None):
        raise fx.FxError("feed down")

    monkeypatch.setattr(fx, "_fetch_rates", offline)
    with SessionLocal() as db:
        for day, rate in ((friday, 1.20), (monday, 1.25)):
            db.add(
                models.FxRate(
                    base="EUR", currency="USD", rate=rate, as_of=day,
                    fetched_at=f"{day}T15:00:00+00:00",
                )
            )
        db.commit()
        assert fx.convert_on(db, 120.0, "USD", "EUR", saturday) == (100.0, friday)


def test_a_purchase_of_today_states_its_debit_until_the_day_has_a_rate(client, monkeypatch):
    feed = Feed(monkeypatch, {OLD: 1.10, TODAY.isoformat(): 1.20})
    feed.until = OLD
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    body = {
        "kind": "buy", "date": TODAY.isoformat(), "institution_id": iid,
        "asset_name": "Apple", "symbol": "AAPL", "quantity": 1, "unit_price": 120.0,
        "currency": "EUR", "price_currency": "USD",
    }

    refused = client.post("/api/transactions", json=body)
    assert refused.status_code == 422, refused.text
    assert "State the amount from your statement" in refused.json()["detail"]

    typed = client.post("/api/transactions", json={**body, "amount": 103.5})
    assert typed.status_code == 201, typed.text
    assert (typed.json()["amount"], typed.json()["fx_as_of"]) == (103.5, None)


def test_an_occurrence_waits_until_its_day_is_over(client, monkeypatch):
    """Two reasons the market's figure for a day that is not over is not its
    close. Measured on 2026-09-16 at 10:55 in Milan, with the session open:
    Yahoo's daily history for VWCE.MI ends in a row dated that day at 165.70,
    the last minute's trade; the same history for VTI, before New York opened,
    ends at the 15th — a Wednesday occurrence would have been bought at
    Tuesday's close and dated Tuesday. Either way the day's own rate may not be
    published yet. So the occurrence is not priced until the day has ended."""
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "PAC Europe", "amount": 250, "currency": "EUR", "frequency": "annual",
            "start_date": TODAY.isoformat(), "source_institution_id": iid,
            "targets": [{"symbol": "VWCE.MI", "institution_id": iid}],
        },
    )
    assert r.status_code == 201, r.text
    priced: list[datetime.date] = []

    def close_on(symbol, on):
        priced.append(on)
        return {"symbol": symbol, "price": 100.0, "as_of": on.isoformat()}

    monkeypatch.setattr(prices, "get_price_on", close_on)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")

    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=TODAY)
        assert out["created"] == [] and priced == []
        assert [s["occurrence"] for s in out["skipped"]] == [TODAY]
        assert db.query(models.Transaction).count() == 0

    tomorrow = TODAY + datetime.timedelta(days=1)
    monkeypatch.setattr(dated, "today", lambda: tomorrow.isoformat())
    with SessionLocal() as db:
        (buy,) = pac.execute_due(db, as_of=tomorrow)["created"]
        assert (buy.date, buy.quantity, buy.amount) == (TODAY.isoformat(), 2, 200.0)
