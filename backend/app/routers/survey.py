"""REST endpoints for the planning questionnaire (survey responses).

Single-user model: GET returns all answers; PUT replaces the whole set with
the provided answers (the frontend sends the full current set on save).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter(prefix="/api", tags=["survey"])


@router.get("/survey", response_model=list[schemas.SurveyAnswerRead])
def get_survey(db: Session = Depends(get_db)) -> list[schemas.SurveyAnswerRead]:
    """Return all stored questionnaire answers."""
    return crud.get_survey_responses(db)


@router.put("/survey", response_model=list[schemas.SurveyAnswerRead])
def put_survey(
    answers: list[schemas.SurveyAnswer],
    db: Session = Depends(get_db),
) -> list[schemas.SurveyAnswerRead]:
    """Replace the whole set of answers with the provided ones."""
    return crud.replace_survey_responses(db, answers)
