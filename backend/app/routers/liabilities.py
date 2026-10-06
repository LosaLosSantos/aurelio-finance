"""REST endpoints for liabilities (debts) and their dated balances.

A liability (mortgage, loan, ...) tracks its outstanding principal as dated
balances, mirroring real-asset valuations. Net worth subtracts the latest
balance of each debt. A liability may optionally link to the real asset it
finances (404 if that asset does not exist).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api", tags=["liabilities"])


def _require_linked_asset(db: Session, real_asset_id: int | None) -> None:
    """404 if the liability names a real asset that does not exist. Null is
    allowed: a debt secured on nothing is a debt, not a dangling reference."""
    if real_asset_id is not None:
        get_or_404(db, models.RealAsset, real_asset_id)


@router.post(
    "/liabilities",
    response_model=schemas.LiabilityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_liability(
    payload: schemas.LiabilityCreate,
    db: Session = Depends(get_db),
) -> schemas.LiabilityRead:
    """Create a new liability (404 if the linked real asset does not exist)."""
    _require_linked_asset(db, payload.real_asset_id)
    return crud.create_liability(db, payload)


@router.get("/liabilities", response_model=list[schemas.LiabilityRead])
def list_liabilities(db: Session = Depends(get_db)) -> list[schemas.LiabilityRead]:
    """List all liabilities."""
    return crud.get_liabilities(db)


@router.get("/liabilities/{liability_id}", response_model=schemas.LiabilityRead)
def get_liability(
    liability_id: int,
    db: Session = Depends(get_db),
) -> schemas.LiabilityRead:
    """Return a single liability, or 404 if it does not exist."""
    return get_or_404(db, models.Liability, liability_id)


@router.put("/liabilities/{liability_id}", response_model=schemas.LiabilityRead)
def update_liability(
    liability_id: int,
    payload: schemas.LiabilityCreate,
    db: Session = Depends(get_db),
) -> schemas.LiabilityRead:
    """Update a liability (404 if it, or the linked real asset, does not exist)."""
    _require_linked_asset(db, payload.real_asset_id)
    get_or_404(db, models.Liability, liability_id)
    return crud.update_liability(db, liability_id, payload)


@router.delete("/liabilities/{liability_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_liability(liability_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a liability (cascades to its balances)."""
    get_or_404(db, models.Liability, liability_id)
    crud.delete_liability(db, liability_id)


@router.post(
    "/liabilities/{liability_id}/balances",
    response_model=schemas.LiabilityBalanceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_balance(
    liability_id: int,
    payload: schemas.LiabilityBalanceCreate,
    db: Session = Depends(get_db),
) -> schemas.LiabilityBalanceRead:
    """Add a dated balance to a liability (409 if one already exists for that date)."""
    get_or_404(db, models.Liability, liability_id)
    try:
        return crud.create_liability_balance(db, liability_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A balance for liability {liability_id} on "
                f"{payload.date.isoformat()} already exists"
            ),
        )


@router.get(
    "/liabilities/{liability_id}/balances",
    response_model=list[schemas.LiabilityBalanceRead],
)
def list_balances(
    liability_id: int,
    db: Session = Depends(get_db),
) -> list[schemas.LiabilityBalanceRead]:
    """List a liability's balances (chronological order)."""
    get_or_404(db, models.Liability, liability_id)
    return crud.get_balances_for_liability(db, liability_id)


@router.put(
    "/liability-balances/{balance_id}",
    response_model=schemas.LiabilityBalanceRead,
)
def update_balance(
    balance_id: int,
    payload: schemas.LiabilityBalanceCreate,
    db: Session = Depends(get_db),
) -> schemas.LiabilityBalanceRead:
    """Update a balance (409 if another balance exists for that liability+date)."""
    get_or_404(db, models.LiabilityBalance, balance_id)
    try:
        return crud.update_liability_balance(db, balance_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A balance for this liability and date already exists",
        )


@router.delete(
    "/liability-balances/{balance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_balance(balance_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a liability balance."""
    get_or_404(db, models.LiabilityBalance, balance_id)
    crud.delete_liability_balance(db, balance_id)
