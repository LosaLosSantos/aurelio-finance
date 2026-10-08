"""CRUD layer: the functions that read/write to the database.

Why separate it from the endpoints (the routers)? So the data-access logic
is reusable and testable on its own, and the routers stay thin (they receive
the request, call a function here, and return the result).

Convention: every function takes the `Session` as its first argument.

What this layer does NOT decide is where a transaction ends. Every write
finishes with `commit(db)` (app/database.py), which commits only when nobody
above it has opened a `unit_of_work` — because whether two writes belong to
one operation is knowledge the caller has and this layer does not.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app import dated, fx, models, schemas
from app.database import commit

if TYPE_CHECKING:  # `positions` imports this module for the price cache
    from app.positions import Position


T = TypeVar("T")

# A function that turns the columns a request leaves a row with into the
# columns it is STORED with: a ledger entry's cash amount, a transfer's
# arrival, a holding's value. It is handed the whole row rather than the
# payload, because on an edit the two are not the same thing — see `_update`.
# The third argument is the set of keys the request actually sent, which is
# what tells "work this out for me" (an empty box) from "I am not talking
# about it" (no box at all).
Build = Callable[[Session, dict, Collection[str]], dict]


def _columns(data: BaseModel, *, drop: tuple[str, ...] = ()) -> dict:
    """The model kwargs a Create payload stands for.

    The allow-list is the schema itself, which is the honest place for it: a
    `*Create` carries exactly the fields the API lets a caller set, and no id,
    no created_at and no parent foreign key — those live on the matching
    `*Read` and on the function signature. So there is no second list in here
    to keep in step with the first one, which is the whole point: these used to
    be thirteen hand-written field-by-field copies, and the failure mode was
    silent. Add a column, forget a line, and it simply never updates.

    Dates come out as ISO 'YYYY-MM-DD' strings, because that is how every date
    column in models.py is stored. That conversion reads the VALUE rather than
    a per-model list of date fields on purpose — a list is the same forgettable
    line one level up, and this way a new date column is handled the day it is
    added, by nobody.

    `drop` is for a field that is not a column: today only a plan's `targets`,
    which are children.
    """
    payload = data.model_dump(exclude=set(drop))
    return {
        key: value.isoformat() if isinstance(value, datetime.date) else value
        for key, value in payload.items()
    }


def _create(db: Session, obj: T) -> T:
    """Persist a new row and return it loaded (so it carries id and created_at)."""
    db.add(obj)
    commit(db)
    db.refresh(obj)
    return obj


def _apply(db: Session, obj: T, payload: dict) -> T:
    """Write a payload onto an existing row and persist it."""
    for key, value in payload.items():
        setattr(obj, key, value)
    commit(db)
    db.refresh(obj)
    return obj


def _update(
    db: Session,
    model: type[T],
    obj_id: int,
    data: BaseModel,
    *,
    build: Build | None = None,
    drop: tuple[str, ...] = (),
    also: dict | None = None,
) -> T | None:
    """Write what a request SAID onto an existing row, or None if it is gone.

    It used to be a full replace of every settable column, which is what a
    `*Create` describes: a row has to start complete, so `_columns` turning the
    schema into every one of its columns is exactly right for an insert. An
    edit is a different sentence. A PUT whose form never had a box for
    `cash_institution_id` parses it as None, and a full replace then writes
    that None over the account that actually paid — destroying a fact nobody
    was editing, with no box to type it back into. Measured on a scratch
    database: one edit of a buy's quantity moved 300.00 of spending from the
    funding account to the holding one, and turned `fund_etf` into nothing.

    So an absent key and an explicit null are told apart, which only pydantic
    can do: `model_fields_set` carries the keys the request actually sent.
    Absent means leave it alone; `null` means clear it, because emptying a box
    is a real gesture and every form in this app already makes it by sending
    the null (not one of the thirteen clears a field by omitting it).

    The allow-list is still the schema, asserted once in
    `test_write_contract.py` — this decides which of those columns ONE request
    may touch, not what the columns are. And it is one place rather than
    thirteen hand-written copies: that failure mode is recorded in `_columns`
    and was paid for.

    `build` is for a resource whose stored columns are not only the ones it was
    handed — a ledger entry's cash amount, a transfer's arrival. It is given
    the row as this request LEAVES it (stored values under the keys the request
    did not send), because a figure worked out from a payload's defaults would
    be worked out from zeroes. `also` is written whatever the request said, for
    the one thing an edit means by itself: correcting a ledger entry clears
    `estimated`.
    """
    obj = db.get(model, obj_id)
    if obj is None:
        return None
    sent = data.model_fields_set
    row = {
        key: value if key in sent else getattr(obj, key)
        for key, value in _columns(data, drop=drop).items()
    }
    payload = row if build is None else build(db, row, sent)
    return _apply(db, obj, {**_decided(data, payload), **(also or {})})


def _decided(data: BaseModel, payload: dict) -> dict:
    """The part of a built row this request is entitled to write.

    A schema field is written when the request sent it. A key the schema does
    not own is one crud worked out for itself — today only `fx_as_of`, the ECB
    day that turned quantity x price into an amount — and a builder puts one in
    the payload only when this request decided the figure it explains. So its
    presence IS the decision, and it travels with that figure rather than being
    re-stated as a list of the fields it depends on, which would be the same
    forgettable line `_columns` removed one level up.
    """
    return {
        key: value
        for key, value in payload.items()
        if key not in type(data).model_fields or key in data.model_fields_set
    }


def create_institution(
    db: Session, data: schemas.InstitutionCreate
) -> models.Institution:
    """Create and persist a new institution, returning the saved object."""
    return _create(db, models.Institution(**_columns(data)))


def get_institutions(db: Session) -> list[models.Institution]:
    """Return all institutions, ordered by id.

    Eager-loads the snapshots, because `InstitutionRead` exposes
    `latest_snapshot` / `snapshot_count` and serializing the list would
    otherwise emit one SELECT per institution to compute them."""
    stmt = (
        select(models.Institution)
        .options(selectinload(models.Institution.snapshots))
        .order_by(models.Institution.id)
    )
    return list(db.scalars(stmt))


def get_institution(db: Session, institution_id: int) -> models.Institution | None:
    """Return a single institution by id, or None if it does not exist."""
    return db.get(models.Institution, institution_id)


# --- Snapshots ------------------------------------------------------------


def create_snapshot(
    db: Session, institution_id: int, data: schemas.SnapshotCreate
) -> models.Snapshot:
    """Create a dated snapshot for an institution. What it is WORTH is not
    stored and not computed here: see `positions.snapshot_values_in_base`.
    The date is stored as an ISO 'YYYY-MM-DD' string. May raise IntegrityError
    if a snapshot already exists for that institution on that date."""
    return _create(
        db, models.Snapshot(institution_id=institution_id, **_columns(data))
    )


def get_snapshots_for_institution(
    db: Session, institution_id: int
) -> list[models.Snapshot]:
    """Return an institution's snapshots, ordered by date (chronological).

    Holdings come WITH them: the response says what each situation was worth,
    and that is a sum over its holdings. Lazily, it is a query per situation —
    which it already was while the sum lived on the model, unguarded, because
    the N+1 test only covered the two properties on `Institution` and
    `Liability`. It covers this endpoint now too."""
    stmt = (
        select(models.Snapshot)
        .where(models.Snapshot.institution_id == institution_id)
        .order_by(models.Snapshot.date)
        .options(selectinload(models.Snapshot.holdings))
    )
    return list(db.scalars(stmt))


def get_snapshot(db: Session, snapshot_id: int) -> models.Snapshot | None:
    """Return a single snapshot by id, or None if it does not exist."""
    return db.get(models.Snapshot, snapshot_id)


def latest_snapshot_for_institution(
    db: Session, institution_id: int, *, on_or_before: str
) -> models.Snapshot | None:
    """The institution's snapshot in force at `on_or_before`, or None.

    One parent's answer to `dated.latest_per_parent` — kept as a query rather
    than a dict lookup because its two callers (the prefill and the clone) want
    exactly one institution's photograph and would otherwise load every
    institution's to throw all but one away. The bound is required for the same
    reason it is required there: this is the same question, and asking it
    without a date is how a photograph of next week became the one a new
    situation was prefilled from."""
    stmt = (
        select(models.Snapshot)
        .where(
            models.Snapshot.institution_id == institution_id,
            models.Snapshot.date <= on_or_before,
        )
        .order_by(models.Snapshot.date.desc(), models.Snapshot.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def clone_latest_snapshot(
    db: Session,
    institution_id: int,
    date: datetime.date,
    quotes: dict[str, dict] | None = None,
    *,
    projected: list[Position],
) -> tuple[models.Snapshot, list[str]] | None:
    """A new dated snapshot pre-filled from the institution's latest one.

    The reason this exists: the newest snapshot is the authority for the whole
    institution, so a photograph that omits a position DELETES it — silently.
    That makes "update one number" mean "re-declare the entire account", and
    every re-declaration is a chance to drop a row by forgetting it. Starting
    from the previous positions turns an act of memory into an act of review.

    What is copied is the part only the user can know — which instruments, how
    many units. What is RE-DERIVED is the part the market knows: anything with
    a ticker gets `quotes`' price for the new date, because a photograph dated
    today holding last month's prices is precisely the thing that made P/L
    collapse to zero.

    `projected` is the institution's projected positions (snapshot anchor +
    ledger entries after it), and it is required — not the source snapshot's
    raw rows. Copying the raw rows silently swallows every buy and sell made
    since: the new photograph would re-assert the old quantities, and because
    the ledger is anchored to the LATEST snapshot, those entries would then be
    considered "already in the photo" and never counted again. That is the same
    silent deletion this function exists to prevent, coming back through the
    door it left open. It used to be optional with a raw-rows fallback, which
    is to say the door was still there — no caller ever used it.

    A row the LEDGER has moved is restated from the projection, whole: its
    value, its unit price and its cost together. Taking the quantity from the
    projection and everything else from the old photograph is what made a new
    situation destroy net worth — 15 units carried at the value of 10, a unit
    price that did not multiply to it, and a cost from before the purchases,
    so money actually paid stopped being cost and reappeared as profit on a
    row marked cost_known. A row the ledger has NOT moved keeps the
    photograph's own figures untouched: there is nothing to restate, and
    re-deriving them could only lose precision.

    The cost is written ONLY where the projection knows it is one
    (`cost_known`). Where it does not, the projected book is a blend of a
    photograph's value and later purchases, and this app does not call a blend
    a cost — the new photograph then carries no cost rather than invent one.

    Everything the projection computes is in the base currency, while a photograph is
    written in whatever the row is denominated in. The figures are converted
    back before they are stored, or the next projection would convert them a
    second time and the position would shrink by the exchange rate every time
    a situation was recorded.

    Returns (snapshot, opaque) where `opaque` names the rows nothing could
    re-price — the ones actually needing the user's attention. None if the
    institution has no snapshot to clone."""
    source = latest_snapshot_for_institution(
        db, institution_id, on_or_before=dated.today()
    )
    if source is None:
        return None

    quotes = quotes or {}
    # Identity fields the projection does not carry (currency, and the recorded
    # value of an opaque row) still come from the photo they were entered in.
    by_key: dict[str, models.Holding] = {}
    for h in source.holdings:
        by_key[h.symbol or h.asset_name] = h

    snapshot = models.Snapshot(
        institution_id=institution_id,
        date=date.isoformat(),
        note=f"Prefilled from the {source.date} situation",
    )
    db.add(snapshot)
    db.flush()

    # The currency each row will be READ BACK in: for a position with units the
    # listing's own wins, which is the rule the projection already values it
    # by; only then the currency typed on the photograph. Converting into any
    # other one stores a number that means something else than it says.
    #
    # A row with neither — born in the ledger, with no listing currency cached —
    # is written in the base, which is what the projection's figure for it is
    # already in: no conversion, and nothing stated in a currency it is not.
    conv = fx.Converter(db)
    symbols = sorted({p.symbol for p in projected if p.symbol})
    listing = (
        {sym: q.get("currency") for sym, q in get_cached_prices(db, symbols).items()}
        if symbols
        else {}
    )

    opaque: list[str] = []
    for p in projected:
        qty = p.quantity
        if qty is not None and qty <= 0:
            continue  # sold out of it since: it does not belong in this photo
        src = by_key.get(p.symbol or p.asset_name)
        quote = quotes.get(p.symbol) if p.symbol else None
        row_ccy = (
            listing[p.symbol]
            if (p.symbol and qty is not None and listing.get(p.symbol))
            else (src.currency if src is not None else conv.base)
        )
        # Has the ledger moved this row since the photograph? If it has not,
        # the photo still describes it exactly.
        moved = src is None or qty != src.quantity

        if quote is not None and qty is not None:
            unit_price = quote["price"]
            value = qty * quote["price"]
            currency = src.currency if src is not None else conv.base
        elif not moved:
            # Carried forward unchanged, and said out loud: this number is as
            # old as the photo it came from, and only the user can refresh it.
            unit_price, value, currency = src.unit_price, src.value, src.currency
            opaque.append(p.asset_name)
        else:
            # Nothing could re-price it and the ledger HAS changed it, so the
            # photograph's figure no longer describes the row: the projection's
            # reading of what it is worth is the only coherent one. A position
            # born in the ledger and never photographed lands here too — for
            # it, what was paid is the only observation of its value there is.
            native = conv.from_base(p.observed_value, row_ccy)
            if native is None:
                # No rate for that currency today. The photograph's figure is
                # stale; a figure in the wrong currency is wrong, and stale
                # beats wrong. The row is named as needing a human either way.
                unit_price, value, currency = (
                    (src.unit_price, src.value, src.currency)
                    if src is not None
                    else (None, p.observed_value, conv.base)
                )
            else:
                value = native
                # Stated per unit too, and consistent with the total by
                # construction. Not optional: a quantity with no unit price
                # re-opens in the form's "total" mode, which submits
                # quantity: null, so the row would lose its units the first
                # time anyone edited it.
                unit_price = (native / qty) if qty else None
                currency = src.currency if src is not None else conv.base
            opaque.append(p.asset_name)

        # The cost, and only where it IS one.
        if not moved:
            cost_basis = src.cost_basis if src is not None else None
            cost_estimated = src.cost_estimated if src is not None else None
        elif p.cost_known:
            cost_basis = conv.from_base(p.book_value, row_ccy)
            cost_estimated = p.cost_estimated
            if cost_basis is None:  # no rate: keep what the photograph knew
                cost_basis = src.cost_basis if src is not None else None
                cost_estimated = src.cost_estimated if src is not None else None
        else:
            cost_basis = cost_estimated = None
        db.add(
            models.Holding(
                snapshot_id=snapshot.id,
                asset_name=p.asset_name,
                asset_class=p.asset_class,
                symbol=p.symbol,
                isin=p.isin,
                quantity=qty,
                unit_price=unit_price,
                value=value,
                # Never re-derived from the value: re-pricing the value while
                # dropping the cost is what made a new situation forget what
                # you paid, and it is the defect this column exists to end.
                # Carried from the photograph while the ledger has not moved
                # the row, and taken from the projection — which has added the
                # cost of every purchase since — once it has.
                cost_basis=cost_basis,
                cost_estimated=cost_estimated,
                currency=currency,
                distribution_policy=p.distribution_policy,
            )
        )
    commit(db)
    db.refresh(snapshot)
    return snapshot, opaque


# --- Holdings -------------------------------------------------------------


def _clean_isin(raw: str | None) -> str | None:
    """An ISIN is uppercase and unspaced by definition, and it is the key the
    look-through hands to the issuer — so a stray space or a lowercase paste
    would silently cost the country breakdown."""
    cleaned = (raw or "").strip().upper().replace(" ", "")
    return cleaned or None


def _holding_columns(db: Session, row: dict, sent: Collection[str]) -> dict:
    """Holding columns: a cleaned ISIN, and a `value` worked out from quantity
    x unit price when it was not given.

    It takes the session it does not need and the sent keys it does not read,
    because the three builders `_update` calls share one shape — see `Build`.
    """
    payload = dict(row)
    payload["isin"] = _clean_isin(row["isin"])
    if payload["value"] is None and row["quantity"] is not None and row["unit_price"] is not None:
        payload["value"] = row["quantity"] * row["unit_price"]
    return payload


def _holding_payload(db: Session, data: schemas.HoldingCreate) -> dict:
    """The columns a NEW holding is stored with."""
    return _holding_columns(db, _columns(data), data.model_fields_set)


def create_holding(
    db: Session, snapshot_id: int, data: schemas.HoldingCreate
) -> models.Holding:
    """Create a holding within a snapshot. If `value` is not provided but
    quantity and unit_price are, it is computed as quantity * unit_price."""
    return _create(
        db, models.Holding(snapshot_id=snapshot_id, **_holding_payload(db, data))
    )


def get_holdings_for_snapshot(db: Session, snapshot_id: int) -> list[models.Holding]:
    """Return a snapshot's holdings, ordered by id."""
    stmt = (
        select(models.Holding)
        .where(models.Holding.snapshot_id == snapshot_id)
        .order_by(models.Holding.id)
    )
    return list(db.scalars(stmt))


