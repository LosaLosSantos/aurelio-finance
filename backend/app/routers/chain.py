"""Reading the analysis runs: the list of them, and one of them.

There is nothing here that RUNS one, and that is the whole shape of this step.
The chain used to be a page with a button; it is now a tool the chat proposes,
the reader confirms on a card, and watches step by step down the panel. What is
left over is the reading, and it is left over for the argument that kept the
chain on a page in the first place: the verdict is a document, and a document
does not belong in a 32%-wide column. So the card opens it here, in the main
column, at the width prose is read at.

By id and not "the latest". A card proposed three conversations ago points at
the run IT produced, and answering it with whatever ran most recently would
show the reader a different document under the receipt they clicked. Which is
also why the LIST had to exist: an app that can already address any run had no
way to say which runs there are, so a run whose card had scrolled out of a
conversation — or whose conversation was deleted — was unreachable while still
being perfectly well stored.

A READER'S SURFACE, and deliberately not a sub-agent's. Nothing here is wired
into `advisor.build_portfolio_context` or `build_person_context`: the analyst
must not see the person and the confidant must not see a figure, and a history
of what the pair concluded last time is exactly the sort of thing that leaks
one into the other. `tests/test_advisor.py` holds that line.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import chain, crud, models, schemas
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api/advisor/chain", tags=["advisor"])

# How far back the list goes. A ceiling and not a page: this is one person's
# machine and the number of times they have asked four models to argue is small
# — but every summary is computed by reading the confidant's own words, so an
# unbounded listing would read a year of transcripts to print a column of
# dates. Raise it the day somebody scrolls to the bottom.
HISTORY_LIMIT = 50


@router.get("", response_model=list[schemas.ChainRunSummary])
def list_chain_runs(db: Session = Depends(get_db)) -> list[schemas.ChainRunSummary]:
    """Every analysis run, newest first: when, how deep, and whether it argued.

    The summary is computed here rather than stored, and that is what makes it
    true of runs that finished before anyone thought to ask the question. The
    marker was already in the confidant's own text; nothing was migrated and
    nothing had to be.
    """
    return [
        schemas.ChainRunSummary(
            id=run.id,
            created_at=run.created_at,
            step_count=len(run.steps),
            revisions=sum(1 for s in run.steps if s.role == "revision"),
            challenge=(chain.challenge_of(run) or "unstated").lower(),
        )
        for run in crud.get_chain_runs(db, limit=HISTORY_LIMIT)
    ]


@router.get("/{run_id}", response_model=schemas.ChainRunRead)
def get_chain_run(run_id: int, db: Session = Depends(get_db)) -> models.ChainRun:
    """One analysis run: the verdict, and every step behind it."""
    return get_or_404(db, models.ChainRun, run_id)
