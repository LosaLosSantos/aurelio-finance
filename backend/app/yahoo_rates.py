"""Yahoo's daily closes for the currencies the ECB does not publish (brief BA,
the reader's decision D1, 2026-10-16).

THE ECB STAYS THE SOURCE FOR EVERY CURRENCY IT PUBLISHES (`fx.rates_on_days`).
A currency it does not publish (TWD, AED, VND: 125 of the 155 ISO codes held
as money, measured on 2026-10-16) used to convert to nothing and be counted as
written, so a balance of 700 TWD read as 700.00 EUR. It is converted here at
Yahoo's rate, the source the app already reads every price from. Only a code
the ECB day in force does not list reaches this module.

WHICH OF YAHOO'S SERIES. Its dollar pair, `USD{code}=X`, crossed at the ECB's
dollar rate of the same day: units of the code per base = Yahoo's units per
dollar x the ECB's dollars per base (1 for a dollar base). Measured in brief
BA's P0 against the 21 currencies whose rate is fixed by law: the dollar pair
within 0.63% at the median on 16 of the 19 that have a history, 1.4 to 2.2%
off nearly every day on PAB, BZD and BBD, p95 up to 3.79%. Yahoo's euro pair
reads as derived from the dollar pairs and went stale: XOF's stood at 636.83
against a legal 655.957 for 91 trading days. And the dollar leg is the ECB's
own, so the ECB stays the source of the dollar.

KEPT LIKE THE ECB'S: one row a day in `fx_rates_yahoo`, the history kept,
asked backwards from the earliest day a reading needs and forwards as days
end. A day is written only once it is over (midnight UTC after it): Yahoo's
row of the day under way is a price still moving.

TRUSTED ONLY WHEN (thresholds and counts from P0: two years, 2024-10-01 to
2026-10-16, of the 99 dollar pairs with a full history):
- Yahoo gives a history: a first window answering on one day only is a quote
  with no history (20 of the 120 currencies Yahoo quotes); the code is then a
  currency no source quotes, asked again a day later;
- a close is within 50% of the median of the five closes ending on its day:
  no close of those two years came near (the largest, BOB's 44.4%, a move
  that held), and the slips measured are far beyond (EURPKR 2.88 for about
  290 on 2025-02-04; one-day moves of 1,571% to 100,138% in twenty years);
- a close is not more than 5% from both its neighbours while they agree
  within 2.5% (175 such prints in 51,916 closes, 97 of them SOS's and 52
  SCR's, seven of SCR's between 10 and 17%), judged once the next close
  exists;
- the close in force is at most 7 days old: the longest gap between two
  closes was 5 days (Easter 2025), and MMK, with none for a year, reads as
  quoted by no source.

A SUM FIXED ON A DAY takes the close in force on that day once the day is
over and Yahoo was asked after (`final`), as `fx._final` does for the ECB;
when that close moved more than 5% from the one before (489 of 52,015 closes,
0.94%), once the next close exists to tell a print from a move.

The network call is `prices._fetch_close_window`, the app's own dated window,
so the suite's boundary refuses it unless a test fakes it.
"""

from __future__ import annotations

import bisect
import datetime
import statistics

from sqlalchemy import inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import models, prices, schemas
from app.database import commit, read_only

SLIP = 0.50
SPIKE = 0.05
NEIGHBOURS_AGREE = 0.025
STALE_DAYS = 7
# A first window reaches this far before the earliest day asked, past a
# weekend and a holiday, so the close in force on that day is in it.
LOOK_BACK_DAYS = 10
# An answer with no history is asked again after this.
QUIET = datetime.timedelta(hours=24)

# When Yahoo was last asked for newer days of a code, and when it last
# answered that it has no daily close for one: rows of `settings`, as the
# ECB's own stamp is (`fx._ASKED_FOR_NEWER`).
_ASKED = "fx_yahoo_asked_for_newer_days:{code}"
_NO_HISTORY = "fx_yahoo_no_daily_close:{code}"
# The earliest day Yahoo was asked about for a code: a reading of days before
# its history (TWD's starts in 2006) asks once, not at every page.
_BACK = "fx_yahoo_asked_back_to:{code}"


def symbol(code: str) -> str:
    """Yahoo's dollar pair for a code: units of it per one US dollar."""
    return f"USD{code}=X"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _day_over(day: str) -> datetime.datetime:
    """Midnight UTC after `day`: the close of a day is final from then."""
    after = datetime.date.fromisoformat(day) + datetime.timedelta(days=1)
    return datetime.datetime.combine(after, datetime.time(0), tzinfo=datetime.timezone.utc)


def _stamp(db: Session, key: str) -> datetime.datetime | None:
    row = db.get(models.Setting, key)
    try:
        return datetime.datetime.fromisoformat(row.value) if row and row.value else None
    except ValueError:
        return None