def get_holding(db: Session, holding_id: int) -> models.Holding | None:
    """Return a single holding by id, or None if it does not exist."""
    return db.get(models.Holding, holding_id)


# --- Real assets ----------------------------------------------------------


def create_real_asset(db: Session, data: schemas.RealAssetCreate) -> models.RealAsset:
    """Create and persist a real asset (house, vehicle, collectible, ...)."""
    return _create(db, models.RealAsset(**_columns(data)))


def get_real_assets(db: Session) -> list[models.RealAsset]:
    """Return all real assets, ordered by id."""
    stmt = select(models.RealAsset).order_by(models.RealAsset.id)
    return list(db.scalars(stmt))


def get_real_asset(db: Session, real_asset_id: int) -> models.RealAsset | None:
    """Return a single real asset by id, or None if it does not exist."""
    return db.get(models.RealAsset, real_asset_id)


def create_real_asset_valuation(
    db: Session, real_asset_id: int, data: schemas.RealAssetValuationCreate
) -> models.RealAssetValuation:
    """Create a dated valuation for a real asset. May raise IntegrityError if a
    valuation already exists for that asset on that date (UNIQUE constraint)."""
    return _create(
        db, models.RealAssetValuation(real_asset_id=real_asset_id, **_columns(data))
    )


def get_valuations_for_real_asset(
    db: Session, real_asset_id: int
) -> list[models.RealAssetValuation]:
    """Return a real asset's valuations, ordered by date (chronological)."""
    stmt = (
        select(models.RealAssetValuation)
        .where(models.RealAssetValuation.real_asset_id == real_asset_id)
        .order_by(models.RealAssetValuation.date)
    )
    return list(db.scalars(stmt))


