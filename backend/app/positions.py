"""What you currently hold, and the one definition of what it is worth.

A *position* is the anchor+events model applied to investments: each
institution's latest snapshot (a dated photograph of what was there) projected
forward with the ledger entries strictly AFTER that snapshot's date. A newer
photograph re-bases, so nothing is double-counted — the same rule the cash
register runs on.

This module exists because that projection is a SHAPE, not a dict. It used to
be fifteen keys built at two construction sites and read by four modules across
three layers, with nothing anywhere declaring what was in it — so consumers
hedged: ``p["currency_note"]`` next to ``p.get("closed_on")`` next to
``p.get("cost_estimated", False)``, for keys that are always present at both
sites. Every one of those is now an attribute a type checker knows about.

The field that mattered most is `current_value`. "Market where the market can
price it, basis where it cannot" was written out twice, in two modules, and the
two bodies disagreed — which is exactly how the dashboard once showed two
financial totals, one above the other, differing by the size of the portfolio's
unrealised gain. It is a property here, with one body, and there is nowhere
else to put a second one.

`replay` is the other thing that lives here rather than being written out
again: average-cost accounting over a position's ledger entries. It was
implemented three times — here, inline in the net worth series, and again in
the dividend path — and the three did not agree. Two of them routed a `close`
into the `else: # buy` arm, so a disposal ADDED its proceeds to the book value
and left the position open; the third ignored a close entirely. There are four
kinds of entry and all four are now named in one place. The one thing the
callers really do differ on, whether the boundary date is included, is a
parameter (`until`, exclusive) instead of a loop each of them writes for
itself.

FX: one `Converter` is threaded through the whole projection and handed back to
the caller, so the rate date that priced these numbers is available to whoever
displays them. Two converters used to run — one for the book values inside the
projection, one for the market values outside it — and the first was discarded,
so a converted figure could reach the screen with no rate date attached to it.
"""

from __future__ import annotations

import decimal
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud, dated, fx, models


# --- Valuing what a photograph recorded ------------------------------------


def amount_in_base(
    amount: float, h: models.Holding, conv: fx.Converter, listing_currency: str | None = None
) -> float:
    """An amount recorded ON a holding, in the base, using that holding's currency
    rule: for a quantity-based position the listing currency wins, since such a
    figure was entered as units x a price in that listing. Shared by `value`
    and `cost_basis` so the two can never drift apart on the conversion."""
    currency = listing_currency if (listing_currency and h.quantity is not None) else h.currency
    return conv.to_base_or_as_stored(amount, currency)


def holding_book_in_base(
    h: models.Holding, conv: fx.Converter, listing_currency: str | None = None
) -> float:
    """A holding's recorded value in the base currency.

    `listing_currency` (the currency its ticker actually trades in) WINS when
    the holding is quantity-based, and for a provable reason: such a value was
    entered as quantity x unit price of that listing, so it cannot be in any
    other currency. Trusting the hand-typed field instead produced a phantom
    profit — a fund labelled USD (its share class) but quoted in EUR in Milan
    had its book divided by the exchange rate while its market value was not,
    and the difference showed up as a 17% gain that never happened.

    With no listing currency known, the holding's own stated one is used. If a rate is missing
    the raw amount passes through: a visible near-miss beats a dropped
    position."""
    return amount_in_base(h.value or 0.0, h, conv, listing_currency)


def holdings_in_base(
    db: Session,
    holdings: Sequence[models.Holding],
    conv: fx.Converter | None = None,
) -> dict[int, float]:
    """Each holding's recorded value in the base currency, keyed by holding id.

    The one way to add photographed rows together. `holding_book_in_base` needs a
    listing currency and a `Converter`, and a Converter needs a session — which
    is the whole reason `Snapshot.value` could not do this and summed lira as
    if they were euro. Anything that totals holdings asks this, so the rule
    that cost a phantom 17% gain is applied once and cannot be re-derived
    wrongly beside it.

    The listing currencies come from the price cache, keyed on SYMBOL with no
    date: a listing's currency does not change, so a photograph from January
    reads the same one the portfolio reads today. That is why a stored
    situation is not a weaker reading than the projection's — it is the same
    figure, from the same lookup. A symbol nothing has ever priced has no
    cached currency, and then both fall back to the hand-typed field, together.

    One price-cache read and one rate load for the whole list, so totalling a
    list of situations costs the same as totalling one."""
    if conv is None:
        conv = fx.Converter(db)
    symbols = sorted({h.symbol for h in holdings if h.symbol})
    listing = {
        sym: q.get("currency")
        for sym, q in (crud.get_cached_prices(db, symbols) if symbols else {}).items()
    }
    return {
        h.id: holding_book_in_base(h, conv, listing.get(h.symbol) if h.symbol else None)
        for h in holdings
    }


def snapshot_values_in_base(
    db: Session,
    snapshots: Sequence[models.Snapshot],
    conv: fx.Converter | None = None,
) -> dict[int, float]:
    """Each situation's value in the base currency — the sum of its holdings — keyed by id.

    It takes a LIST because the situations list endpoint has one, and asking
    per-snapshot would re-read the price cache and reload the rates once per
    row. Pass the snapshots with their holdings already loaded (see
    `crud.get_snapshots_for_institution`): this walks `snap.holdings`, and a
    lazy collection makes that a query per situation."""
    per_holding = holdings_in_base(db, [h for s in snapshots for h in s.holdings], conv)
    return {s.id: sum(per_holding[h.id] for h in s.holdings) for s in snapshots}


@dataclass(frozen=True, slots=True)
class Opening:
    """How a photographed row opens, before any ledger entry is applied: what
    it recorded, what of that was paid and for how many units.

    One reading for the two walks that open a row: `project`, from the latest
    situation, and `recover_paid`, from every situation (brief AW). Read twice,
    the rule for a cost that paid for some of the units would have had two
    bodies to drift apart."""

    # The value the photograph recorded, in the base.
    from_photo: float
    # A cost typed on the row, in the base; None where none was.
    recorded_cost: float | None
    # The units that cost paid for, when it says it paid for some of them.
    covered: float | None
    book: float
    paid: float
    units_paid: float | None
    estimated: bool


