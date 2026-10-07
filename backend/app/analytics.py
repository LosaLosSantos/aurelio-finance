"""Dashboard analytics: read-only aggregations over financial and real wealth.

Financial wealth = institutions. An institution's value has two parts:
- Investments: the latest snapshot's holdings EXCLUDING cash (market-priced
  positions you revalue manually until price auto-fetch exists).
- Cash: a live "register" projected from the latest CashAnchor (an actual
  balance at a date) plus linked income/expenses and transfers after that date.

Real wealth = real assets with dated valuations.

Currency: every amount is converted to the base currency by `fx.Converter`
before it is added to anything — holdings, cash anchors, income, expenses,
transfers, ledger entries, real-asset valuations and debt balances, each from
the currency its row states.
A reading of a day converts at the rates in force on that day: today's
totals at today's, each point of the net worth history at its own — see
`compute_net_worth_series`.
- "Net worth over time" carries forward investments/real assets, and uses the
  live projection for cash, sampled at each event date up to today.

Dates are stored as 'YYYY-MM-DD' strings (sort lexicographically = chronologically).
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import crud, dated, fx, models, positions, prices, tax


# --- Date / recurrence helpers --------------------------------------------


def _parse(d: str | None) -> datetime.date | None:
    """Parse an ISO 'YYYY-MM-DD' string into a date (None passes through)."""
    return datetime.date.fromisoformat(d) if d else None


def add_months(d: datetime.date, n: int) -> datetime.date:
    """Add n months to a date, clamping the day to the target month's length
    (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    index = d.month - 1 + n
    year = d.year + index // 12
    month = index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


# How many months between two occurrences of a recurring flow.
STEP_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}


def recurrence(
    start: datetime.date, step: int, until: datetime.date
) -> Iterator[datetime.date]:
    """The dates of something that repeats every `step` months from `start`,
    up to `until` inclusive: a flow's payments, a plan's buys.

    The k-th date is `start` plus k*step months, never the date before it plus
    `step`. `add_months` clamps the day to a short month, and a clamped day
    carried forward stays clamped: a salary on the 30th, stepped from the
    payment before it, was paid on 28 February and then on the 28th of every
    month after it, for good (measured by the reviewer, 2026-10-03). Stepped
    from the start, the 28th belongs to February alone and March is the 30th
    again. A day up to the 28th is never clamped, so its dates are the same
    either way.

    Bounded at 10,000 dates, as the loops it replaced were."""
    for k in range(10000):
        occ = add_months(start, k * step)
        if occ > until:
            return
        yield occ


def _flow_sum_in_window(
    amount: float,
    frequency: str | None,
    start: datetime.date | None,
    end: datetime.date | None,
    lo: datetime.date,
    hi: datetime.date,
) -> float:
    """Total of a flow's occurrences in the window (lo, hi] — lo EXCLUSIVE (the
    anchor balance already 'banked' everything up to its date), hi INCLUSIVE —
    bounded by the flow's own [start, end]. A flow with no start_date cannot be
    placed in time and contributes 0. A one_off occurs once, on its start_date.
    The others fall on `recurrence`'s dates, so the day of the start is the
    day of every payment, the last day of a shorter month aside.
    """
    if start is None:
        return 0.0
    freq = frequency or "monthly"
    if freq == "one_off":
        in_window = lo < start <= hi
        within_life = end is None or start <= end
        return amount if (in_window and within_life) else 0.0

    step = STEP_MONTHS.get(freq, 1)
    last = hi if end is None else min(hi, end)
    return sum((amount for occ in recurrence(start, step, last) if occ > lo), 0.0)



def _days_since(iso: str | None, today: datetime.date | None = None) -> int | None:
    """Whole days since an ISO date, or None if there is no date to count from."""
    if not iso:
        return None
    try:
        then = datetime.date.fromisoformat(iso)
    except ValueError:
        return None
    return ((today or datetime.date.today()) - then).days


# --- Cash register (live projection) --------------------------------------


def compute_cash_position(
    db: Session,
    institution_id: int,
    as_of: datetime.date | None = None,
    conv: fx.Converter | None = None,
) -> dict | None:
    """Project an institution's cash at `as_of` (default today) from its latest
    anchor on/before that date::

        projected = anchor + income - expenses + transfers_in - transfers_out
                    - buys + sells (proceeds, dividends and closed positions)

    counting only events strictly AFTER the anchor date, up to as_of. Returns
    None if the institution does not exist; a zeroed breakdown if it has no
    anchor yet (there is no starting balance to project from).

    Every figure in the breakdown is in the base currency: each anchor, flow
    and transfer is converted from the currency its row states before it is
    added. One register can hold rows in several currencies — a multi-currency
    account is an ordinary thing — and adding them as stored is how an anchor
    of 1,250 dollars counted as 1,250 euro. Pass `conv` to share one rate load
    across several registers."""
    if as_of is None:
        as_of = datetime.date.today()
    if conv is None:
        # The rates of the day asked about: a register read for a past date
        # converts at that date, as the history's point for it does.
        conv = fx.Converter(db, on=as_of.isoformat())
    in_base = conv.to_base_or_as_stored
    inst = db.get(models.Institution, institution_id)
    if inst is None:
        return None

    as_of_iso = as_of.isoformat()
    result = {
        "institution_id": inst.id,
        "institution_name": inst.name,
        "as_of": as_of,
        # The unit of every figure below, from the converter that makes them.
        "base_currency": conv.base,
        "anchor_date": None,
        "anchor_amount": 0.0,
        "income": 0.0,
        "expenses": 0.0,
        "transfers_in": 0.0,
        "transfers_out": 0.0,
        "buys": 0.0,
        "sells": 0.0,
        "projected": 0.0,
    }

    anchor = dated.latest_on_or_before(inst.cash_anchors, as_of_iso)
    if anchor is None:
        return result

    lo = _parse(anchor.date)
    income = sum(
        _flow_sum_in_window(
            in_base(i.amount, i.currency),
            i.frequency, _parse(i.start_date), _parse(i.end_date), lo, as_of,
        )
        for i in db.scalars(
            select(models.IncomeSource).where(
                models.IncomeSource.institution_id == inst.id
            )
        )
    )
    expenses = sum(
        _flow_sum_in_window(
            in_base(e.amount, e.currency),
            e.frequency, _parse(e.start_date), _parse(e.end_date), lo, as_of,
        )
        for e in db.scalars(
            select(models.Expense).where(models.Expense.institution_id == inst.id)
        )
    )

    transfers = dated.events_after(
        anchor, db.scalars(select(models.Transfer)), until=as_of_iso
    )
    # Each side in its own figure: what left the source, and what reached the
    # destination — two sums when the accounts hold two currencies.
    transfers_in = sum(
        in_base(t.to_amount, t.to_currency) for t in transfers if t.to_institution_id == inst.id
    )
    transfers_out = sum(
        in_base(t.amount, t.currency) for t in transfers if t.from_institution_id == inst.id
    )

    # Ledger cash effects for this institution (a transaction's
    # cash_institution_id, defaulting to the holding institution): buys draw
    # cash out; everything else pays in — sale proceeds, dividends, and what
    # came back when a position was closed. Each entry's amount is in its own
    # `currency` — the cash side, fixed on its day — and converts like any
    # other amount in this register.
    buys_out = sells_in = 0.0
    for t in dated.events_after(
        anchor, db.scalars(select(models.Transaction)), until=as_of_iso
    ):
        if (t.cash_institution_id or t.institution_id) != inst.id:
            continue
        if t.kind == "buy":
            buys_out += in_base(t.amount, t.currency)
        else:  # sell | dividend | close
            sells_in += in_base(t.amount, t.currency)

    anchor_amount = in_base(anchor.amount, anchor.currency)
    result.update(
        anchor_date=lo,
        anchor_amount=anchor_amount,
        income=income,
        expenses=expenses,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        buys=buys_out,
        sells=sells_in,
        projected=anchor_amount
        + income
        - expenses
        + transfers_in
        - transfers_out
        - buys_out
        + sells_in,
    )
    return result