def get_real_asset_valuation(
    db: Session, valuation_id: int
) -> models.RealAssetValuation | None:
    """Return a single valuation by id, or None if it does not exist."""
    return db.get(models.RealAssetValuation, valuation_id)


# --- Liabilities (debts) ----------------------------------------------------


def create_liability(db: Session, data: schemas.LiabilityCreate) -> models.Liability:
    """Create and persist a liability (mortgage, loan, ...)."""
    return _create(db, models.Liability(**_columns(data)))


def get_liabilities(db: Session) -> list[models.Liability]:
    """Return all liabilities, ordered by id.

    Eager-loads the balances for `LiabilityRead.latest_balance` — same N+1,
    same fix as `get_institutions`."""
    stmt = (
        select(models.Liability)
        .options(selectinload(models.Liability.balances))
        .order_by(models.Liability.id)
    )
    return list(db.scalars(stmt))


def get_liability(db: Session, liability_id: int) -> models.Liability | None:
    """Return a single liability by id, or None if it does not exist."""
    return db.get(models.Liability, liability_id)


def update_liability(
    db: Session, liability_id: int, data: schemas.LiabilityCreate
) -> models.Liability | None:
    return _update(db, models.Liability, liability_id, data)


def create_liability_balance(
    db: Session, liability_id: int, data: schemas.LiabilityBalanceCreate
) -> models.LiabilityBalance:
    """Create a dated outstanding balance for a liability. May raise
    IntegrityError if a balance already exists for that liability on that date."""
    return _create(
        db, models.LiabilityBalance(liability_id=liability_id, **_columns(data))
    )


def get_balances_for_liability(
    db: Session, liability_id: int
) -> list[models.LiabilityBalance]:
    """Return a liability's balances, ordered by date (chronological)."""
    stmt = (
        select(models.LiabilityBalance)
        .where(models.LiabilityBalance.liability_id == liability_id)
        .order_by(models.LiabilityBalance.date)
    )
    return list(db.scalars(stmt))


def get_liability_balance(
    db: Session, balance_id: int
) -> models.LiabilityBalance | None:
    """Return a single balance by id, or None if it does not exist."""
    return db.get(models.LiabilityBalance, balance_id)


def update_liability_balance(
    db: Session, balance_id: int, data: schemas.LiabilityBalanceCreate
) -> models.LiabilityBalance | None:
    return _update(db, models.LiabilityBalance, balance_id, data)


# --- Income sources -------------------------------------------------------


def create_income_source(
    db: Session, data: schemas.IncomeSourceCreate
) -> models.IncomeSource:
    """Create and persist an income source (dates stored as ISO strings)."""
    return _create(db, models.IncomeSource(**_columns(data)))