def open_photographed(
    h: models.Holding, conv: fx.Converter, quote_ccy: str | None
) -> Opening:
    """A photographed row's opening, in the base (see `Opening`)."""
    # A value-only lump keeps the photograph's figures unchanged: there
    # is no quantity to add units to or remove units from, so the
    # ledger has nothing to merge into it.
    from_photo = holding_book_in_base(h, conv, quote_ccy)
    # A cost the user typed is a cost whether or not the row has units.
    # It used to be read in one place only, the branch that DISPOSES
    # of a position, so the same holding said "cost unknown" for as
    # long as it was held and then measured its gain against the
    # recorded figure the moment it was closed: one number in the
    # database, two opposite answers, decided by whether you had sold.
    # Answering it while held is only payable now: while `current_value`
    # fell back to the book, making the book the cost took the
    # difference straight out of the net worth.
    recorded_cost = (
        amount_in_base(h.cost_basis, h, conv, quote_ccy)
        if h.cost_basis is not None
        else None
    )
    # A cost that paid for only some of the units (`cost_quantity`,
    # brief AV): what a new situation started from the last writes on
    # a row partly bought since the one before. Those units open at
    # that cost, the others at the photograph's value.
    covered = (
        h.cost_quantity
        if (recorded_cost is not None and h.cost_quantity is not None and h.quantity
            and h.cost_quantity < h.quantity and from_photo != 0)
        else None
    )
    if covered is not None:
        book = recorded_cost + from_photo * (h.quantity - covered) / h.quantity
    else:
        book = recorded_cost if recorded_cost is not None else from_photo
    # What of that book was PAID, and for how many units (brief AV):
    # all of it where a cost is recorded, the part its units cover
    # where it says so, none where the book is a photograph's value. A
    # photograph that recorded no value and no cost puts its units in
    # the paid pool at zero, which is how they have always been read
    # (as costing nothing, and cost_known once a buy joins them): kept
    # as it was, and filed under STILL OPEN.
    if covered is not None:
        paid, units_paid = recorded_cost, covered
    elif recorded_cost is not None or from_photo == 0:
        paid, units_paid = recorded_cost or 0.0, h.quantity
    else:
        paid, units_paid = 0.0, (None if h.quantity is None else 0.0)
    return Opening(
        from_photo=from_photo,
        recorded_cost=recorded_cost,
        covered=covered,
        book=book,
        paid=paid,
        units_paid=units_paid,
        estimated=bool(h.cost_estimated) if recorded_cost is not None else False,
    )


def latest_snapshot_by_institution(
    db: Session, as_of: str | None = None
) -> dict[int, models.Snapshot]:
    """For each institution id, its most recent snapshot — the anchor photo:
    what a projection starts from, and the cut-off that decides which ledger
    entries are still 'after the photo'.

    `as_of` asks the same question of a past date: the photograph that was in
    force THEN. That is the whole of what the net worth series needs in order
    to run on the projection instead of on a carry-forward of its own. Left
    out, the date is TODAY — never "whatever the newest row happens to be".
    They used to be the same call, and a snapshot dated next week was then the
    anchor for now: an empty one emptied the portfolio, with nothing sold and
    no day passed.

    The walk itself is `dated.latest_per_parent`; this name stays because
    "the anchor photo" is what callers mean, and the type says Snapshot."""
    return dated.latest_per_parent(
        db,
        models.Snapshot,
        models.Snapshot.institution_id,
        on_or_before=as_of or dated.today(),
    )


# --- The shape --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Position:
    """One investment position, as it stands today.

    Frozen because a projection is a reading, not a record: nothing downstream
    should be able to adjust a number and have the adjustment travel to the
    next consumer. Every field is always set at both construction sites — the
    snapshot path and the ledger-born path — so no reader needs a default."""

    institution_id: int | None
    asset_name: str
    symbol: str | None
    isin: str | None
    asset_class: str | None
    distribution_policy: str | None
    quantity: float | None
    # What the position COST, in the base: a recorded purchase where there is one,
    # otherwise the value the photograph was taken at (and then `cost_known`
    # is False, because that is not a price anybody paid).
    book_value: float
    # What the position was last OBSERVED to be worth: the figure its
    # photograph recorded, carried forward with the ledger entries after it.
    # Distinct from book_value because a photograph is an observation of VALUE
    # and a recorded cost_basis is a price PAID, and the two are different
    # facts about the same row — the receipt says 400, the statement says 500.
    # For a position born in the ledger the two coincide: nothing ever
    # photographed it, so what was paid is the only observation there is.
    observed_value: float
    # What it is worth NOW, from the price cache — None when nothing can price
    # it (no ticker, no quantity, or no quote).
    market_value: float | None
    # What the disposals realized on the units paid for: a gain or a loss.
    realized_pl: float
    # What they realized on a photograph's value with no cost: the movement
    # since it, not a profit (brief AV; see `replay`).
    realized_movement: float
    dividends: float
    # The part of `dividends` that is still the market's GROSS figure. An
    # auto-recorded dividend is what the issuer declared per share, which no
    # withholding has been taken out of yet (`pac.execute_dividends`); the
    # moment the reader corrects the row with the credit their broker actually
    # paid, the amount becomes the net one and `estimated` clears in the same
    # gesture. There is no gross/net column, so this flag is the only thing
    # that separates the rows a tax estimate may still be applied to from the
    # rows where applying one would tax the same money twice.
    dividends_estimated: float
    # NOT `cost_basis is not None`: a blend of a recorded cost and a snapshot
    # value is not a known cost, and claiming it is makes the P/L lie. True
    # when ALL of the book is money paid, which `book_paid` says in figures.
    cost_known: bool
    # True when any unit behind the PAID part of that cost was not priced off a
    # contract note: a photographed cost DERIVED from a broker's reported %
    # return, or a buy still marked estimated, which is a plan's buy at the
    # market close until the reader corrects it (`replay` carries it). It said
    # "every unit came from a recorded fill" of every position born in the
    # ledger, PAC buys included, until brief AI; and it was false on a blend
    # whatever its buys were, until brief AV.
    cost_estimated: bool
    # Of `book_value`, the money PAID: a buy's cash, or a cost recorded on the
    # photograph. The rest of the book is a photograph's value that no cost was
    # recorded for. One row mixes the two as soon as a plan or a buy adds to a
    # position photographed without its cost, which used to make the whole row
    # "cost unknown" (brief AV, measured: 300.00 of 1,300.00 paid, the row said
    # it knew none of it). Equal to `book_value` when `cost_known`.
    book_paid: float
    # The units that money paid for, of `quantity`: a buy's own units, and a
    # photograph's whose cost is recorded. They keep their own average price,
    # so the part of a P/L that is a gain is the one on the units actually
    # bought (`replay`). None on a row with no units.
    units_paid: float | None
    # The date this position was last CONFIRMED — the photo it sits in, or its
    # most recent ledger entry if it never appeared in one. Two different
    # things age here and calling both "stale" hides the difference: on a
    # priced row the value is today's and only the claim "I hold 24 units" is
    # old, while an opaque row is old in every respect and nothing can refresh
    # it. The row carries the date; the reader is told which kind.
    observed_on: str
    # Set when a `close` entry disposed of this position after the photo.
    closed_on: str | None
    # Set when the hand-typed currency disagrees with the listing's own, so the
    # UI can point at a field worth correcting.
    currency_note: str | None

    @property
    def current_value(self) -> float:
        """What this position is worth now: its market value where the market
        can price it, its last OBSERVED value where it cannot.

        The ONE definition. The fallback is deliberately not `book_value`: that
        is what the position cost, and a question about worth must not be
        answered with a price somebody paid. It used to be, and the two
        mechanisms of the net worth chart disagreed about it in public — every
        historical point showed the photograph's 500 while today's point and
        the Dashboard showed the receipt's 400, for the same position on the
        same screen.

        Callers that show a total are expected to also say how much of it came
        from each — an unpriceable lump valued at last month's photo is not the
        same fact as a live quote, and `is_priced` is how a row says which it
        is."""
        return self.market_value if self.market_value is not None else (self.observed_value or 0.0)

    @property
    def is_priced(self) -> bool:
        """Whether the market could put a number on this position today."""
        return self.market_value is not None


