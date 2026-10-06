"""REST endpoints for the "holdings" resource (positions within a snapshot).

Holdings are children of a snapshot: create/list URLs are nested under the
snapshot. Before operating we check that the snapshot exists (otherwise 404).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404, holding_read, holding_reads

router = APIRouter(prefix="/api", tags=["holdings"])


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
    return holding_read(db, crud.create_holding(db, snapshot_id, payload))


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
    """Update a holding (value recomputed from quantity*price if not given)."""
    get_or_404(db, models.Holding, holding_id)
    return holding_read(db, crud.update_holding(db, holding_id, payload))


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a holding."""
    get_or_404(db, models.Holding, holding_id)
    crud.delete_holding(db, holding_id)
