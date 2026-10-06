"""REST endpoints for market prices: quotes, ISIN resolution, and refreshing a
holding's unit price from the live quote.

These reach external services (Yahoo via yfinance, OpenFIGI) at request time, so
a failure returns 502 with a clear message rather than crashing.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud, fx, models, prices, schemas
from app.database import get_db
from app.routers.deps import get_or_404, holding_read

router = APIRouter(prefix="/api", tags=["prices"])


@router.get("/fx/rates", response_model=list[schemas.FxRateRead])
def get_fx_rates(
    refresh: bool = False, db: Session = Depends(get_db)
) -> list[schemas.FxRateRead]:
    """The ECB reference rates in force today against the base (units per 1
    base): the latest published day, asked for at most once a day. Empty until
    the first successful fetch; ?refresh=true asks again. Each row names its
    base and its day, so a rate is never a bare number here either."""
    base = fx.base_currency(db)
    rates = fx.rates_on(db, base, datetime.date.today().isoformat(), refresh=refresh)
    day = next(iter(rates.values()))["as_of"] if rates else None
    return crud.get_fx_rate_rows(db, base, day) if day else []


@router.get("/prices/quote", response_model=schemas.PriceQuote)
def get_quote(
    symbol: str = Query(..., min_length=1),
    on: datetime.date | None = Query(
        default=None,
        description="Close on/just before this date, for recording a past purchase",
    ),
    db: Session = Depends(get_db),
) -> schemas.PriceQuote:
    """Price for a Yahoo symbol (e.g. VWCE.MI, AAPL, BTC-EUR): the latest
    close, or the close on a given date when `on` is passed — which is what
    turns backfilling an old purchase into typing a date and a quantity.

    A dated close comes back without a currency from the market, and the
    currency it is in is exactly what a ledger entry has to state. A listing's
    currency does not change, so the one the price cache has learned for the
    symbol is given with it; a symbol nothing has priced yet has none to give."""
    try:
        if on is not None:
            quote = prices.get_price_on(symbol, on)
            cached = crud.get_cached_prices(db, [quote["symbol"]]).get(quote["symbol"], {})
            return {**quote, "currency": cached.get("currency")}
        return prices.get_quote(symbol, fx.base_currency(db))
    except prices.NoCloseYet as exc:
        # 404, and neither of the two below: the market answered and the symbol
        # is fine — that day's close is what does not exist (yet). It used to be
        # a 200 carrying a null price, which left the form's price box empty
        # with nothing said, and an empty box reads like a broken ticker.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except prices.MarketUnreachable as exc:
        # 503, not 502: "nobody answered" is a different answer from "that
        # symbol is wrong", and a client that cannot tell them apart will
        # tell someone to correct a ticker that was right.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except prices.PriceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/prices/listing-currencies", response_model=dict[str, str])
def get_listing_currencies(db: Session = Depends(get_db)) -> dict[str, str]:
    """{symbol: currency} for every listing whose trading currency is known,
    from the price cache alone — no market call. What a ledger form proposes as
    the currency of a price, before anyone has typed one."""
    return crud.get_listing_currencies(db)


@router.get("/prices/resolve", response_model=list[schemas.IsinSuggestion])
def resolve_isin(isin: str = Query(..., min_length=1)) -> list[schemas.IsinSuggestion]:
    """Suggest tickers for an ISIN (you may need to add a Yahoo suffix like .MI)."""
    try:
        return prices.resolve_isin(isin)
    except prices.MarketUnreachable as exc:
        # 503, not 502: "nobody answered" is a different answer from "that
        # symbol is wrong", and a client that cannot tell them apart will
        # tell someone to correct a ticker that was right.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except prices.PriceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post(
    "/holdings/{holding_id}/refresh-price", response_model=schemas.HoldingRead
)
def refresh_holding_price(
    holding_id: int, db: Session = Depends(get_db)
) -> schemas.HoldingRead:
    """Fetch the live quote for a holding's symbol and update its unit price
    (recomputing value if the holding is quantity-based)."""
    holding = get_or_404(db, models.Holding, holding_id)
    if not holding.symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This holding has no symbol/ticker to fetch a price for",
        )
    try:
        quote = prices.get_quote(holding.symbol, fx.base_currency(db))
    except prices.MarketUnreachable as exc:
        # 503, not 502: "nobody answered" is a different answer from "that
        # symbol is wrong", and a client that cannot tell them apart will
        # tell someone to correct a ticker that was right.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except prices.PriceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return holding_read(
        db, crud.set_holding_price(db, holding, quote["price"])
    )