@dataclass(frozen=True, slots=True)
class PositionState:
    """A position after its ledger entries have been applied: the units held,
    what they cost, and the cash the ledger has already handed back — realized
    on a disposal, collected as a dividend.

    Named because three modules used to walk the same entries and each keep a
    different subset of this reading. The projection kept all four numbers;
    the net worth series kept two and emitted a delta per event instead of a
    state; the dividend path kept only the quantity. Nothing anywhere said
    they were the same walk, so nothing stopped them drifting — and they had."""

    quantity: float
    book: float
    # What the disposals realized on the units PAID for: a gain or a loss
    # against a price paid. Their result on a photograph's value with no cost
    # is `realized_movement` (brief AV).
    realized_pl: float
    dividends: float
    # Of that dividend cash, how much is still the market's gross figure —
    # see the field of the same name on `Position` for why the distinction
    # cannot be recovered from the amounts alone.
    dividends_estimated: float
    # Whether the units held include one whose price was estimated: a buy
    # still marked estimated, or an opening the caller said was. Cleared when
    # the walk empties the position, since no unit is left behind it.
    cost_estimated: bool = False
    # The paid pool (brief AV): of `book`, the money paid, and the units it
    # paid for. See `replay` for how each kind of entry moves it.
    paid: float = 0.0
    paid_units: float = 0.0
    # What the disposals realized on the rest: the movement since a
    # photograph whose value no cost was recorded for. Not a profit, and not
    # what a tax is estimated on; `realized_pl` plus this is the whole result.
    realized_movement: float = 0.0


# --- The projection ---------------------------------------------------------


def replay(
    entries: list[models.Transaction],
    *,
    start_qty: float = 0.0,
    start_book: float = 0.0,
    start_estimated: bool = False,
    start_paid: float | None = None,
    start_paid_units: float | None = None,
    start_whole: bool | None = None,
    until: str | None = None,
    amount_of: Callable[[models.Transaction], float] | None = None,
) -> PositionState:
    """Average-cost accounting: apply ledger entries in date order to a
    position that starts at (start_qty, start_book). A buy adds units at cost;
    a sell removes units at the RUNNING AVERAGE cost — the gap between that
    cost and its proceeds is its result; a dividend only collects cash; a
    close takes the position in its entirety, so what its proceeds are
    measured against is the WHOLE remaining book. A sell of more units than
    held is clamped (data-entry error, not short selling).

    A sell and a close follow ONE rule for what their result is (brief AV, the
    reader's choice): the part on the units paid for is a gain or a loss,
    `realized_pl`; the rest, on a photograph's value with no cost, is
    `realized_movement`, named and not called a profit. The part paid is the
    proceeds those units fetched (their share of the units disposed of) less
    what the pool paid for them. It used to be two rules: a sell counted its
    whole result as a gain, and a close of a row with no recorded cost counted
    nothing, so one event had two answers (measured: +130.00 sold, 0.00
    closed). With no unit held there is no share to take, and `start_whole`
    decides: all of it a gain where everything was paid, all of it movement
    where it was not. Left out, it is read off the opening.

    There are FOUR kinds and all four are named here. Routing the fourth into
    `else: # buy` is what made a close read as a purchase: its proceeds added
    to the book value, the position left open, and the same money reported as
    held and as spent at the same time.

    `until` is an ISO date and it is EXCLUSIVE — an entry ON that date is not
    applied. It is in the signature because it is the one thing the callers
    genuinely disagree about: the dividend path needs the units held STRICTLY
    before the ex-date (you have to own the shares before it), the projection
    wants everything. A boundary that turns on < against <= is not something a
    reader should have to recover by comparing three copies of a loop.

    `start_estimated` says the opening's cost was itself estimated. A buy
    still marked estimated (a plan's buy at the market close, until the
    reader corrects it) makes the units held estimated too, whatever the
    others cost: an average over them is no contract note's figure. A walk
    that empties the position clears it.

    `start_paid` and `start_paid_units` say how much of the opening was money
    paid, and for how many of its units (brief AV): the PAID POOL. Left out,
    the opening is taken as paid, as every caller but the projection's
    photographed rows means it. A buy adds its cash and its units to the pool;
    a sell of u units from qty takes u/qty of the pool's units and of its
    money, which is the money the book loses in proportion, so the book stays
    average cost and the pool keeps its own average price; a close empties it;
    a dividend does not touch it. What the pool holds is what was bought, at
    what it cost: on a fund photographed at 195 with no cost and 4 units bought
    since at 191.50, a price of 200 is +34.00 on the 4 and a movement of +30.00
    on the 6, where a share of the money would have said +25.32 and +38.68.

    `amount_of` is how an entry's cash figure enters the book: the stored
    `amount` when left out, which is right only for a caller that reads units
    alone (the dividend path). An amount is in its entry's own `currency`, and
    a book adds entries together, so a caller that reads money passes the
    conversion — the projection passes its converter."""
    qty, book = start_qty, start_book
    paid = start_book if start_paid is None else start_paid
    paid_units = start_qty if start_paid_units is None else start_paid_units
    # Whether everything is paid, for a disposal when no unit is held: a
    # value-only row, or a position already emptied. With units, the pool says.
    whole = start_whole if start_whole is not None else (
        paid_units >= qty if qty > 0 else paid >= book
    )
    realized = movement = dividends = dividends_estimated = 0.0
    estimated = start_estimated
    for t in sorted(entries, key=lambda t: (t.date, t.id)):
        if until is not None and t.date >= until:
            break
        cash = amount_of(t) if amount_of is not None else t.amount
        if t.kind == "sell":
            avg = (book / qty) if qty > 0 else 0.0
            sold = min(t.quantity, max(qty, 0.0))
            result = cash - sold * avg
            if qty > 0:
                # The same expression as the book's, so a pool that is the
                # whole book stays exactly the whole book, and its gain is
                # exactly the whole result.
                paid_out = sold * (paid / qty)
                gain = cash * (paid_units / qty) - paid_out
                paid -= paid_out
                paid_units -= sold * (paid_units / qty)
            else:
                gain = result if whole else 0.0
            book -= sold * avg
            qty = max(qty - t.quantity, 0.0)
            realized += gain
            movement += result - gain
            if qty <= 0:
                estimated = False
        elif t.kind == "close":
            # Everything goes at once. There are no units to price against an
            # average, so the basis is the entire book the entries built.
            result = cash - book
            gain = (cash * (paid_units / qty) - paid) if qty > 0 else (result if whole else 0.0)
            realized += gain
            movement += result - gain
            qty = book = paid = paid_units = 0.0
            estimated = False
        elif t.kind == "dividend":
            dividends += cash
            # Split here and nowhere else. Three modules used to walk these
            # entries and each keep a different subset, which is why this
            # function exists at all; a caller that recovered the gross share
            # with a query of its own would be the fourth walk, and it would
            # not be filtered by the anchor the way these entries are.
            if t.estimated:
                dividends_estimated += cash
        else:  # buy
            if qty <= 0:
                whole = True  # a position bought from nothing is all paid
            qty += t.quantity
            book += cash
            paid += cash
            paid_units += t.quantity
            if t.estimated:
                estimated = True
        if qty > 0:
            whole = paid_units >= qty
    return PositionState(
        qty, book, realized, dividends, dividends_estimated, estimated, paid, paid_units,
        movement,
    )