def compute_all_cash_positions(
    db: Session, as_of: datetime.date | None = None, conv: fx.Converter | None = None
) -> list[dict]:
    """Projected cash for every institution (ordered by id), in the base
    currency, with one rate load for all of them."""
    if conv is None:
        conv = fx.Converter(db, on=as_of.isoformat() if as_of else None)
    ids = list(
        db.scalars(select(models.Institution.id).order_by(models.Institution.id))
    )
    return [compute_cash_position(db, i, as_of, conv) for i in ids]


def _cash_total(
    db: Session, as_of: datetime.date | None = None, conv: fx.Converter | None = None
) -> float:
    """Sum of projected cash across all institutions at `as_of`."""
    return sum(p["projected"] for p in compute_all_cash_positions(db, as_of, conv))


# --- Latest-value helpers --------------------------------------------------


def _latest_valuation_by_asset(
    db: Session, as_of: str
) -> dict[int, models.RealAssetValuation]:
    """For each real asset id, the valuation in force at `as_of`.

    In force, not simply newest: a valuation dated next month is a guess about
    a day that has not happened, and it used to be this app's answer to what
    the house is worth today — one 1.00 row dated eleven days out took 200,000
    off the net worth."""
    return dated.latest_per_parent(
        db,
        models.RealAssetValuation,
        models.RealAssetValuation.real_asset_id,
        on_or_before=as_of,
    )


def _latest_balance_by_liability(
    db: Session, as_of: str
) -> dict[int, models.LiabilityBalance]:
    """For each liability id, the outstanding balance in force at `as_of`.

    Bounded for the same reason as the valuations above, and it is the half
    that hurts more: a future balance does not shrink the total, it grows it."""
    return dated.latest_per_parent(
        db,
        models.LiabilityBalance,
        models.LiabilityBalance.liability_id,
        on_or_before=as_of,
    )


# --- Summary / allocation / series ----------------------------------------


