"""Foreign-exchange rates (ECB via frankfurter.app) and conversion to the base.

Every total is in ONE currency, the base, which the reader's database names in
`settings` (`base_currency`, read by `base_currency`); anything in another
currency is converted at the ECB daily reference rate. Rates are stored in the
DB (fx_rates) one row per published DAY, and kept: the table is the history of
the rates, and today's rate is simply the one in force today. `rates_on` is the
one reading of it. If the feed cannot be reached, what is stored keeps serving
(stale beats nothing — same policy as the composition cache), with its day
attached.

THE BASE LIVES IN THE DATABASE, AND ONLY A SESSION CAN READ IT. There is no
module constant and no value filled in at startup: that would be a constant
with extra steps, and it would be wrong in silence in the second process — the
MCP server opens the same kind of file read-only and has its own base to read.
A `Converter` reads it from the session it was given, once, and every figure it
produces is in that base; a response that carries those figures says which one
(`base_currency`), from the same converter, so a number never travels without
its unit.

Conversion semantics: frankfurter returns `rate` = units of CUR per 1 unit of
the base it was asked for, so amount_in_base = amount / rate. The cache is
keyed by that base as well as by currency, and every read names the base it
wants: the feed never lists the base among its own rates, so a rate that did
not say which base it belongs to would be read against whichever base asked
next. An unknown currency (no rate available yet) converts to None so callers
can choose an honest fallback instead of silently mixing currencies.

The network call lives in `_fetch_rates` so tests monkeypatch it.
"""

from __future__ import annotations

import bisect
import datetime
from collections.abc import Iterable
from contextlib import contextmanager

from sqlalchemy import inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import models
from app.database import commit, read_only

# The key in `settings`, and the base of a database that never chose one — the
# only base every figure it holds was ever computed in.
BASE_CURRENCY_KEY = "base_currency"
DEFAULT_BASE_CURRENCY = "EUR"
FRANKFURTER_URL = "https://api.frankfurter.app"
CACHE_TTL_HOURS = 24  # ECB publishes one reference rate per working day


class FxError(Exception):
    """Raised when rates cannot be fetched and no cache exists."""


class BaseRatesUnavailable(Exception):
    """The rates against a base could not be stored, so it cannot be chosen."""


class BaseNotQuoted(ValueError):
    """A base the ECB's feed does not quote: no total could be converted into
    it (`crud.change_base`)."""


# The first day the ECB published reference rates. A figure dated before it
# has no rate in any base, and a store cannot be asked to reach further back.
FEED_FIRST_DAY = "1999-01-04"


def base_currency(db: Session) -> str:
    """The currency every total of this database is in.

    Read from `settings`, where the reader's choice is kept; a database that has
    never made one is in EUR, the base it has always had. Nothing else decides
    it — no import-time constant, no process-wide value — so two processes over
    two files each read their own."""
    row = db.get(models.Setting, BASE_CURRENCY_KEY)
    chosen = (row.value or "").strip().upper() if row is not None else ""
    return chosen or DEFAULT_BASE_CURRENCY