def _closed_on(entries: list[models.Transaction], quantity: float | None) -> str | None:
    """The day the last close among `entries` disposed of the position, while
    it holds no units.

    A position bought again after its close is open again, and "disposed of"
    beside the units it holds would be false. Measured on the ledger-born path
    (brief AV): closed, then 2 units bought, it read closed_on with the 2 held.
    One rule on both paths."""
    if quantity is not None and quantity > 0:
        return None
    last = max((t for t in entries if t.kind == "close"), key=lambda t: (t.date, t.id), default=None)
    return last.date if last is not None else None


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    """Everything `project` reads from the database, loaded once.

    It exists so the net worth series can project at 130 different dates
    without asking for the same three tables 130 times. Every date shares the
    snapshots, the ledger and the listing currencies; only the anchor moves."""

    snapshots: list[models.Snapshot]
    transactions: list[models.Transaction]
    listing: dict[str, str | None]
    quotes: dict[str, dict]


def load_projection_inputs(db: Session) -> ProjectionInputs:
    """The three reads `project` needs, in three queries."""
    snapshots = list(db.scalars(select(models.Snapshot)))
    txs = list(db.scalars(select(models.Transaction)))
    # What each ticker actually trades in — the authority for a qty-based
    # holding's book value (see holding_book_in_base) — and its cached price.
    symbols = sorted({h.symbol for snap in snapshots for h in snap.holdings if h.symbol}
                     | {t.symbol for t in txs if t.symbol})
    cached = crud.get_cached_prices(db, symbols) if symbols else {}
    return ProjectionInputs(
        snapshots=snapshots,
        transactions=txs,
        listing={sym: q.get("currency") for sym, q in cached.items()},
        quotes=cached,
    )


