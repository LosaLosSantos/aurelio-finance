"""Ledger catch-up: PAC auto-execution and dividend collection.

No timer is needed: both schedules are reconstructable retroactively. On
demand (the frontend triggers this at app start):
- every elapsed PAC occurrence with no matching Transaction gets a Buy at that
  day's market close (unless the plan names no source institution, in which
  case there is no account for the money to leave and the occurrence is
  reported instead of executed);
- every dividend ex-date of a position that follows its dividends (stated
  distributing, or stating no policy, when its own history decides:
  `_follows_dividends`) gets a `dividend` transaction crediting the
  institution's cash (quantity = shares held at the ex-date, reconstructed
  from the snapshot anchor + ledger).

So the app realigns even after months of not being opened. Created entries
are marked `estimated` (close prices / gross dividends approximate the real
fills — e.g. withholding tax is NOT deducted) and the user can correct them.

Yahoo is asked for a ticker's dividend history until it answers, and then not
again that day: every later catch-up works from the answer it gave
(`_dividend_history`). The whole history the first time a ticker is followed;
after that, a window reaching back to its earliest situation.

Currencies: a plan's contribution is in the plan's currency, each target's
price in its listing's, and a dividend per share in the currency Yahoo names
for it, or in its listing's when it names none, as every real answer measured
on 2026-10-05 did. Every price
is converted at the rate of ITS OWN DAY — the close a plan buys at, the ex-date
a dividend is paid for — never at today's: an occurrence caught up three months
late spends what that day's rate made of the budget, and the account is
debited what it would have been debited then. The debit itself is worked out by
`crud` from the same rate, so it carries the rate's day as `fx_as_of` beside
`estimated`. Without a rate for the day, or without knowing what a listing
trades in, the occurrence is skipped and retried and nothing is written — the
same answer as a missing price.

A day whose close the market has not published is that same answer once more,
and it is the one that used to be given wrongly: the occurrence waits, nothing
is written, and it comes back on the next run. It is `prices.NoCloseYet` that
says so, at the source, rather than a NaN travelling into the allocation and
being reported here as a budget too small to buy a unit. What a plan buys when
a day never gets a close at all — a weekend, a holiday, a gap in the feed — is
`prices._close_on`'s policy, and the buy is then dated the session it was
priced at. A weekend does not wait for it (brief AJ): the first session after
it is bought as soon as that session has ended.

PAC fill models (plan.execution):
- whole_units (default): floor(amount / price) units; the remainder simply
  never leaves the source institution's cash (no separate bookkeeping).
- fractional: exactly `amount` invested, fractional quantity.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import crud, dividend_pairs, fx, models, prices, schemas
from app.analytics import STEP_MONTHS, add_months, recurrence
from app.database import commit, sole_writer
from app import dated
from app.positions import latest_snapshot_by_institution, project, replay

logger = logging.getLogger(__name__)


def plan_occurrences(plan: models.AccumulationPlan, up_to: datetime.date) -> list[datetime.date]:
    """The plan's scheduled dates from start_date to `up_to` (inclusive),
    bounded by end_date. A plan with no start_date has no schedule.

    Stepped from the start (`analytics.recurrence`): a plan on the 31st buys
    on the 31st, on the last day of a shorter month, and on the 31st again
    after it. It used to step from the date before, so every buy after the
    first short month fell on the 28th. The buys written then keep their
    dates, and `_settled_months` still finds them."""
    if not plan.start_date:
        return []
    step = STEP_MONTHS.get(plan.frequency or "monthly", 1)
    last = up_to
    if plan.end_date:
        last = min(up_to, datetime.date.fromisoformat(plan.end_date))
    return list(recurrence(datetime.date.fromisoformat(plan.start_date), step, last))


def _settled_months(db: Session, plan_id: int) -> set[str]:
    """The months ('YYYY-MM') in which the plan has a settled occurrence: one
    that bought, or one that ran and could not (`crud.get_plan_occurrences_settled`).

    The catch-up asks "is this occurrence settled?" of its month, not of its
    exact date, because not every date already written is on the schedule
    any more. A plan used to be stepped from the date before, so one started
    on the 31st has buys written on the 28th from its first February on.
    Stepped from the start, the same months fall on the 30th and the 31st,
    and asked by date every one of them would be bought again: measured on a
    plan from 2026-01-31 with 9 buys written the old way, 7 more, the cash
    debited twice. A plan buys at most once a month at every frequency it
    takes, so the month names the occurrence whatever day it was written on.

    It also keeps an edited start day from buying the elapsed months again
    on the new day (measured: from the 15th to the 20th, 9 buys of 9 again).
    What it does not change is a frequency switched on a running plan: the
    months the new schedule adds were never bought, so they are, as before."""
    return {iso[:7] for iso in crud.get_plan_occurrences_settled(db, plan_id)}


def first_unsettled(
    db: Session, plan: models.AccumulationPlan, today: datetime.date
) -> datetime.date | None:
    """The first occurrence of `plan`'s schedule that its catch-up has not
    settled (`_settled_months`): due already and not bought yet (today's, a
    weekend's waiting for its session, one whose close did not answer), or
    still to come. None when the plan has no first buy day, or no occurrence
    left before its last day.

    The catch-up reads the plan's amount when it buys, so this is the first
    occurrence a change of amount reaches, which the chat's card names (brief
    AO). Looked for up to thirteen months past today or the first buy, the
    longest step a plan takes and a month more."""
    if not plan.start_date:
        return None
    start = datetime.date.fromisoformat(plan.start_date)
    done = _settled_months(db, plan.id)
    return next(
        (
            occ
            for occ in plan_occurrences(plan, add_months(max(today, start), 13))
            if occ.isoformat()[:7] not in done
        ),
        None,
    )


def allocate(
    budget: float, weights: list[float], unit_prices: list[float], fractional: bool
) -> list[float]:
    """How many units of each target one occurrence buys.

    Fractional brokers are trivial: each target gets its exact share.

    Whole-unit brokers are not, and the naive answer wastes real money. Giving
    each target its own slice and flooring leaves every slice with its own
    remainder — three slices of 60 EUR against a 90 EUR fund buy nothing at
    all, while the same 180 EUR buys two units. So the budget is spent as one
    pot: units are bought one at a time, each going to whichever target is
    furthest BELOW its intended share, until nothing else fits. That spends the
    budget down as far as it goes while staying as close to the requested mix
    as whole units allow.

    KNOWN LIMIT, and it is reported rather than hidden: a target whose unit
    price exceeds its share of the budget is never bought, because buying it
    would blow past its weight. A 250 EUR fund at 30% of 400 EUR needs either a
    bigger contribution or a bigger weight — `execute_due` says so.

    The loop is bounded by the remainder shrinking by at least the cheapest
    price on every pass, so it always terminates."""
    total_w = sum(w for w in weights if w > 0)
    if total_w <= 0 or not unit_prices:
        return [0.0] * len(unit_prices)
    shares = [(w / total_w if w > 0 else 0.0) for w in weights]

    if fractional:
        return [
            (budget * s / p) if p > 0 else 0.0 for s, p in zip(shares, unit_prices)
        ]

    qty = [0.0] * len(unit_prices)
    remainder = budget
    while True:
        # Only what is still affordable, and only what was actually asked for.
        affordable = [
            i
            for i, p in enumerate(unit_prices)
            if 0 < p <= remainder + 1e-9 and shares[i] > 0
        ]
        if not affordable:
            return qty
        # Furthest below its intended share of the whole budget.
        pick = max(affordable, key=lambda i: shares[i] - (qty[i] * unit_prices[i]) / budget)
        qty[pick] += 1
        remainder -= unit_prices[pick]


def _fill(plan: models.AccumulationPlan, price: float) -> tuple[float, float] | None:
    """(quantity, amount_spent) for a single-target occurrence at `price`, or
    None if the budget cannot buy even one whole unit."""
    if (plan.execution or "whole_units") == "fractional":
        return plan.amount / price, plan.amount
    qty = math.floor(plan.amount / price)
    if qty < 1:
        return None
    return float(qty), qty * price


class StoredValueRefused(ValueError):
    """A row already on disk carries a value the write schema refuses.

    The catch-up builds its entries out of what is STORED and never re-typed:
    a cash anchor's currency, a holding's, the listing currency the price cache
    learned from Yahoo. So a row written before a rule existed meets that rule
    again HERE — where there is no reader to correct it and no box to correct
    it in — and pydantic's answer to a value it will not accept is to raise.

    Which is the same failure the currency rule is deliberately kept off the
    ...Read models to avoid: a stored row taking away the screen it would be
    corrected from. One level down, the screen is the whole app — `catch_up` is
    documented "safe to call at every app start", so an uncaught refusal there
    answers 500 before anything is drawn. Measured on a scratch database: one
    legacy cash anchor in 'Doll' turned that route from 200 with a skip into a
    500 with a traceback.

    So it is caught and reported as a skip, like a price that did not answer
    and a rate that is not published yet: the occurrence waits, nothing is
    written, and the reason names what to fix."""


def _entry(**fields) -> schemas.TransactionCreate:
    """A ledger payload built from STORED values, or `StoredValueRefused`.

    Every catch-up entry goes through here rather than building its own
    `TransactionCreate`, so the two paths make one decision about a value the
    schema refuses instead of one each — and a third path added later inherits
    it by construction."""
    try:
        return schemas.TransactionCreate(**fields)
    except ValidationError as exc:
        raise StoredValueRefused(
            "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg'].removeprefix('Value error, ')}"
                for e in exc.errors()
            )
            + " (that value is recorded on a row rather than typed here, so"
            " correcting the row is what lets this entry through on the next run)"
        ) from exc


def execute_due(db: Session, as_of: datetime.date | None = None) -> dict:
    """Create a Buy for every elapsed, still-unexecuted occurrence of every
    plan. Idempotent: an occurrence whose month is already settled
    (`_settled_months`) is never executed again, not even by two catch-ups
    running at once (`_settle`). Price failures (offline, bad ticker) skip
    that occurrence — it is retried on the next run."""
    if as_of is None:
        # `dated.today()` rather than the clock directly: this function asks
        # "is this occurrence elapsed?" and the loop below asks "is its day
        # over?", and the two questions read the same today or they disagree.
        as_of = datetime.date.fromisoformat(dated.today())

    created: list[models.Transaction] = []
    skipped: list[dict] = []
    for plan in crud.get_accumulation_plans(db):
        occurrences = plan_occurrences(plan, as_of)
        if not occurrences:
            continue  # not started yet, or no start_date: nothing due
        targets = list(plan.targets)
        if not targets:
            skipped.append(
                {"label": plan.name, "occurrence": None, "reason": "plan has no target"}
            )
            continue
        # A plan that does not say where the money comes from cannot take it
        # from anywhere. Every buy below writes
        # `cash_institution_id=plan.source_institution_id`, so with no source
        # the cash side is addressed to nobody: the register keeps only the
        # entries belonging to the institution it is computing, finds that null
        # matches no id there is, and skips them everywhere — while the
        # positions they create count in full. The plan's spending adds itself
        # to the net worth. Measured: 1000.00 of cash, two elapsed occurrences
        # of 100.00, net worth 1000.00 -> 1200.00 and the cash still 1000.00.
        #
        # `AccumulationPlanWrite` stops a plan like this being SAVED. This is
        # for one saved before that door closed, which the reader's database
        # has none of. Nothing is recorded, so the occurrences stay due and the
        # plan runs in full the moment a source is named: an unnamed source is
        # a question, not a verdict on the schedule.
        #
        # A target with no institution is deliberately NOT refused here. With a
        # source the arithmetic is right to the cent — the position is merely
        # one no situation can photograph — and a plan that is running
        # correctly does not get stopped because the form it was typed into
        # grew stricter afterwards.
        if plan.source_institution_id is None:
            skipped.append(
                {
                    "label": plan.name,
                    "occurrence": None,
                    "reason": (
                        "the plan does not say which account funds it: open it "
                        "and name the source, or its buys spend money no "
                        "account loses"
                    ),
                }
            )
            continue
        # A plan whose own currency is not a currency code says so before
        # anything is priced. The rate step below would only say that no rate
        # is known for it, and a typo would read as a rate nobody published
        # (brief BA, measured at 279acf8: "no exchange rate from EUR to Doll is
        # known for 2026-09-16"). Nothing is recorded, so the plan runs in full
        # once the code is corrected.
        if not schemas.is_currency_code(plan.currency):
            skipped.append(
                {
                    "label": plan.name,
                    "occurrence": None,
                    "reason": (
                        f"'{plan.currency}' is not a currency code: it is recorded on the "
                        "plan, so correcting it there is what lets its buys through on "
                        "the next run"
                    ),
                }
            )
            continue
        done = _settled_months(db, plan.id)
        pending = [occ for occ in occurrences if occ.isoformat()[:7] not in done]
        # An occurrence whose day is not over is not priced yet, for two
        # reasons, and either is enough. The market has no close for it: measured
        # on 2026-09-16 at 10:55 in Milan with the session open, Yahoo's daily
        # history for VWCE.MI ended in a row dated that day at 165.70 — the last
        # minute's trade — and the one for VTI, before New York opened, ended at
        # the 15th, so the occurrence would have been bought at the day before's
        # close and dated then. And the ECB may not have published the day's
        # rate, and a debit written at yesterday's keeps it for good. Nothing is
        # written; the next run after the day ends buys it.
        today = dated.today()
        for occ in pending:
            if occ.isoformat() >= today:
                skipped.append(
                    {
                        "label": plan.name,
                        "occurrence": occ,
                        "reason": (
                            f"{occ.isoformat()} is not over: the market has no close "
                            "for it yet, nor the ECB perhaps a rate; bought on the "
                            "first run after it"
                        ),
                    }
                )
        pending = [occ for occ in pending if occ.isoformat() < today]
        if not pending:
            continue
        # What each target's price is in. A listing's currency does not change,
        # so the price cache's is the answer when anything has priced the
        # symbol; otherwise the market is asked once for all of them. A target
        # whose currency nobody can tell is not priced as if it were the plan's
        # — the plan waits, as it does for a missing price.
        symbols = sorted({t.symbol for t in targets})
        listing = {
            sym: q.get("currency")
            for sym, q in crud.get_cached_prices(db, symbols).items()
            if q.get("currency")
        }
        unknown = [s for s in symbols if s not in listing]
        if unknown:
            listing.update(prices.get_currencies(unknown))
        unknown = [s for s in symbols if s not in listing]
        if unknown:
            skipped.append(
                {
                    "label": plan.name,
                    "occurrence": None,
                    "reason": (
                        f"the currency {', '.join(unknown)} trades in is not known yet, so "
                        "its price cannot be set against the plan's budget (retried on "
                        "the next run)"
                    ),
                }
            )
            continue
        for occ in pending:
            # Price every target on the same day BEFORE buying anything. If one
            # cannot be priced the whole occurrence is skipped and retried next
            # run: a partial fill would spend the budget on the targets that
            # answered and then count the occurrence as done, so the silent one
            # would never be bought — the requested mix would drift for good.
            #
            # A day whose close is not published is one of those failures, and
            # it says so in those words: `prices.NoCloseYet`. It used to arrive
            # here as a NaN price instead, which the allocation read as zero
            # affordable units and this function then reported as a budget too
            # small to buy anything — a message about money, for a day the
            # market had simply not published yet, and one that RECORDED the
            # occurrence as run (below) and never retried it.
            quotes: list[dict] = []
            failure: str | None = None
            for t in targets:
                try:
                    quotes.append(prices.get_price_on(t.symbol, occ))
                except prices.PriceError as exc:
                    failure = f"{t.symbol}: {exc}"
                    break
            if failure is not None:
                skipped.append({"label": plan.name, "occurrence": occ, "reason": failure})
                continue

            # Each price in the plan's currency, at the rate of its own close
            # day — never today's. Without that rate the occurrence waits, and
            # nothing about it is written.
            in_plan: list[float] = []
            for t, quote in zip(targets, quotes):
                converted, _ = fx.convert_on(
                    db, quote["price"], listing[t.symbol], plan.currency, quote["as_of"]
                )
                if converted is None:
                    failure = (
                        f"{t.symbol}: no exchange rate from {listing[t.symbol]} to "
                        f"{plan.currency} is known for {quote['as_of']}"
                    )
                    break
                in_plan.append(converted)
            if failure is not None:
                skipped.append({"label": plan.name, "occurrence": occ, "reason": failure})
                continue

            fractional = (plan.execution or "whole_units") == "fractional"
            # Last time's change is part of this contribution. Without it a
            # target priced above its share of ONE payment is never bought at
            # all, however long the plan runs — which is not how a standing
            # order behaves: the money you set aside and did not spend is still
            # set aside.
            #
            # The carry as it stood when this occurrence was worked out:
            # `_settle` asks for it again under the write lock, and writes
            # nothing if another catch-up has moved it since.
            worked_from = plan.carried_remainder
            carried = 0.0 if fractional else (worked_from or 0.0)
            budget = plan.amount + carried
            quantities = allocate(
                budget,
                [t.weight for t in targets],
                in_plan,
                fractional=fractional,
            )
            # The legs as they will be stored, and what they will debit —
            # worked out by the one function that stores them, at each close's
            # rate, so the carried change is measured against the same figures
            # the register will take out.
            # A leg the schema refuses is a value ALREADY RECORDED that can no
            # longer be written — a plan's own currency, or the one its target's
            # listing was learned to trade in. It skips the whole occurrence,
            # like a price that did not answer: one occurrence is one unit of
            # work, and a mix missing a leg is not the mix that was asked for.
            try:
                legs = [
                    _entry(
                        kind="buy",
                        # The market day the close refers to: the occurrence's
                        # own, or the first ended session after it when that day
                        # never got a close (a weekend, a holiday, a gap in the
                        # feed). Never a day BEFORE the occurrence — see
                        # `prices._close_on`.
                        date=datetime.date.fromisoformat(quote["as_of"]),
                        institution_id=t.institution_id,
                        cash_institution_id=plan.source_institution_id,
                        asset_name=t.asset_name or t.symbol,
                        symbol=t.symbol,
                        # so a position born from this plan is look-through-able
                        isin=t.isin,
                        asset_class="fund_etf",
                        quantity=qty,
                        unit_price=quote["price"],
                        fees=0.0,
                        # No amount: `crud` works it out from the close at that
                        # day's rate, and records the day when a rate was used.
                        currency=plan.currency,
                        price_currency=listing[t.symbol],
                        note=f"Auto-executed from PAC '{plan.name}'",
                    )
                    for t, quote, qty in zip(targets, quotes, quantities)
                    if qty > 0  # its share did not reach one whole unit this time
                ]
                # Worked out HERE, before `_settle` takes the write lock: working
                # a leg out can ask Frankfurter for its close day's rate, and
                # nothing that waits on the network may run with the lock held.
                columns = [crud._transaction_payload(db, data) for data in legs]
            except StoredValueRefused as exc:
                skipped.append({"label": plan.name, "occurrence": occ, "reason": str(exc)})
                continue
            spent = sum(c["amount"] for c in columns)
            # Whatever this contribution could not place waits for the next
            # one. Recorded as a running balance rather than derived from past
            # occurrences, which would break the moment the contribution amount
            # changed.
            #
            # Written by `_settle` together with whichever record settles this
            # occurrence (the buys, or the unfilled record) in one unit of
            # work, so the balance and the reason it changed land together or
            # not at all.
            #
            # It used to be committed only by a buy, because an occurrence that
            # bought nothing stayed due and had to recompute this from scratch
            # next run. That was the safe half of a broken rule: the occurrence
            # came back with a FRESH contribution on top of a carry a later
            # occurrence had already spent. Now that an unfilled occurrence
            # records itself, it never comes back, and the balance it leaves is
            # the one that stands.
            carry = None if fractional else round(budget - spent, 2)

            # This occurrence RAN and bought nothing. It has no transaction to
            # prove it, so it says so itself, together with the carry it just
            # absorbed, in one unit of work, because a contribution recorded as
            # spent into a balance that did not survive is money the plan
            # forgets it was given. It is not retried: the money is in the
            # carry and the next occurrence will spend it. A priced failure,
            # higher up, records nothing and IS retried: it never got this far.
            unfilled: str | None = None
            if not any(q > 0 for q in quantities):
                cheapest = min(in_plan)
                unfilled = (
                    f"the {budget:.2f} {plan.currency} available (contribution "
                    f"{plan.amount:.2f}{f' + {carried:.2f} carried' if carried else ''}) "
                    f"cannot buy a whole unit of any target (cheapest is "
                    f"{cheapest:.2f} {plan.currency})"
                )

            # One occurrence, one unit of work. Pricing every target before
            # buying anything (above) covers a target that cannot be PRICED; it
            # says nothing about one that cannot be WRITTEN. Each leg used to
            # commit for itself, so a failure between them left the earlier legs
            # on disk carrying the occurrence key — which retires the occurrence
            # and strands the rest of the mix for good, the very outcome the
            # price check exists to prevent. The carried remainder lands in the
            # same unit as the buys that produced it, instead of riding on
            # whichever write committed next.
            written = _settle(
                db,
                plan,
                occ.isoformat(),
                worked_from=worked_from,
                carry=carry,
                columns=columns,
                unfilled=unfilled,
            )
            if written is None:
                # Another catch-up settled this occurrence, or moved the carry
                # it was worked out from, while this one was asking Yahoo. That
                # one reports what it wrote; whatever it could not settle comes
                # back at the next start, like a price that did not answer.
                continue
            if unfilled is not None:
                skipped.append({"label": plan.name, "occurrence": occ, "reason": unfilled})
                continue
            created.extend(written)

            # A target that got nothing is worth saying out loud: left silent it
            # looks like the plan is running fine while one fund is never
            # actually bought.
            starved = [
                f"{t.symbol} ({p:.2f} > its share of {budget:.2f} {plan.currency})"
                for t, p, n in zip(targets, in_plan, quantities)
                if n <= 0
            ]
            if starved:
                skipped.append(
                    {
                        "label": plan.name,
                        "occurrence": occ,
                        "reason": (
                            "bought nothing for " + ", ".join(starved)
                            + ": raise the contribution or its weight"
                        ),
                    }
                )
    return {"created": created, "skipped": skipped}


def _settle(
    db: Session,
    plan: models.AccumulationPlan,
    occurrence: str,
    *,
    worked_from: float | None,
    carry: float | None,
    columns: list[dict],
    unfilled: str | None,
) -> list[models.Transaction] | None:
    """Write what one occurrence came to, or nothing if it is no longer this
    catch-up's to write. What it came to is the buys (`columns`, already worked
    out) or, when it bought nothing, the record saying so (`unfilled`, its
    reason), with the carry it leaves (None for a fractional plan, which keeps
    none). Returns the buys written, [] for an unfilled occurrence, or None
    when nothing was written.

    Two catch-ups run at once (two tabs, or React's StrictMode on the
    development server), and everything this one worked from was read before
    it asked Yahoo for the close. So both questions that decide the write are
    asked again here, with SQLite's write lock held (`sole_writer`), where no
    other catch-up can change the answer before this one commits:

    - Is the occurrence still unsettled, asked of its month as the catch-up
      asks it (`_settled_months`)? Two catch-ups both wrote its buys
      (measured 2026-09-30: twice, 10 trials of 10). Its buys and its unfilled
      record live in two tables, which is why a unique index on the buys could
      not close this: refused on one occurrence, the second catch-up went on
      and recorded the NEXT one unfilled while the first had bought it, and
      a month later the plan bought a unit with money it had never been given.
    - Is the carry still the one this occurrence was worked out from? What it
      buys depends on it, and the other catch-up moves it by settling an
      earlier occurrence, one this catch-up skipped because Yahoo did not
      answer it. An edit of the plan's amount or fill model moves it too
      (`crud.update_accumulation_plan`); the occurrence then waits for the
      next start instead of being bought from the plan as it was.

    Either answer changed means somebody else is settling this plan, and the
    occurrence is left to them, or to the next start. Nothing in here reaches
    the network: the buys' columns arrive worked out."""
    with sole_writer(db):
        stored = db.scalar(
            select(models.AccumulationPlan.carried_remainder).where(
                models.AccumulationPlan.id == plan.id
            )
        )
        if stored != worked_from or occurrence[:7] in _settled_months(db, plan.id):
            return None
        if carry is not None:
            plan.carried_remainder = carry
        if unfilled is not None:
            crud.record_unfilled_occurrence(db, plan.id, occurrence, unfilled)
            return []
        return [
            crud.store_transaction(
                db, c, plan_id=plan.id, plan_occurrence=occurrence, estimated=True
            )
            for c in columns
        ]


