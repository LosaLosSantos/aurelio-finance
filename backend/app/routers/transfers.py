"""REST endpoints for transfers (cash moved between institutions on a date).

A transfer lowers the source institution's projected cash by what left it and
raises the target's by what arrived. Either endpoint may be null (e.g. cash
withdrawn to physical cash, or an external deposit), and the projection simply
ignores a null endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api", tags=["transfers"])


def _refused_without_a_rate(exc: crud.TransferRateUnknown) -> HTTPException:
    """422: the transfer is well-formed, and the one figure it needs — what
    reached the destination — has no final rate to be worked out at."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/transfers",
    response_model=schemas.TransferRead,
    status_code=status.HTTP_201_CREATED,
)
def create_transfer(
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
) -> schemas.TransferRead:
    """Create a cash transfer between institutions."""
    try:
        return crud.create_transfer(db, payload)
    except crud.TransferRateUnknown as exc:
        raise _refused_without_a_rate(exc)


@router.get("/transfers", response_model=list[schemas.TransferRead])
def list_transfers(db: Session = Depends(get_db)) -> list[schemas.TransferRead]:
    """List all transfers (chronological order)."""
    return crud.get_transfers(db)


@router.get("/transfers/{transfer_id}", response_model=schemas.TransferRead)
def get_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
) -> schemas.TransferRead:
    """Return a single transfer, or 404 if it does not exist."""
    return get_or_404(db, models.Transfer, transfer_id)


@router.put("/transfers/{transfer_id}", response_model=schemas.TransferRead)
def update_transfer(
    transfer_id: int,
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
) -> schemas.TransferRead:
    """Update a transfer. A `to_amount` sent empty is worked out again, at the
    rate final for the (possibly new) date; one left OUT of the body is not
    touched at all, like every other column the request does not mention —
    see `crud._update`."""
    get_or_404(db, models.Transfer, transfer_id)
    try:
        return crud.update_transfer(db, transfer_id, payload)
    except crud.TransferRateUnknown as exc:
        raise _refused_without_a_rate(exc)


@router.delete("/transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer(transfer_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a transfer."""
    get_or_404(db, models.Transfer, transfer_id)
    crud.delete_transfer(db, transfer_id)
