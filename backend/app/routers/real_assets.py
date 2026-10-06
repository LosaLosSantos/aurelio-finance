"""REST endpoints for the "real_assets" resource (real/physical wealth).

Real assets (house, vehicle, collectible, ...) are owned directly, not held at
an institution — so this is a branch parallel to the financial one. Each asset
has dated valuations (mirroring account snapshots), which gives it a history.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api", tags=["real_assets"])


@router.post(
    "/real-assets",
    response_model=schemas.RealAssetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_real_asset(
    payload: schemas.RealAssetCreate,
    db: Session = Depends(get_db),
) -> schemas.RealAssetRead:
    """Create a new real asset."""
    return crud.create_real_asset(db, payload)


@router.get("/real-assets", response_model=list[schemas.RealAssetRead])
def list_real_assets(db: Session = Depends(get_db)) -> list[schemas.RealAssetRead]:
    """List all real assets."""
    return crud.get_real_assets(db)


@router.get("/real-assets/{real_asset_id}", response_model=schemas.RealAssetRead)
def get_real_asset(
    real_asset_id: int,
    db: Session = Depends(get_db),
) -> schemas.RealAssetRead:
    """Return a single real asset, or 404 if it does not exist."""
    return get_or_404(db, models.RealAsset, real_asset_id)


@router.post(
    "/real-assets/{real_asset_id}/valuations",
    response_model=schemas.RealAssetValuationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_valuation(
    real_asset_id: int,
    payload: schemas.RealAssetValuationCreate,
    db: Session = Depends(get_db),
) -> schemas.RealAssetValuationRead:
    """Add a dated valuation to a real asset (409 if one already exists for that date)."""
    get_or_404(db, models.RealAsset, real_asset_id)
    try:
        return crud.create_real_asset_valuation(db, real_asset_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A valuation for real asset {real_asset_id} on "
                f"{payload.date.isoformat()} already exists"
            ),
        )


@router.get(
    "/real-assets/{real_asset_id}/valuations",
    response_model=list[schemas.RealAssetValuationRead],
)
def list_valuations(
    real_asset_id: int,
    db: Session = Depends(get_db),
) -> list[schemas.RealAssetValuationRead]:
    """List a real asset's valuations (chronological order)."""
    get_or_404(db, models.RealAsset, real_asset_id)
    return crud.get_valuations_for_real_asset(db, real_asset_id)


@router.get(
    "/real-asset-valuations/{valuation_id}",
    response_model=schemas.RealAssetValuationRead,
)
def get_valuation(
    valuation_id: int,
    db: Session = Depends(get_db),
) -> schemas.RealAssetValuationRead:
    """Return a single valuation, or 404 if it does not exist."""
    return get_or_404(db, models.RealAssetValuation, valuation_id)


@router.put("/real-assets/{real_asset_id}", response_model=schemas.RealAssetRead)
def update_real_asset(
    real_asset_id: int,
    payload: schemas.RealAssetCreate,
    db: Session = Depends(get_db),
) -> schemas.RealAssetRead:
    """Update a real asset."""
    get_or_404(db, models.RealAsset, real_asset_id)
    return crud.update_real_asset(db, real_asset_id, payload)


@router.put(
    "/real-asset-valuations/{valuation_id}",
    response_model=schemas.RealAssetValuationRead,
)
def update_valuation(
    valuation_id: int,
    payload: schemas.RealAssetValuationCreate,
    db: Session = Depends(get_db),
) -> schemas.RealAssetValuationRead:
    """Update a valuation (409 if another valuation exists for that asset+date)."""
    get_or_404(db, models.RealAssetValuation, valuation_id)
    try:
        return crud.update_real_asset_valuation(db, valuation_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A valuation for this asset and date already exists",
        )


@router.delete("/real-assets/{real_asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_real_asset(real_asset_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a real asset (cascades to its valuations)."""
    get_or_404(db, models.RealAsset, real_asset_id)
    crud.delete_real_asset(db, real_asset_id)


@router.delete(
    "/real-asset-valuations/{valuation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_valuation(valuation_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a real-asset valuation."""
    get_or_404(db, models.RealAssetValuation, valuation_id)
    crud.delete_real_asset_valuation(db, valuation_id)
