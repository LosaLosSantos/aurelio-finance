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

from collections.abc import Callable, Sequence
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
    realized_pl: float
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
    # value is not a known cost, and claiming it is makes the P/L lie.
    cost_known: bool
    # True when any unit behind that cost was not priced off a contract note:
    # a photographed cost DERIVED from a broker's reported % return, or a buy
    # still marked estimated, which is a plan's buy at the market close until
    # the reader corrects it (`replay` carries it). It said "every unit came
    # from a recorded fill" of every position born in the ledger, PAC buys
    # included, until brief AI.
    cost_estimated: bool
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


# --- The projection ---------------------------------------------------------


def replay(
    entries: list[models.Transaction],
    *,
    start_qty: float = 0.0,
    start_book: float = 0.0,
    start_estimated: bool = False,
    until: str | None = None,
    amount_of: Callable[[models.Transaction], float] | None = None,
) -> PositionState:
    """Average-cost accounting: apply ledger entries in date order to a
    position that starts at (start_qty, start_book). A buy adds units at cost;
    a sell removes units at the RUNNING AVERAGE cost — the gap between that
    cost and its proceeds is the realized P/L; a dividend only collects cash;
    a close takes the position in its entirety, so what its proceeds are
    measured against is the WHOLE remaining book. A sell of more units than
    held is clamped (data-entry error, not short selling).

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

    `amount_of` is how an entry's cash figure enters the book: the stored
    `amount` when left out, which is right only for a caller that reads units
    alone (the dividend path). An amount is in its entry's own `currency`, and
    a book adds entries together, so a caller that reads money passes the
    conversion — the projection passes its converter."""
    qty, book = start_qty, start_book
    realized = dividends = dividends_estimated = 0.0
    estimated = start_estimated
    for t in sorted(entries, key=lambda t: (t.date, t.id)):
        if until is not None and t.date >= until:
            break
        cash = amount_of(t) if amount_of is not None else t.amount
        if t.kind == "sell":
            avg = (book / qty) if qty > 0 else 0.0
            sold = min(t.quantity, max(qty, 0.0))
            book -= sold * avg
            qty = max(qty - t.quantity, 0.0)
            realized += cash - sold * avg
            if qty <= 0:
                estimated = False
        elif t.kind == "close":
            # Everything goes at once. There are no units to price against an
            # average, so the basis is the entire book the entries built.
            realized += cash - book
            qty = book = 0.0
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
            qty += t.quantity
            book += cash
            if t.estimated:
                estimated = True
    return PositionState(qty, book, realized, dividends, dividends_estimated, estimated)


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

    def _closure(inst_id: int | None, h: models.Holding, anchor: str):
        """The `close` entry that disposed of this row after the photo, if any.

        Matched on the ticker when there is one and on the name when there is
        not — because the rows that most need an exit are exactly the ones no
        ticker describes, and until now their only way out was to vanish from a
        photograph, which is the silent deletion this is meant to replace."""
        for t in dated.events_after(anchor, txs, until=day):
            if t.kind != "close" or t.institution_id != inst_id:
                continue
            if (h.symbol and t.symbol == h.symbol) or t.asset_name == h.asset_name:
                return t
        return None

    out: list[Position] = []  # merged view: snapshot holdings + ledger
    seen: set[tuple[int | None, str]] = set()
    for inst_id, snap in fin_latest.items():
        for h in snap.holdings:
            if (h.asset_class or "") == "cash":
                continue  # cash lives in the register
            quote_ccy = listing.get(h.symbol) if h.symbol else None
            # A value-only lump keeps the photograph's figures unchanged: there
            # is no quantity to add units to or remove units from, so the
            # ledger has nothing to merge into it.
            from_photo = holding_book_in_base(h, conv, quote_ccy)
            quantity, observed = h.quantity, from_photo
            # A cost the user typed is a cost whether or not the row has units.
            # It used to be read in one place only — the branch that DISPOSES
            # of a position — so the same holding said "cost unknown" for as
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
            book = recorded_cost if recorded_cost is not None else from_photo
            cost_known_from_photo = recorded_cost is not None
            realized = dividends = dividends_estimated = 0.0
            # True once a recorded purchase contributes to the book: only then
            # is "average cost" a price actually paid rather than the price at
            # which a snapshot happened to be taken.
            cost_known = cost_known_from_photo
            cost_estimated = bool(h.cost_estimated) if cost_known_from_photo else False
            closed_on: str | None = None

            closed = _closure(inst_id, h, snap.date)
            if closed is not None:
                # Gone, and where it went is on record. The position keeps the
                # gain it locked in but stops counting toward what you hold.
                opening = (
                    amount_in_base(h.cost_basis, h, conv, quote_ccy)
                    if h.cost_basis is not None
                    else from_photo
                )
                quantity, book, observed = 0.0, 0.0, 0.0
                realized = (cash(closed) - opening) if h.cost_basis is not None else 0.0
                cost_known = h.cost_basis is not None
                closed_on = closed.date
                if h.symbol:
                    seen.add((inst_id, h.symbol))
            elif h.symbol and h.quantity is not None:
                # Merge the ledger only into quantity-based holdings.
                seen.add((inst_id, h.symbol))
                later = _later_txs(inst_id, h.symbol)
                # A recorded cost is the basis when there is one (the same
                # figure read above, for every photographed row). Otherwise the
                # photograph's value stands in — and then it is NOT a cost, and
                # the row says so.
                recorded = recorded_cost
                opening = recorded if recorded is not None else from_photo
                walked = replay(
                    later,
                    start_qty=h.quantity,
                    start_book=opening,
                    start_estimated=recorded is not None and bool(h.cost_estimated),
                    amount_of=cash,
                )
                quantity, book = walked.quantity, walked.book
                realized, dividends = walked.realized_pl, walked.dividends
                dividends_estimated = walked.dividends_estimated
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
                # starts presenting itself as profit.
                cost_known = recorded is not None or (
                    from_photo == 0 and any(t.kind == "buy" for t in later)
                )
                # And estimated when any unit behind that cost is: the
                # photograph's derived cost, or a plan's buy at the close on
                # top of it. It read the photograph alone, so a recorded cost
                # with plan buys added claimed a contract note for all of it.
                cost_estimated = cost_known and walked.cost_estimated

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
                    dividends=dividends,
                    dividends_estimated=dividends_estimated,
                    cost_known=cost_known,
                    cost_estimated=cost_estimated,
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
    # `_closure` binds by NAME above. Reaching one again here gave it a second
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
        # the same question through `_closure`, which also has to match on the
        # asset NAME; here the entries were selected by symbol already, so the
        # last close among them is the answer. Without this a position that
        # only ever existed in the ledger had no way to be shown as closed:
        # `_closure` iterates snapshot holdings, and this one is in none.
        closed = max(
            (t for t in later if t.kind == "close"),
            key=lambda t: (t.date, t.id),
            default=None,
        )
        qty, book = walked.quantity, walked.book
        realized, divs = walked.realized_pl, walked.dividends
        if closed is None and qty <= 0 and not realized and not divs:
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
                dividends=divs,
                dividends_estimated=walked.dividends_estimated,
                cost_known=any(t.kind == "buy" for t in later),
                # Every unit came from a recorded buy, and a plan's buy is
                # priced at the market close and marked estimated: the cost
                # is estimated while one of those is behind the units held.
                cost_estimated=walked.cost_estimated,
                # Born from the ledger: its quantity was last confirmed by its
                # most recent entry, not by any photograph.
                observed_on=latest.date,
                closed_on=closed.date if closed is not None else None,
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
