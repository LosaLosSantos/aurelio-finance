"""The anchor rule, with a name.

Every number this app reports is a *dated series read at a date*: the latest
photograph on or before some day, plus the events that happened strictly after
it. That rule was written out eleven times before this module existed — seven
copies of "the latest record for each parent" and five different grammars for
"strictly after the anchor", including two that were half-open intervals and
two that were open-ended and one that only differed in what it called the
variable. Each of the five had to get the strictness right on its own, and
nothing anywhere would have noticed if one of them stopped.

They are four operations and they are named here:

``latest_per_parent``   one record per parent, the one in force at a date
``latest_on_or_before``  the record in force AT a date (the anchor)
``carry_forward``        the total of what was in force, across parents
``events_after``         what happened after the anchor — the central rule

The three that ask what was IN FORCE take the date they are asked at, and none
of them will answer without one (`events_after` is the exception, and only on
its right-hand edge: an open-ended `until` is a real question). That is not
ceremony: "the latest row there is" and "the latest row in force" are
different questions, and the projections asked the first one while meaning the
second. A photograph dated eleven days from now was therefore the app's
account of today, and an empty one emptied the portfolio. The bound is
mandatory so that the question cannot be asked by accident again — a caller
that means today says `today()`, and can be read as meaning it.

Nothing here holds a policy about WHAT the records mean. `Snapshot` has
children and `RealAssetValuation` does not; a liability's balance falls and an
asset's valuation rises. The tables stay separate on purpose: what they share
is the shape of the question, not the payload.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterable, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


def today() -> str:
    """Today, as the ISO string the dated tables are keyed by.

    The bound for every question about NOW. It lives here, next to the
    functions that demand a bound, so that "as of today" is one spelling rather
    than a `datetime.date.today().isoformat()` written out at each call site —
    and so the callers that mean today are greppable as a set.

    The app runs locally against the reader's own clock, so there is no
    timezone to be wrong about: today is the day it is where the database is."""
    return datetime.date.today().isoformat()


def local_day(iso_timestamp: str) -> str:
    """'2026-08-12T23:14:03+00:00' -> '2026-08-13' for a reader in Rome.

    Timestamps are stored in UTC; the day the reader remembers doing something
    is the LOCAL one, and the two differ for the hours around midnight.
    Truncating the string would hand a model the UTC day next to a "Today is"
    line written in local time, the same off-by-one the frontend guards
    against by never taking a date from toISOString(). The seconds are noise;
    a model needs the day.

    Here and not in the chat, which had it first: the contexts the analysis
    reads date the questionnaire's answers with it too, and the chat imports
    the module that builds them."""
    return datetime.datetime.fromisoformat(iso_timestamp).astimezone().date().isoformat()


def date_of(record: Any) -> str:
    """The ISO date of a dated thing: a mapped row's `.date`, or the first
    element of a `(date, value)` pair. Both shapes are already in use — the
    carry-forward totals collapse rows to pairs before they ever get here —
    and neither is worth a second copy of every function below."""
    date = getattr(record, "date", None)
    return date if date is not None else record[0]


def latest_per_parent(
    db: Session, model: type[T], parent_col: Any, *, on_or_before: str
) -> dict[Any, T]:
    """For each parent, its most recent row of `model` — the anchor photograph.

    `parent_col` is the mapped column holding the parent's id (e.g.
    ``models.Snapshot.institution_id``). Ordering ascending and letting the
    last write win keeps ties resolved the way every hand-written copy of this
    already did, and one query answers for every parent instead of one per
    parent — which is what the two model properties this replaces could never
    do, being N+1 by construction.

    `on_or_before` is the date the question is asked AT, and it is required:
    see the module docstring. History passes the day it is drawing; a caller
    asking what is true now passes `today()`."""
    stmt = (
        select(model)
        .where(model.date <= on_or_before)  # type: ignore[attr-defined]
        .order_by(parent_col, model.date)  # type: ignore[attr-defined]
    )
    latest: dict[Any, T] = {}
    for row in db.scalars(stmt):
        latest[getattr(row, parent_col.key)] = row  # ascending -> last seen wins
    return latest


def latest_per_parent_of(
    records: Iterable[T], parent_of: Any, *, on_or_before: str
) -> dict[Any, T]:
    """`latest_per_parent` over rows ALREADY in memory.

    The same question, asked of a list instead of a table, because a caller
    that asks it at 130 different dates must not re-read the table 130 times.
    `parent_of` maps a record to its parent's id, and `on_or_before` is
    required for the same reason as in `latest_per_parent`."""
    latest: dict[Any, T] = {}
    for rec in records:
        d = date_of(rec)
        if d > on_or_before:
            continue
        key = parent_of(rec)
        current = latest.get(key)
        if current is None or d >= date_of(current):
            latest[key] = rec
    return latest


def latest_on_or_before(records: Iterable[Any], iso_date: str) -> Any | None:
    """The record in force at `iso_date`: the latest one dated ON or BEFORE it,
    or None if the series had not started yet.

    ON or before, inclusive — a photograph taken today describes today. This is
    the other half of `events_after`, and the two boundaries are deliberately
    complementary: what the anchor already contains, it contains up to and
    including its own date, so the events that are still outstanding are the
    ones strictly after it. Nothing is counted twice and nothing falls between
    them."""
    best = None
    for rec in records:
        d = date_of(rec)
        if d <= iso_date and (best is None or d >= date_of(best)):
            best = rec
    return best


def carry_forward(
    series_by_parent: dict[Any, Sequence[tuple[str, float]]],
    iso_date: str,
    value: Any = None,
) -> float:
    """Sum, across parents, the value in force at `iso_date`.

    A valuation stands until a newer one replaces it: that is what a dated
    photograph MEANS, and it is why a total on an old date is a sum of
    whichever photographs were current then, not of today's. Parents whose
    series has not started by that date contribute nothing — a house bought
    next year is not worth its price today.

    Takes `(iso_date, value)` pairs rather than rows, because the three callers
    value three different columns — a snapshot's holdings summed and converted,
    an asset's valuation, a liability's balance — and choosing between them in
    here would be this module holding a policy about payloads it has no
    business knowing.

    `value(parent, amount)`, when given, is applied to each parent's figure in
    force before it is added — the caller's way of converting it at the rate
    of `iso_date` rather than the rate of the day the figure was recorded, with
    the policy staying on the caller's side."""
    total = 0.0
    for parent, records in series_by_parent.items():
        rec = latest_on_or_before(records, iso_date)
        if rec is not None:
            total += rec[1] if value is None else value(parent, rec[1])
    return total