def _fetch_rates(base: str, start: str, end: str | None = None) -> dict[str, dict[str, float]]:
    """{day: {currency: rate}} for every day the ECB published from the day in
    force on `start` up to `end` (or up to its latest, when `end` is None):
    units of each currency per 1 `base`, which is itself never in the dict.

    Measured against the feed on 2026-09-15: a range starting on a day with no
    publication starts at the working day before it — a Saturday gives its
    Friday, 1 January gives 31 December — so the first day returned is always
    the one in force on `start`; a range in the future answers 404; a year of
    every currency is 256 days in about 100 kB. Network call."""
    import httpx

    resp = httpx.get(
        f"{FRANKFURTER_URL}/{start}..{end or ''}",
        params={"base": base},
        timeout=30,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json().get("rates", {})


def _today() -> str:
    """Today, as the ISO day the rates are keyed by."""
    return datetime.date.today().isoformat()


# When the feed was last asked for the days after the newest one stored, per
# base, in `settings` — the table the catalogue keeps its own stamp in.
#
# Not `fx_rates.fetched_at`. That column says when a day's rows were written,
# and it used to say this too: the newest day came back in every forward fetch,
# so its stamp doubled as "asked for newer days". A fetch BACKWARDS writes that
# same day again whenever it is also the oldest one stored — every store of a
# single day, which is every database migrated from 9a02bd4 — and the first
# reading of the past made the store believe it had just asked for days it had
# never asked about. Measured on 2026-09-16: a PAC close of 2026-09-15 debited
# at the rate of 2026-09-11. Two questions, two stamps.
_ASKED_FOR_NEWER = "fx_asked_for_newer_days:{base}"


def _asked_for_newer(db: Session, base: str) -> datetime.datetime | None:
    row = db.get(models.Setting, _ASKED_FOR_NEWER.format(base=base))
    try:
        return datetime.datetime.fromisoformat(row.value) if row and row.value else None
    except ValueError:
        return None


def _day_over(day: str) -> datetime.datetime:
    """The moment `day` is over for the feed: midnight UTC after it. The ECB
    publishes a day's rates that afternoon, so a question asked after this has
    heard every rate the day will ever have."""
    after = datetime.date.fromisoformat(day) + datetime.timedelta(days=1)
    return datetime.datetime.combine(after, datetime.time(0), tzinfo=datetime.timezone.utc)


def _has_heard_of(asked: datetime.datetime | None, day: str, now: datetime.datetime) -> bool:
    """Whether a feed last asked for newer days at `asked` has already said
    whether `day` has a rate of its own.

    For a day that is over: only if it was asked after the day ended. Asked
    before, the day's rate may have come out since — twenty hours is fresh by
    the clock and says nothing about a publication made after the question.
    For the day still under way: the 24 hours a reading of today tolerates,
    since it reads again tomorrow and says which day's rate it used."""
    if asked is None:
        return False
    over = _day_over(day)
    if now >= over:
        return asked >= over
    return (now - asked) <= datetime.timedelta(hours=CACHE_TTL_HOURS)


def rates_on(
    db: Session, base: str, day: str, refresh: bool = False
) -> dict[str, dict]:
    """`rates_on_days` for one day: the rates in force on `day`."""
    return rates_on_days(db, base, [day], refresh)[day]


def rates_on_days(
    db: Session, base: str, days: list[str], refresh: bool = False
) -> dict[str, dict[str, dict]]:
    """{day: {currency: {"rate": float, "as_of": ECB day}}} — for each of
    `days`, the rates in force on it against `base`: those of the latest day
    the ECB published on or before it. The ONE reading of the rates, for today
    and for any other day; `rates_on` asks it about a single day.

    Many days at once because the net worth history asks about every point it
    draws, and asking one day at a time would re-read the stored days and
    reload the rates once per point. However many days are asked, the feed is
    asked at most twice (once backwards, once forwards) and the table is read
    the same number of times.

    The day in force is chosen whole, the way the feed itself chooses it: a
    currency that day does not list is unknown, not borrowed from an older day.
    The ECB stops publishing currencies (the lev at the end of 2025), and a rate
    months out of date wearing a recent date is the confident wrong answer.

    WHEN THE FEED IS ASKED. Only when what is stored cannot answer, and only
    for a range that touches what is stored, so the history is contiguous by
    construction and a stored day followed by a later stored day is the day in
    force for every date between them:

    * the earliest day asked precedes every stored day (or nothing is
      stored): the range from that day to the oldest stored one, which the
      feed starts at the day in force on it;
    * a day asked falls after the NEWEST stored day, and the feed has not been
      asked for newer days since that day was over — or, for a day still under
      way, in the last 24 hours (or `refresh`): the range from that stored day
      onwards. A newer publication cannot be ruled out without asking, and a
      rate one day behind would be served as current. When the feed was last
      asked is its own record (`_ASKED_FOR_NEWER`), written only by a fetch
      with no end.

    On a session that has declared it cannot write, or when the feed does not
    answer, what is stored serves: the day in force among the stored days, or
    nothing. That is safe because `as_of` travels with every rate and says how
    old it is. The one caller that sets the flag is a read-only reader of
    somebody else's database (`app/mcp_server.py`); the app refreshes these
    rates whenever it runs, and a reader asking a second process to do it is
    asking the wrong one.

    `base` has no default, on purpose. Every question about this table is a
    question about ONE base's rows, and a default would let a caller that
    never thought about it read another base's answers as its own. Rows of
    other bases are not read, refreshed or deleted."""
    if not days:
        return {}
    today = datetime.date.today().isoformat()
    asked = {day: min(day, today) for day in days}
    earliest = min(asked.values())
    stored = _stored_days(db, base)

    needs: list[tuple[str, str | None]] = []
    if not stored:
        needs.append((earliest, None))
    else:
        if earliest < stored[0]:
            needs.append((earliest, stored[0]))
        newer = {d for d in asked.values() if d > stored[-1]}
        now = datetime.datetime.now(datetime.timezone.utc)
        heard = _asked_for_newer(db, base)
        if newer and (refresh or not all(_has_heard_of(heard, d, now) for d in newer)):
            needs.append((stored[-1], None))

    if needs and not read_only(db):
        fetched_any = False
        for start, end in needs:
            try:
                fetched = _fetch_rates(base, start, end)
            except Exception:
                fetched = {}  # offline / feed down / a day before the ECB's first
            if fetched:
                _store(db, base, fetched, asked_for_newer=end is None)
                fetched_any = True
        if fetched_any:
            stored = _stored_days(db, base)

    in_force = {
        day: stored[i - 1] if (i := bisect.bisect_right(stored, d)) else None
        for day, d in asked.items()
    }
    wanted = sorted({d for d in in_force.values() if d is not None})
    by_day: dict[str, dict[str, dict]] = {d: {} for d in wanted}
    if wanted:
        for r in db.scalars(
            select(models.FxRate).where(
                models.FxRate.base == base, models.FxRate.as_of.in_(wanted)
            )
        ):
            by_day[r.as_of][r.currency] = {"rate": r.rate, "as_of": r.as_of}
    return {day: by_day[d] if d is not None else {} for day, d in in_force.items()}


def _stored_days(db: Session, base: str) -> list[str]:
    """The days stored for `base`, oldest first."""
    return list(
        db.scalars(
            select(models.FxRate.as_of)
            .where(models.FxRate.base == base)
            .distinct()
            .order_by(models.FxRate.as_of)
        )
    )


def _store(
    db: Session, base: str, fetched: dict[str, dict[str, float]], asked_for_newer: bool
) -> None:
    """Every fetched day's rates, written or rewritten, stamped now — and, for
    a fetch that had no end, the moment the feed was asked for newer days, in
    the same commit as the days it answered with.

    IDEMPOTENT, because it is called in parallel with itself. The first page
    load of a day fires several requests at once; each finds no rate for the
    day, each asks the feed, and each stores the same rows. This used to read
    what existed and then add what did not — a check-then-act, and every
    request had read "nothing" before the first one wrote, so the second
    commit died on the primary key. Measured on 2026-09-17: six sessions over
    an empty store, one stored and five raised, and the reader met it as a 500
    on the Dashboard. The stamp below had the same shape (`db.get`, then
    `db.add`). So each write is ONE statement that says what it means — this
    row, whatever was there — and SQLite serialises the writers; the second
    one waits for the first and then rewrites the same values.

    Written as statements rather than objects, so the session's identity map
    does not see them: a row this session loaded earlier would otherwise keep
    the rate it remembered until the next commit, and inside a caller's unit
    of work there is no commit before the read that follows. `_forget` expires
    exactly those rows."""
    now = models._utcnow_iso()
    key = _ASKED_FOR_NEWER.format(base=base)
    if asked_for_newer:
        stamp = sqlite_insert(models.Setting).values(key=key, value=now)
        db.execute(stamp.on_conflict_do_update(index_elements=["key"], set_={"value": now}))
    rows = [
        {"base": base, "currency": cur, "as_of": day, "rate": float(rate), "fetched_at": now}
        for day, rates in fetched.items()
        for cur, rate in rates.items()
    ]
    if rows:
        upsert = sqlite_insert(models.FxRate)
        # Many parameter sets, not one statement with a VALUES row each: a
        # base chosen today stores every day since the oldest record, and one
        # statement for a year of 30 currencies (7,560 rows, 37,800 variables)
        # is refused by SQLite as "too many SQL variables" — measured.
        db.execute(
            upsert.on_conflict_do_update(
                index_elements=["base", "currency", "as_of"],
                set_={"rate": upsert.excluded.rate, "fetched_at": upsert.excluded.fetched_at},
            ),
            rows,
        )
    _forget(db, base, set(fetched), key if asked_for_newer else None)
    commit(db)


def _forget(db: Session, base: str, days: set[str], setting_key: str | None) -> None:
    """Expire what this session holds of the rows `_store` just wrote, so the
    next read loads them. Only those: expiring everything would also discard a
    caller's changes that have not been flushed yet."""
    for obj in list(db.identity_map.values()):
        identity = inspect(obj).identity
        if isinstance(obj, models.FxRate):
            written = identity is not None and identity[0] == base and identity[2] in days
        elif isinstance(obj, models.Setting):
            written = setting_key is not None and identity == (setting_key,)
        else:
            written = False
        if written:
            db.expire(obj)


# Some exchanges quote in a currency's MINOR unit, and the code differs from the
# major one only by case: London gives 'GBp' (pence) for one fund and 'GBP'
# (pounds) for another ON THE SAME EXCHANGE, so "London means pence" is not a
# rule either. Upper-casing before conversion turned 3361 pence into 3361
# pounds — a position worth ~39 EUR valued at ~3.870, a hundredfold error that
# looks perfectly plausible on screen. The pairs below are every minor unit an
# equity or fund is actually quoted in.
#
# 'GBp' is the only one where CASE is the whole distinction — 'GBP' is pounds,
# 'GBp' is pence, and one lowercase letter separates a hundredfold. So it is
# matched exactly, and a sloppy 'gbp' still means pounds. The others have no
# major-unit twin, so any spelling of them is unambiguous.
_MINOR_EXACT = {"GBp": ("GBP", 100.0)}  # pence, as Yahoo spells it
_MINOR_ANY_CASE = {
    "GBX": ("GBP", 100.0),  # pence, the other common spelling
    "ZAC": ("ZAR", 100.0),  # South African cents
    "ILA": ("ILS", 100.0),  # agorot
}


def feed_currencies(db: Session) -> list[str]:
    """The currencies a base can be: those the ECB feed quotes today against
    the current base, and the base itself (the feed never lists the base among
    its own rates). Only the current base when the feed has never answered."""
    base = base_currency(db)
    return sorted(set(rates_on(db, base, _today())) | {base})


def rates_for(
    db: Session, currencies: Iterable[str]
) -> tuple[str | None, dict[str, float], list[str]]:
    """The rates in force today against the base for `currencies`, spelt as
    records spell them: the ECB day they were published, {code: units of it per
    one unit of the base}, and the spellings the ECB publishes no rate for.

    A minor unit is read as its major one, as every conversion reads it, so
    pence ask for the pound's rate; the base itself needs none and is left out.
    Read from the store like any conversion of today (`rates_on`), so it asks
    the feed only when a conversion would have.

    For the chat's picture, which converted every total at these rates and
    never said what they were: in the reader's second test round (2026-10-08)
    the chat answered that it had no exchange rate, with the app holding the
    ECB's."""
    base = base_currency(db)
    wanted: dict[str, str] = {}
    for written in currencies:
        if not written or not written.strip():
            continue
        _, code = _in_major_units(1.0, written)
        if code != base:
            wanted.setdefault(code, written.strip())
    if not wanted:
        return None, {}, []
    in_force = rates_on(db, base, _today())
    known = {
        code: in_force[code]
        for code in sorted(wanted)
        if code in in_force and in_force[code]["rate"]
    }
    published = max((entry["as_of"] for entry in known.values()), default=None)
    missing = sorted(written for code, written in wanted.items() if code not in known)
    return published, {code: entry["rate"] for code, entry in known.items()}, missing


def choose_base(db: Session, new_base: str, since: str | None) -> None:
    """Make `new_base` the base — but only once its rates are in the store.

    A base with no rates stored is not a base yet: every amount in another
    currency would pass through `to_base_or_as_stored` as it was typed, euro
    added up as dollars, and nothing would say so. The app would fetch them at
    its first reading. A reader that cannot fetch — the MCP server opens the
    file read-only — would add them up in silence for as long as the app was
    not opened. So the rates are fetched HERE, from `since` (the oldest
    recorded day, which the history's first point is drawn at) to today, and
    the setting is written only when they are stored. If the feed does not
    answer, nothing changes and the refusal says why.

    Nothing recorded is touched. Every stored amount keeps the currency it was
    written in; fixed sums — a debit, what a transfer delivered — were worked
    out on their day and are not worked out again. Every total moves, the
    history's too, because it is the same wealth in another unit."""
    today = _today()
    first = max(min(since or today, today), FEED_FIRST_DAY)
    rates_on_days(db, new_base, sorted({first, today}))
    stored = _stored_days(db, new_base)
    if not stored or stored[0] > first or not rates_on(db, new_base, today):
        raise BaseRatesUnavailable(
            f"The ECB rates against {new_base} could not be fetched, so the base "
            f"is still {base_currency(db)}: without them every amount in another "
            f"currency would be added to the totals as if it were in {new_base}. "
            "Try again when the app can reach the rate feed."
        )
    row = db.get(models.Setting, BASE_CURRENCY_KEY)
    if row is None:
        db.add(models.Setting(key=BASE_CURRENCY_KEY, value=new_base))
    else:
        row.value = new_base
    commit(db)


def _in_major_units(amount: float, currency: str) -> tuple[float, str]:
    """(amount, currency) restated in the currency's MAJOR unit.

    Runs BEFORE the upper-casing that would erase the distinction, which is
    the whole point: upper-casing first is what turned pence into pounds."""
    raw = currency.strip()
    minor = _MINOR_EXACT.get(raw) or _MINOR_ANY_CASE.get(raw.upper())
    if minor is not None:
        return amount / minor[1], minor[0]
    return amount, raw.upper()


class Converter:
    """Lazy converter into the database's base currency: rates are loaded
    (cache-first) only when the first amount in another currency shows up, so
    a computation all in the base never touches FX at all.

    `base` is read from the session on first use, or given by a caller that has
    already read it (`converters_on`). A response built from this converter's
    figures declares `conv.base` — the base they were computed in, not a second
    reading that could disagree with it.

    `on` is the day whose rates it converts at — today when left out. A
    reading of a past day converts at that day's rates, for the reason the net
    worth history does not price its past with today's quotes: a rate is a
    price. `used_as_of` then reports the ECB day that was actually in force."""

    def __init__(
        self, db: Session, on: str | None = None, _load=None, base: str | None = None
    ):
        self._db = db
        self._on = on
        self._load = _load
        self._base = base
        self._rates: dict[str, dict] | None = None
        self.used_as_of: str | None = None  # date of the rates actually used
        # What this converter could NOT convert and passed through anyway, by
        # the currency it was written in: {'Doll': {'amount': 2324.0, 'count': 1}}.
        # Read by whatever builds the payload, the way `used_as_of` is — so the
        # callers of `to_base_or_as_stored` keep making one decision between
        # them instead of a copy of it each. Nine of them call it by name and
        # two bind it to a local `in_base` called thirteen times more, counted
        # 2026-09-22; the point is that none of the counts is a number this
        # file has to keep in step with.
        self.unconverted: dict[str | None, dict] = {}
        self._recording = True

    @property
    def base(self) -> str:
        """The currency every figure this converter returns is in."""
        if self._base is None:
            self._base = base_currency(self._db)
        return self._base

    def _rates_now(self) -> dict[str, dict]:
        if self._rates is None:
            day = self._on or _today()
            self._rates = (
                self._load(day) if self._load is not None else rates_on(self._db, self.base, day)
            )
        return self._rates

    def to_base(self, amount: float | None, currency: str | None) -> float | None:
        """Convert into the base. Returns None when the amount exists but
        cannot be converted — no rate is known for its currency, or its
        currency is not known at all — and the caller must handle that, not
        hide it.

        A missing currency is NOT read as the base. It used to be read as EUR,
        which was the base, so the two claims were one; with a base that can be
        anything, reading "not known yet" as "the same as the base" would price
        a listing whose currency never came back as if it traded in whatever the
        reader chose. Every stored row states its currency; only a quote whose
        listing is not known yet arrives without one."""
        if amount is None or currency is None:
            return None
        amount, cur = _in_major_units(amount, currency)
        if cur == self.base:
            return amount
        entry = self._rates_now().get(cur)
        if entry is None or not entry["rate"]:
            return None
        self.used_as_of = max(self.used_as_of or "", entry["as_of"])
        return amount / entry["rate"]

    def to_base_or_as_stored(self, amount: float, currency: str) -> float:
        """`to_base`, with the one fallback this app applies when a rate is
        missing: the amount passes through as it was stored, and the converter
        REMEMBERS that it did.

        Not a guess at the rate. The figure is kept rather than dropped, so a
        total holding an amount the feed has never priced is visibly off
        instead of silently short by a whole account. It is the rule holdings
        have always been valued by (`positions.amount_in_base`), and the cash
        register, real assets and debts use it through this method, so the
        portfolio and the register cannot fail in two different ways on the
        same missing rate.

        But "visibly off" was a hope, not a mechanism: nothing said it had
        happened. `to_base`'s own docstring already required the caller to
        handle a None rather than hide it, and this method was the caller that
        hid it — measured on the reader's own database, a real asset written in
        `Doll` puts 2,324.00 into the net worth as if it were euro, with nothing
        anywhere saying so. So the fallback stays (a total that quietly DROPS a
        holding is as wrong as one that inflates) and it is recorded in
        `unconverted`, for the payload to carry to the reader.

        Zero and None are not recorded: there is nothing for a reader to act on
        in an amount that changes no total."""
        converted = self.to_base(amount, currency)
        if converted is not None:
            return converted
        if self._recording and amount:
            seen = self.unconverted.setdefault(currency, {"amount": 0.0, "count": 0})
            seen["amount"] += amount
            seen["count"] += 1
        return amount

    def unconverted_amounts(self) -> list[dict]:
        """What this converter had to pass through unconverted, largest first.

        One entry per currency: how many AMOUNTS were passed through, and what
        those amounts come to as they were written.

        That sum is a volume of rows, and it is NOT the amount any figure is
        wrong by — the difference matters enough to be said twice, because one
        converter serves several totals and an amount can reach them in roles
        that do not add up. It goes wrong in BOTH directions, measured:

        * a holding worth 1,000 TWD that COST 900 TWD reports 1,900.00 over 2,
          against an investments total of 1,000.00: the cost basis converts
          too, and it feeds the book value rather than the net worth;
        * adding a real asset of 1,000 TWD and a debt of 1,000 TWD reports
          3,900.00 over 4, and the net worth does not move at all — the debt
          subtracts exactly what the asset adds;
        * and it UNDERSTATES, by any multiple you like: an income of 100 TWD a
          month against an anchor dated a year earlier puts 1,200.00 into
          `cash_total` and into the net worth, and reports 100.00 over 1 — a
          recurring amount is converted once and multiplied afterwards.

        So it is not a bound in either direction, and nothing may present it as
        one.

        THE ALTERNATIVE, AND WHY IT IS NOT TAKEN — a choice with a price, not
        an impossibility. Making the figure mean "the error in the net worth"
        takes knowing each amount's ROLE where it is converted, and that CAN be
        done with the shape already in this class: a `recording_as(role)` beside
        `not_recording()`, a four-line wrapper over the two cost-basis sites and
        one `with` around the liabilities sum. Built as a prototype in about
        thirty lines and measured: {'TWD/value': 1000.0, 'TWD/cost': 900.0} with
        a signed net-worth error of {'TWD': 1000.0}, and again at value 2000 /
        cost 900 / debt 1000 for the same 1,000.00. Three sites to tag, not
        thirteen.

        What it costs is the reason it waits: a site added later and left
        untagged would understate the error silently, which is exactly the
        failure `crud._columns` was written to refuse — so it needs a discovery
        test that finds every conversion and insists each declares a role,
        which is the real work. Until that exists the number stays what it
        honestly is, and everything that prints it says so:
        `schemas.UnconvertedAmount`, `UnconvertedNotice.tsx`.

        Largest first for the same reason the omissions are sorted by value —
        the one worth acting on is the one at the front."""
        return [
            {"currency": code, "amount": seen["amount"], "count": seen["count"]}
            for code, seen in sorted(
                self.unconverted.items(), key=lambda kv: -kv[1]["amount"]
            )
        ]

    @contextmanager
    def not_recording(self):
        """Convert without adding to `unconverted`, for a reading that is not
        part of a total.

        One caller: `analytics._unaccounted`, which REPLAYS every photograph an
        institution has, so one holding's value passes through here once per
        photograph. Counted, a single unconvertible row would report a multiple
        of itself — and what that function reports is what a position was worth
        when it went MISSING, a past figure that enters no total this converter
        is building. Measured with this guard off: three photographs each naming
        one holding of 1,000 in a currency with no rate reported 3,000.00 over 3
        amounts, against an investments total of 1,000.00. With it, 1,000.00
        over 1.

        The cost of the guard is that `_unaccounted`'s own figures can be
        unconvertible without saying so. They are values that already LEFT the
        totals, reported in a notice of their own, so that is a smaller silence
        than the one this closes — but it is one."""
        was, self._recording = self._recording, False
        try:
            yield self
        finally:
            self._recording = was

    def from_base(self, amount: float | None, currency: str | None) -> float | None:
        """The same conversion backwards: an amount in the base restated in
        `currency`.

        It exists because a projection computes in the base while a photograph
        is written in whatever the row is denominated in. Handing a snapshot a
        base figure to store under a USD row does not just mislabel it — the
        next projection converts it AGAIN, so the number shrinks by the rate
        every time a situation is recorded.

        Mirrors `to_base` in both directions of the minor-unit rule: pence go
        back to pence, not to pounds. Returns None when the rate is unknown,
        for the same reason — the caller decides what to do about it, and the
        one thing nobody may do is guess."""
        if amount is None or currency is None:
            return None
        # What the target currency's MAJOR unit is, and how many minor units
        # go into it. `_in_major_units` answers both, on a probe of 1.
        minor_per_major, major = _in_major_units(1.0, currency)
        if major == self.base:
            return amount / minor_per_major
        entry = self._rates_now().get(major)
        if entry is None or not entry["rate"]:
            return None
        self.used_as_of = max(self.used_as_of or "", entry["as_of"])
        return amount * entry["rate"] / minor_per_major


def convert_on(
    db: Session, amount: float, from_currency: str, to_currency: str, day: str
) -> tuple[float | None, str | None]:
    """`amount` in `from_currency` restated in `to_currency` at the rates in
    force on `day`, and the ECB day those rates were published — or
    (None, None) when a rate that day is unknown.

    For a figure that is FIXED on its day rather than restated whenever it is
    read: what a purchase paid in one currency and listed in another took out
    of the account. It goes through a `Converter` on that day, there and back
    through the base, so it is the same conversion — minor units included —
    that every total uses; there is no second rule here. Two spellings of one
    currency ("GBp" pence into "GBP" pounds) are only the minor-unit step, and
    report no rate day, because no rate was used."""
    per_from, from_major = _in_major_units(1.0, from_currency)
    per_to, to_major = _in_major_units(1.0, to_currency)
    if from_major == to_major:
        return amount * per_from / per_to, None

    base = base_currency(db)

    def convert() -> tuple[float | None, str | None]:
        conv = Converter(db, on=day, base=base)
        converted = conv.from_base(conv.to_base(amount, from_currency), to_currency)
        if converted is None or not _final(db, base, day, conv.used_as_of):
            return None, None
        return converted, conv.used_as_of

    converted, rate_day = convert()
    if converted is None:
        # A sum that is never restated is worth one more question: the day's
        # rate may have come out since the store last asked, which a reading
        # would pick up tomorrow and this cannot.
        rates_on(db, base, day, refresh=True)
        converted, rate_day = convert()
    return converted, rate_day


def _final(db: Session, base: str, day: str, rate_day: str | None) -> bool:
    """Whether the rates of `rate_day` are the ones `day` ended with — the
    only rates a sum fixed on `day` may be worked out at.

    Its own publication is. An earlier one is only once nothing can have been
    published between them: a later day is stored (the history is contiguous),
    or the feed was asked for newer days after `day` was over. Until then the
    day in force is only the latest one heard of — on a morning before the ECB
    publishes, yesterday's — and a debit written at it would keep yesterday's
    rate for good."""
    if rate_day is None:
        return False
    if rate_day == day:
        return True
    stored = _stored_days(db, base)
    if stored and stored[-1] > day:
        return True
    heard = _asked_for_newer(db, base)
    return heard is not None and heard >= _day_over(day)


def converters_on(db: Session, days: list[str]) -> dict[str, Converter]:
    """One `Converter` per day, sharing a single lazy load of all their rates.

    For a reading that converts at many days at once — the net worth history.
    Nothing is read until the first non-base amount is converted on any of the
    days; then every day's rates arrive together from `rates_on_days`, so a
    series of a hundred points costs one load, not a hundred, and a series all
    in the base currency costs none. The base is read once for all of them."""
    loaded: dict[str, dict[str, dict]] = {}
    base = base_currency(db)

    def load(day: str) -> dict[str, dict]:
        if not loaded:
            loaded.update(rates_on_days(db, base, list(days)))
        return loaded[day]  # every day asked is a key, with {} when none was in force

    return {day: Converter(db, on=day, _load=load, base=base) for day in days}