def get_income_sources(db: Session) -> list[models.IncomeSource]:
    """Return all income sources, ordered by id."""
    stmt = select(models.IncomeSource).order_by(models.IncomeSource.id)
    return list(db.scalars(stmt))


def get_income_source(db: Session, income_id: int) -> models.IncomeSource | None:
    """Return a single income source by id, or None if it does not exist."""
    return db.get(models.IncomeSource, income_id)


# --- Expenses -------------------------------------------------------------


def create_expense(db: Session, data: schemas.ExpenseCreate) -> models.Expense:
    """Create and persist an expense (dates stored as ISO strings)."""
    return _create(db, models.Expense(**_columns(data)))


def get_expenses(db: Session) -> list[models.Expense]:
    """Return all expenses, ordered by id."""
    stmt = select(models.Expense).order_by(models.Expense.id)
    return list(db.scalars(stmt))


def get_expense(db: Session, expense_id: int) -> models.Expense | None:
    """Return a single expense by id, or None if it does not exist."""
    return db.get(models.Expense, expense_id)


# --- Cash anchors ---------------------------------------------------------


def create_cash_anchor(
    db: Session, institution_id: int, data: schemas.CashAnchorCreate
) -> models.CashAnchor:
    """Create a dated cash anchor for an institution. May raise IntegrityError
    if an anchor already exists for that institution on that date."""
    return _create(
        db, models.CashAnchor(institution_id=institution_id, **_columns(data))
    )


def get_cash_anchors(db: Session) -> list[models.CashAnchor]:
    """Every institution's cash anchors, by institution then date."""
    stmt = select(models.CashAnchor).order_by(
        models.CashAnchor.institution_id, models.CashAnchor.date
    )
    return list(db.scalars(stmt))


def get_listing_currencies(db: Session) -> dict[str, str]:
    """{symbol: currency} for every listing whose trading currency the price
    cache has learned. Nothing is asked of the market: a listing not priced
    yet is simply absent."""
    stmt = select(models.PriceCache.symbol, models.PriceCache.currency).where(
        models.PriceCache.currency.is_not(None)
    )
    return {symbol: currency for symbol, currency in db.execute(stmt)}


def get_cash_anchors_for_institution(
    db: Session, institution_id: int
) -> list[models.CashAnchor]:
    """Return an institution's cash anchors, ordered by date (chronological)."""
    stmt = (
        select(models.CashAnchor)
        .where(models.CashAnchor.institution_id == institution_id)
        .order_by(models.CashAnchor.date)
    )
    return list(db.scalars(stmt))


def get_cash_anchor(db: Session, anchor_id: int) -> models.CashAnchor | None:
    """Return a single cash anchor by id, or None if it does not exist."""
    return db.get(models.CashAnchor, anchor_id)


def update_cash_anchor(
    db: Session, anchor_id: int, data: schemas.CashAnchorCreate
) -> models.CashAnchor | None:
    return _update(db, models.CashAnchor, anchor_id, data)


# --- Transfers ------------------------------------------------------------


class TransferRateUnknown(ValueError):
    """What reached the destination of a transfer across two currencies cannot
    be worked out, because its day has no final rate. Refused rather than
    guessed: a rate of an earlier day would stay in the sum for good."""


def _transfer_columns(db: Session, row: dict, sent: Collection[str]) -> dict:
    """Transfer columns, with what arrived filled in.

    A stated `to_amount` is kept as typed, with `fx_as_of` empty — it came from
    the destination's statement, and the bank's rate is not the ECB's. Left
    out, it is worked out from `amount` by `fx.convert_on` at the rate final
    for the transfer's DATE: the same sum when the currencies are one (no rate
    is used and none is recorded), and otherwise a sum in cents with the rate's
    day beside it. Never today's rate: an arrival restated at every reading
    would make a balance drift with the exchange rate.

    `fx_as_of` is put in the payload only in those two cases — the day this
    call used, or the empty that a figure off a statement means — because it
    explains ONE figure and is written exactly when that figure is. An edit
    that never mentioned the arrival leaves both alone rather than stripping
    the rate's day off a sum it did not touch (`_decided`)."""
    payload = dict(row)
    if payload.get("to_amount") is None:
        arrived, fx_day = fx.convert_on(
            db, row["amount"], row["currency"], row["to_currency"], row["date"]
        )
        if arrived is None:
            raise TransferRateUnknown(
                f"No final exchange rate from {row['currency']} to {row['to_currency']} is "
                f"known for {row['date']} yet, so what reached the destination "
                f"cannot be worked out in {row['to_currency']}. State the amount that "
                "arrived: the figure on the destination account's statement."
            )
        payload["to_amount"] = round(arrived, 2) if fx_day is not None else arrived
        payload["fx_as_of"] = fx_day
    elif "to_amount" in sent:
        payload["fx_as_of"] = None
    return payload


def _transfer_payload(db: Session, data: schemas.TransferCreate) -> dict:
    """The columns a NEW transfer is stored with."""
    return _transfer_columns(db, _columns(data), data.model_fields_set)


def create_transfer(db: Session, data: schemas.TransferCreate) -> models.Transfer:
    """Create a cash transfer between institutions (date stored as ISO string)."""
    return _create(db, models.Transfer(**_transfer_payload(db, data)))


def get_transfers(db: Session) -> list[models.Transfer]:
    """Return all transfers, ordered by date (chronological)."""
    stmt = select(models.Transfer).order_by(models.Transfer.date)
    return list(db.scalars(stmt))


def get_transfer(db: Session, transfer_id: int) -> models.Transfer | None:
    """Return a single transfer by id, or None if it does not exist."""
    return db.get(models.Transfer, transfer_id)


def update_transfer(
    db: Session, transfer_id: int, data: schemas.TransferCreate
) -> models.Transfer | None:
    return _update(db, models.Transfer, transfer_id, data, build=_transfer_columns)


# --- Deletes --------------------------------------------------------------
# Deleting a parent cascades to its children (ORM cascade + SQLite ON DELETE
# CASCADE): e.g. deleting an institution removes its accounts -> snapshots ->
# holdings. Each helper returns True if the row existed and was deleted.


def _delete(db: Session, obj: object | None) -> bool:
    if obj is None:
        return False
    db.delete(obj)
    commit(db)
    return True


def delete_institution(db: Session, institution_id: int) -> bool:
    return _delete(db, db.get(models.Institution, institution_id))


def delete_snapshot(db: Session, snapshot_id: int) -> bool:
    return _delete(db, db.get(models.Snapshot, snapshot_id))


def delete_holding(db: Session, holding_id: int) -> bool:
    return _delete(db, db.get(models.Holding, holding_id))


def delete_real_asset(db: Session, real_asset_id: int) -> bool:
    return _delete(db, db.get(models.RealAsset, real_asset_id))


def delete_real_asset_valuation(db: Session, valuation_id: int) -> bool:
    return _delete(db, db.get(models.RealAssetValuation, valuation_id))


def delete_liability(db: Session, liability_id: int) -> bool:
    return _delete(db, db.get(models.Liability, liability_id))


