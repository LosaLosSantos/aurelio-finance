"""REST endpoints for the watchlist: the ideas the chat parked, and dropping one.

Read and delete only, and the missing POST is a decision. Nothing in this app
creates a watchlist line except a suggestion card the reader accepted, and a
line's whole value is the three sentences that came with it — why, on the basis
of what, and what the suggestion did not know. A form posting those by hand
would be a surface with nobody behind it, and an endpoint nobody calls is still
an endpoint that has to keep working. The day the reader wants to add one
themselves, the POST arrives with the screen that fills it in.

Nothing here totals anywhere. A watchlist line is not a holding: it moves no
net worth, no allocation and no cash projection, which is exactly what makes it
safe for a model to propose.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[schemas.WatchlistItemRead])
def list_watchlist(db: Session = Depends(get_db)) -> list[models.WatchlistItem]:
    """Every idea on the list, most recently added first."""
    return crud.get_watchlist_items(db)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_item(item_id: int, db: Session = Depends(get_db)) -> None:
    """Drop one idea. It owned nothing, so nothing is recomputed."""
    get_or_404(db, models.WatchlistItem, item_id)
    crud.delete_watchlist_item(db, item_id)
