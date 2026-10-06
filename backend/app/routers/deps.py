"""Shared route dependencies, and the two responses a router cannot build alone.

One 404, said one way. This used to be fifty-one hand-written raises across
thirteen routers plus seven `_require_*` helpers between them — two of which,
in cash_anchors.py and snapshots.py, were identical character for character.
Nothing was wrong with any of them, which is the point: fifty-one copies of a
correct thing is fifty-one chances for the fifty-second to be worded
differently, or to check the wrong id, or to be forgotten.

`holding_read` and `snapshot_read` are here for exactly that reason. A holding
and a situation each carry a figure the ORM row cannot answer for itself —
what it is worth in the base currency — because the conversion needs a `fx.Converter` and a
Converter needs a session. Eleven endpoints across three routers return one of
those two shapes. Eleven places to supply a money total is eleven chances to
supply it raw, and the last time a total was computed somewhere that had no
session it summed Turkish lira and the page put a euro sign on the answer.
"""

from __future__ import annotations

import re
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import crud, fx, models, pac, positions, schemas

T = TypeVar("T")


def _label(model: type) -> str:
    """'AccumulationPlan' -> 'Accumulation plan'.

    Derived from the model's own name rather than read from a table of nice
    names, so a new table needs no entry here and cannot be given one that
    drifts from what it is called everywhere else.
    """
    return " ".join(re.findall(r"[A-Z][a-z0-9]*", model.__name__)).capitalize()


def get_or_404(db: Session, model: type[T], obj_id: int) -> T:
    """The row with that id, or a 404 saying what was looked for and which id.

    Returning the row rather than only asserting it exists is deliberate: a
    caller that needs it does not fetch it twice, and one that only needs the
    guarantee can ignore the return.
    """
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{_label(model)} {obj_id} not found",
        )
    return obj


def transaction_reads(
    db: Session, txs: list[models.Transaction]
) -> list[schemas.TransactionRead]:
    """Ledger entries as the API returns them, each with `currency_note` when
    the currency its price was recorded in is not the one its listing trades in.

    The note exists for the entries written before a ledger entry could say
    what its price was in: every one of them was read as euro, and the
    migration that gave them a price currency could only write down that
    reading. Whether a 100.00 typed against a dollar listing was dollars or
    euro is not in the row, so it is pointed out — never rewritten. One read of
    the price cache for the whole list."""
    symbols = sorted({t.symbol for t in txs if t.symbol})
    listing = {
        sym: q.get("currency")
        for sym, q in (crud.get_cached_prices(db, symbols) if symbols else {}).items()
    }
    out = []
    for t in txs:
        trades_in = listing.get(t.symbol) if t.symbol else None
        note = (
            f"the price is recorded in {t.price_currency}, but {t.symbol} trades in "
            f"{trades_in}: open the entry and state the currencies and the amount "
            "your statement shows"
            if (trades_in and t.price_currency and trades_in.upper() != t.price_currency.upper()
                and t.price_currency != trades_in)
            else None
        )
        out.append(
            schemas.TransactionRead.model_validate(t).model_copy(update={"currency_note": note})
        )
    return out


def holding_reads(
    db: Session, holdings: list[models.Holding]
) -> list[schemas.HoldingRead]:
    """Holdings as the API returns them, `value_base` included.

    The stored `value` is whatever the reader typed, in whatever `currency`
    they typed it in, and it stays that way — it is what the edit form puts
    back in the box. What nobody may do is add two of those together or print a
    euro sign on one, and the Wealth page did both. So the row carries the
    converted figure beside the typed one, and display and totals read that.

    One price-cache read and one rate load for the whole list. Each row says
    the base its converted figure is in, from the converter that made it. And
    one read of the dividend answers the catch-up keeps, for when each ticker
    last paid."""
    conv = fx.Converter(db)
    values = positions.holdings_in_base(db, holdings, conv)
    last_paid = pac.last_dividends(db, {h.symbol for h in holdings if h.symbol})
    return [
        schemas.HoldingRead(
            **schemas.HoldingBase.model_validate(h, from_attributes=True).model_dump(),
            id=h.id,
            snapshot_id=h.snapshot_id,
            value_base=values[h.id],
            base_currency=conv.base,
            last_dividend=last_paid.get(h.symbol),
        )
        for h in holdings
    ]


def holding_read(db: Session, holding: models.Holding) -> schemas.HoldingRead:
    """One holding, valued the same way as a list of them."""
    return holding_reads(db, [holding])[0]


def snapshot_reads(
    db: Session, snapshots: list[models.Snapshot]
) -> list[schemas.SnapshotRead]:
    """Situations as the API returns them, each with what it was worth in the
    base currency, and which currency that is.

    Pass them with their holdings loaded (`crud.get_snapshots_for_institution`
    does): the value is a sum over them, and a lazy collection makes that a
    query per situation."""
    conv = fx.Converter(db)
    values = positions.snapshot_values_in_base(db, snapshots, conv)
    return [
        schemas.SnapshotRead(
            id=s.id,
            institution_id=s.institution_id,
            date=s.date,
            note=s.note,
            value_base=values[s.id],
            base_currency=conv.base,
            created_at=s.created_at,
        )
        for s in snapshots
    ]


def snapshot_read(db: Session, snapshot: models.Snapshot) -> schemas.SnapshotRead:
    """One situation, valued the same way as a list of them."""
    return snapshot_reads(db, [snapshot])[0]