def delete_liability_balance(db: Session, balance_id: int) -> bool:
    return _delete(db, db.get(models.LiabilityBalance, balance_id))


def delete_income_source(db: Session, income_id: int) -> bool:
    return _delete(db, db.get(models.IncomeSource, income_id))


def delete_expense(db: Session, expense_id: int) -> bool:
    return _delete(db, db.get(models.Expense, expense_id))


def delete_cash_anchor(db: Session, anchor_id: int) -> bool:
    return _delete(db, db.get(models.CashAnchor, anchor_id))


def delete_transfer(db: Session, transfer_id: int) -> bool:
    return _delete(db, db.get(models.Transfer, transfer_id))


# --- Survey (planning questionnaire) --------------------------------------


def get_survey_responses(db: Session) -> list[models.SurveyResponse]:
    """Return all stored questionnaire answers, ordered by id."""
    stmt = select(models.SurveyResponse).order_by(models.SurveyResponse.id)
    return list(db.scalars(stmt))


def upsert_survey_response(
    db: Session,
    question_key: str,
    answer: str | None,
    *,
    topic: str | None = None,
    question: str | None = None,
) -> models.SurveyResponse:
    """Write ONE questionnaire answer, by key, leaving every other one alone.

    The other write path below replaces the entire questionnaire — it deletes
    all of it and reinserts what it was handed. That is right for the form,
    which renders every question and posts them all back, and it is
    catastrophic for a caller that knows about one: a chat told "I turned 31"
    would erase the profile in order to fill in a line of it.

    `topic` and `question` are written only when they are given, so a caller
    correcting an answer cannot blank the label the question is filed under, or
    replace the form's wording with a paraphrase of it. A None `answer` IS
    written: clearing one is a thing to be able to do, and `_render_survey`
    already reads a blank as unanswered rather than as a stated nothing.

    An answer that changes is dated the day it changed; one written again as
    it was keeps its day (see `models.SurveyResponse.created_at`).
    """
    row = db.scalar(
        select(models.SurveyResponse).where(
            models.SurveyResponse.question_key == question_key
        )
    )
    if row is None:
        return _create(
            db,
            models.SurveyResponse(
                question_key=question_key, topic=topic, question=question, answer=answer
            ),
        )
    payload: dict = {"answer": answer}
    if answer != row.answer:
        payload["created_at"] = models._utcnow_iso()
    if topic is not None:
        payload["topic"] = topic
    if question is not None:
        payload["question"] = question
    return _apply(db, row, payload)


def replace_survey_responses(
    db: Session, items: list[schemas.SurveyAnswer]
) -> list[models.SurveyResponse]:
    """Replace the whole set of answers with the provided ones (single user).

    Whole means whole: an answer the payload does not name is DELETED, not left
    alone. That is only safe while the caller sends back everything it read,
    which the Profile form does — including the rows it does not render itself,
    since the chat can now write questions the form never asked. A caller that
    knows about one answer wants `upsert_survey_response` above.

    An answer sent back as it was keeps the day it was recorded. The form sends
    every answer at each Save, and its one button also saves the tax rates and
    the base currency, so reinserting a fresh row dated every answer with the
    day of the last Save, the chat's included: a statement made weeks earlier
    then read to the analysis as made that day.
    """
    # Read before the delete: plain values, since the rows go with it.
    before = {r.question_key: (r.answer, r.created_at) for r in get_survey_responses(db)}
    db.execute(delete(models.SurveyResponse))
    for item in items:
        row = models.SurveyResponse(
            question_key=item.question_key,
            topic=item.topic,
            question=item.question,
            answer=item.answer,
        )
        said, since = before.get(item.question_key, (None, None))
        if since is not None and said == item.answer:
            row.created_at = since
        db.add(row)
    commit(db)
    return get_survey_responses(db)


# --- Watchlist (ideas, not holdings) --------------------------------------


def create_watchlist_item(
    db: Session, data: schemas.WatchlistItemCreate
) -> models.WatchlistItem:
    """Park one idea, with what it rested on. Owns nothing and totals nowhere."""
    return _create(db, models.WatchlistItem(**_columns(data)))


def get_watchlist_items(db: Session) -> list[models.WatchlistItem]:
    """Every line, most recently added first — a watchlist is read from the top."""
    stmt = select(models.WatchlistItem).order_by(models.WatchlistItem.id.desc())
    return list(db.scalars(stmt))


def find_watchlist_item(
    db: Session, *, isin: str | None = None, symbol: str | None = None
) -> models.WatchlistItem | None:
    """The line already watching this fund (by its ISIN) or this share (by its
    symbol, among the lines that have no ISIN), if there is one.

    Suggesting something that is already on the list is not a second idea, it
    is the same one — so the tool refuses rather than filing a duplicate whose
    only difference is which day it was written. A share is looked for only
    among shares: on a fund's line the symbol is a hint, and the same ticker
    there names a listing of that fund, not this share."""
    if isin:
        where = models.WatchlistItem.isin == isin.strip().upper()
    else:
        where = (models.WatchlistItem.isin.is_(None)) & (
            models.WatchlistItem.symbol == (symbol or "").strip().upper()
        )
    return db.scalars(select(models.WatchlistItem).where(where)).first()


def delete_watchlist_item(db: Session, item_id: int) -> bool:
    return _delete(db, db.get(models.WatchlistItem, item_id))


# --- Goals ----------------------------------------------------------------


def create_goal(db: Session, data: schemas.GoalCreate) -> models.Goal:
    """Create and persist a goal (the target_date is stored as an ISO string)."""
    return _create(db, models.Goal(**_columns(data)))


def get_goals(db: Session) -> list[models.Goal]:
    """Return all goals, ordered by id."""
    stmt = select(models.Goal).order_by(models.Goal.id)
    return list(db.scalars(stmt))


# --- Transactions (the investment ledger) ---------------------------------


class LedgerRateUnknown(ValueError):
    """The debit of an entry across two currencies cannot be worked out,
    because no rate is known for its day. Refused rather than guessed."""


def _transaction_columns(db: Session, row: dict, sent: Collection[str]) -> dict:
    """Ledger columns: ISO date, amount defaulted per kind — a buy costs
    quantity*price + fees; a sell/dividend nets quantity*price - fees
    (proceeds after fees, floored at 0), worked out in cents. An amount the
    reader states is kept as stated.

    quantity*price is in `price_currency` and the fees and the amount are in
    `currency`, so when the two differ the gross is converted first — at the
    rates in force on the entry's DATE, never today's. An account is debited a
    fixed sum on the day; working it out again at the current rate would make
    the balance of a euro account drift with the dollar. The day of the rate
    used is stored beside the figure as `fx_as_of`, which is also what says the
    figure was derived here and not copied from a statement: an amount the
    reader typed is kept as typed, with `fx_as_of` empty.

    Which is why `fx_as_of` is written only when this call decided the amount
    — worked it out, or was handed one. An edit that never mentioned the amount
    leaves the pair alone; see `_decided`."""
    payload = dict(row)
    if payload.get("amount") is None:
        gross, fx_day = fx.convert_on(
            db,
            row["quantity"] * row["unit_price"],
            row["price_currency"] or row["currency"],
            row["currency"],
            row["date"],
        )
        if gross is None:
            raise LedgerRateUnknown(
                f"No exchange rate from {row['price_currency']} to {row['currency']} is "
                f"known for {row['date']}, so the {row['kind']} cannot be "
                f"worked out in {row['currency']}. State the amount from your "
                "statement. That is the figure the account actually moved by."
            )
        fees = row["fees"] or 0.0
        # An account is debited and credited in cents, whichever way the gross
        # was reached: at a rate, from pence into pounds, or in the price's own
        # currency. Only the first was rounded until brief AI, so a dividend of
        # 30 x 0.352345 in the account's currency was stored as
        # 10.570350000000001. Rounded again after the fees, which a float sum
        # can leave a hair off a cent (0.1 + 0.2).
        gross = round(gross, 2)
        moved = gross + fees if row["kind"] == "buy" else max(gross - fees, 0.0)
        payload["amount"] = round(moved, 2)
        payload["fx_as_of"] = fx_day
    elif "amount" in sent:
        payload["fx_as_of"] = None
    return payload


