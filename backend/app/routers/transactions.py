"""REST endpoints for the investment ledger (buy transactions) and the PAC
catch-up. The catch-up reaches Yahoo for historical closes, so per-occurrence
failures are reported as `skipped` instead of failing the request."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, pac, schemas
from app.database import get_db
from app.routers.deps import get_or_404, transaction_reads


def _refused_without_a_rate(exc: crud.LedgerRateUnknown) -> HTTPException:
    """422: the entry is well-formed, and the one figure it needs — what the
    account moved by — cannot be worked out without a rate for its day."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

router = APIRouter(prefix="/api", tags=["transactions"])


@router.post(
    "/transactions",
    response_model=schemas.TransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    data: schemas.TransactionWrite, db: Session = Depends(get_db)
) -> schemas.TransactionRead:
    """Record a buy manually (a purchase made outside any PAC).

    `TransactionWrite` rather than `TransactionCreate`: an entry posted here
    must name the institution holding it, because the cash has to leave a real
    account. The PAC writes through `crud` directly and keeps its looser
    payload — see the schema for what the difference is and why it is not a
    migration."""
    try:
        tx = crud.create_transaction(db, data)
    except crud.LedgerRateUnknown as exc:
        raise _refused_without_a_rate(exc)
    return transaction_reads(db, [tx])[0]


@router.get("/transactions", response_model=list[schemas.TransactionRead])
def list_transactions(db: Session = Depends(get_db)) -> list[schemas.TransactionRead]:
    """All recorded transactions, most recent first."""
    return transaction_reads(db, crud.get_transactions(db))


@router.get("/transactions/{tx_id}", response_model=schemas.TransactionRead)
def get_transaction(tx_id: int, db: Session = Depends(get_db)) -> schemas.TransactionRead:
    return transaction_reads(db, [get_or_404(db, models.Transaction, tx_id)])[0]


@router.put("/transactions/{tx_id}", response_model=schemas.TransactionRead)
def update_transaction(
    tx_id: int, data: schemas.TransactionWrite, db: Session = Depends(get_db)
) -> schemas.TransactionRead:
    """Correct a transaction with the real broker fill (clears `estimated`).

    The same requirement as the POST, and this is the door an existing
    institution-less row is repaired through: attaching one is a one-field
    edit."""
    get_or_404(db, models.Transaction, tx_id)
    try:
        tx = crud.update_transaction(db, tx_id, data)
    except crud.LedgerRateUnknown as exc:
        raise _refused_without_a_rate(exc)
    return transaction_reads(db, [tx])[0]


@router.delete("/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(tx_id: int, db: Session = Depends(get_db)) -> None:
    get_or_404(db, models.Transaction, tx_id)
    crud.delete_transaction(db, tx_id)


@router.post("/transactions/catch-up", response_model=schemas.CatchUpResult)
def catch_up(db: Session = Depends(get_db)) -> schemas.CatchUpResult:
    """Ledger catch-up (idempotent — safe to call at every app start): a Buy
    for every elapsed, still-unexecuted PAC occurrence at that day's close,
    and a dividend entry for every ex-date of every position that follows its
    dividends: stated distributing, or stating no policy, when its own history
    decides. Items that cannot be priced are skipped and retried on the next
    run."""
    return pac.catch_up(db)
