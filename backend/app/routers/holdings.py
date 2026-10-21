"""REST endpoints for the "holdings" resource (positions within a snapshot).

Holdings are children of a snapshot: create/list URLs are nested under the
snapshot. Before operating we check that the snapshot exists (otherwise 404).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, paid_recovery, schemas
from app.database import get_db
from app.routers.deps import get_or_404, holding_read, holding_reads

router = APIRouter(prefix="/api", tags=["holdings"])


def _refused(exc: crud.HoldingRefused) -> HTTPException:
    """A row the app will not store: a 422 whose detail is the sentence,
    which the form shows as written. A cost that pays for more units than the
    row holds (brief AV), and units with no price, value or cost (brief BE)."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/snapshots/{snapshot_id}/holdings",
    response_model=schemas.HoldingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_holding(
    snapshot_id: int,
    payload: schemas.HoldingCreate,
    db: Session = Depends(get_db),
) -> schemas.HoldingRead:
    """Add a holding to the given snapshot."""
    get_or_404(db, models.Snapshot, snapshot_id)
    try:
        return holding_read(db, crud.create_holding(db, snapshot_id, payload))
    except crud.HoldingRefused as exc:
        raise _refused(exc)


@router.get(
    "/snapshots/{snapshot_id}/holdings",
    response_model=list[schemas.HoldingRead],
)
def list_holdings(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> list[schemas.HoldingRead]:
    """List a snapshot's holdings."""
    get_or_404(db, models.Snapshot, snapshot_id)
    return holding_reads(db, crud.get_holdings_for_snapshot(db, snapshot_id))


@router.get("/holdings/{holding_id}", response_model=schemas.HoldingRead)
def get_holding(
    holding_id: int,
    db: Session = Depends(get_db),
) -> schemas.HoldingRead:
    """Return a single holding, or 404 if it does not exist."""
    return holding_read(db, get_or_404(db, models.Holding, holding_id))


@router.put("/holdings/{holding_id}", response_model=schemas.HoldingRead)
def update_holding(
    holding_id: int,
    payload: schemas.HoldingCreate,
    db: Session = Depends(get_db),
) -> schemas.HoldingRead:
    """Update a holding (value recomputed from quantity*price if not given).
    A cost left as it was keeps the units it paid for, so units typed below
    them are refused with a sentence (brief AV)."""
    get_or_404(db, models.Holding, holding_id)
    try:
        return holding_read(db, crud.update_holding(db, holding_id, payload))
    except crud.HoldingRefused as exc:
        raise _refused(exc)


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a holding."""
    get_or_404(db, models.Holding, holding_id)
    crud.delete_holding(db, holding_id)


def _not_now(exc: paid_recovery.Refused) -> HTTPException:
    """A press on a proposal that is gone or has changed: a 409 whose detail is
    the sentence the page shows."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/holdings/{holding_id}/paid-recovery", response_model=schemas.HoldingRead)
def accept_paid(
    holding_id: int,
    payload: schemas.PaidAccept,
    db: Session = Depends(get_db),
) -> schemas.HoldingRead:
    """Write what the ledger paid onto this row, as the Portfolio proposed it
    (brief AW): the figures worked out again now, the page's only saying which
    proposal the reader saw. 409 with a sentence when nothing is proposed any
    more, the figures changed, or no rate can state them in the row's
    currency."""
    get_or_404(db, models.Holding, holding_id)
    try:
        (written,) = paid_recovery.accept(
            db, [schemas.PaidAcceptRow(holding_id=holding_id, **payload.model_dump())]
        )
    except paid_recovery.Refused as exc:
        raise _not_now(exc)
    except crud.HoldingCostRefused as exc:
        raise _refused(exc)
    return holding_read(db, written)


@router.post(
    "/holdings/{holding_id}/paid-recovery/decline",
    status_code=status.HTTP_204_NO_CONTENT,
)
def decline_paid(holding_id: int, db: Session = Depends(get_db)) -> None:
    """Decline this row's proposal: it is never proposed again, on this row or
    on a situation started from it later. 409 when nothing is proposed."""
    get_or_404(db, models.Holding, holding_id)
    try:
        paid_recovery.decline(db, holding_id)
    except paid_recovery.Refused as exc:
        raise _not_now(exc)


@router.post("/paid-recovery", response_model=list[schemas.HoldingRead])
def accept_all_paid(
    payload: schemas.PaidAcceptAll,
    db: Session = Depends(get_db),
) -> list[schemas.HoldingRead]:
    """Accept every proposal the page showed at once, in one transaction: all
    written, or none (409) if any is gone or has changed."""
    try:
        written = paid_recovery.accept(db, payload.rows)
    except paid_recovery.Refused as exc:
        raise _not_now(exc)
    except crud.HoldingCostRefused as exc:
        raise _refused(exc)
    return holding_reads(db, written)
