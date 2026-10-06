"""REST endpoints for the "institutions" resource.

An APIRouter is a "mini-app" of endpoints that is later attached to the main
app in main.py. Here the routers stay thin: they validate the input (thanks to
the Pydantic schemas), call the `crud` layer, and return the output (which
FastAPI serializes according to `response_model`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api", tags=["institutions"])


@router.post(
    "/institutions",
    response_model=schemas.InstitutionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_institution(
    payload: schemas.InstitutionCreate,
    db: Session = Depends(get_db),
) -> schemas.InstitutionRead:
    """Create a new institution."""
    return crud.create_institution(db, payload)


@router.get("/institutions", response_model=list[schemas.InstitutionRead])
def list_institutions(db: Session = Depends(get_db)) -> list[schemas.InstitutionRead]:
    """List all institutions."""
    return crud.get_institutions(db)


@router.get("/institutions/{institution_id}", response_model=schemas.InstitutionRead)
def get_institution(
    institution_id: int,
    db: Session = Depends(get_db),
) -> schemas.InstitutionRead:
    """Return a single institution, or 404 if it does not exist."""
    return get_or_404(db, models.Institution, institution_id)


@router.put("/institutions/{institution_id}", response_model=schemas.InstitutionRead)
def update_institution(
    institution_id: int,
    payload: schemas.InstitutionCreate,
    db: Session = Depends(get_db),
) -> schemas.InstitutionRead:
    """Update an institution."""
    get_or_404(db, models.Institution, institution_id)
    return crud.update_institution(db, institution_id, payload)


@router.delete("/institutions/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_institution(institution_id: int, db: Session = Depends(get_db)) -> None:
    """Delete an institution (cascades to its accounts, snapshots and holdings)."""
    get_or_404(db, models.Institution, institution_id)
    crud.delete_institution(db, institution_id)