def events_after(
    anchor: Any | None, records: Iterable[T], until: str | None = None
) -> list[T]:
    """The events the anchor does NOT already account for: everything dated
    strictly AFTER it, up to and including `until`.

    The interval is **half-open on the left and closed on the right**::

        (anchor, until]     with until=None meaning open-ended

    Both boundaries are deliberate, and both cost a day of somebody's time
    before they were written down:

    * **Strictly after the anchor.** A photograph taken on the 1st already
      contains everything that had happened by the end of the 1st, so a buy
      dated the 1st is IN it. Applying that buy on top would count the same
      money twice. This is the app's central invariant — every projection in
      it, cash and positions alike, is `anchor + events_after(anchor)`.
    * **Including `until`.** A series point for the 1st must show what the 1st
      looked like when it ended: a sale that day has happened by then. The one
      caller that genuinely wants the other rule is the dividend path, which
      needs the units held strictly BEFORE the ex-date — and that stays where
      it is, as `replay(..., until=...)`, exclusive and documented as such,
      rather than being folded in here as a flag nobody could read.

    `anchor` may be a dated record, a bare ISO string, or None (no anchor yet,
    so every event is still outstanding). Order is preserved; the caller sorts
    if it cares."""
    lo = "" if anchor is None else (anchor if isinstance(anchor, str) else date_of(anchor))
    return [
        r
        for r in records
        if date_of(r) > lo and (until is None or date_of(r) <= until)
    ]