def _set_stamp(db: Session, key: str, when: datetime.datetime) -> None:
    value = when.isoformat()
    stamp = sqlite_insert(models.Setting).values(key=key, value=value)
    db.execute(stamp.on_conflict_do_update(index_elements=["key"], set_={"value": value}))


def stored(db: Session, code: str) -> list[tuple[str, float]]:
    """The closes kept for `code`, oldest first."""
    return [
        (r.as_of, r.rate)
        for r in db.scalars(
            select(models.FxRateYahoo)
            .where(models.FxRateYahoo.currency == code)
            .order_by(models.FxRateYahoo.as_of)
        )
    ]


def _store(
    db: Session, code: str, closes: list[tuple[str, float]], now: datetime.datetime,
    asked_for_newer: bool,
) -> None:
    """Every close of a day that is over, written or rewritten (the same
    one-statement upsert `fx._store` uses, for the same parallel first page
    loads), and the stamp of a forward fetch, in one commit."""
    rows = [
        {"currency": code, "as_of": day, "rate": float(close), "fetched_at": now.isoformat()}
        for day, close in closes
        if now >= _day_over(day)
    ]
    if rows:
        upsert = sqlite_insert(models.FxRateYahoo)
        db.execute(
            upsert.on_conflict_do_update(
                index_elements=["currency", "as_of"],
                set_={"rate": upsert.excluded.rate, "fetched_at": upsert.excluded.fetched_at},
            ),
            rows,
        )
    keys = set()
    if asked_for_newer:
        keys.add(_ASKED.format(code=code))
        _set_stamp(db, _ASKED.format(code=code), now)
    _forget(db, code, {row["as_of"] for row in rows}, keys)
    commit(db)


def _forget(db: Session, code: str, days: set[str], keys: set[str]) -> None:
    """Expire what this session holds of the rows just written by statement,
    and only those (`fx._forget` says why)."""
    for obj in list(db.identity_map.values()):
        identity = inspect(obj).identity
        if isinstance(obj, models.FxRateYahoo):
            written = identity is not None and identity[0] == code and identity[1] in days
        elif isinstance(obj, models.Setting):
            written = identity is not None and identity[0] in keys
        else:
            written = False
        if written:
            db.expire(obj)


def _fetch(code: str, start: datetime.date, end: datetime.date) -> list[tuple[str, float]] | None:
    """Yahoo's closes of `code` in [start, end), or None when Yahoo did not
    answer: an outage is not a currency without a rate. Network call."""
    try:
        rows = prices._fetch_close_window(symbol(code), start, end)
    except Exception:
        return None
    return [(day, close) for day, close in rows if close is not None and close > 0]