# What Yahoo last answered about a ticker's dividend history, and on which of
# the reader's days: one row per ticker in `settings`, the shape of
# `fx._ASKED_FOR_NEWER` (a key per thing asked about, read before asking,
# written as one statement). It keeps the ANSWER, not only a stamp, because the
# later catch-ups of the same day need it and must not ask again for it: a
# dividend whose write waited for its rate, a holding entered in the
# afternoon, the same fund at a second account.
#
# {"on": day, "since": day or null, "dividends": [...], "last": day or null}.
# `since` is how far back the kept history reaches: null for the whole
# history, which is asked the first time a ticker is followed; after that,
# each day a window reaching back to the latest situations that follow it,
# because the whole history is every daily price the ticker ever had (brief
# AF, 2026-10-05). Each day's window is MERGED into what was kept (brief AZ):
# the events before the window stay, every event the window reaches is the
# window's, so the history keeps what an older situation, a dividend whose
# window straddles a situation, and the stretches between situations need,
# with no wider request a day. A ticker whose kept history does not reach a
# year before its earliest situation is asked once from there.
# `last` is the latest dividend Yahoo has listed, carried from answer to
# answer. It is what a holding's line shows. A row brief X wrote has neither
# key: it holds the whole history, and its latest dividend is its last.
#
# So `settings` holds a cache as well as configuration. Not a table of its own
# like `price_cache`: that would be a migration on the reader's real money for
# a small feature, and every read of `settings` is by key, so nothing that
# reads configuration ever meets these rows.
_DIVIDENDS_ASKED = "dividends_asked:{symbol}"