def project(
    db: Session,
    conv: fx.Converter | None = None,
    *,
    as_of: str | None = None,
    inputs: ProjectionInputs | None = None,
) -> list[Position]:
    """Current investment positions = each institution's latest snapshot
    holdings projected forward with the ledger entries strictly AFTER that
    snapshot's date and no later than today (a newer snapshot re-bases, so
    nothing is double-counted — same anchor+events model, and the same
    `(anchor, today]` interval, as the cash register). Ledger entries for symbols
    absent from the latest snapshot create new positions. Fully-sold positions
    disappear from the list but keep their realized P/L / dividends in the
    rows that produced them. Book values are in the base: a holding recorded in
    another currency converts at the ECB rate BEFORE the ledger (base cash
    amounts) is applied on top.

    Pass `conv` to share one converter with the rest of a computation — its
    `used_as_of` then covers every conversion that fed the numbers a caller is
    about to display, book and market alike. Left out, the projection makes its
    own and the rate date goes nowhere.

    `as_of` (ISO date) asks the same question of a PAST day: the photograph in
    force then, projected with the entries in `(anchor, as_of]`. The market is
    left out of a past day on purpose — a quote is today's fact, and pricing
    history with it invents a past that never happened — so every position
    comes back unpriced and `current_value` is its last observed value. This is what the net
    worth series now runs on, instead of a carry-forward of the photographs
    with an overlay of its own: that mechanism had no way to retract a position
    the ledger had closed, so a disposed row kept counting at every historical
    date after its own exit.

    Every position comes back with BOTH readings — `book_value` (what it cost)
    and `observed_value` (what its photograph said it was worth) — because a
    caller asking for a history of net worth and a caller asking what the P/L
    is are asking different questions of the same row. There is no parameter to
    pick one: a projection that answered only the question its caller happened
    to request is how the two ended up on the same screen disagreeing.

    `inputs` reuses one load of the tables across many dates (see
    `load_projection_inputs`); left out, this makes its own."""
    if conv is None:
        conv = fx.Converter(db)
    if inputs is None:
        inputs = load_projection_inputs(db)
    # `as_of=None` means today, not the end of time — for the photograph AND
    # for the ledger. `day` is that bound, and every read below takes it.
    # `as_of` itself stays None when the caller asked about now: it is also how
    # this function knows the market is allowed to speak, which a past day's
    # projection must not let it do.
    #
    # The ledger half was missing. A photograph cannot describe a day that has
    # not happened, and that was bounded; an ENTRY dated after today was still
    # applied to today, while the cash register stopped at today. So a buy
    # scheduled ten days out brought its units at once and its cost never: 10
    # units held became 20, investments 1000.00 -> 2000.00, cash unmoved, and
    # the net worth gained the purchase from nothing. Storing such an entry
    # stays allowed — a scheduled buy is a fact the reader may state — and it
    # is applied on its day, in the position and in the cash together.
    day = as_of or dated.today()
    fin_latest = dated.latest_per_parent_of(
        inputs.snapshots,
        lambda s: s.institution_id,
        on_or_before=day,
    )
    txs = inputs.transactions
    listing = inputs.listing

    def cash(t: models.Transaction) -> float:
        """An entry's cash figure in the base: stored in its own `currency`, and
        converted by the same converter as every other figure here, so a
        purchase debited in dollars adds dollars to no euro book."""
        return conv.to_base_or_as_stored(t.amount, t.currency)

    def _later_txs(inst_id: int | None, symbol: str) -> list[models.Transaction]:
        return dated.events_after(
            fin_latest.get(inst_id),
            (t for t in txs if t.institution_id == inst_id and t.symbol == symbol),
            until=day,
        )

    def _closes(inst_id: int | None, h: models.Holding, anchor: str) -> list[models.Transaction]:
        """The `close` entries that disposed of this row after the photo, in
        date order.

        Matched on the ticker when there is one and on the name when there is
        not — because the rows that most need an exit are exactly the ones no
        ticker describes, and until now their only way out was to vanish from a
        photograph, which is the silent deletion this is meant to replace."""
        return sorted(
            (
                t for t in dated.events_after(anchor, txs, until=day)
                if t.kind == "close" and t.institution_id == inst_id
                and ((h.symbol and t.symbol == h.symbol) or t.asset_name == h.asset_name)
            ),
            key=lambda t: (t.date, t.id),
        )

    out: list[Position] = []  # merged view: snapshot holdings + ledger
    seen: set[tuple[int | None, str]] = set()
    for inst_id, snap in fin_latest.items():
        for h in snap.holdings:
            if (h.asset_class or "") == "cash":
                continue  # cash lives in the register
            quote_ccy = listing.get(h.symbol) if h.symbol else None
            opened = open_photographed(h, conv, quote_ccy)
            from_photo, recorded_cost = opened.from_photo, opened.recorded_cost
            quantity, observed, book = h.quantity, from_photo, opened.book
            cost_known_from_photo = recorded_cost is not None and opened.covered is None
            realized = movement = dividends = dividends_estimated = 0.0
            # True once a recorded purchase contributes to the book: only then
            # is "average cost" a price actually paid rather than the price at
            # which a snapshot happened to be taken.
            cost_known = cost_known_from_photo
            cost_estimated = opened.estimated
            closed_on: str | None = None
            paid, units_paid = opened.paid, opened.units_paid
            opening = book

            closes = _closes(inst_id, h, snap.date)
            if h.symbol and h.quantity is not None:
                # Merge the ledger only into quantity-based holdings: every
                # entry of its ticker after the photo, and a close that names
                # the row without its ticker. The close is walked like any
                # other entry (brief AV). Settled against the photograph alone,
                # it counted what was bought since as gain (+530.00 where
                # selling the same units realized +230.00), dropped the
                # dividends before it from the totals, and lost a buy after it.
                seen.add((inst_id, h.symbol))
                later = _later_txs(inst_id, h.symbol)
                later += [t for t in closes if t.symbol != h.symbol]
                # A recorded cost is the basis when there is one (the same
                # figure read above, for every photographed row). Otherwise the
                # photograph's value stands in — and then it is NOT a cost, and
                # the row says so; where the cost paid for some of the units,
                # both, each for its own units (`opening`).
                recorded = recorded_cost
                walked = replay(
                    later,
                    start_qty=h.quantity,
                    start_book=opening,
                    start_estimated=recorded is not None and bool(h.cost_estimated),
                    start_paid=paid,
                    start_paid_units=units_paid,
                    amount_of=cash,
                )
                quantity, book = walked.quantity, walked.book
                paid, units_paid = walked.paid, walked.paid_units
                realized, dividends = walked.realized_pl, walked.dividends
                movement = walked.realized_movement
                dividends_estimated = walked.dividends_estimated
                closed_on = _closed_on(later, quantity)
                # The same walk, opened at what the photograph SAID instead of
                # at what was paid. Two openings, one set of entries: a buy adds
                # its cost to both, a sell removes units at each walk's own
                # running average — so the value reading stays a value reading
                # all the way along, instead of being the cost reading wearing
                # a different label. When no cost was recorded the two openings
                # are the same number and this is the same walk twice, which is
                # cheap and keeps the field always meaningful.
                #
                # A photograph that recorded no VALUE (a quantity typed with no
                # price) is not an observation of zero — it is no observation,
                # and opening the walk at 0 made a position the user said cost
                # 400 report a worth of nothing, dragging the whole net worth
                # down with it. The rule is the ledger-born one, applied to the
                # same fact: with no photographed value, what was paid is the
                # only observation there is.
                observed = (
                    walked.book
                    if (recorded is None or from_photo == 0)
                    else replay(
                        later, start_qty=h.quantity, start_book=from_photo, amount_of=cash
                    ).book
                )
                # True only when EVERY unit's basis is a price paid: either the
                # cost was recorded, or the photograph contributed nothing and
                # the whole position came from the ledger. One buy on top of a
                # photograph is not enough — that basis is a blend, and letting
                # a blend claim to be a cost is how a mostly-invented figure
                # starts presenting itself as profit. A cost recorded for some
                # of the units only is not either; `book_paid` says how much
                # of the book was paid (brief AV).
                cost_known = cost_known_from_photo or (
                    from_photo == 0 and any(t.kind == "buy" for t in later)
                )
                # And estimated when any unit behind the part PAID is: the
                # photograph's derived cost, or a plan's buy at the close on
                # top of it. It read the photograph alone, so a recorded cost
                # with plan buys added claimed a contract note for all of it;
                # and it asked `cost_known` first, so a photograph with plan
                # buys on top said nothing of theirs (brief AV).
                cost_estimated = walked.cost_estimated
            elif closes:
                # A row with no units, or no ticker: the ledger merges nothing
                # into it but its first close, which settles it whole. The same
                # walk counts it, so a row with no units is paid all or nothing,
                # by whether a cost is recorded: with none, its result is the
                # movement since the photograph, said as such, where it used
                # to be 0.00.
                closed = closes[0]
                walked = replay(
                    [closed],
                    start_qty=h.quantity or 0.0,
                    start_book=book,
                    start_paid=paid,
                    start_paid_units=units_paid or 0.0,
                    start_whole=recorded_cost is not None,
                    amount_of=cash,
                )
                quantity, book, observed = 0.0, 0.0, 0.0
                paid, units_paid = 0.0, 0.0
                realized, movement = walked.realized_pl, walked.realized_movement
                closed_on = closed.date
                if h.symbol:
                    seen.add((inst_id, h.symbol))

            out.append(
                Position(
                    institution_id=inst_id,
                    asset_name=h.asset_name,
                    symbol=h.symbol,
                    isin=h.isin,
                    asset_class=h.asset_class,
                    distribution_policy=h.distribution_policy,
                    quantity=quantity,
                    book_value=book,
                    observed_value=observed,
                    market_value=None,  # priced in one batch below
                    realized_pl=realized,
                    realized_movement=movement,
                    dividends=dividends,
                    dividends_estimated=dividends_estimated,
                    cost_known=cost_known,
                    cost_estimated=cost_estimated,
                    book_paid=paid,
                    units_paid=units_paid,
                    observed_on=snap.date,
                    closed_on=closed_on,
                    currency_note=(
                        f"recorded as {h.currency}, but {h.symbol} trades in {quote_ccy}"
                        if (quote_ccy and h.currency and h.quantity is not None
                            and quote_ccy.upper() != h.currency.upper())
                        else None
                    ),
                )
            )

    # Positions born purely from the ledger (no holding in the latest
    # snapshot). Only a SYMBOLED entry can start one: the schema refuses a buy
    # or a sell with no ticker, so the only entry that can carry a null symbol
    # is a close — and a close settles a row some photograph took, which
    # `_closes` binds by NAME above. Reaching one again here gave it a second
    # position of its own: the Gold bar closed for 430 was reported as +80 on
    # the row that actually held it and +430 again on a row that never
    # existed. It also put a null symbol into a sort against a real one, which
    # is a TypeError rather than a number.
    ledger_born = {
        (t.institution_id, t.symbol)
        for t in txs
        if t.symbol and t.date <= day
    } - seen
    for inst_id, symbol in sorted(ledger_born, key=lambda k: (k[0] or 0, k[1])):
        later = _later_txs(inst_id, symbol)
        if not later:
            continue  # everything predates the snapshot: it's in the photo
        walked = replay(later, amount_of=cash)
        # The entry that disposed of this row, for its DATE alone — replay has
        # already taken the position out of the numbers. The snapshot path asks
        # the same question of `_closes`, which also has to match on the asset
        # NAME; here the entries were selected by symbol already, so the last
        # close among them is the answer. Without this a position that only
        # ever existed in the ledger had no way to be shown as closed:
        # `_closes` reads snapshot holdings, and this one is in none.
        qty, book = walked.quantity, walked.book
        realized, divs = walked.realized_pl, walked.dividends
        closed_on = _closed_on(later, qty)
        if (
            not any(t.kind == "close" for t in later)
            and qty <= 0 and not realized and not walked.realized_movement and not divs
        ):
            continue
        latest = max(later, key=lambda t: (t.date, t.id))
        out.append(
            Position(
                institution_id=inst_id,
                asset_name=latest.asset_name,
                symbol=symbol,
                isin=next((x.isin for x in later if x.isin), None),
                asset_class=latest.asset_class,
                distribution_policy=None,
                quantity=qty,
                book_value=book,
                # Nothing ever photographed this row, so what was paid is the
                # only observation of its value there is.
                observed_value=book,
                market_value=None,
                realized_pl=realized,
                realized_movement=walked.realized_movement,
                dividends=divs,
                dividends_estimated=walked.dividends_estimated,
                cost_known=any(t.kind == "buy" for t in later),
                # Every unit came from a recorded buy, and a plan's buy is
                # priced at the market close and marked estimated: the cost
                # is estimated while one of those is behind the units held.
                cost_estimated=walked.cost_estimated,
                # All of it paid, by construction: nothing was photographed.
                book_paid=walked.paid,
                units_paid=walked.paid_units,
                # Born from the ledger: its quantity was last confirmed by its
                # most recent entry, not by any photograph.
                observed_on=latest.date,
                closed_on=closed_on,
                currency_note=None,
            )
        )

    # What each position is worth NOW, from the price cache — no network, so
    # every consumer of this projection (net worth, allocation, look-through
    # weights) gets today's value without the dashboard waiting on Yahoo.
    #
    # This is the field that lets `book_value` finally mean one thing. It used
    # to serve four consumers with two incompatible needs: three wanted "what
    # is it worth" and one wanted "what did it cost", and all four got "what
    # the photograph said" — which is neither.
    if as_of is not None:
        return out  # a past day has no market; see the docstring
    cached = inputs.quotes

    def _market(p: Position) -> float | None:
        quote = cached.get(p.symbol) if (p.symbol and p.quantity is not None) else None
        if quote is None:
            return None
        return conv.to_base(p.quantity * quote["price"], quote.get("currency"))

    return [replace(p, market_value=_market(p)) for p in out]


