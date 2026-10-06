"""REST endpoints for the cash register: anchors + projected positions.

An anchor is a manually-entered ACTUAL cash balance for an institution at a
date. The projected position at a date = latest anchor + linked income −
expenses ± transfers after the anchor date (see analytics.compute_cash_position).
UNIQUE(institution_id, date) → one anchor per institution per date (409 on dup).
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import analytics, crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api", tags=["cash"])


@router.post(
    "/institutions/{institution_id}/cash-anchors",
    response_model=schemas.CashAnchorRead,
    status_code=status.HTTP_201_CREATED,
)
def create_cash_anchor(
    institution_id: int,
    payload: schemas.CashAnchorCreate,
    db: Session = Depends(get_db),
) -> schemas.CashAnchorRead:
    """Create a dated cash anchor for the institution (409 if that date exists)."""
    get_or_404(db, models.Institution, institution_id)
    try:
        return crud.create_cash_anchor(db, institution_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A cash anchor for institution {institution_id} on "
                f"{payload.date.isoformat()} already exists"
            ),
        )


@router.get(
    "/institutions/{institution_id}/cash-anchors",
    response_model=list[schemas.CashAnchorRead],
)
def list_cash_anchors(
    institution_id: int,
    db: Session = Depends(get_db),
) -> list[schemas.CashAnchorRead]:
    """List an institution's cash anchors (chronological order)."""
    get_or_404(db, models.Institution, institution_id)
    return crud.get_cash_anchors_for_institution(db, institution_id)


@router.get("/cash-anchors", response_model=list[schemas.CashAnchorRead])
def list_all_cash_anchors(db: Session = Depends(get_db)) -> list[schemas.CashAnchorRead]:
    """Every institution's cash anchors, by institution then date — in one
    request. A form that proposes the currency of an account on a date needs
    the anchor in force then for whichever account the reader picks, and
    asking per account would be one request for each of them."""
    return crud.get_cash_anchors(db)


@router.get(
    "/institutions/{institution_id}/cash",
    response_model=schemas.CashPosition,
)
def get_cash_position(
    institution_id: int,
    as_of: datetime.date | None = None,
    db: Session = Depends(get_db),
) -> schemas.CashPosition:
    """Projected cash for the institution at `as_of` (default today), with its
    breakdown (anchor, income, expenses, transfers)."""
    get_or_404(db, models.Institution, institution_id)
    return analytics.compute_cash_position(db, institution_id, as_of)


@router.get("/cash/positions", response_model=list[schemas.CashPosition])
def list_cash_positions(
    as_of: datetime.date | None = None,
    db: Session = Depends(get_db),
) -> list[schemas.CashPosition]:
    """Projected cash for every institution at `as_of` (default today)."""
    return analytics.compute_all_cash_positions(db, as_of)


@router.get("/cash-anchors/{anchor_id}", response_model=schemas.CashAnchorRead)
def get_cash_anchor(
    anchor_id: int,
    db: Session = Depends(get_db),
) -> schemas.CashAnchorRead:
    """Return a single cash anchor, or 404 if it does not exist."""
    return get_or_404(db, models.CashAnchor, anchor_id)


@router.put("/cash-anchors/{anchor_id}", response_model=schemas.CashAnchorRead)
def update_cash_anchor(
    anchor_id: int,
    payload: schemas.CashAnchorCreate,
    db: Session = Depends(get_db),
) -> schemas.CashAnchorRead:
    """Update a cash anchor (409 if another anchor exists for that date)."""
    get_or_404(db, models.CashAnchor, anchor_id)
    try:
        return crud.update_cash_anchor(db, anchor_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cash anchor for this institution and date already exists",
        )


@router.delete("/cash-anchors/{anchor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cash_anchor(anchor_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a cash anchor."""
    get_or_404(db, models.CashAnchor, anchor_id)
    crud.delete_cash_anchor(db, anchor_id)