def _transaction_payload(db: Session, data: schemas.TransactionCreate) -> dict:
    """The columns a NEW ledger entry is stored with.

    Reached from `pac` and `tools` as well as from here: what a card says a buy
    will cost is worked out by the function that stores it, not by a second
    copy of the rule."""
    return _transaction_columns(db, _columns(data), data.model_fields_set)


def create_transaction(
    db: Session, data: schemas.TransactionCreate, **extra
) -> models.Transaction:
    """Record a transaction (manual buy, or PAC catch-up via `extra`:
    plan_id, plan_occurrence, estimated)."""
    return store_transaction(db, _transaction_payload(db, data), **extra)


def store_transaction(db: Session, columns: dict, **extra) -> models.Transaction:
    """Record a ledger entry whose columns `_transaction_payload` has already
    worked out.

    For the catch-up, which writes under SQLite's write lock
    (`database.sole_writer`): working the columns out can ask Frankfurter for
    a day's rate, so it is done before the lock is taken, and storing them is
    all that is left to do while it is held."""
    return _create(db, models.Transaction(**columns, **extra))


def get_transactions(db: Session) -> list[models.Transaction]:
    """All transactions, most recent execution date first."""
    stmt = select(models.Transaction).order_by(
        models.Transaction.date.desc(), models.Transaction.id.desc()
    )
    return list(db.scalars(stmt))


def get_transaction(db: Session, tx_id: int) -> models.Transaction | None:
    """A single transaction by id, or None if it does not exist."""
    return db.get(models.Transaction, tx_id)


def update_transaction(
    db: Session, tx_id: int, data: schemas.TransactionCreate
) -> models.Transaction | None:
    """Overwrite a transaction with the payload. Editing marks it as no longer
    estimated: the user has confirmed/corrected it with real numbers."""
    return _update(
        db,
        models.Transaction,
        tx_id,
        data,
        build=_transaction_columns,
        also={"estimated": False},
    )


def delete_transaction(db: Session, tx_id: int) -> bool:
    return _delete(db, db.get(models.Transaction, tx_id))


def get_plan_occurrences_executed(db: Session, plan_id: int) -> set[str]:
    """The schedule slots (plan_occurrence dates) a plan actually BOUGHT on."""
    stmt = select(models.Transaction.plan_occurrence).where(
        models.Transaction.plan_id == plan_id,
        models.Transaction.plan_occurrence.is_not(None),
    )
    return set(db.scalars(stmt))


def get_plan_occurrences_settled(db: Session, plan_id: int) -> set[str]:
    """The schedule slots a plan is FINISHED with — which is not the same
    question. An occurrence is finished if it bought (its transactions carry
    the key) or if it ran and could not afford a unit (recorded, because
    nothing else remembers). The catch-up asks this one; asking the first one
    is what made an unfilled occurrence run again with new money."""
    unfilled = select(models.PlanUnfilledOccurrence.occurrence).where(
        models.PlanUnfilledOccurrence.plan_id == plan_id
    )
    return get_plan_occurrences_executed(db, plan_id) | set(db.scalars(unfilled))


def record_unfilled_occurrence(
    db: Session, plan_id: int, occurrence: str, reason: str
) -> models.PlanUnfilledOccurrence:
    """Record that an occurrence ran and bought nothing, and why."""
    return _create(
        db,
        models.PlanUnfilledOccurrence(
            plan_id=plan_id, occurrence=occurrence, reason=reason
        ),
    )


def get_dividend_dates_recorded(
    db: Session, institution_id: int | None, symbol: str
) -> set[str]:
    """Ex-dates already recorded as dividend transactions for a position
    (institution + symbol) — the idempotency key for the dividend catch-up."""
    stmt = select(models.Transaction.date).where(
        models.Transaction.kind == "dividend",
        models.Transaction.symbol == symbol,
        models.Transaction.institution_id == institution_id,
    )
    return set(db.scalars(stmt))


# --- Price cache (last fetched market price per symbol) -------------------


