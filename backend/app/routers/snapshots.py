"""REST endpoints for snapshots (a dated 'situation' of an institution).

A snapshot belongs to an institution and holds the positions (holdings) at a
date; `value_base` is those holdings converted to the base currency and added
up, with `base_currency` saying which one, which is
why every response here is built by `deps.snapshot_read` rather than handed
back as an ORM row: the conversion needs a session and a model cannot have one.
UNIQUE(institution_id, date) → one snapshot per institution per date; a
violation returns 409 Conflict.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, dated, models, positions, prices, schemas
from app.database import get_db
from app.routers.deps import get_or_404, snapshot_read, snapshot_reads

router = APIRouter(prefix="/api", tags=["snapshots"])


def _date_taken(institution_name: str, date: datetime.date) -> HTTPException:
    """The refusal BOTH creation paths raise, written for the reader.

    One situation per institution per date is the model, so this 409 is a
    correct answer and not a malfunction. It used to be addressed to whoever
    was reading the logs — "A snapshot for institution 2 on ..." — and the
    reader who typed "Broker B" has never heard of institution 2: the id is a
    fact about our table, not about their money. The two paths also wrote the
    sentence twice, which is how they would have drifted apart.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{institution_name} already has a situation on {date.isoformat()}",
    )


@router.post(
    "/institutions/{institution_id}/snapshots",
    response_model=schemas.SnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot(
    institution_id: int,
    payload: schemas.SnapshotCreate,
    db: Session = Depends(get_db),
) -> schemas.SnapshotRead:
    """Create a dated snapshot for the institution (409 if that date exists)."""
    institution = get_or_404(db, models.Institution, institution_id)
    # Read before the write: a rollback expires the instance, and the name is
    # what the refusal has to say.
    name = institution.name
    try:
        return snapshot_read(db, crud.create_snapshot(db, institution_id, payload))
    except IntegrityError:
        db.rollback()
        raise _date_taken(name, payload.date)


@router.post(
    "/institutions/{institution_id}/snapshots/prefilled",
    response_model=schemas.PrefilledSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_prefilled_snapshot(
    institution_id: int,
    payload: schemas.SnapshotCreate,
    db: Session = Depends(get_db),
) -> schemas.PrefilledSnapshotRead:
    """A new dated situation, starting from the positions of the previous one.

    The newest snapshot is the authority for the whole institution, so one that
    omits a position deletes it — which is why updating a single number
    otherwise means re-declaring the entire account from memory. Here the list
    arrives already filled: everything with a ticker is re-priced for the new
    date, and `needs_attention` names the rows nothing could re-price, which
    are exactly the ones worth looking at.

    409 if a snapshot already exists on that date; 404 if there is nothing to
    prefill from."""
    institution = get_or_404(db, models.Institution, institution_id)
    name = institution.name

    source = crud.latest_snapshot_for_institution(
        db, institution_id, on_or_before=dated.today()
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Institution {institution_id} has no situation yet, so "
                "there is nothing to start from"
            ),
        )

    # The PROJECTED positions, not the source rows: a buy or sell recorded
    # since that photo has already moved the quantities, and copying the raw
    # rows would re-assert the old ones and swallow the ledger entries for good.
    projected = [
        p for p in positions.project(db) if p.institution_id == institution_id
    ]

    # One batched request for every ticker. A failure is not fatal: an unpriced
    # row simply carries its old value forward and is reported in
    # needs_attention, like any other opaque one.
    symbols = sorted({p.symbol for p in projected if p.symbol})
    quotes: dict[str, dict] = {}
    if symbols:
        try:
            quotes = prices.get_quotes(symbols)
        except prices.PriceError:
            quotes = {}

    try:
        result = crud.clone_latest_snapshot(
            db, institution_id, payload.date, quotes, projected=projected
        )
    except IntegrityError:
        db.rollback()
        raise _date_taken(name, payload.date)
    snapshot, opaque = result
    return schemas.PrefilledSnapshotRead(
        **snapshot_read(db, snapshot).model_dump(),
        copied_from=source.date,
        repriced=sorted(quotes),
        needs_attention=opaque,
    )


@router.get(
    "/institutions/{institution_id}/snapshots",
    response_model=list[schemas.SnapshotRead],
)
def list_snapshots(
    institution_id: int,
    db: Session = Depends(get_db),
) -> list[schemas.SnapshotRead]:
    """List an institution's snapshots (chronological order)."""
    get_or_404(db, models.Institution, institution_id)
    return snapshot_reads(db, crud.get_snapshots_for_institution(db, institution_id))


@router.get("/snapshots/{snapshot_id}", response_model=schemas.SnapshotRead)
def get_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> schemas.SnapshotRead:
    """Return a single snapshot, or 404 if it does not exist."""
    return snapshot_read(db, get_or_404(db, models.Snapshot, snapshot_id))


@router.put("/snapshots/{snapshot_id}", response_model=schemas.SnapshotRead)
def update_snapshot(
    snapshot_id: int,
    payload: schemas.SnapshotCreate,
    db: Session = Depends(get_db),
) -> schemas.SnapshotRead:
    """Update a snapshot (409 if another snapshot exists for that institution+date)."""
    snapshot = get_or_404(db, models.Snapshot, snapshot_id)
    name = snapshot.institution.name
    try:
        return snapshot_read(db, crud.update_snapshot(db, snapshot_id, payload))
    except IntegrityError:
        db.rollback()
        raise _date_taken(name, payload.date)


@router.delete("/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a snapshot (cascades to its holdings)."""
    get_or_404(db, models.Snapshot, snapshot_id)
    crud.delete_snapshot(db, snapshot_id)