def _parent_currencies(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    """{real asset id: currency} and {liability id: currency}, in two queries.

    A valuation and a balance carry no currency of their own: they are figures
    about their parent, in the parent's currency. Read here as two small maps
    rather than through the relationship, which would load each parent on its
    own when a total walks the rows."""
    assets = dict(db.execute(select(models.RealAsset.id, models.RealAsset.currency)).all())
    debts = dict(db.execute(select(models.Liability.id, models.Liability.currency)).all())
    return assets, debts



def _declared_by(photo: models.Snapshot) -> tuple[set[str], set[str], dict[str, float | None]]:
    """What a photograph ASSERTS: the tickers it names, the names it names, and
    the units it claims under each.

    Both halves of the identity, not `symbol or asset_name`, because the two
    sides of this comparison do not have to agree about which one a row is
    keyed by — and when they disagree the old rule read a rename as a
    disappearance. The units come along because a photograph makes two separate
    assertions about a row with a quantity ("I hold this" and "I hold this
    much"), and only the first was ever being checked."""
    symbols: set[str] = set()
    names: set[str] = set()
    units: dict[str, float | None] = {}
    for h in photo.holdings:
        if (h.asset_class or "") == "cash":
            continue  # cash lives in the register
        if h.symbol:
            symbols.add(h.symbol)
            units[h.symbol] = h.quantity
        names.add(h.asset_name)
        units.setdefault(h.asset_name, h.quantity)
    return symbols, names, units


def _is_named_by(p: positions.Position, symbols: set[str], names: set[str]) -> bool:
    """Whether a photograph names this position, by EITHER half of its identity.

    The ticker where both sides have one, the name otherwise — the same rule
    `positions._closure` matches a disposal by, and for the same reason: the
    rows most likely to be re-keyed are exactly the ones a ticker does not
    describe yet. Giving a value-only row its ticker is the gesture this app
    exists to reward, and under the old rule it changed the key, so the row
    read as one position vanishing and another appearing — a 1000.00 loss
    reported against a total that had not moved."""
    return bool(p.symbol and p.symbol in symbols) or p.asset_name in names


def _units_claimed(p: positions.Position, units: dict[str, float | None]) -> float | None:
    """How many units a photograph claims for this position, under either half
    of its identity. None when it does not name it, or names it as a row with
    no quantity — an opaque row's value is ALL it asserts, and a value that
    moved is the market, not an omission."""
    for key in (p.symbol, p.asset_name):
        if key is not None and key in units:
            return units[key]
    return None


def _unaccounted(db: Session, conv: fx.Converter | None = None) -> dict[str, list[dict]]:
    """Value the app believed an institution held that its photographs do not
    account for — and, where a situation did not account for it, what that same
    situation declared instead.

    A photograph that omits a position deletes it: the value simply leaves the
    net worth and no line says where. Selling is an assertion with a date and
    proceeds; forgetting is the absence of one. Nothing can tell them apart
    after the fact, so the least the app can do is name what is missing and how
    much it was worth, instead of letting the total quietly shrink.

    The comparison is against the PROJECTION — what the app believed — and it
    is made at EVERY photograph, so that a position born in the ledger, an
    account's first situation, and a warning buried by the next situation are
    all the same question with one answer. What changed here is what
    "accounted for" MEANS. It used to mean "some row in the newer photograph
    has the same key", and three different kinds of loss fit through that:

    * **A quantity that shrinks rather than a name that vanishes.** A situation
      restating 1 unit of a position the app believed was 10 kept the name, so
      the check saw nothing and 900.00 left in silence. A photograph with a
      quantity makes two assertions, and only one of them was being read.

    * **A partial disposal silencing a total one.** The old rule asked whether
      any sell existed, never how much it sold, so one unit sold out of ten
      explained the whole position vanishing. It is not needed as a rule at
      all now: the projection applies disposals itself, with the average-cost
      arithmetic that is written once in `replay`, so what is believed is
      already net of everything the ledger disposed of. What is left is
      genuinely unaccounted for.

    * **A row that changed key.** Matching on `symbol or asset_name` meant
      giving a value-only row its ticker read as one position leaving and
      another arriving. Both halves of the identity are compared now.

    And what a situation declared that the app did not believe is reported
    beside what it dropped, because the two are usually the same money. Three
    summary rows replaced by twenty-one positions is a portfolio described
    better, not the three rows' value lost, and the app could only say the
    second. It does not claim they ARE the same money — nothing here can know
    that, and saying which row replaced which needs a stable identity this
    schema does not have yet. It puts both numbers in the
    reader's hands, which is the whole of what is needed to tell a
    reformulation from a loss at a glance."""
    if conv is None:
        conv = fx.Converter(db)
    with conv.not_recording():
        return _unaccounted_walk(db, conv)


def _unaccounted_walk(db: Session, conv: fx.Converter) -> dict[str, list[dict]]:
    """`_unaccounted`'s body, run with the converter not recording what it could
    not convert — see `fx.Converter.not_recording` for why: this walk replays
    every photograph, so a single unconvertible row would be counted once per
    photograph after it, into a report about TODAY's totals that it is not part
    of."""
    today = dated.today()
    inst_names = {i.id: i.name for i in db.scalars(select(models.Institution))}
    # The holdings are loaded WITH the photographs: this walk asks every
    # photograph what it declares, so lazy-loading is one query per photograph.
    snapshots = list(
        db.scalars(
            select(models.Snapshot)
            .where(models.Snapshot.date <= today)  # in force, never merely newest
            .options(selectinload(models.Snapshot.holdings))
        )
    )
    txs = list(db.scalars(select(models.Transaction)))
    # The listing currencies the projection values quantity-based rows by —
    # built here rather than by `load_projection_inputs`, which would re-read
    # the two tables above to assemble the same thing. Its quotes are left out
    # deliberately: a past-dated projection has no market by design, so what
    # comes back is what was OBSERVED, and that is the only honest answer to
    # "how much was this worth when it went missing".
    symbols_seen = sorted(
        {h.symbol for s in snapshots for h in s.holdings if h.symbol}
        | {t.symbol for t in txs if t.symbol}
    )
    listing = {
        sym: q.get("currency")
        for sym, q in (
            crud.get_cached_prices(db, symbols_seen) if symbols_seen else {}
        ).items()
    }

    by_inst: dict[int, list[models.Snapshot]] = {}
    for snap in snapshots:
        by_inst.setdefault(snap.institution_id, []).append(snap)

    missing: dict[tuple[int | None, str], dict] = {}
    instead: dict[tuple[int | None, str], dict] = {}
    for inst_id, snaps in by_inst.items():
        snaps.sort(key=lambda s: (s.date, s.id))
        inst_txs = [t for t in txs if t.institution_id == inst_id]
        latest_symbols, latest_names, latest_units = _declared_by(snaps[-1])

        def disposed_late(p: positions.Position, after: str) -> bool:
            """A disposal recorded for this position AFTER the situation that
            dropped it, and no later than today.

            The projection has already applied every disposal dated up to the
            photograph itself, so this is only about the ones recorded late —
            and a late record is still a record. The notice tells the reader
            "Sold → record a close"; the form dates it today; the situation
            that dropped the row is months old. Refusing that as an explanation
            left the one gesture the notice prescribes unable to clear it, with
            nothing anywhere saying it had to be backdated. Measured: the close
            lands, the totals come out right — 1400.00 − 400.00 + 430.00 —
            and the warning stayed. A warning its own remedy cannot clear
            teaches the reader to ignore it, and then the true one goes unread.

            The lower bound stays: a disposal dated before the situation that
            dropped the row cannot be about the units it was still holding
            afterwards, which is what keeps a position bought back after an old
            sale from being explained by that sale."""
            return any(
                t.kind in ("sell", "close")
                and (t.symbol == p.symbol or t.asset_name == p.asset_name)
                and after < t.date <= today
                for t in inst_txs
            )

        for photo in snaps:
            # What the ledger says this account held ON the day of this
            # photograph, anchored at the one before it. The photograph itself
            # is held out of the inputs so it cannot anchor the reading of
            # itself, and `as_of` is its own date so that a disposal recorded
            # on that day is applied: a photograph of the 6th already contains
            # everything that happened by the end of the 6th, which is the same
            # rule `events_after` is strict about on its other edge.
            inputs = positions.ProjectionInputs(
                snapshots=[s for s in snaps if s.date < photo.date],
                transactions=inst_txs,
                listing=listing,
                quotes={},
            )
            believed = [
                p
                for p in positions.project(db, conv, as_of=photo.date, inputs=inputs)
                # A position the ledger has already taken out is not missing
                # from the photograph — it is gone, and where it went is on
                # record. That is a disposal, which is the thing this whole
                # function exists to tell apart from a forgetting.
                if p.closed_on is None
                and (p.quantity is None or p.quantity > 0)
                and (p.asset_class or "") != "cash"
            ]
            symbols, names, units = _declared_by(photo)
            unaccounted_here = False

            for p in believed:
                if _is_named_by(p, symbols, names):
                    # Named — but a row with units asserts how MANY, and that
                    # assertion can shrink while the name stays put.
                    claimed = _units_claimed(p, units)
                    if not (p.quantity and claimed is not None and claimed < p.quantity):
                        continue
                    still_claimed = _units_claimed(p, latest_units)
                    if still_claimed is None or still_claimed >= p.quantity:
                        continue  # the newest situation claims them again
                    if disposed_late(p, photo.date):
                        continue
                    short = p.quantity - claimed
                    value = p.current_value * short / p.quantity
                    unaccounted_here = True
                    missing[(inst_id, p.symbol or p.asset_name)] = {
                        "asset_name": p.asset_name,
                        "symbol": p.symbol,
                        "institution": inst_names.get(inst_id),
                        "institution_id": inst_id,
                        "last_seen": p.observed_on,
                        "dropped_on": photo.date,
                        "last_value": round(value, 2),
                        "units_missing": short,
                    }
                    continue
                # Not named at all. Unless a later situation names it again —
                # "dropped by mistake → put it back" is what the notice tells
                # the reader to do, and doing it puts the value back in the
                # totals, so nothing left them.
                if _is_named_by(p, latest_symbols, latest_names):
                    continue
                if disposed_late(p, photo.date):
                    continue
                unaccounted_here = True
                missing[(inst_id, p.symbol or p.asset_name)] = {
                    "asset_name": p.asset_name,
                    "symbol": p.symbol,
                    "institution": inst_names.get(inst_id),
                    "institution_id": inst_id,
                    # When the app last had it on record — a photograph it sat
                    # in, or its most recent ledger entry if it never appeared
                    # in one.
                    "last_seen": p.observed_on,
                    "dropped_on": photo.date,
                    "last_value": round(p.current_value, 2),
                    "units_missing": None,  # the whole row, not part of it
                }

            if not unaccounted_here:
                continue
            # What this situation declared that the app was not expecting. Only
            # collected for a situation that also failed to account for
            # something: value ARRIVING is not a breach of the rule this
            # function enforces — a reader is allowed to declare things the app
            # had never heard of — and reporting it on its own would turn every
            # ordinary purchase into a notice.
            believed_symbols = {p.symbol for p in believed if p.symbol}
            believed_names = {p.asset_name for p in believed}
            for h in photo.holdings:
                if (h.asset_class or "") == "cash":
                    continue
                if (h.symbol and h.symbol in believed_symbols) or (
                    h.asset_name in believed_names
                ):
                    continue
                instead[(inst_id, h.symbol or h.asset_name)] = {
                    "asset_name": h.asset_name,
                    "symbol": h.symbol,
                    "institution": inst_names.get(inst_id),
                    "institution_id": inst_id,
                    "appeared_on": photo.date,
                    "value": round(
                        positions.holding_book_in_base(
                            h, conv, listing.get(h.symbol) if h.symbol else None
                        ),
                        2,
                    ),
                }

    gone = sorted(missing.values(), key=lambda r: -r["last_value"])
    arrived = sorted(instead.values(), key=lambda r: -r["value"])
    return {"omissions": gone, "arrivals": arrived}


def _unresolved_omissions(db: Session, conv: fx.Converter | None = None) -> list[dict]:
    """Just the missing half of `_unaccounted`, for callers that only report it."""
    return _unaccounted(db, conv)["omissions"]


def compute_summary(db: Session, as_of: datetime.date | None = None) -> dict:
    """Net worth = financial (investments + cash) + real − liabilities, plus counts."""
    if as_of is None:
        as_of = datetime.date.today()
    conv = fx.Converter(db)  # one rate load for the whole computation
    # All four series read at the SAME date, and never past it. `as_of` is
    # today unless a caller said otherwise, and the summary is the one place
    # where a row dated ahead of it could reach every total at once.
    as_of_iso = as_of.isoformat()
    fin_latest = positions.latest_snapshot_by_institution(db, as_of_iso)
    real_latest = _latest_valuation_by_asset(db, as_of_iso)
    liab_latest = _latest_balance_by_liability(db, as_of_iso)

    # Projected positions (snapshot anchor + later buys), so recording a buy
    # moves value from cash to investments instead of leaking it.
    #
    # Valued at the MARKET where the market can price them. It used to be the
    # sum of book values, which meant net worth never moved unless you took a
    # new photograph — and it is why recording real purchase costs would
    # otherwise have made you poorer on paper by the size of your gains.
    held = positions.project(db, conv)
    unaccounted = _unaccounted(db, conv)
    investments_total = sum(p.current_value for p in held)
    at_market = sum(p.current_value for p in held if p.is_priced)
    cash_total = _cash_total(db, as_of, conv)
    financial_total = investments_total + cash_total
    # A valuation and a balance are in their PARENT's currency — the asset's,
    # the debt's — so the parents' currencies are read once for the lot.
    asset_ccy, debt_ccy = _parent_currencies(db)
    real_total = sum(
        conv.to_base_or_as_stored(v.value, asset_ccy.get(v.real_asset_id))
        for v in real_latest.values()
    )
    liabilities_total = sum(
        conv.to_base_or_as_stored(b.balance, debt_ccy.get(b.liability_id))
        for b in liab_latest.values()
    )

    dates = [s.date for s in fin_latest.values()]
    dates += [v.date for v in real_latest.values()]
    dates += [b.date for b in liab_latest.values()]
    as_of_data = max(dates) if dates else None

    return {
        "net_worth": financial_total + real_total - liabilities_total,
        "financial_total": financial_total,
        "investments_total": investments_total,
        # How much of that total the market actually priced, and how much is a
        # figure carried over from the last photograph. Same rule as the
        # look-through's coverage: state the share you can vouch for instead of
        # presenting one number as if it were all equally solid.
        "investments_at_market": at_market,
        "investments_at_book": investments_total - at_market,
        # Value that left the totals because a newer photograph did not mention
        # it, with nothing on record saying where it went. Never silent.
        "unresolved_omissions": unaccounted["omissions"],
        # And what the same situations declared instead. Value arriving breaks
        # no rule on its own; beside what went missing it is usually the same
        # money described better, and only both numbers can say which.
        "declared_instead": unaccounted["arrivals"],
        # The other direction of the same rule: nothing LEAVES the totals in
        # silence, and nothing enters them unconverted in silence either. An
        # amount whose currency has no rate is added as it was stored — the
        # figure is kept rather than dropped, which is the right trade — so
        # these figures name the currencies that happened in, and how much was
        # written in each. NOT how much any total above is out by: see
        # `fx.Converter.unconverted_amounts`, which measures it going wrong in
        # both directions.
        "unconverted": conv.unconverted_amounts(),
        "cash_total": cash_total,
        "real_total": real_total,
        "liabilities_total": liabilities_total,
        "base_currency": conv.base,
        "institutions": db.scalar(
            select(func.count()).select_from(models.Institution)
        ),
        "real_assets": db.scalar(select(func.count()).select_from(models.RealAsset)),
        "liabilities": db.scalar(select(func.count()).select_from(models.Liability)),
        "as_of": as_of_data,
    }


def compute_allocation(db: Session, as_of: datetime.date | None = None) -> dict:
    """Allocation from latest values: financial by asset_class (investments from
    snapshots + cash from the live register), real by category.

    Valued at the MARKET, the same way compute_summary values them, and for a
    stronger reason: this is a RISK view. It answers "what do I hold", not
    "what did I pay", and the two stop being the same number the moment
    anything moves. Summing book values here left the Dashboard showing two
    financial totals, one above the other, that disagreed by the size of the
    portfolio's unrealised gain.
    """
    if as_of is None:
        as_of = datetime.date.today()
    conv = fx.Converter(db)  # one rate load for positions, cash and real assets
    real_latest = _latest_valuation_by_asset(db, as_of.isoformat())

    by_asset_class: dict[str, float] = {}
    for p in positions.project(db, conv):  # snapshot anchor + later buys
        key = p.asset_class or "unclassified"
        by_asset_class[key] = by_asset_class.get(key, 0.0) + p.current_value

    cash_total = _cash_total(db, as_of, conv)
    if cash_total:
        by_asset_class["cash"] = by_asset_class.get("cash", 0.0) + cash_total

    asset_ccy, _ = _parent_currencies(db)
    by_real_category: dict[str, float] = {}
    for val in real_latest.values():
        key = (val.real_asset.category if val.real_asset else None) or "unclassified"
        by_real_category[key] = by_real_category.get(key, 0.0) + conv.to_base_or_as_stored(
            val.value, asset_ccy.get(val.real_asset_id)
        )

    return {
        "financial_total": sum(by_asset_class.values()),
        "real_total": sum(by_real_category.values()),
        "by_asset_class": [
            {"asset_class": k, "value": v} for k, v in sorted(by_asset_class.items())
        ],
        "by_real_category": [
            {"category": k, "value": v} for k, v in sorted(by_real_category.items())
        ],
        "base_currency": conv.base,
    }


def _cash_totals_by_date(
    db: Session,
    dates: list[str],
    inst_ids: list[int],
    convs: dict[str, fx.Converter] | None = None,
) -> dict[str, float]:
    """Projected cash across all institutions, at every date in `dates`.

    Exactly `compute_cash_position`'s arithmetic — anchor + income − expenses
    + transfers − buys + sells, counting only what happened strictly after the
    anchor — but with the four tables read ONCE for the whole series instead of
    once per institution per date. That is the whole of the quadratic: the
    series asked the register 4 institutions x 130 dates times, and every one
    of those calls SELECTed all transfers and all transactions to filter them
    in Python.

    `compute_cash_position` stays as it is, and stays the reference: it is what
    the cash register page answers with, and `test_cash_register.py` asserts
    this function agrees with it date by date rather than trusting the rewrite.

    That includes the conversion. Every anchor, flow and transfer is converted
    from its own currency here exactly as it is there, and at the same day's
    rates: each date with its own converter (`convs`, one per date, sharing
    one load — see `fx.converters_on`). The agreement tests keep an account in
    dollars, and a feed with a different rate per day, because with one rate
    or with every amount in euro a copy that converted wrongly would still
    agree with the other to the cent.
    """
    if convs is None:
        convs = fx.converters_on(db, dates)
    anchors_by_inst: dict[int, list[models.CashAnchor]] = {}
    for a in db.scalars(select(models.CashAnchor)):
        anchors_by_inst.setdefault(a.institution_id, []).append(a)
    incomes: dict[int, list[models.IncomeSource]] = {}
    for i in db.scalars(select(models.IncomeSource)):
        incomes.setdefault(i.institution_id, []).append(i)
    expenses: dict[int, list[models.Expense]] = {}
    for e in db.scalars(select(models.Expense)):
        expenses.setdefault(e.institution_id, []).append(e)
    transfers = list(db.scalars(select(models.Transfer)))
    ledger = list(db.scalars(select(models.Transaction)))
    ledger_by_inst: dict[int, list[models.Transaction]] = {}
    for t in ledger:
        ledger_by_inst.setdefault(t.cash_institution_id or t.institution_id, []).append(t)
    transfers_by_inst: dict[int, list[models.Transfer]] = {}
    for t in transfers:
        for iid in {t.to_institution_id, t.from_institution_id}:
            if iid is not None:
                transfers_by_inst.setdefault(iid, []).append(t)

    totals: dict[str, float] = {}
    for d in dates:
        d_date = datetime.date.fromisoformat(d)
        in_base = convs[d].to_base_or_as_stored
        total = 0.0
        for iid in inst_ids:
            anchor = dated.latest_on_or_before(anchors_by_inst.get(iid, []), d)
            if anchor is None:
                continue  # no starting balance to project from
            lo = _parse(anchor.date)
            projected = in_base(anchor.amount, anchor.currency)
            for i in incomes.get(iid, []):
                projected += _flow_sum_in_window(
                    in_base(i.amount, i.currency), i.frequency,
                    _parse(i.start_date), _parse(i.end_date), lo, d_date,
                )
            for e in expenses.get(iid, []):
                projected -= _flow_sum_in_window(
                    in_base(e.amount, e.currency), e.frequency,
                    _parse(e.start_date), _parse(e.end_date), lo, d_date,
                )
            for t in dated.events_after(anchor, transfers_by_inst.get(iid, []), until=d):
                if t.to_institution_id == iid:
                    projected += in_base(t.to_amount, t.to_currency)
                if t.from_institution_id == iid:
                    projected -= in_base(t.amount, t.currency)
            for t in dated.events_after(anchor, ledger_by_inst.get(iid, []), until=d):
                moved = in_base(t.amount, t.currency)
                projected += -moved if t.kind == "buy" else moved
            total += projected
        totals[d] = total
    return totals


def compute_net_worth_series(
    db: Session, as_of: datetime.date | None = None
) -> list[dict]:
    """Net worth over time, sampled at every event date up to `as_of` (today):
    ``net_worth = financial + real − liabilities``, where financial is the
    investment projection plus the projected cash.

    ONE mechanism for every point. Each date's investments are
    `positions.project(as_of=d)` — the photograph in force on that day plus the
    ledger entries after it — which is the same function today's point has
    always used and the same one the portfolio page reports. It used to be two:
    today came from the projection, and every earlier point from a
    carry-forward of the photographs with a book-delta overlay bolted on. That
    overlay seeded its state by `h.symbol == t.symbol`, so a close with no
    ticker — exactly the row that most needs an explicit exit, since no price
    can ever refresh it — could never find the holding it disposed of, and the
    position went on counting at every historical date after its own sale.

    Real assets and liabilities stay a carry-forward, because that is all they
    are: a dated valuation stands until a newer one replaces it, with no events
    in between to project."""
    if as_of is None:
        as_of = datetime.date.today()
    as_of_iso = as_of.isoformat()

    inputs = positions.load_projection_inputs(db)
    snaps = inputs.snapshots
    ledger = inputs.transactions
    vals = list(db.scalars(select(models.RealAssetValuation)))
    balances = list(db.scalars(select(models.LiabilityBalance)))
    anchors = list(db.scalars(select(models.CashAnchor)))
    transfers = list(db.scalars(select(models.Transfer)))
    if not (snaps or vals or balances or anchors or transfers or ledger):
        return []

    inst_ids = list(db.scalars(select(models.Institution.id)))
    asset_ccy, debt_ccy = _parent_currencies(db)

    assets: dict[int, list] = {}
    for v in vals:
        assets.setdefault(v.real_asset_id, []).append((v.date, v.value))
    debts: dict[int, list] = {}
    for b in balances:
        debts.setdefault(b.liability_id, []).append((b.date, b.balance))

    # Sample at every meaningful event date capped at today, plus today itself.
    event_dates = (
        {s.date for s in snaps}
        | {v.date for v in vals}
        | {b.date for b in balances}
        | {a.date for a in anchors}
        | {t.date for t in transfers}
        | {t.date for t in ledger}
    )
    all_dates = sorted({d for d in event_dates if d <= as_of_iso} | {as_of_iso})
    # EACH POINT AT ITS OWN DAY'S RATES. A point is what the wealth was worth on
    # its date, and a rate is a price: converting the past at today's rate
    # restated every point at a rate none of them had, and moved the whole line
    # each time the rate moved — the lie this series already refuses to tell
    # with today's quotes. One converter per date, all loaded together, and
    # each point says which ECB day it was converted at.
    convs = fx.converters_on(db, all_dates)
    cash_by_date = _cash_totals_by_date(db, all_dates, inst_ids, convs)

    series: list[dict] = []
    for d in all_dates:
        # Today is the one date where we can do better than the photographs:
        # the market has a price for most of it. `project` gives an earlier day
        # its photograph's own figures instead — inventing history from today's
        # prices is precisely the lie this series used to tell.
        conv = convs[d]
        held = positions.project(
            db,
            conv,
            inputs=inputs,
            **({} if d == as_of_iso else {"as_of": d}),
        )
        inv = sum(p.current_value for p in held)
        # A valuation in force on `d` may have been recorded months earlier; it
        # is converted at `d`'s rate, because the point is about `d`.
        real = dated.carry_forward(
            assets, d, lambda aid, v: conv.to_base_or_as_stored(v, asset_ccy.get(aid))
        )
        liab = dated.carry_forward(
            debts, d, lambda lid, v: conv.to_base_or_as_stored(v, debt_ccy.get(lid))
        )
        financial = inv + cash_by_date[d]
        series.append(
            {
                "date": d,
                "net_worth": financial + real - liab,
                "financial": financial,
                "real": real,
                "liabilities": liab,
                "base_currency": conv.base,
                "fx_as_of": conv.used_as_of,
            }
        )
    return series


def compute_portfolio(db: Session, live: bool = False) -> dict:
    """The investment portfolio = the projected positions (latest snapshot per
    institution + later buys from the ledger), with their book values.
    Quantity-based, symboled positions also get a market price: if `live`, all
    symbols are fetched in ONE batch and stored in the price cache; otherwise
    the cache is reused (so the page loads instantly and works offline). Every
    price carries its `as_of` close date so staleness stays visible. A
    per-symbol price failure leaves that row unpriced."""
    names = {i.id: i.name for i in db.scalars(select(models.Institution))}
    # ONE converter for the whole view. The projection used to make its own and
    # throw it away, so a book value converted at an ECB rate could reach the
    # screen while `fx_as_of` — the date of that very rate — stayed null.
    conv = fx.Converter(db)
    held = positions.project(db, conv)

    priceable = sorted(
        {p.symbol for p in held if p.symbol and p.quantity is not None}
    )
    quotes: dict[str, dict] = {}
    if live and priceable:
        try:
            quotes = prices.get_quotes(priceable)
        except prices.PriceError:
            quotes = {}  # total fetch failure -> everything stays unpriced
        if quotes:
            crud.upsert_price_caches(db, quotes)
            # The batch download has no currency info; reuse what the cache
            # already knows and look up only the still-unknown listings (a
            # listing's currency never changes, so this converges to zero
            # lookups).
            cached = crud.get_cached_prices(db, list(quotes))
            for sym, q in quotes.items():
                q["currency"] = cached.get(sym, {}).get("currency")
            missing = [s for s, q in quotes.items() if not q.get("currency")]
            if missing:
                found = prices.get_currencies(missing)
                if found:
                    crud.set_price_cache_currencies(db, found)
                    for sym, cur in found.items():
                        quotes[sym]["currency"] = cur
    elif priceable:
        quotes = crud.get_cached_prices(db, priceable)

    # The positions above were valued before this fetch, so on a first live run
    # the listing currencies were not known yet. Now that they are cached, redo
    # the (purely in-memory) projection so the book uses them.
    if live and quotes:
        held = positions.project(db, conv)

    rows: list[dict] = []
    total_book = 0.0
    total_market = 0.0
    total_realized = 0.0
    total_dividends = 0.0
    total_dividends_estimated = 0.0
    as_of_dates: list[str] = []
    # When each ticker last paid, from the dividend answers the catch-up keeps:
    # what a row whose own history decides its dividends shows. Imported here
    # because `pac` imports this module.
    from app import pac

    last_paid = pac.last_dividends(db, {p.symbol for p in held if p.symbol})
    for p in held:
        book = p.book_value
        total_book += book
        total_realized += p.realized_pl
        total_dividends += p.dividends
        total_dividends_estimated += p.dividends_estimated
        live_price = as_of = market = delta = delta_pct = currency = None
        quote = (
            quotes.get(p.symbol) if (p.symbol and p.quantity is not None) else None
        )
        if quote is not None:
            # Market value converts to the base at the ECB rate. If the
            # listing's currency is not known yet, or no rate is available for
            # it, the row stays UNPRICED rather than mixing currencies.
            currency = quote.get("currency")
            market = conv.to_base(p.quantity * quote["price"], currency)
            if market is not None:
                live_price, as_of = quote["price"], quote["as_of"]
                delta = market - book
                delta_pct = (delta / book) if book else None
                as_of_dates.append(as_of)
            else:
                currency = None  # unpriced row: show nothing, not half-data
        # A row counts toward the market total at its market value if priced,
        # otherwise at what it was last OBSERVED to be worth — never at what it
        # cost. This total is the "what is it worth" total: falling back to the
        # book made an unpriceable row answer the other question inside a sum
        # the screen labels Market.
        total_market += market if market is not None else p.observed_value
        qty = p.quantity
        rows.append(
            {
                # None, not "?". A position held at no institution is a real
                # state — the PAC creates one whenever a plan target names no
                # institution — and it is not the same claim as a bank whose
                # name we failed to look up. The glyph made the two identical
                # and was indistinguishable from an institution actually called
                # "?", so the row said nothing about why it could never be
                # photographed. The view says it instead.
                "institution": names.get(p.institution_id),
                # The id beside the name, because a screen that already knows
                # which account it is showing should not have to match on a
                # display string to find its own rows.
                "institution_id": p.institution_id,
                "asset_name": p.asset_name,
                "symbol": p.symbol,
                # The key a fund's facts are read by from the catalogue
                # (`advisor._render_positions`). Not in the page's payload:
                # `schemas.PortfolioRow` does not declare it.
                "isin": p.isin,
                "asset_class": p.asset_class,
                "distribution_policy": p.distribution_policy,
                "last_dividend": last_paid.get(p.symbol),
                "quantity": qty,
                "book_value": book,
                # What it is worth, beside what it cost. Without this the row
                # cannot explain its own contribution to total_market, and the
                # difference between the two totals had no visible source.
                "observed_value": p.observed_value,
                # Only a real purchase makes this an average COST; otherwise it
                # is just the price the snapshot was taken at, and the UI says so.
                "avg_cost": (book / qty) if qty else None,
                "cost_known": p.cost_known,
                "cost_estimated": p.cost_estimated,
                "observed_on": p.observed_on,
                "closed_on": p.closed_on,
                # On a priced row only the QUANTITY is this old; the value is
                # today's. On an unpriced one, everything is.
                "quantity_age_days": _days_since(p.observed_on),
                "currency_note": p.currency_note,
                "realized_pl": p.realized_pl,
                "dividends": p.dividends,
                "dividends_estimated": p.dividends_estimated,
                "live_price": live_price,
                "currency": currency,  # listing currency (null = unpriced)
                "as_of": as_of,
                "market_value": market,
                "delta": delta,
                "delta_pct": delta_pct,
            }
        )
    any_priced = bool(as_of_dates)
    unaccounted = _unaccounted(db, conv)
    return {
        "rows": rows,
        "total_book": total_book,
        "total_market": total_market if any_priced else None,
        "priced": any_priced,
        # The OLDEST close date among priced rows: "prices at least as of ...".
        "prices_as_of": min(as_of_dates) if any_priced else None,
        "base_currency": conv.base,
        "total_realized": total_realized,
        "total_dividends": total_dividends,
        # The gross subset, named beside the sum it is part of rather than
        # left to be recovered downstream: the split exists because only the
        # auto-recorded rows are still pre-withholding, and a caller that
        # re-derived it with a query of its own would not be filtered by the
        # snapshot anchors these totals were walked under.
        "total_dividends_estimated": total_dividends_estimated,
        # The declared tax estimate, attached where its two bases are computed
        # so the figure and the numbers it came from cannot drift apart. It is
        # in the payload and in NO total above it — see app/tax.py.
        "tax_estimate": tax.estimate(
            tax.read_rates(db),
            realized=total_realized,
            dividends_estimated=total_dividends_estimated,
            dividends_recorded=total_dividends - total_dividends_estimated,
        ),
        "unresolved_omissions": unaccounted["omissions"],
        "declared_instead": unaccounted["arrivals"],
        # And what no rate could be applied to at all, which is the same
        # converter's other half — see compute_summary.
        "unconverted": conv.unconverted_amounts(),
        # ECB rate date, when any FX conversion was actually applied — to a
        # book value or to a market value, since both now run through the same
        # converter. A number restated at a rate says which rate.
        "fx_as_of": conv.used_as_of,
    }


# Convert a per-occurrence amount to a monthly run-rate, based on frequency.
# Unknown/missing frequency is assumed monthly; one-off amounts are excluded.
_MONTHLY_FACTOR = {
    "monthly": 1.0,
    "quarterly": 1.0 / 3.0,
    "semiannual": 1.0 / 6.0,
    "annual": 1.0 / 12.0,
    "one_off": 0.0,
}


def _monthly(amount: float, frequency: str | None) -> float:
    return amount * _MONTHLY_FACTOR.get(frequency or "monthly", 1.0)


def flow_status(flow, on: str) -> str:
    """Where one income or expense stands on `on`: "ended" when its end date is
    before that day, "scheduled" when its first payment is after it, and "in
    force" otherwise. Both bounds count as in force, and a flow with no start
    date is in force: nothing says it has not started.

    The one rule for every reader of the monthly figures. A flow whose end
    comes before its start contradicts itself, and reads as ended."""
    if flow.end_date is not None and flow.end_date < on:
        return "ended"
    if flow.start_date is not None and flow.start_date > on:
        return "scheduled"
    return "in force"


def compute_flows_in_force(db: Session, on: str) -> dict:
    """The income and expenses IN FORCE on `on`, as a monthly run-rate in the
    base currency, with the ones still to start and the ones that have ended
    listed apart and never counted (`flow_status`).

    The one computation behind every monthly figure: the Cash flow page and
    the Dashboard (`/api/dashboard/cashflow`), the chat's context and the
    analyst's. The page and the chat used to read a run-rate that ignored the
    dates, so a salary that starts next month was summed as one running now,
    and a gym cancelled in the spring was still being paid, with nothing on
    screen or in the chat to say either. Brief Z moved the analysis off it;
    brief AI the rest.

    Beyond the filter, three cases had to be decided:

    - A flow with NO start date is counted as in force, and counted in
      `undated` so the reader of the figure can be told. The cash register
      makes the opposite choice for its own reason: a projection cannot place
      an undated occurrence in time, so it adds nothing for it.
    - A one-off adds nothing a month. One still to come is listed with the
      scheduled flows: it is money that will move.
    - A flow that has ENDED is listed apart, so whoever reads the figures can
      say why it is not in them.

    `in_force`, `scheduled` and `ended` list each flow as the chat prints it,
    with the name the reader gave it, how it is classified and its id (for
    the page, which marks its own rows), and never its notes, which the chat
    does not read either (the reader's choice, 2026-10-02, for the analyst to
    read the records as the chat does)."""
    conv = fx.Converter(db)

    def monthly(flow) -> float:
        return _monthly(conv.to_base_or_as_stored(flow.amount, flow.currency), flow.frequency)

    def described(flow, side: str, classified: str | None) -> dict:
        return {
            "side": side,
            "id": flow.id,
            "name": flow.name,
            "classified": classified,
            "category": flow.category,
            "amount": flow.amount,
            "currency": flow.currency,
            "frequency": flow.frequency,
            "start_date": flow.start_date,
            "end_date": flow.end_date,
        }

    flows = [
        (described(i, "income", i.kind), i)
        for i in db.scalars(select(models.IncomeSource).order_by(models.IncomeSource.id))
    ] + [
        (described(e, "expense", e.nature), e)
        for e in db.scalars(select(models.Expense).order_by(models.Expense.id))
    ]
    by_status: dict[str, list[tuple[dict, object]]] = {"in force": [], "scheduled": [], "ended": []}
    for shown, flow in flows:
        by_status[flow_status(flow, on)].append((shown, flow))
    running = by_status["in force"]
    running_in = [flow for shown, flow in running if shown["side"] == "income"]
    running_out = [flow for shown, flow in running if shown["side"] == "expense"]
    monthly_income = sum(monthly(i) for i in running_in)
    monthly_expenses = sum(monthly(e) for e in running_out)
    monthly_net = monthly_income - monthly_expenses

    return {
        "on": on,
        # How many are in force, so "none" can be told from a sum of zero.
        "incomes_in_force": len(running_in),
        "expenses_in_force": len(running_out),
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        "monthly_net": monthly_net,
        "savings_rate": (monthly_net / monthly_income) if monthly_income > 0 else None,
        "active_income": sum(monthly(i) for i in running_in if i.kind == "active"),
        "passive_income": sum(monthly(i) for i in running_in if i.kind == "passive"),
        "essential_expenses": sum(monthly(e) for e in running_out if e.nature == "essential"),
        "discretionary_expenses": sum(
            monthly(e) for e in running_out if e.nature == "discretionary"
        ),
        "undated": sum(1 for f in running_in + running_out if f.start_date is None),
        "in_force": [shown for shown, _ in running],
        "scheduled": sorted(
            (shown for shown, _ in by_status["scheduled"]),
            key=lambda f: (f["start_date"], f["side"]),
        ),
        "ended": sorted(
            (shown for shown, _ in by_status["ended"]),
            key=lambda f: (f["end_date"], f["side"]),
        ),
        "base_currency": conv.base,
    }
