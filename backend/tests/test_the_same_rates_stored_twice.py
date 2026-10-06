"""Two readers that store the same rates of the same day both succeed.

The first page load of a day fires several requests at once. Each finds no
rate for the day, each asks the feed, and each stores what came back — the same
rows. `fx._store` used to read what existed and then add what did not, and
every request had read "nothing" before the first one wrote: the second commit
died on the primary key. Found on 2026-09-17 as a 500 on /api/dashboard/summary
while the chat's "before" was being run on a copy of the reader's database, and
reproduced without the network: an empty store, a feed that takes 0.3 s, six
sessions asking at once — one stored, five IntegrityError.

Storing a day's rates is idempotent now, so the parallel requests here are
made to overlap on purpose: the fake feed holds every caller until all of them
are inside it, which is exactly the moment that used to be the race.
"""

from __future__ import annotations

import threading

from sqlalchemy import select

from app import crud, fx, models
from app.database import SessionLocal, unit_of_work

DAY = "2026-09-11"
RATES = {DAY: {"USD": 1.1592, "GBP": 0.85815}}
TODAY = fx._today()
READERS = 6


def _feed_that_holds(monkeypatch, callers: int, payload=RATES) -> list[str]:
    """A feed every one of `callers` must be inside before any of them gets an
    answer — so each of them has already decided the store is empty. Calls
    after those are answered at once. Returns the list of starts it was asked
    for, to show the overlap really happened."""
    everyone_in = threading.Barrier(callers, timeout=10)
    lock = threading.Lock()
    asked: list[str] = []

    def fetch(base, start, end=None):
        with lock:
            asked.append(start)
            held = len(asked) <= callers
        if held:
            everyone_in.wait()
        return {day: dict(rates) for day, rates in payload.items()}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def _in_parallel(work, n: int) -> list[BaseException]:
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run():
        try:
            work()
        except BaseException as exc:  # noqa: BLE001 — every failure is the finding
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a reader never came back"
    return errors


def _stored(base: str = "EUR") -> dict[tuple[str, str], float]:
    with SessionLocal() as db:
        return {
            (r.as_of, r.currency): r.rate
            for r in db.scalars(select(models.FxRate).where(models.FxRate.base == base))
        }


def test_six_sessions_storing_the_same_day_all_succeed(client, monkeypatch):
    """The reproduction, as it was measured: an empty store and six sessions
    asking for today's rates together. Every one of them gets the rates, and
    the table holds each row once."""
    asked = _feed_that_holds(monkeypatch, READERS)
    answers: list[dict] = []
    lock = threading.Lock()

    def read():
        with SessionLocal() as db:
            got = fx.rates_on(db, "EUR", TODAY)
        with lock:
            answers.append(got)

    errors = _in_parallel(read, READERS)

    assert errors == [], [f"{type(e).__name__}: {e}" for e in errors]
    assert len(asked) == READERS, "the readers did not overlap, so nothing was tested"
    assert len(answers) == READERS
    assert all(a["USD"] == {"rate": 1.1592, "as_of": DAY} for a in answers)
    assert _stored() == {(DAY, "USD"): 1.1592, (DAY, "GBP"): 0.85815}
    with SessionLocal() as db:
        assert fx._asked_for_newer(db, "EUR") is not None


def test_the_dashboard_loaded_by_parallel_requests_answers_every_one(client, monkeypatch):
    """The same collision where the reader met it: requests that each convert
    a dollar figure, fired together at a store that is behind. Every one of
    them answers 200 with the converted total."""
    iid = client.post("/api/institutions", json={"name": "Schwab"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": DAY}).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "A fund", "asset_class": "fund_etf", "value": 1159.20,
              "currency": "USD"},
    )
    assert r.status_code == 201, r.text
    assert _stored() == {}, "setup stored rates, so the store is not behind"

    asked = _feed_that_holds(monkeypatch, READERS)
    statuses: list[int] = []
    totals: list[float] = []
    lock = threading.Lock()

    def load():
        response = client.get("/api/dashboard/summary")
        with lock:
            statuses.append(response.status_code)
            if response.status_code == 200:
                totals.append(response.json()["net_worth"])

    errors = _in_parallel(load, READERS)

    assert errors == [], [f"{type(e).__name__}: {e}" for e in errors]
    assert len(asked) >= READERS, "the requests did not overlap, so nothing was tested"
    assert statuses == [200] * READERS
    assert totals == [1000.0] * READERS  # 1159.20 USD / 1.1592


def test_a_day_rewritten_inside_a_unit_of_work_reads_back_as_written(client, monkeypatch):
    """What the ORM used to give for free, kept. The store writes statements,
    which the session's identity map does not see, so a row the session is
    still HOLDING — the rates endpoint loads the rows after reading the rates —
    would keep the rate it remembered until the next commit, and inside a unit
    of work there is none before the read that follows. Held here on purpose:
    rows nobody holds leave the identity map on their own, and a test that let
    them go passed with the expiry deleted."""
    feed = {"payload": RATES}
    monkeypatch.setattr(
        fx, "_fetch_rates",
        lambda base, start, end=None: {d: dict(r) for d, r in feed["payload"].items()},
    )
    with SessionLocal() as db, unit_of_work(db):
        assert fx.rates_on(db, "EUR", TODAY)["USD"]["rate"] == 1.1592
        held = {r.currency: r for r in crud.get_fx_rate_rows(db, "EUR", DAY)}
        assert held["USD"].rate == 1.1592

        feed["payload"] = {DAY: {"USD": 1.2000, "GBP": 0.85815}}
        assert fx.rates_on(db, "EUR", TODAY, refresh=True)["USD"]["rate"] == 1.2
        assert held["USD"].rate == 1.2
    assert _stored()[(DAY, "USD")] == 1.2