# --- What was paid before the latest situation (brief AW) -------------------


def units_agree(walked: float, stated: float) -> bool:
    """Whether a situation holds the units the ledger walks to.

    Equal but for float noise; or, for a figure typed from a statement, equal
    at the decimals it was typed with, while half a unit at those decimals is
    at most a thousandth of the units. A broker prints its units rounded
    (12.7346 for the 12.734563 its contract notes add up to), and a situation
    started from the last one writes the walk's own float, which the first
    test takes. Measured (brief AW): typed at 2, 3 or 4 decimals against a
    ledger of 6, an exact rule called each one a disagreement, and the
    purchases before it went unread; typed at 0 or 1 decimal (13, 12.7 for
    12.7346), the bound refuses what rounding alone would let through. A
    stored float keeps no trailing zero ("12.70" reads as one decimal), which
    can only make the rule more lenient, within the bound."""
    if _same(walked, stated):
        return True
    half = 0.5 * 10.0 ** -_decimals(stated)
    if half > 0.001 * abs(stated):
        return False
    return abs(walked - stated) <= half * (1 + 1e-9)


def _same(a: float, b: float) -> bool:
    """Equal but for the noise float arithmetic adds."""
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _decimals(figure: float) -> int:
    """The decimals a figure was typed with, read off its shortest repr:
    12.7346 has four, 13.0 none."""
    exponent = decimal.Decimal(repr(figure)).normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def typed_cost(h: models.Holding) -> bool:
    """Whether a row's cost is the reader's own: for every unit, and not an
    estimate.

    No form writes anything else: a cost the reader changes is sent with
    `cost_quantity` null and `cost_estimated` false (brief AV), and the chat's
    tools write no cost. A cost for some of the units, or one still marked
    estimated, was written by "Start from the last one" (or an API client)
    from the ledger, which the walk can read again."""
    return (
        h.cost_basis is not None
        and (h.cost_quantity is None or (h.quantity is not None and h.cost_quantity >= h.quantity))
        and not h.cost_estimated
    )