def upsert_price_caches(db: Session, quotes: dict[str, dict]) -> None:
    """Store the latest fetched price per symbol (insert or overwrite). A
    quote may carry "currency"; a known cached currency is never overwritten
    with None (a listing's currency does not change).

    One `INSERT ... ON CONFLICT DO UPDATE` a symbol, since brief AJ: the
    catch-up the app posts at every page load now refreshes prices too, and
    two of those run at once (two tabs, React's StrictMode). Read-then-insert
    let the second die on the key, which is how the rate store failed until
    dd8370b."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    now = models._utcnow_iso()
    for sym, q in quotes.items():
        row = sqlite_insert(models.PriceCache).values(
            symbol=sym,
            price=q["price"],
            as_of=q["as_of"],
            currency=q.get("currency"),
            fetched_at=now,
        )
        db.execute(
            row.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "price": row.excluded.price,
                    "as_of": row.excluded.as_of,
                    "fetched_at": row.excluded.fetched_at,
                    "currency": func.coalesce(row.excluded.currency, models.PriceCache.currency),
                },
            )
        )
    commit(db)
    # The statements went round the identity map: a row this session already
    # holds would still read the price it had, inside a unit of work above all,
    # where `commit` only flushes and expires nothing.
    # Read off the identity keys, (class, primary key, token), so an instance
    # the commit has already expired is not loaded just to be asked its symbol.
    for key in list(db.identity_map.keys()):
        if key[0] is models.PriceCache and key[1] and key[1][0] in quotes:
            held = db.identity_map.get(key)
            if held is not None:
                db.expire(held)


def earliest_dated_record(db: Session) -> str | None:
    """The oldest day any figure is recorded on — the first point the net
    worth history draws, and so the first day a reading may need a rate for."""
    columns = (
        models.Snapshot.date,
        models.CashAnchor.date,
        models.Transfer.date,
        models.Transaction.date,
        models.RealAssetValuation.date,
        models.LiabilityBalance.date,
    )
    days = [d for d in (db.scalar(select(func.min(c))) for c in columns) if d]
    return min(days) if days else None


def get_fx_rate_rows(db: Session, base: str, day: str) -> list[models.FxRate]:
    """The ECB rates published for `day` against `base`, ordered by currency."""
    stmt = (
        select(models.FxRate)
        .where(models.FxRate.base == base, models.FxRate.as_of == day)
        .order_by(models.FxRate.currency)
    )
    return list(db.scalars(stmt))


def set_price_cache_currencies(db: Session, currencies: dict[str, str]) -> None:
    """Backfill the trading currency of already-cached symbols."""
    for sym, cur in currencies.items():
        row = db.get(models.PriceCache, sym)
        if row is not None:
            row.currency = cur
    commit(db)


def get_cached_prices(db: Session, symbols: list[str]) -> dict[str, dict]:
    """Cached prices for the given symbols, in the same shape as
    prices.get_quotes() plus the cached trading currency:
    {symbol: {"symbol", "price", "as_of", "currency"}}."""
    if not symbols:
        return {}
    stmt = select(models.PriceCache).where(models.PriceCache.symbol.in_(symbols))
    return {
        c.symbol: {
            "symbol": c.symbol,
            "price": c.price,
            "as_of": c.as_of,
            "currency": c.currency,
        }
        for c in db.scalars(stmt)
    }


# --- Advisor chain runs ----------------------------------------------------


def create_chain_run(
    db: Session, verdict: str, steps: list[dict]
) -> models.ChainRun:
    """Persist a completed chain run with its ordered steps."""
    run = models.ChainRun(verdict=verdict)
    for i, s in enumerate(steps, start=1):
        run.steps.append(
            models.ChainStep(
                step_no=i,
                role=s["role"],
                title=s["title"],
                model=s.get("model"),
                output=s["output"],
                duration_ms=s.get("duration_ms"),
                cost=s.get("cost"),
            )
        )
    db.add(run)
    commit(db)
    db.refresh(run)
    return run


def get_latest_chain_run(db: Session) -> models.ChainRun | None:
    """The most recent chain run, or None if the chain has never been run."""
    stmt = select(models.ChainRun).order_by(models.ChainRun.id.desc()).limit(1)
    return db.scalars(stmt).first()


def get_chain_runs(db: Session, limit: int) -> list[models.ChainRun]:
    """The most recent runs, newest first, with their steps already loaded.

    The steps come along because every question the list answers is asked of
    them — how deep the run went, and whether the confidant's own marker says
    it argued. Lazily loaded that is a query per run, which is the N+1 that
    `tests/test_no_n_plus_one.py` exists about; here it would also be one query
    per run to answer a question about honesty, which is a poor thing to pay
    for by the page.

    `limit` is the caller's, and it is not optional: a listing with no ceiling
    reads every word four models ever wrote in order to print a date.
    """
    stmt = (
        select(models.ChainRun)
        .options(selectinload(models.ChainRun.steps))
        .order_by(models.ChainRun.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


# --- Chat conversations ---------------------------------------------------


def create_chat_conversation(db: Session) -> models.ChatConversation:
    """Open an empty conversation. It gets its title from its first question."""
    conv = models.ChatConversation()
    db.add(conv)
    commit(db)
    db.refresh(conv)
    return conv


def get_chat_conversations(db: Session) -> list[models.ChatConversation]:
    """Every conversation, the one most recently spoken to first."""
    stmt = select(models.ChatConversation).order_by(
        models.ChatConversation.updated_at.desc(), models.ChatConversation.id.desc()
    )
    return list(db.scalars(stmt))


def get_chat_conversation(db: Session, conversation_id: int) -> models.ChatConversation | None:
    return db.get(models.ChatConversation, conversation_id)


def delete_chat_conversation(db: Session, conversation_id: int) -> bool:
    return _delete(db, db.get(models.ChatConversation, conversation_id))


def find_chat_card(db: Session, card_id: str) -> tuple[models.ChatMessage, dict] | None:
    """The message holding the card with this id, and the card itself.

    A LIKE over the blocks column narrows to the one row before anything is
    parsed, and the parse is what actually decides — the id is a hex uuid, so
    a substring hit that is not the card is a coincidence that would have to
    be arranged, and it is thrown out here rather than trusted. It is a scan,
    and it is honest about being one: a conversation is tens of messages, an
    index on a field inside a JSON blob is not a thing SQLite has for free, and
    the alternative is a table whose only job is to point back here.
    """
    stmt = select(models.ChatMessage).where(models.ChatMessage.blocks.like(f"%{card_id}%"))
    for msg in db.scalars(stmt):
        for block in json.loads(msg.blocks):
            if block.get("kind") == "card" and block.get("card_id") == card_id:
                return msg, block
    return None


def settle_chat_card(
    db: Session, message: models.ChatMessage, card_id: str, outcome: str, result: dict | None
) -> dict | None:
    """Record what became of one card, on the block that proposed it — or
    return None because somebody else got there first.

    Rewritten in place and not appended beside, because the card IS the record
    of the proposal and a second block saying "that one was confirmed" is two
    things to keep in step. What was proposed and what happened are then one
    object, which is what makes the history readable a month later.

    A compare-and-swap, and it has to be one. Reading the card, seeing
    "pending" and then writing is not a decision taken once: two tabs — the
    same two tabs the staleness rule exists for — both read pending, both run
    the tool, and the ledger ends up with two rows for one purchase. Measured,
    before this was a CAS: two simultaneous confirms, two 200s, the write run
    twice. The UPDATE carries the blocks text the caller decided on as its
    condition, so exactly one of them changes a row; the loser gets None,
    raises, and takes its half-done write down with it.

    Assigning the whole column is not optional either: `blocks` is Text holding
    JSON, not a mutable JSON type, so a list parsed out of it and edited in
    Python leaves the row clean and a commit writes nothing at all — a settled
    card that silently stays pending, which is the quietest way this could go
    wrong.

    `updated_at` moves too. Confirming a write is speaking to a conversation,
    and the history list orders by that; a conversation that took a decision
    and did not rise is a conversation that looks untouched.
    """
    before = message.blocks
    blocks = json.loads(before)
    for block in blocks:
        if block.get("kind") == "card" and block.get("card_id") == card_id:
            block["outcome"] = outcome
            block["result"] = result
            break
    after = json.dumps(blocks, ensure_ascii=False)

    changed = db.execute(
        update(models.ChatMessage)
        .where(models.ChatMessage.id == message.id, models.ChatMessage.blocks == before)
        .values(blocks=after)
    )
    if changed.rowcount == 0:
        return None
    message.conversation.updated_at = models._utcnow_iso()
    commit(db)
    # The raw UPDATE went round the identity map, so the loaded object still
    # holds the old text until it is told otherwise.
    db.refresh(message)
    return next(
        b for b in json.loads(message.blocks)
        if b.get("kind") == "card" and b.get("card_id") == card_id
    )


def append_chat_message(
    db: Session,
    conversation: models.ChatConversation,
    role: str,
    blocks: list[dict],
    *,
    status: str | None = None,
    detail: str | None = None,
    model: str | None = None,
    prompt_tokens: int | None = None,
    cached_tokens: int | None = None,
    cost: float | None = None,
) -> models.ChatMessage:
    """Add one turn at the end. The first question names the conversation, and
    every turn moves `updated_at`, which is what keeps the live conversation at
    the top of the history."""
    if conversation.title is None and role == "user":
        text = " ".join(b.get("text", "") for b in blocks if b.get("kind") == "text").strip()
        conversation.title = text[:80] or None
    msg = models.ChatMessage(
        seq=len(conversation.messages) + 1,
        role=role,
        blocks=json.dumps(blocks, ensure_ascii=False),
        status=status,
        detail=detail,
        model=model,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        cost=cost,
    )
    conversation.messages.append(msg)
    conversation.updated_at = models._utcnow_iso()
    commit(db)
    db.refresh(msg)
    return msg


# --- Composition cache (ETF look-through) ---------------------------------


def get_composition_cache(db: Session, symbol: str) -> models.CompositionCache | None:
    """The cached composition for a symbol, or None."""
    return db.get(models.CompositionCache, symbol)


def upsert_composition_cache(
    db: Session,
    symbol: str,
    isin: str | None,
    resolved_name: str | None,
    source: str | None,
    data: str,
) -> models.CompositionCache:
    """Insert or overwrite a symbol's cached composition, re-stamping fetched_at.
    An accepted write clears any refusal: the entry is as new as its data."""
    row = db.get(models.CompositionCache, symbol)
    if row is None:
        row = models.CompositionCache(
            symbol=symbol, isin=isin, resolved_name=resolved_name, source=source, data=data
        )
        db.add(row)
    else:
        row.isin, row.resolved_name, row.source, row.data = isin, resolved_name, source, data
        row.fetched_at = models._utcnow_iso()
        row.refused_at = None
    commit(db)
    db.refresh(row)
    return row


def note_refused_refresh(db: Session, row: models.CompositionCache) -> None:
    """Record that a refresh of this entry was refused, leaving its data and
    its fetched_at exactly as they were."""
    row.refused_at = models._utcnow_iso()
    commit(db)


# --- Accumulation plans (PAC) ---------------------------------------------


def create_accumulation_plan(
    db: Session, data: schemas.AccumulationPlanCreate
) -> models.AccumulationPlan:
    """Create and persist an accumulation plan (dates stored as ISO strings)."""
    plan = models.AccumulationPlan(**_columns(data, drop=("targets",)))
    plan.targets = _plan_targets(data)
    return _create(db, plan)


def _plan_targets(data: schemas.AccumulationPlanCreate) -> list[models.PlanTarget]:
    """The plan's targets, in the order they were given — the order is the one
    the user typed, and it is what the allocation reports back to them."""
    return [
        models.PlanTarget(
            symbol=(t.symbol or "").strip(),
            isin=_clean_isin(t.isin),
            asset_name=(t.asset_name or "").strip() or None,
            institution_id=t.institution_id,
            weight=t.weight,
            position=i,
        )
        for i, t in enumerate(data.targets)
    ]


def get_accumulation_plans(db: Session) -> list[models.AccumulationPlan]:
    """Return all accumulation plans, ordered by id."""
    stmt = select(models.AccumulationPlan).order_by(models.AccumulationPlan.id)
    return list(db.scalars(stmt))


def get_accumulation_plan(
    db: Session, plan_id: int
) -> models.AccumulationPlan | None:
    """Return a single accumulation plan by id, or None if it does not exist."""
    return db.get(models.AccumulationPlan, plan_id)


def update_accumulation_plan(
    db: Session, plan_id: int, data: schemas.AccumulationPlanCreate
) -> models.AccumulationPlan | None:
    obj = db.get(models.AccumulationPlan, plan_id)
    if obj is None:
        return None
    sent = data.model_fields_set
    amount = data.amount if "amount" in sent else obj.amount
    execution = data.execution if "execution" in sent else obj.execution
    if amount != obj.amount or execution != obj.execution:
        # The carried change belongs to the OLD contribution: measuring it
        # against a new amount or a new fill model would be meaningless, so it
        # starts again rather than carrying a figure that no longer means what
        # it meant. Read off what this request LEAVES the plan with, not off
        # the payload: a request that never mentioned the execution has not
        # changed it, and comparing the schema's default against the stored
        # value would throw the balance away on every edit.
        obj.carried_remainder = 0.0
    return _update(
        db,
        models.AccumulationPlan,
        plan_id,
        data,
        drop=("targets",),
        # Replaced wholesale rather than diffed: the targets ARE the plan's
        # composition, and a half-updated one would leave a stale target behind
        # that the next execution would silently keep buying. Only when they
        # were sent, though — a request that did not mention them is not a
        # request to empty the plan.
        also={"targets": _plan_targets(data)} if "targets" in sent else None,
    )


def delete_accumulation_plan(db: Session, plan_id: int) -> bool:
    return _delete(db, db.get(models.AccumulationPlan, plan_id))


def get_goal(db: Session, goal_id: int) -> models.Goal | None:
    """Return a single goal by id, or None if it does not exist."""
    return db.get(models.Goal, goal_id)


def delete_goal(db: Session, goal_id: int) -> bool:
    return _delete(db, db.get(models.Goal, goal_id))


# --- Updates (what the request said; parent ids are never among it) -------


def update_institution(
    db: Session, institution_id: int, data: schemas.InstitutionCreate
) -> models.Institution | None:
    return _update(db, models.Institution, institution_id, data)


def update_snapshot(
    db: Session, snapshot_id: int, data: schemas.SnapshotCreate
) -> models.Snapshot | None:
    return _update(db, models.Snapshot, snapshot_id, data)


def update_holding(
    db: Session, holding_id: int, data: schemas.HoldingCreate
) -> models.Holding | None:
    return _update(db, models.Holding, holding_id, data, build=_holding_columns)


def set_holding_price(
    db: Session, holding: models.Holding, price: float
) -> models.Holding:
    """Store the latest known unit price on a holding.

    It deliberately does NOT touch `value`. A holding lives inside a snapshot —
    a dated photograph — so rewriting its value with today's market price would
    silently re-date the record: the photo would claim to be from its original
    date while holding today's numbers. That is what made "P/L vs recorded"
    collapse to exactly 0 (book and market became the same figure).
    To record today's values, take a NEW snapshot; the Portfolio view computes
    market value from live prices on its own and never needs `value` rewritten.

    Nor the currency. It used to stamp the quote's currency on a holding that
    had none, and no holding can have none any more (a7d2e94c10b8). On a row
    with units the listing's currency is what values it anyway, whatever was
    typed, and a disagreement is shown as `currency_note` for the reader to
    correct — not overwritten for them."""
    return _apply(db, holding, {"unit_price": price})


def update_real_asset(
    db: Session, real_asset_id: int, data: schemas.RealAssetCreate
) -> models.RealAsset | None:
    return _update(db, models.RealAsset, real_asset_id, data)


def update_real_asset_valuation(
    db: Session, valuation_id: int, data: schemas.RealAssetValuationCreate
) -> models.RealAssetValuation | None:
    return _update(db, models.RealAssetValuation, valuation_id, data)


def update_income_source(
    db: Session, income_id: int, data: schemas.IncomeSourceCreate
) -> models.IncomeSource | None:
    return _update(db, models.IncomeSource, income_id, data)


def update_expense(
    db: Session, expense_id: int, data: schemas.ExpenseCreate
) -> models.Expense | None:
    return _update(db, models.Expense, expense_id, data)


def update_goal(
    db: Session, goal_id: int, data: schemas.GoalCreate
) -> models.Goal | None:
    return _update(db, models.Goal, goal_id, data)