def _parse_kept(value: str | None) -> dict | None:
    """A kept answer as stored, or None when there is none or it cannot be
    read. One that cannot be read counts as never asked: the next answer
    replaces it, and it never breaks a route the app calls at every start."""
    try:
        stored = json.loads(value) if value else None
        if not isinstance(stored, dict) or not isinstance(stored.get("dividends"), list):
            return None
        datetime.date.fromisoformat(stored["on"])
        if stored.get("since") is not None:
            datetime.date.fromisoformat(stored["since"])
    except (ValueError, KeyError, TypeError):
        return None
    return stored


def _kept(db: Session, symbol: str) -> dict | None:
    """The answer last kept about `symbol`, whatever its day.

    Read as a column rather than as a `Setting` object, so the session holds
    nothing the statement in `_keep_answer` could leave stale."""
    return _parse_kept(
        db.scalar(
            select(models.Setting.value).where(
                models.Setting.key == _DIVIDENDS_ASKED.format(symbol=symbol)
            )
        )
    )


def _last_known(kept: dict | None) -> str | None:
    """The latest dividend a kept answer knows of, up to its own day."""
    if kept is None:
        return None
    if "last" in kept:
        return kept["last"] if isinstance(kept["last"], str) else None
    days = (d.get("date") for d in kept["dividends"] if isinstance(d, dict))
    return max((d for d in days if isinstance(d, str) and d <= kept["on"]), default=None)


