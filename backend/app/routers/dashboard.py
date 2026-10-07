"""REST endpoints for the dashboard (read-only aggregations).

Thin router: it just calls the `analytics` layer and returns the result,
which FastAPI validates/serializes via `response_model`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import analytics, composition, dated, schemas
from app.database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=schemas.DashboardSummary)
def get_summary(db: Session = Depends(get_db)) -> schemas.DashboardSummary:
    """Net worth (financial + real) and a few counts."""
    return analytics.compute_summary(db)


@router.get("/allocation", response_model=schemas.DashboardAllocation)
def get_allocation(db: Session = Depends(get_db)) -> schemas.DashboardAllocation:
    """Allocation: financial by asset class, real by category."""
    return analytics.compute_allocation(db)


@router.get("/net-worth-series", response_model=list[schemas.NetWorthPoint])
def get_net_worth_series(db: Session = Depends(get_db)) -> list[schemas.NetWorthPoint]:
    """Net worth over time (carry-forward), summing accounts and real assets."""
    return analytics.compute_net_worth_series(db)


@router.get("/cashflow", response_model=schemas.CashFlowSummary)
def get_cashflow(db: Session = Depends(get_db)) -> schemas.CashFlowSummary:
    """The income and expenses in force today as a monthly run-rate, the
    savings rate and the splits, and the flows left out: the ones still to
    start and the ones that have ended."""
    return analytics.compute_flows_in_force(db, dated.today())


@router.get("/portfolio", response_model=schemas.Portfolio)
def get_portfolio(
    live: bool = False, db: Session = Depends(get_db)
) -> schemas.Portfolio:
    """Investment positions (latest snapshot per institution). With ?live=true,
    fetch market prices (one batch) and update the price cache; otherwise reuse
    cached prices. Market value + P/L are computed vs the recorded value."""
    return analytics.compute_portfolio(db, live=live)


@router.get("/portfolio/composition", response_model=schemas.PortfolioComposition)
def get_portfolio_composition(
    refresh: bool = False, db: Session = Depends(get_db)
) -> schemas.PortfolioComposition:
    """Look-through composition of the whole portfolio: aggregated country and
    sector exposure plus cross-fund holding overlap. Per-symbol data comes
    from the 15-day cache; ?refresh=true forces a refetch from the sources
    (justETF / Morningstar / Yahoo). Positions no source can decompose stay
    whole and lower `coverage_pct` — honestly."""
    return composition.compute_portfolio_composition(db, refresh=refresh)