@dataclass(frozen=True, slots=True)
class LedgerLine:
    """An entry the walk read into a paid part, as a proposal shows it."""

    date: str
    kind: str
    quantity: float
    amount: float  # in the base
    estimated: bool


@dataclass(frozen=True, slots=True)
class PaidProposal:
    """What the ledger paid for a row of a latest situation, where the row
    says less, or says it from a cost the ledger has since corrected."""

    holding_id: int
    institution_id: int
    asset_name: str
    symbol: str
    situation_date: str
    quantity: float
    # What the walk carries: money paid, in the base, and for how many units.
    paid: float
    units: float
    estimated: bool
    # Where the walk started reading, and the cost recorded there when it
    # started from one: part of `paid`, said apart from the purchases.
    since: str
    opening_paid: float | None
    opening_units: float | None
    entries: tuple[LedgerLine, ...]
    # What the row says today: nothing paid, or a cost "Start from the last
    # one" carried, which the proposal then updates (both figures are said).
    row_paid: float
    row_units: float
    row_estimated: bool


@dataclass(frozen=True, slots=True)
class UnreadPurchases:
    """Purchases on record the walk could not read into a row of a latest
    situation, because a situation's units disagreed with the ledger's: the
    most recent such situation, one per row, so they do not leave in
    silence."""

    holding_id: int
    institution_id: int
    asset_name: str
    symbol: str
    situation_date: str  # the situation that disagreed
    stated_units: float
    walked_units: float
    paid: float  # not read, in the base
    units: float
    since: str
    purchases: int
    # A cost recorded where the reading started, part of `paid`, said apart
    # from the purchases.
    opening_paid: float | None


@dataclass(frozen=True, slots=True)
class Recovery:
    """What `recover_paid` found."""

    proposals: list[PaidProposal]
    unread: list[UnreadPurchases]


@dataclass(slots=True)
class _Pool:
    """A row as the walk holds it between two situations: the units, the
    book, and the paid pool of `replay`."""

    quantity: float
    book: float
    paid: float
    paid_units: float
    estimated: bool
    # Units a photograph recorded with no value and no cost sit in the paid
    # pool at zero (`open_photographed`, STILL OPEN): nothing bought them, so
    # nothing is proposed from a pool that holds them.
    unbought: bool = False


@dataclass(frozen=True, slots=True)
class _Drop:
    """Where a disagreement left paid units unread, kept until the walk ends."""

    date: str
    stated: float
    walked: float
    paid: float
    units: float
    since: str
    purchases: int
    opening_paid: float | None


def recover_paid(
    inputs: ProjectionInputs,
    conv: fx.Converter,
    *,
    day: str,
    declined: Collection[int] = (),
) -> Recovery:
    """What the ledger paid for each row of a latest situation that the row
    does not say: one walk across every situation of each account, per row
    with a ticker and units, in date order, with the ledger between them.

    Why: `project` reads the ledger only after each account's latest
    situation, so a purchase before it is read only through what that
    situation recorded. On a row carried by the code before brief AV, the
    purchases were folded into the situation's value (measured: 110.00 read as
    paid where the ledger held 410.00). This proposes them back and writes
    nothing; `paid_recovery` writes a proposal on the reader's press.

    Each stretch of the ledger goes through `replay` and its two pools, one
    entry at a time, so that a position emptied on the way starts its
    purchases again. A row opens at the first situation of its account that
    holds it, as `project` opens it (`open_photographed`); what the ledger
    holds on or before an account's first situation is in that photograph and
    is not read. At each later situation:

    * units that agree (`units_agree`): the paid pool carries, and the other
      units open again at that situation's value. A cost "Start from the last
      one" carried there is read again from the same ledger.
    * a cost the reader typed for every unit (`typed_cost`): their figure, and
      the walk starts again from it.
    * units that disagree: the walk cannot know what was bought there, so it
      starts again from what the row states (the reader's rule, 2026-10-15),
      and says when that left purchases on record unread (`UnreadPurchases`).
    * a row the reader declined (`declined`, holding ids): the walk starts
      again there, so what was declined is never proposed again, on it or on
      a situation started from it later. Measured: remembered as "not this
      row" only, the next situation brought the same proposal back.

    Proposed, on a latest row with nothing paid, when the walk carries paid
    units; on one whose cost was carried, when the walk differs in units, in
    the estimate, or in money by more than half a cent. Money is compared only
    when every purchase is in the row's own currency: the amounts convert at
    today's rate, while a carried cost was converted on its own day, and a
    rate's move alone is no correction. Never proposed: a cost the reader
    typed, a row with no value and no cost, a ticker on two rows of one
    situation (the walk cannot say which), units no purchase bought."""

    def cash(t: models.Transaction) -> float:
        return conv.to_base_or_as_stored(t.amount, t.currency)

    by_inst: dict[int, list[models.Snapshot]] = {}
    for snap in inputs.snapshots:
        if snap.date <= day:
            by_inst.setdefault(snap.institution_id, []).append(snap)
    proposals: list[PaidProposal] = []
    unread: list[UnreadPurchases] = []
    for inst_id, snaps in sorted(by_inst.items()):
        snaps.sort(key=lambda s: (s.date, s.id))
        ledger = [
            t for t in inputs.transactions
            if t.institution_id == inst_id and t.symbol and t.date <= day
        ]
        for symbol in sorted({h.symbol for s in snaps for h in s.holdings if _walked(h)}):
            row = _RowWalk(symbol, inputs.listing.get(symbol), conv, cash, declined)
            prev: str | None = None
            for snap in snaps:
                if prev is not None:
                    row.stretch(
                        sorted(
                            dated.events_after(
                                prev, (t for t in ledger if t.symbol == symbol), until=snap.date
                            ),
                            key=lambda t: (t.date, t.id),
                        ),
                        prev,
                    )
                row.situation(snap)
                prev = snap.date
            proposal, left = row.found(snaps[-1])
            if proposal is not None:
                proposals.append(proposal)
            if left is not None:
                unread.append(left)
    return Recovery(proposals, unread)


def _walked(h: models.Holding) -> bool:
    """A row the ledger can buy into: a ticker and units, and not cash."""
    return bool(h.symbol) and h.quantity is not None and (h.asset_class or "") != "cash"


