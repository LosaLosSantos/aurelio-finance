"""REST endpoints for financial goals + the goal-planning calculation.

Goals are either a 'safe' qualitative type or a concrete target (amount +
horizon). For concrete targets, `POST /api/planning/required-return` returns
the annual return needed to reach them, with a short realism note.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import crud, models, planning, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api", tags=["goals"])


@router.post("/goals", response_model=schemas.GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: schemas.GoalCreate,
    db: Session = Depends(get_db),
) -> schemas.GoalRead:
    """Create a new goal."""
    return crud.create_goal(db, payload)


@router.get("/goals", response_model=list[schemas.GoalRead])
def list_goals(db: Session = Depends(get_db)) -> list[schemas.GoalRead]:
    """List all goals."""
    return crud.get_goals(db)


@router.get("/goals/{goal_id}", response_model=schemas.GoalRead)
def get_goal(goal_id: int, db: Session = Depends(get_db)) -> schemas.GoalRead:
    """Return a single goal, or 404 if it does not exist."""
    return get_or_404(db, models.Goal, goal_id)


@router.put("/goals/{goal_id}", response_model=schemas.GoalRead)
def update_goal(
    goal_id: int,
    payload: schemas.GoalCreate,
    db: Session = Depends(get_db),
) -> schemas.GoalRead:
    """Update a goal."""
    get_or_404(db, models.Goal, goal_id)
    return crud.update_goal(db, goal_id, payload)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a goal."""
    get_or_404(db, models.Goal, goal_id)
    crud.delete_goal(db, goal_id)


@router.post("/planning/required-return", response_model=schemas.RequiredReturnResult)
def required_return(payload: schemas.RequiredReturnRequest) -> schemas.RequiredReturnResult:
    """Annual return needed to reach a dated target, plus a realism note."""
    return planning.compute_required_return(
        payload.current_amount,
        payload.monthly_contribution,
        payload.target_amount,
        payload.target_date,
    )