def _asked_back(db: Session, code: str, day: datetime.date) -> None:
    """Record that Yahoo was asked about `code` from `day` on, written with
    the closes that answer it (`_store` commits)."""
    key = _BACK.format(code=code)
    value = day.isoformat()
    stamp = sqlite_insert(models.Setting).values(key=key, value=value)
    db.execute(stamp.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    _forget(db, code, set(), {key})


def _heard_of(heard: datetime.datetime | None, day: str, now: datetime.datetime) -> bool:
    """`fx._has_heard_of` for Yahoo: whether a fetch at `heard` has already
    said whether `day` has a close of its own."""
    if heard is None:
        return False
    over = _day_over(day)
    if now >= over:
        return heard >= over
    return (now - heard) <= datetime.timedelta(hours=24)


def ensure(db: Session, code: str, days: list[str], refresh: bool = False) -> None:
    """Ask Yahoo for what the store cannot answer about `code` on `days`, as
    `fx.rates_on_days` asks the ECB: backwards when the earliest day asked is
    before every close kept (from `LOOK_BACK_DAYS` earlier), forwards when a
    day asked is after the newest one and Yahoo was not asked since that day
    was over. Never for a code that is not a currency code, nor on a session
    that cannot write."""
    if not days or read_only(db) or not schemas.is_currency_code(code):
        return
    now = _now()
    today = datetime.date.today()
    asked = sorted({min(d, today.isoformat()) for d in days})
    earliest = datetime.date.fromisoformat(asked[0]) - datetime.timedelta(days=LOOK_BACK_DAYS)
    tomorrow = today + datetime.timedelta(days=1)
    kept = stored(db, code)
    if not kept:
        quiet = _stamp(db, _NO_HISTORY.format(code=code))
        if quiet is not None and now - quiet < QUIET and not refresh:
            return
        answer = _fetch(code, earliest, tomorrow)
        if answer is None:
            return
        if len({day for day, _ in answer}) <= 1:
            # A quote with no history, or nothing: no source quotes it.
            key = _NO_HISTORY.format(code=code)
            _set_stamp(db, key, now)
            _forget(db, code, set(), {key})
            commit(db)
            return
        _asked_back(db, code, earliest)
        _store(db, code, answer, now, asked_for_newer=True)
        return
    back = db.get(models.Setting, _BACK.format(code=code))
    if earliest.isoformat() < kept[0][0] and (back is None or earliest.isoformat() < back.value):
        answer = _fetch(code, earliest, datetime.date.fromisoformat(kept[0][0]))
        if answer is not None:
            _asked_back(db, code, earliest)
            _store(db, code, answer, now, asked_for_newer=False)
    newer = [d for d in asked if d > kept[-1][0]]
    heard = _stamp(db, _ASKED.format(code=code))
    if newer and (refresh or not all(_heard_of(heard, d, now) for d in newer)):
        answer = _fetch(code, datetime.date.fromisoformat(kept[-1][0]), tomorrow)
        if answer is not None:
            _store(db, code, answer, now, asked_for_newer=True)


def trusted(closes: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """The closes the rules of this module let through, oldest first: within
    `SLIP` of the median of the five ending on each, and not a print `SPIKE`
    from both neighbours that agree within `NEIGHBOURS_AGREE`."""
    kept = []
    last = len(closes) - 1
    for i, (day, close) in enumerate(closes):
        window = [c for _, c in closes[max(0, i - 4): i + 1]]
        if len(window) >= 3 and abs(close / statistics.median(window) - 1) > SLIP:
            continue
        if 0 < i < last:
            before, after = closes[i - 1][1], closes[i + 1][1]
            off = (close / before - 1, close / after - 1)
            if abs(after / before - 1) < NEIGHBOURS_AGREE and (
                min(off) > SPIKE or max(off) < -SPIKE
            ):
                continue
        kept.append((day, close))
    return kept


def in_force(kept: list[tuple[str, float]], day: str) -> tuple[str, float] | None:
    """The close in force on `day`: the latest kept on or before it, at most
    `STALE_DAYS` old."""
    i = bisect.bisect_right([d for d, _ in kept], day)
    if i == 0:
        return None
    close_day, close = kept[i - 1]
    old = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(close_day)).days
    return (close_day, close) if old <= STALE_DAYS else None


def rates_on_days(db: Session, base: str, days: list[str], code: str) -> dict[str, dict | None]:
    """{day: {"rate": units of `code` per 1 `base`, "as_of": Yahoo's day,
    "ecb_as_of": the ECB day of the dollar leg (None for a dollar base)} or
    None}: Yahoo's close in force on each day, crossed at the ECB's dollar of
    the same Yahoo day. None where no close is trusted, or the ECB has no
    dollar rate in force on it."""
    from app import fx  # fx reads this module from its converter

    ensure(db, code, days)
    kept = trusted(stored(db, code))
    today = datetime.date.today().isoformat()
    hits = {day: in_force(kept, min(day, today)) for day in days}
    yahoo_days = sorted({hit[0] for hit in hits.values() if hit is not None})
    if base == "USD":
        legs = {day: (1.0, None) for day in yahoo_days}
    else:
        ecb = fx.rates_on_days(db, base, yahoo_days) if yahoo_days else {}
        legs = {
            day: (ecb[day]["USD"]["rate"], ecb[day]["USD"]["as_of"])
            for day in yahoo_days
            if "USD" in ecb.get(day, {}) and ecb[day]["USD"]["rate"]
        }
    out: dict[str, dict | None] = {}
    for day, hit in hits.items():
        leg = legs.get(hit[0]) if hit is not None else None
        out[day] = (
            {"rate": hit[1] * leg[0], "as_of": hit[0], "ecb_as_of": leg[1]}
            if leg is not None
            else None
        )
    return out


def final(db: Session, code: str, day: str, used: str) -> bool:
    """Whether Yahoo's close of `used` is the one `day` ended with, the only
    one a sum fixed on `day` may be worked out at: Yahoo was asked after the
    day was over (so no close of its own can still come), and the close, if it
    is the newest kept, moved no more than `SPIKE` from the one before."""
    heard = _stamp(db, _ASKED.format(code=code))
    if heard is None or heard < _day_over(day):
        return False
    kept = trusted(stored(db, code))
    days = [d for d, _ in kept]
    if used not in days:
        return False
    i = days.index(used)
    if i == len(kept) - 1 and i > 0 and abs(kept[i][1] / kept[i - 1][1] - 1) > SPIKE:
        return False
    return True


def no_source(db: Session, code: str) -> bool:
    """Whether Yahoo said it has no daily close for `code` when last asked:
    with the ECB publishing none, no source quotes it."""
    return (
        schemas.is_currency_code(code)
        and _stamp(db, _NO_HISTORY.format(code=code.strip())) is not None
        and not stored(db, code.strip())
    )