def last_dividends(db: Session, symbols) -> dict[str, str]:
    """{symbol: the latest dividend Yahoo has listed for it}, from the answers
    the catch-up keeps: what a holding's line shows when its own history
    decides its dividends. A symbol never asked about, or whose history lists
    none, is absent. One read for all of them."""
    keys = {_DIVIDENDS_ASKED.format(symbol=s): s for s in symbols if s}
    if not keys:
        return {}
    rows = db.execute(
        select(models.Setting.key, models.Setting.value).where(models.Setting.key.in_(list(keys)))
    )
    found = {keys[key]: _last_known(_parse_kept(value)) for key, value in rows}
    return {symbol: last for symbol, last in found.items() if last}


def _keep_answer(
    db: Session, symbol: str, today: str, answer: list[dict], since: str | None, last: str | None
) -> None:
    """Keep `answer` as the day's, whatever the row held before.

    One statement that says so, `INSERT ... ON CONFLICT DO UPDATE`: two
    catch-ups can run at once (two tabs, or React's StrictMode on the
    development server) and both find no answer, and a read-then-insert would
    make the second die on the key, as the rate store's did until dd8370b.
    Committed at once, so the answer outlives anything that fails after it."""
    key = _DIVIDENDS_ASKED.format(symbol=symbol)
    value = json.dumps(
        {"on": today, "since": since, "dividends": answer, "last": last}, separators=(",", ":")
    )
    upsert = sqlite_insert(models.Setting).values(key=key, value=value)
    db.execute(upsert.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    commit(db)


def _dividend_history(
    db: Session,
    symbol: str,
    today: str,
    need: str,
    reach: str,
    answers: dict[str, prices.DividendWindow | prices.PriceError],
) -> prices.DividendWindow:
    """Every dividend Yahoo has listed for `symbol` since `reach`, or longer,
    asked for until Yahoo answers and then not again that day.

    `need` is the latest situation among the accounts that follow the ticker
    (the earliest of those), which is what each day's window reaches back to;
    `reach` is how far back the kept history must go: a year before the
    earliest situation that follows it, so a dividend whose window straddles
    that situation, and every stretch after it, can be read (brief AZ).

    Today's kept history when it reaches `reach`; otherwise Yahoo is asked,
    and what it answers is merged into the kept history (`_merge`) and kept
    for the rest of the day. The whole history the first time a ticker is
    followed, which is what tells its line when it last paid; after that a
    window from `need`, or from the day of the answer before when that is
    earlier; and once, from `reach`, when the kept history does not reach it
    (one kept before brief AZ, or a situation entered with an older date).
    Only an answer is kept: a window nobody answered (which yfinance reports
    without raising) and a `PriceError` (the fetch failed) are not, so the
    next catch-up asks again. Within one catch-up the outcome, whichever it is,
    is reused from `answers`, so a fund held at two accounts is asked about
    once."""
    if symbol not in answers:
        kept = _kept(db, symbol)
        held = None if kept is None else kept.get("since")
        reaches = kept is not None and (held is None or held <= reach)
        if kept is not None and kept["on"] == today and reaches:
            # Yahoo's answer of today, as it was kept.
            answer = prices.DividendWindow(answered=True, dividends=kept["dividends"])
        else:
            if kept is None:
                since = datetime.date.min
            else:
                start = need if reaches else reach
                since = min(datetime.date.fromisoformat(start), datetime.date.fromisoformat(kept["on"]))
            try:
                fetched = prices.get_dividends_since(symbol, since)
            except prices.PriceError as exc:
                answers[symbol] = exc
                raise
            answer = fetched
            if fetched.answered:
                merged = _merge(kept, fetched, since)
                seen = [d["date"] for d in merged if d["date"] <= today]
                last = max([*seen, *filter(None, [_last_known(kept)])], default=None)
                # How far back the merged history now reaches: the whole
                # history once either side was, else the earlier of the two.
                kept_from = None if since == datetime.date.min or held is None else min(since.isoformat(), held)
                _keep_answer(db, symbol, today, merged, kept_from, last)
                answer = prices.DividendWindow(answered=True, dividends=merged)
        answers[symbol] = answer
    outcome = answers[symbol]
    if isinstance(outcome, prices.PriceError):
        raise outcome
    return outcome


def _merge(kept: dict | None, fetched: prices.DividendWindow, since: datetime.date) -> list[dict]:
    """The kept history with Yahoo's new answer in its place: every event the
    answer reaches (strictly after `since`, the cut `get_dividends_since`
    makes) is the answer's, so a dividend Yahoo corrected or withdrew is as it
    says now; every event before it stays as kept."""
    lo = since.isoformat()
    before = [] if kept is None else [
        d for d in kept["dividends"] if isinstance(d, dict) and isinstance(d.get("date"), str) and d["date"] <= lo
    ]
    return sorted([*before, *fetched.dividends], key=lambda d: d["date"])


def _follows_dividends(h: models.Holding) -> bool:
    """Whether the catch-up asks Yahoo about this holding's dividends.

    A stated policy is obeyed: Distributing is asked, anything else is not (an
    accumulating fund reinvests what it earns). An empty one no longer means
    "never": the holding's own dividend history decides. A share has no policy
    to choose, it pays or it does not, and before this rule a share with none
    had whatever it paid recorded nowhere, the cash it credits included. The
    class cannot tell a share from
    a fund typed by hand ("Stocks & ETF" files both as `equity`), so a fund
    with no policy follows its history too. Crypto pays none: not asked, which
    would be a request a day for nothing."""
    if not h.symbol or h.quantity is None:
        return False
    if h.distribution_policy:
        return h.distribution_policy == "dist"
    return (h.asset_class or "") != "crypto"


# How every dividend the catch-up records starts its note: where the row came
# from, which no edit makes false. `crud` keeps the string, since it tells the
# catch-up's own rows from the reader's when it gives them their ex-date
# (brief AZ); the ledger form and the chat's card used to read it to keep such
# a row on its ex-date, which its own column now does.
AUTO_RECORDED = crud.AUTO_DIVIDEND_NOTE


def execute_dividends(db: Session, as_of: datetime.date | None = None) -> dict:
    """Record a `dividend` transaction for every ex-date of every position that
    follows its dividends (`_follows_dividends`), from its snapshot anchor
    onward. Idempotent per (institution, symbol, ex-date), two catch-ups at
    once included (`_record_dividend`). Amounts are GROSS (Yahoo has no
    withholding tax) and marked estimated — correct them with the net credit.
    Positions known only from the ledger are skipped: the dist/acc policy
    lives on snapshot holdings. Yahoo's answer about a ticker's history is
    kept for the rest of the day it was given (`_dividend_history`).

    A dividend the reader has entered themselves is not recorded beside it
    (brief AZ): their entry dated in the dividend's window is recognised as it
    when the pairing is unique both ways (`dividend_pairs`), and every other
    case is asked, as is an entry beside the app's estimate of the same
    dividend. Every stretch between situations is read, each dividend with the
    units of the stretch its ex-date falls in, so one the catch-up never met
    is recorded too; and a dividend whose window holds the account's latest
    balance, with no payment date known, is asked about: whether its money was
    already in that balance. A listing whose payment days Yahoo names has its
    dividends dated on them, and one still ahead waits for its day
    (`_payment_day`). Returns what was recorded, skipped, recognised, asked
    and waited for."""
    # The reader's day, read once: it says which ex-dates are due (`as_of`,
    # unless the caller names another day) and whether Yahoo has already
    # answered about a ticker today.
    today = dated.today()
    if as_of is None:
        # `dated.today()` rather than the clock directly: this function asks
        # "is this occurrence elapsed?" and the loop below asks "is its day
        # over?", and the two questions read the same today or they disagree.
        as_of = datetime.date.fromisoformat(today)

    created: list[models.Transaction] = []
    skipped: list[dict] = []
    recognised: list[dict] = []
    questions: list[dict] = []
    waiting: list[dict] = []
    answers: dict[str, prices.DividendWindow | prices.PriceError] = {}
    # What Yahoo's quote said of a listing's payment day in this catch-up, so
    # one held at two accounts is asked once, and the dividends whose day it
    # taught that is still ahead, which are said once (`_payment_day`).
    payment_answers: dict[str, prices.PaymentDay | None] = {}
    learnt: dict[str, set[str]] = {}
    all_txs = list(db.scalars(select(models.Transaction)))
    names = {i.id: i.name for i in db.scalars(select(models.Institution))}
    # Every situation of every account up to `as_of`, oldest first: each
    # dividend's units come from the stretch its ex-date falls in (brief AZ).
    # One cut for one question: a snapshot dated after the day being caught up
    # to would decide which units are held on days it had not been taken yet.
    situations = _situations(db, as_of)
    # The tickers each account follows, in any of its situations, with the
    # latest holding that follows each (its name and class go on the row).
    followed: dict[int, dict[str, models.Holding]] = {}
    for inst_id, snaps in situations.items():
        for snap in snaps:
            for h in snap.holdings:
                if _follows_dividends(h):
                    followed.setdefault(inst_id, {})[h.symbol] = h
    # What each listing trades in, when anything has priced it. A dividend per
    # share is in that currency unless Yahoo names another; where it is not
    # known the holding's own currency stands in, the rule a position is valued
    # by.
    listing = {
        sym: q["currency"]
        for sym, q in crud.get_cached_prices(
            db, sorted({sym for symbols in followed.values() for sym in symbols})
        ).items()
        if q.get("currency")
    }
    # How far back each ticker's answer must reach: each day's window, to the
    # latest situation of the accounts that follow it (the earliest of those),
    # and the kept history, to a year before their earliest situation.
    need: dict[str, str] = {}
    reach: dict[str, str] = {}
    for inst_id, symbols in followed.items():
        latest, first = situations[inst_id][-1].date, situations[inst_id][0].date
        year_before = (datetime.date.fromisoformat(first) - _HISTORY_BEFORE_FIRST).isoformat()
        for sym in symbols:
            need[sym] = min(need.get(sym, latest), latest)
            reach[sym] = min(reach.get(sym, year_before), year_before)
    balances = crud.get_latest_balance_days(db, today)
    for inst_id, symbols in followed.items():
        snaps = situations[inst_id]
        balance = balances.get(inst_id)
        for symbol, latest_holding in symbols.items():
            try:
                window = _dividend_history(db, symbol, today, need[symbol], reach[symbol], answers)
            except prices.PriceError as exc:
                skipped.append({"label": symbol, "occurrence": None, "reason": str(exc)})
                continue
            if not window.answered:
                # Nobody answered. Not kept, so the next catch-up asks again,
                # and said nowhere, as before: the next start retries by itself.
                continue
            # A row this catch-up wrote, still on the ex-date it was written on
            # but keeping none (one the reader corrected before rows kept their
            # ex-date), takes it now, before the reader can move it (brief AZ).
            listed = list(window.dividends)
            # Where each dividend's money can arrive, which is where the
            # reader's entry of it can be dated (`dividend_pairs.windows`).
            spans = dividend_pairs.windows(d["date"] for d in listed)
            crud.adopt_ex_dates(db, inst_id, symbol, _adoptable(db, inst_id, symbol, spans))
            due = _due(snaps, [t for t in all_txs if t.institution_id == inst_id and t.symbol == symbol],
                       symbol, listed, spans, as_of)
            # The reader's own entries of these dividends: one recognised when
            # the pairing is unique both ways, every other case asked, and a
            # dividend some entry could be is not recorded meanwhile.
            pairing, ledger = _pairing(db, inst_id, symbol, due, spans)
            for tx_id, x in pairing.recognised:
                seen = _recognise(db, inst_id, symbol, tx_id, x, due, spans)
                if seen is not None:
                    recognised.append(_recognition(inst_id, names, symbol, x, seen))
            questions.extend(
                _questions(pairing, ledger, due, inst_id, names, latest_holding, listed, listing)
            )
            # Recorded (by its ex-date wherever its row is dated, brief AZ), or
            # deleted by the reader, which stays deleted (brief AO).
            done = crud.get_dividend_dates_settled(db, inst_id, symbol)
            # The dividends the loop below may record, and what Yahoo has
            # said of their payment days (`_payment_day`).
            pending = [x for x in due if x not in done and x not in pairing.held]
            paid = crud.get_payment_days(db, symbol) if _says_payment_days(symbol) else {}
            for x, item in due.items():
                # The holding of the stretch the ex-date falls in: its name,
                # class and currency go on the row.
                d, shares, h = item.event, item.units, item.holding
                ex_date = datetime.date.fromisoformat(x)
                if x in done or x in pairing.held:
                    continue
                end = spans[x][1]
                if item.first and not (balance is not None and x <= balance < end):
                    # Before the account's first situation, the units are the
                    # first situation's, which nothing says were held then:
                    # such a dividend is recorded only when the reader answers
                    # the question below, which says so. With the latest
                    # balance outside its window it would count nowhere, or
                    # count on that guess (the ledger before the first
                    # situation is unread, brief AW).
                    continue
                if "unreadable" in d:
                    # Said on its own ex-date, and asked again at every start
                    # until the reader records that dividend by hand: any row
                    # on the day counts as done, theirs included.
                    skipped.append(
                        {
                            "label": h.symbol,
                            "occurrence": ex_date,
                            "reason": (
                                f"Yahoo lists a dividend on {d['date']} that cannot be read, "
                                f"because {d['unreadable']}: enter it from your statement"
                            ),
                        }
                    )
                    continue
                # The day its money is counted from (brief AZ): the day Yahoo
                # says it is paid, for a listing it says that of (the reader's
                # D3); otherwise its ex-date, unless the account's latest
                # balance falls in the dividend's window, where only the reader
                # knows whether the money was already in it, and the app asks.
                said = ""
                credited = ex_date
                paid_on = _payment_day(db, symbol, x, pending, paid, payment_answers, learnt, today)
                if paid_on and paid_on > today and not item.first:
                    # Not paid yet: recorded on the day it is, and said once,
                    # by the catch-up that learnt the day.
                    if x in learnt.get(symbol, set()):
                        waiting.append(_waiting(inst_id, names, symbol, item, listing, paid_on))
                    continue
                if paid_on and not item.first:
                    credited = datetime.date.fromisoformat(paid_on)
                    said = ", on its payment date as Yahoo lists it"
                elif balance is not None and x <= balance < end:
                    told = crud.get_balance_answer(db, inst_id, symbol, x)
                    if told == ("after", balance) and paid_on and paid_on > balance:
                        if paid_on > today:
                            continue
                        credited = datetime.date.fromisoformat(paid_on)
                        said = ", on its payment date as Yahoo lists it"
                    elif told == ("after", balance):
                        credited = datetime.date.fromisoformat(balance) + datetime.timedelta(days=1)
                        said = f", dated the day after your balance of {balance}, which did not hold it"
                    elif told != ("in", balance):
                        questions.append(_balance_question(inst_id, names, symbol, item, listing, balance))
                        continue
                if item.first:
                    said += f", for the {shares:g} units of your first situation, of {item.situation}"
                # The currency Yahoo names for this dividend, which no real
                # answer measured did; then the listing's.
                paid_in = d.get("currency") or listing.get(h.symbol) or h.currency
                # Credited in the currency the account keeps its cash in: the
                # anchor in force on the ex-date, or the account's first one
                # when the dividend predates them all (`crud.account_currency_on`,
                # the rule every form proposes a currency by). An account with
                # no anchor has no balance to be wrong against, and the
                # dividend is recorded in the currency it was paid in.
                held_in = crud.account_currency_on(db, inst_id, d["date"])
                # Converted at the ex-date's rate by `crud`, which records that
                # day as `fx_as_of` beside `estimated` — the dividend is gross
                # AND converted, and the credit from the statement corrects both.
                #
                # The payload is built INSIDE the try, and that is the whole of
                # the second `except`: three of its fields are read off stored
                # rows — the anchor's currency, the holding's, and what the
                # price cache learned the listing trades in — so a row written
                # before a rule existed raises here, on a route the app calls at
                # every start. See `StoredValueRefused`.
                try:
                    data = _entry(
                        kind="dividend",
                        date=ex_date,
                        institution_id=inst_id,
                        asset_name=h.asset_name,
                        symbol=h.symbol,
                        asset_class=h.asset_class,
                        quantity=shares,
                        unit_price=d["dps"],
                        fees=0.0,
                        currency=held_in or paid_in,
                        price_currency=paid_in,
                        # Where the row came from, and nothing an edit can make
                        # false: the reader corrects the amount with the broker's
                        # net credit, and `estimated`, not this note, says whether
                        # that has happened. It used to say "gross", which stayed
                        # on the row after the correction. The unit is the
                        # listing's: a figure per share without one is five pence
                        # or five pounds.
                        note=f"{AUTO_RECORDED}: a dividend of {d['dps']} {paid_in} per share{said}",
                    )
                    # Worked out before `_record_dividend` takes the write
                    # lock: for a dividend paid in another currency this is
                    # where Frankfurter is asked for the ex-date's rate
                    # (measured 2026-09-30), and nothing that waits on the
                    # network may run with the lock held.
                    columns = crud._transaction_payload(db, data)
                except (crud.LedgerRateUnknown, StoredValueRefused) as exc:
                    skipped.append({"label": h.symbol, "occurrence": ex_date, "reason": str(exc)})
                    continue
                # Worked out on its ex-date, as every dividend is (across two
                # currencies at that day's rate, which `fx_as_of` keeps), and
                # dated the day its money is counted from, the day the cash
                # register reads.
                columns["date"] = credited.isoformat()
                written = _record_dividend(db, inst_id, h.symbol, x, columns, spans[x])
                if written is not None:
                    created.append(written)
    return {
        "created": created,
        "skipped": skipped,
        "recognised": recognised,
        "questions": questions,
        "waiting": waiting,
    }


def _record_dividend(
    db: Session,
    institution_id: int,
    symbol: str,
    ex_date: str,
    columns: dict,
    span: tuple[str, str],
) -> models.Transaction | None:
    """Write one dividend, or nothing if it is already recorded, asked again
    with SQLite's write lock held (`sole_writer`).

    `done` in the caller was read before the payload was worked out, and two
    catch-ups at once both found the ex-date missing there and both wrote it:
    brief X measured it, 10 trials of 10, with both held between the question
    and the write. Asked here, the second finds the first one's row and writes
    nothing; the first reports it. Any dividend row on that account, ticker and
    ex-date counts, the reader's own included, and so does one the reader
    deleted from that day, exactly as `done` does.

    The row keeps its ex-date (brief AZ), so the reader can move it to the day
    its money arrived and the catch-up still finds it by that day. And an entry
    of the reader's that appeared in the dividend's window since the pairing
    was read stops the write too: the next catch-up pairs it."""
    with sole_writer(db):
        if ex_date in crud.get_dividend_dates_settled(db, institution_id, symbol):
            return None
        apart = crud.get_dividends_apart(db, institution_id, symbol)
        _, unkeyed = _dividend_rows(db, institution_id, symbol)
        if any(
            dividend_pairs.inside(t.date, span) and (t.id, ex_date) not in apart for t in unkeyed
        ):
            return None
        return crud.store_transaction(db, columns, estimated=True, ex_date=ex_date)


# How far before an account's earliest situation the kept history reaches: a
# dividend paid after that situation can have its ex-date up to a year before
# it (a yearly payer's ex-dates were measured 357 to 364 days apart).
_HISTORY_BEFORE_FIRST = datetime.timedelta(days=366)


def _situations(db: Session, as_of: datetime.date) -> dict[int, list[models.Snapshot]]:
    """{institution id: its situations dated up to `as_of`, oldest first}."""
    out: dict[int, list[models.Snapshot]] = {}
    for snap in db.scalars(
        select(models.Snapshot)
        .where(models.Snapshot.date <= as_of.isoformat())
        .order_by(models.Snapshot.institution_id, models.Snapshot.date, models.Snapshot.id)
    ):
        out.setdefault(snap.institution_id, []).append(snap)
    return out


def _following(snap: models.Snapshot, symbol: str) -> models.Holding | None:
    """The holding of `symbol` in this situation, when it follows dividends."""
    return next((h for h in snap.holdings if h.symbol == symbol and _follows_dividends(h)), None)


@dataclass(frozen=True)
class _Due:
    """A dividend of one position the catch-up would record: Yahoo's event,
    the units held strictly before its ex-date, the holding that follows it in
    the situation those units come from and that situation's day, and whether
    it is the account's first situation standing in for a day before it."""

    event: dict
    units: float
    holding: models.Holding
    situation: str
    first: bool = False


def _due(
    snaps: list[models.Snapshot],
    entries: list[models.Transaction],
    symbol: str,
    listed: list[dict],
    spans: dict[str, tuple[str, str]],
    as_of: datetime.date,
) -> dict[str, _Due]:
    """Every dividend Yahoo lists for `symbol`, up to `as_of`, that this
    account held units of, each with the units of the stretch its ex-date falls
    in: the situation strictly before it, and the ledger since (`entries`, the
    position's rows). Every stretch, not only the one after the latest
    situation (brief AZ): a dividend the catch-up never met inside an earlier
    one was never recorded at all (measured at `eaa89fc`).

    An ex-date before the account's first situation counts only when its
    window reaches past that situation, so its money can have come after, and
    then with the first situation's units, which nothing else says."""
    first = snaps[0]
    out: dict[str, _Due] = {}
    for d in listed:
        x = d["date"]
        if x > as_of.isoformat():
            continue
        before = [s for s in snaps if s.date < x]
        if before:
            snap = before[-1]
            h = _following(snap, symbol)
            if h is None:
                continue
            # Units held STRICTLY before the ex-date: you have to own the
            # shares before it. `until` is exclusive, and it is the whole
            # reason that boundary is a parameter rather than a loop each
            # caller writes for itself.
            units = replay(dated.events_after(snap, entries), start_qty=h.quantity, until=x).quantity
            item = _Due(d, units, h, snap.date)
        else:
            h = _following(first, symbol)
            if h is None or spans[x][1] <= first.date:
                continue
            item = _Due(d, h.quantity, h, first.date, first=True)
        if item.units > 0:
            out[x] = item
    return out


def _says_payment_days(symbol: str) -> bool:
    """Whether Yahoo's quote can name this listing's payment day: one with no
    exchange suffix. Measured 2026-10-16 on 40 public tickers: 12 of the 12
    such that were shares or ADRs named one (the 2 US funds did not); of the
    26 with a suffix, the same US shares in Frankfurt among them, only one
    named any, a year stale."""
    return "." not in symbol


def _payment_day(
    db: Session,
    symbol: str,
    x: str,
    pending: list[str],
    paid: dict[str, str],
    payment_answers: dict[str, prices.PaymentDay | None],
    learnt: dict[str, set[str]],
    today: str,
) -> str | None:
    """The day Yahoo says the dividend of `x` is paid, or None (brief AZ, the
    reader's D3).

    Asked of Yahoo's quote once for each dividend of a listing that says it
    (`_says_payment_days`): the first time the catch-up is about to record one
    not asked about, at most once a catch-up for the listing, and the answer
    kept for every dividend still to record (`paid`, `crud.remember_payment_
    day`): the day it names for the one whose ex-date it names, "" for the
    others. A day before its ex-date is not that dividend's (a Swiss share's
    was a year stale) and is kept as "". Nobody answering keeps nothing, and
    the dividend is recorded as if no day were known. The days still ahead
    that this answer taught go in `learnt`, to be said once."""
    if not _says_payment_days(symbol):
        return None
    if x not in paid and symbol not in payment_answers:
        told = prices.get_payment_day(symbol)
        payment_answers[symbol] = told
        if told is not None:
            for y in pending:
                if y in paid:
                    continue
                named = told.paid_on if told.ex_date == y and told.paid_on and told.paid_on >= y else ""
                crud.remember_payment_day(db, symbol, y, named)
                paid[y] = named
                if named and named > today:
                    learnt.setdefault(symbol, set()).add(y)
    return paid.get(x) or None


def _waiting(
    institution_id: int,
    names: dict[int, str],
    symbol: str,
    item: _Due,
    listing: dict[str, str],
    paid_on: str,
) -> dict:
    """A dividend whose payment day Yahoo names and is still ahead: recorded
    on that day, and said once meanwhile, so it is not taken for one missed."""
    d = item.event
    return {
        "institution_id": institution_id,
        "institution_name": names.get(institution_id, ""),
        "symbol": symbol,
        "ex_date": d["date"],
        "paid_on": paid_on,
        "dps": d.get("dps"),
        "currency": d.get("currency") or listing.get(symbol) or item.holding.currency,
    }


def _balance_question(
    institution_id: int,
    names: dict[int, str],
    symbol: str,
    item: _Due,
    listing: dict[str, str],
    balance: str,
) -> dict:
    """The question a dividend asks when the account's latest balance falls
    in its window and no payment date is known (brief AZ): whether its money
    was already in that balance."""
    d = item.event
    return {
        "kind": "in_balance",
        "institution_id": institution_id,
        "institution_name": names.get(institution_id, ""),
        "symbol": symbol,
        "asset_name": item.holding.asset_name,
        "dividends": [{
            "ex_date": d["date"],
            "dps": d.get("dps"),
            "currency": d.get("currency") or listing.get(symbol) or item.holding.currency,
            "units": item.units,
            "estimate": None,
        }],
        "entries": [],
        "balance_date": balance,
        "first_situation": item.situation if item.first else None,
    }


def _dividend_rows(
    db: Session, institution_id: int, symbol: str
) -> tuple[dict[str, list[models.Transaction]], list[models.Transaction]]:
    """This position's dividend rows, read now: by the ex-date each keeps, and
    those that keep none (the reader's own entries, and any older row of the
    app's not given one yet).

    Read from the database, not from the session's copies: under the write
    lock this is the question asked again, and a copy loaded before another
    catch-up gave a row its ex-date still says it has none (found by the test
    of two catch-ups at once: both reported the same entry recognised), as
    brief Y found of a plan's carry."""
    keyed: dict[str, list[models.Transaction]] = {}
    unkeyed: list[models.Transaction] = []
    for t in db.scalars(
        select(models.Transaction)
        .where(
            models.Transaction.kind == "dividend",
            models.Transaction.institution_id == institution_id,
            models.Transaction.symbol == symbol,
        )
        .order_by(models.Transaction.date, models.Transaction.id)
        .execution_options(populate_existing=True)
    ):
        if t.ex_date:
            keyed.setdefault(t.ex_date, []).append(t)
        else:
            unkeyed.append(t)
    return keyed, unkeyed


def _adoptable(
    db: Session, institution_id: int, symbol: str, spans: dict[str, tuple[str, str]]
) -> set[str]:
    """The ex-dates whose dividend the catch-up's own row can take as its key
    (`crud.adopt_ex_dates`): that row is dated on the ex-date, keeps none, and
    is the only row keeping none in the dividend's window. Beside an entry of
    the reader's it is not taken alone: the two may be one dividend counted
    twice, which the pairing then asks about rather than settles in silence."""
    _, unkeyed = _dividend_rows(db, institution_id, symbol)
    days = set()
    for x, span in spans.items():
        inside = [t for t in unkeyed if dividend_pairs.inside(t.date, span)]
        if len(inside) == 1 and inside[0].date == x and (inside[0].note or "").startswith(AUTO_RECORDED):
            days.add(x)
    return days


@dataclass(frozen=True)
class _Ledger:
    """What a pairing was read from, for the questions it raises."""

    keyed: dict[str, list[models.Transaction]]
    unkeyed: list[models.Transaction]


def _pairing(
    db: Session,
    institution_id: int,
    symbol: str,
    due: dict[str, _Due],
    spans: dict[str, tuple[str, str]],
) -> tuple[dividend_pairs.Pairing, _Ledger]:
    """The reader's entries of this position paired with the dividends they
    could be (`dividend_pairs.pair`), read from the ledger as it is now: the
    dividends due and not recorded, and those due that only the app's
    still-estimated row holds, which an entry beside it doubles."""
    keyed, unkeyed = _dividend_rows(db, institution_id, symbol)
    deleted = crud.get_dividend_dates_deleted(db, institution_id, symbol)
    dividends = [dividend_pairs.Dividend(x) for x in due if x not in keyed and x not in deleted]
    for x, rows in keyed.items():
        if x in due and x not in deleted and len(rows) == 1 and rows[0].estimated:
            dividends.append(dividend_pairs.Dividend(x, estimate_id=rows[0].id))
    pairing = dividend_pairs.pair(
        dividends,
        [(t.id, t.date) for t in unkeyed],
        spans,
        crud.get_dividends_apart(db, institution_id, symbol),
    )
    return pairing, _Ledger(keyed, unkeyed)


def _recognise(
    db: Session,
    institution_id: int,
    symbol: str,
    tx_id: int,
    ex_date: str,
    due: dict[str, _Due],
    spans: dict[str, tuple[str, str]],
) -> models.Transaction | None:
    """Give the reader's entry the ex-date of the dividend it is, asked again
    with the write lock held: the pairing read again, and written only while
    it still pairs those two alone. The entry, or None."""
    with sole_writer(db):
        pairing, _ = _pairing(db, institution_id, symbol, due, spans)
        if (tx_id, ex_date) not in pairing.recognised:
            return None
        tx = db.get(models.Transaction, tx_id)
        tx.ex_date = ex_date
    return tx


def _entry_view(t: models.Transaction) -> dict:
    """An entry as the banner names it."""
    return {
        "id": t.id,
        "date": t.date,
        "amount": t.amount,
        "currency": t.currency,
        "estimated": t.estimated,
    }


def _recognition(
    institution_id: int, names: dict[int, str], symbol: str, ex_date: str, t: models.Transaction
) -> dict:
    return {
        "institution_id": institution_id,
        "institution_name": names.get(institution_id, ""),
        "symbol": symbol,
        "ex_date": ex_date,
        "entry": _entry_view(t),
    }


def _questions(
    pairing: dividend_pairs.Pairing,
    ledger: _Ledger,
    due: dict[str, _Due],
    institution_id: int,
    names: dict[int, str],
    h: models.Holding,
    listed: list[dict],
    listing: dict[str, str],
) -> list[dict]:
    """What the pairing could not settle, as the questions the banner asks:
    a double (an entry beside the app's estimate of the same dividend), a
    dividend two entries could be, an entry two dividends could be."""
    events = {d["date"]: d for d in listed}
    rows = {t.id: t for t in ledger.unkeyed}

    def dividend(x: str) -> dict:
        estimate = next((t for t in ledger.keyed.get(x, []) if t.estimated), None)
        event = events.get(x, {})
        return {
            "ex_date": x,
            "dps": event.get("dps"),
            "currency": event.get("currency") or listing.get(h.symbol) or h.currency,
            "units": due[x].units if x in due else (estimate.quantity if estimate else None),
            "estimate": _entry_view(estimate) if estimate is not None else None,
        }

    def asked(kind: str, xs: list[str], ids: list[int]) -> dict:
        return {
            "kind": kind,
            "institution_id": institution_id,
            "institution_name": names.get(institution_id, ""),
            "symbol": h.symbol,
            "asset_name": h.asset_name,
            "dividends": [dividend(x) for x in xs],
            "entries": [_entry_view(rows[i]) for i in ids],
        }

    out = [asked("same_dividend", [x], [tx_id]) for tx_id, x in pairing.doubles]
    out += [asked("which_entry", [x], ids) for x, ids in pairing.by_dividend]
    out += [asked("which_dividend", xs, [tx_id]) for tx_id, xs in pairing.by_entry]
    return out


class AnswerRefused(ValueError):
    """An answer to a question about a dividend that no longer stands, in the
    sentence the reader sees."""


def answer_dividend(db: Session, answer: schemas.DividendAnswer) -> dict:
    """Write the reader's answer to a question the catch-up asked about a
    dividend (brief AZ), then run the dividend catch-up again, which records
    or asks what follows from it. Every answer is checked against the ledger
    as it is now, so a question answered twice, or after the rows it named
    changed, is refused with a sentence rather than written.

    "link": the entry is the dividend of that ex-date; it takes the ex-date,
    and the app's estimate of the same dividend, if there is one, is deleted
    (its deletion remembered, brief AO). "apart": each entry named is not the
    dividend named beside it, and the two are never paired again.
    "in_balance" and "after_balance": the dividend's money was already in the
    account's latest balance, or came after it; the catch-up then records it
    on its ex-date, or on the day after that balance."""
    institution = db.get(models.Institution, answer.institution_id)
    if institution is None:
        raise AnswerRefused("That account is no longer on record.")
    symbol = answer.symbol
    kept = _kept(db, symbol)
    spans = dividend_pairs.windows(d["date"] for d in (kept["dividends"] if kept else []))

    def entry(tx_id: int) -> models.Transaction:
        # From the database, not the session's copy (see `_dividend_rows`).
        tx = db.get(models.Transaction, tx_id, populate_existing=True)
        if (
            tx is None
            or tx.kind != "dividend"
            or tx.institution_id != institution.id
            or tx.symbol != symbol
            or tx.ex_date is not None
        ):
            raise AnswerRefused(
                f"That entry of {symbol} at {institution.name} is no longer one the question was "
                "about: reload the page to see what is asked now."
            )
        return tx

    def listed(x: str) -> tuple[str, str]:
        if x not in spans:
            raise AnswerRefused(f"Yahoo no longer lists a dividend of {symbol} with ex-date {x}.")
        return spans[x]

    if answer.answer == "link":
        x = answer.ex_date.isoformat()
        span = listed(x)
        with sole_writer(db):
            tx = entry(answer.transaction_id)
            if not dividend_pairs.inside(tx.date, span):
                raise AnswerRefused(
                    f"Your entry of {tx.date} falls outside the days the dividend with ex-date {x} "
                    "can be paid on."
                )
            keyed, _ = _dividend_rows(db, institution.id, symbol)
            if any(not t.estimated for t in keyed.get(x, [])):
                raise AnswerRefused(
                    f"The dividend of {symbol} with ex-date {x} already has an entry of yours."
                )
            tx.ex_date = x
            for t in keyed.get(x, []):
                crud.delete_transaction(db, t.id)
    elif answer.answer in ("in_balance", "after_balance"):
        x = answer.ex_date.isoformat()
        listed(x)
        latest = crud.get_latest_balance_days(db, dated.today()).get(institution.id)
        if latest != answer.balance_date.isoformat():
            raise AnswerRefused(
                f"The balance of {answer.balance_date.isoformat()} is no longer the latest at "
                f"{institution.name}: reload the page to see what is asked now."
            )
        crud.remember_balance_answer(
            db, institution.id, symbol, x, "in" if answer.answer == "in_balance" else "after", latest
        )
    else:
        pairs = []
        for p in answer.pairs:
            listed(p.ex_date.isoformat())
            pairs.append((entry(p.transaction_id).id, p.ex_date.isoformat()))
        crud.remember_apart(db, institution.id, symbol, pairs)
    result = execute_dividends(db)
    return {**result, "accounts": _accounts(db, result["created"])}


# Symbols the day's batch asked about and Yahoo priced nothing for, while it
# priced others or while the market answered: a delisted ticker, one typed
# wrong. Not asked again until the reader's next day, or each page load would
# ask Yahoo about them once more (seen in the browser on a copy of the test
# database, brief AJ). Brief AJ kept them in the process, and every restart
# asked again: measured 2026-10-08, a symbol Yahoo does not know cost the first
# batch of a process 12 requests, and 8 each time after (brief AK). So they are
# kept where the dividend answers are, in `settings`: one row a symbol, its
# value the reader's day it was asked, read only on that day. Every batch that
# comes back deletes the rows of an earlier day as the day's are written, so
# the table holds one day's at most and a symbol no longer held leaves no row
# behind. A batch that priced nothing at all writes nothing when the market
# did not answer either, and the next load asks again (`refresh_prices`).
_UNPRICED_ON = "unpriced:{symbol}"


def _unpriced_today(db: Session, symbols: list[str], today: str) -> set[str]:
    """Which of `symbols` the batch priced nothing for today. One read."""
    keys = {_UNPRICED_ON.format(symbol=s): s for s in symbols}
    rows = db.execute(
        select(models.Setting.key, models.Setting.value).where(models.Setting.key.in_(list(keys)))
    )
    return {keys[key] for key, value in rows if value == today}


def _remember_unpriced(db: Session, symbols: list[str], today: str) -> None:
    """Forget the rows of an earlier day, and keep `symbols` as priced nothing
    for today. Statements rather than objects, each saying what it means, since
    two catch-ups run at once (the dividend answers' `INSERT ... ON CONFLICT
    DO UPDATE`); nothing reads these rows as objects, so the session holds none
    to keep in step. Committed at once, like the dividend answers."""
    db.execute(
        delete(models.Setting)
        .where(
            models.Setting.key.startswith(_UNPRICED_ON.format(symbol=""), autoescape=True),
            models.Setting.value != today,
        )
        .execution_options(synchronize_session=False)
    )
    for symbol in symbols:
        upsert = sqlite_insert(models.Setting).values(key=_UNPRICED_ON.format(symbol=symbol), value=today)
        db.execute(upsert.on_conflict_do_update(index_elements=["key"], set_={"value": today}))
    commit(db)


def refresh_prices(db: Session) -> dict[str, dict]:
    """Bring the price cache to the latest close, once a day for each symbol
    the positions are priced by.

    In the reader's test round (2026-10-08) the cached closes were days old, and
    the chat said so: nothing but the "Refresh market prices" button and the
    per-position refresh ever asked. Brief AJ: the catch-up the app posts at
    every page load does it, for every symbol whose cached price was not
    fetched today.

    All of them in one batch, the one the button asks, a ticker whose
    dividends were asked a moment before included. Brief AJ priced that one
    from its dividend answer by reading yfinance's internals; through
    yfinance's public calls one request gives the dividends exactly or the
    dividends with a close, not both (brief AK, `prices._fetch_dividends`).
    So a followed ticker costs two requests a day, its dividends and its
    price, and the second waits on nothing: the batch runs its requests in
    threads (measured 2026-10-08, 18 symbols in 1.24 s).

    A listing's currency is the cache's; one it never learnt is asked once
    (`get_currencies`). A symbol that does not answer keeps the price it had,
    with its date, which the picture and the pages show, and one Yahoo priced
    nothing for, while it priced others or while the market answered, is not
    asked again that day, a restart included (`_UNPRICED_ON`). Returns what
    was written."""
    held = sorted({p.symbol for p in project(db) if p.symbol and p.quantity is not None})
    if not held:
        return {}
    today = dated.today()
    cached = {
        row.symbol: row
        for row in db.scalars(select(models.PriceCache).where(models.PriceCache.symbol.in_(held)))
    }
    stale = [s for s in held if s not in cached or dated.local_day(cached[s].fetched_at) != today]
    if not stale:
        return {}
    remembered = _unpriced_today(db, stale, today)
    due = [s for s in stale if s not in remembered]
    if not due:
        return {}
    known = {s: cached[s].currency for s in due if s in cached and cached[s].currency}
    try:
        quotes = prices.get_quotes(due)
    except prices.PriceError as exc:
        logger.warning("The daily price refresh could not reach the market: %s", exc)
        return {}
    unpriced = [s for s in due if s not in quotes]
    # Priced nothing at all: a market that did not answer, or only symbols
    # Yahoo does not know, such as one typed wrong and added after the day's
    # first batch, which would be asked again at every load until the next day.
    # The canary tells them apart, as it does for one quote
    # (`prices.market_reachable`: a symbol always quoted, its verdict kept 20
    # seconds). Nobody answering says nothing about any one symbol.
    if unpriced and not quotes and not prices.market_reachable():
        unpriced = []
    _remember_unpriced(db, unpriced, today)
    if not quotes:
        return {}
    unknown = [s for s in quotes if s not in known]
    found = prices.get_currencies(unknown) if unknown else {}
    for symbol, quote in quotes.items():
        quote["currency"] = known.get(symbol) or found.get(symbol)
    crud.upsert_price_caches(db, quotes)
    return quotes


def catch_up(db: Session, as_of: datetime.date | None = None) -> dict:
    """Run every ledger catch-up (PAC buys first, then dividends — so a buy
    recorded today counts toward today's dividend share count on the next
    run), then the day's prices (`refresh_prices`), which write no ledger
    entry. Returns the merged {created, skipped}, with the dividends the
    reader had entered themselves (`recognised`) and the questions only they
    can answer (`questions`, brief AZ)."""
    pacs = execute_due(db, as_of)
    divs = execute_dividends(db, as_of)
    try:
        refresh_prices(db)
    except Exception:
        # A route the app calls at every start: a price it could not refresh
        # stays the one it was, with its date, and the ledger above stands.
        logger.exception("The daily price refresh failed")
    created = pacs["created"] + divs["created"]
    return {
        "created": created,
        "skipped": pacs["skipped"] + divs["skipped"],
        "recognised": divs["recognised"],
        "questions": divs["questions"],
        "waiting": divs["waiting"],
        "accounts": _accounts(db, created),
    }


def _accounts(db: Session, rows: list[models.Transaction]) -> dict[int, str]:
    """{id: name} of every account `rows` belong to, for the banner's list."""
    ids = {t.institution_id for t in rows if t.institution_id is not None}
    if not ids:
        return {}
    return dict(db.execute(
        select(models.Institution.id, models.Institution.name).where(models.Institution.id.in_(sorted(ids)))
    ).all())
