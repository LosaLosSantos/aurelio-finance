"""REST endpoints for the local instrument registry.

The search is answered entirely from SQLite, so it is instant and works with no
network at all. The download is the app's own, started by every page load and
run in the background (`catalogue.ensure`): justETF has no timeout of its own,
21 s on a dead network, and must never sit on the path of someone typing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import catalogue, prices, schemas
from app.database import get_db

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


@router.get("/search", response_model=schemas.InstrumentSearch)
def search_instruments(
    q: str = Query("", description="Free text: name, issuer, ticker"),
    limit: int = Query(8, ge=1, le=25),
    db: Session = Depends(get_db),
) -> schemas.InstrumentSearch:
    """Instrument families matching `q`, local only.

    Families, not rows: an accumulating fund and its distributing twin carry
    the same name and differ only in what they do with dividends, so showing
    one of a pair alone invites picking the wrong one without ever revealing
    there was a choice."""
    return schemas.InstrumentSearch(**catalogue.search(db, q, limit))


@router.get("/catalogue", response_model=schemas.CatalogueStatus)
def catalogue_status(db: Session = Depends(get_db)) -> schemas.CatalogueStatus:
    """What the registry holds and when it was last downloaded."""
    return schemas.CatalogueStatus(**catalogue.status(db))


@router.post("/catalogue/ensure", response_model=schemas.CatalogueStatus)
def ensure_catalogue(db: Session = Depends(get_db)) -> schemas.CatalogueStatus:
    """Asked at every page load. Starts a download in the background when the
    catalogue is missing or a week old and none is running, and answers at once
    with where things stand: nobody presses anything for the catalogue."""
    return schemas.CatalogueStatus(**catalogue.ensure(db))


@router.post("/catalogue/refresh", response_model=schemas.CatalogueStatus)
def refresh_catalogue(db: Session = Depends(get_db)) -> schemas.CatalogueStatus:
    """Download now and wait for it, whatever the catalogue's age. No page calls
    it: it is the door for a download by hand, behind the same one-at-a-time
    guard as the app's own (409 while one runs). 502 if the source fails or
    sends something that is not a catalogue, the stored copy left exactly as it
    was, since a failed download must never leave the picker emptier than it
    found it."""
    try:
        catalogue.refresh(db)
    except catalogue.Busy as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:  # network, parsing, source layout change, refused
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not download the instrument catalogue: {exc}",
        )
    return schemas.CatalogueStatus(**catalogue.status(db))


@router.get("/lookup", response_model=schemas.SymbolLookup)
def lookup_symbols(
    q: str = Query("", description="Free text: company, coin, ticker"),
    limit: int = Query(8, ge=1, le=25),
) -> schemas.SymbolLookup:
    """The live lane: shares, ETFs, crypto and futures — everything the fund
    catalogue cannot hold, and the only source of a symbol that actually
    prices.

    Deliberately a SEPARATE endpoint from /search. The catalogue answers from
    SQLite in milliseconds; this one is a network call. Combining them would
    make the instant lane wait for the slow one, and would let an outage empty
    a list that had perfectly good local results to show."""
    results = prices.lookup(q, limit)
    # An empty list from a source that never answered is not the same claim as
    # an empty list from one that did.
    reachable = bool(results) or len((q or "").strip()) < 2
    return schemas.SymbolLookup(results=results, reachable=reachable)