class _RowWalk:
    """One row's walk across its account's situations (see `recover_paid`)."""

    def __init__(
        self,
        symbol: str,
        quote_ccy: str | None,
        conv: fx.Converter,
        cash: Callable[[models.Transaction], float],
        declined: Collection[int],
    ):
        self.symbol, self.quote_ccy, self.conv = symbol, quote_ccy, conv
        self.cash, self.declined = cash, declined
        self.pool: _Pool | None = None
        # Where the reading starts, the cost recorded there if any, and the
        # entries read since: what a proposal shows.
        self.since: str | None = None
        self.opening: tuple[float, float] | None = None
        self.read: list[models.Transaction] = []
        self.drop: _Drop | None = None
        # The pool as it reached the last situation, before that situation
        # took it: what a proposal compares with the row.
        self.walked: _Pool | None = None
        self.verdict = ""

    def _start(self, h: models.Holding, opened: Opening, date: str) -> None:
        """Start again at a situation, from what its row states."""
        self.pool = _Pool(
            h.quantity, opened.book, opened.paid, opened.units_paid or 0.0, opened.estimated,
            unbought=opened.recorded_cost is None and opened.from_photo == 0 and h.quantity > 0,
        )
        self.since, self.read = date, []
        self.opening = (
            (opened.paid, opened.units_paid)
            if opened.recorded_cost is not None and (opened.units_paid or 0.0) > 0
            else None
        )

    def _forget(self) -> None:
        self.pool, self.since, self.opening, self.read, self.drop = None, None, None, [], None

    def stretch(self, entries: list[models.Transaction], after: str) -> None:
        """The ledger between two situations, through `replay`."""
        for t in entries:
            if self.pool is None:
                # Held by no situation before: read from nothing.
                self.pool = _Pool(0.0, 0.0, 0.0, 0.0, False)
                self.since, self.read, self.opening = after, [], None
            state = replay(
                [t],
                start_qty=self.pool.quantity,
                start_book=self.pool.book,
                start_estimated=self.pool.estimated,
                start_paid=self.pool.paid,
                start_paid_units=self.pool.paid_units,
                amount_of=self.cash,
            )
            self.pool = _Pool(
                state.quantity, state.book, state.paid, state.paid_units,
                state.cost_estimated, self.pool.unbought and state.quantity > 0,
            )
            if t.kind in ("buy", "sell"):
                self.read.append(t)
            if state.quantity <= 0:
                # Emptied: nothing bought before stands behind a unit now.
                self.since, self.read, self.opening = t.date, [], None

    def situation(self, snap: models.Snapshot) -> None:
        """What a situation says of the row, against what the walk holds."""
        rows = [h for h in snap.holdings if h.symbol == self.symbol and _walked(h)]
        self.walked = None
        if len(rows) > 1:
            self.verdict = "doubled"
            self._forget()
            return
        if not rows:
            self.verdict = "absent"
            if self.pool is not None and self.pool.quantity > 0:
                # The ledger holds what the situation does not: the omission
                # notice speaks for it, and the walk starts again from nothing.
                self._forget()
            return
        (h,) = rows
        opened = open_photographed(h, self.conv, self.quote_ccy)
        if h.id in self.declined:
            self.verdict, self.drop = "declined", None
            self._start(h, opened, snap.date)
        elif self.pool is None:
            self.verdict, self.drop = "opens", None
            self._start(h, opened, snap.date)
        elif units_agree(self.pool.quantity, h.quantity):
            if typed_cost(h):
                self.verdict, self.drop = "typed cost", None
                self._start(h, opened, snap.date)
                return
            self.verdict, self.walked = "agrees", self.pool
            units = min(self.pool.paid_units, h.quantity)
            unit_value = opened.from_photo / h.quantity if h.quantity else 0.0
            self.pool = _Pool(
                h.quantity, self.pool.paid + unit_value * (h.quantity - units),
                self.pool.paid, units, self.pool.estimated, self.pool.unbought,
            )
        else:
            lost = self.pool.paid_units - (opened.units_paid or 0.0)
            bought = sum(1 for t in self.read if t.kind == "buy")
            if bought and lost > 1e-9 * max(1.0, self.pool.paid_units) and not self.pool.unbought:
                self.drop = _Drop(
                    snap.date, h.quantity, self.pool.quantity, self.pool.paid - opened.paid,
                    lost, self.since or snap.date, bought,
                    self.opening[0] if self.opening else None,
                )
            self.verdict = "disagrees"
            self._start(h, opened, snap.date)

    def found(
        self, latest: models.Snapshot
    ) -> tuple[PaidProposal | None, UnreadPurchases | None]:
        """The proposal and the unread purchases for the row of the latest
        situation, if it holds the row once."""
        rows = [h for h in latest.holdings if h.symbol == self.symbol and _walked(h)]
        if len(rows) != 1:
            return None, None
        (h,) = rows
        left = None
        if self.drop is not None:
            d = self.drop
            left = UnreadPurchases(
                holding_id=h.id, institution_id=latest.institution_id,
                asset_name=h.asset_name, symbol=self.symbol, situation_date=d.date,
                stated_units=d.stated, walked_units=d.walked, paid=d.paid, units=d.units,
                since=d.since, purchases=d.purchases, opening_paid=d.opening_paid,
            )
        w = self.walked
        if self.verdict != "agrees" or w is None or w.unbought:
            return None, left
        opened = open_photographed(h, self.conv, self.quote_ccy)
        units = min(w.paid_units, h.quantity)
        if opened.recorded_cost is None:
            differs = opened.from_photo != 0 and not _same(units, 0.0)
        else:
            row_ccy = self.quote_ccy if self.quote_ccy else h.currency
            in_its_own = all(t.currency == row_ccy for t in self.read if t.kind == "buy")
            differs = (
                not _same(units, opened.units_paid or 0.0)
                or w.estimated != opened.estimated
                or (in_its_own and abs(w.paid - opened.paid) > 0.005)
            )
        if not differs:
            return None, left
        return PaidProposal(
            holding_id=h.id,
            institution_id=latest.institution_id,
            asset_name=h.asset_name,
            symbol=self.symbol,
            situation_date=latest.date,
            quantity=h.quantity,
            paid=w.paid,
            units=units,
            estimated=w.estimated,
            since=self.since or latest.date,
            opening_paid=self.opening[0] if self.opening else None,
            opening_units=self.opening[1] if self.opening else None,
            entries=tuple(
                LedgerLine(t.date, t.kind, t.quantity, self.cash(t), bool(t.estimated))
                for t in self.read
            ),
            row_paid=opened.paid if opened.recorded_cost is not None else 0.0,
            row_units=(opened.units_paid or 0.0) if opened.recorded_cost is not None else 0.0,
            row_estimated=opened.estimated,
        ), left
