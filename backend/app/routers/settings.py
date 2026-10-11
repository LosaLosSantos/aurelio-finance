"""REST endpoints for the reader's settings: the declared tax rates, and the
base currency every total is shown in.

WHY THIS IS NOT `/api/settings/{key}`. The `settings` table is key->value and
a generic door over it would be two lines shorter — and would also let the
browser overwrite `catalogue_fetched_at`, the row that decides whether the
instrument registry looks fresh. A typed resource for the three keys somebody
actually sets keeps every other key out of reach and gives the frontend a
generated type instead of a bag of strings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, fx, schemas, tax
from app.database import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _read(db: Session) -> schemas.TaxSettingsRead:
    rates = tax.read_rates(db)
    return schemas.TaxSettingsRead(
        country=rates.country,
        capital_gains_rate=rates.capital_gains,
        dividend_withholding_rate=rates.dividend_withholding,
        known_countries=[
            schemas.TaxCountryDefault(
                country=name,
                capital_gains_rate=d.capital_gains,
                dividend_withholding_rate=d.dividend_withholding,
                regime=d.regime,
                omits=d.omits,
            )
            for name, d in tax.DEFAULTS.items()
        ],
    )


@router.get("/tax", response_model=schemas.TaxSettingsRead)
def get_tax_settings(db: Session = Depends(get_db)) -> schemas.TaxSettingsRead:
    """The declared rates, with the handful of countries this app ships a
    default for. The defaults come down as data to OFFER, never applied: a
    reader's own figure beats any table shipped here, and a rate that changed
    itself because a country field changed is a rate nobody declared."""
    return _read(db)


@router.put("/tax", response_model=schemas.TaxSettingsRead)
def put_tax_settings(
    data: schemas.TaxSettings, db: Session = Depends(get_db)
) -> schemas.TaxSettingsRead:
    """Replace all three. A null clears that key, which is how the reader says
    they do not know a rate — distinct from writing 0, which claims they pay
    nothing."""
    tax.write_rates(
        db,
        country=data.country,
        capital_gains=data.capital_gains_rate,
        dividend_withholding=data.dividend_withholding_rate,
    )
    return _read(db)


def _base_read(db: Session) -> schemas.BaseCurrencySettingRead:
    return schemas.BaseCurrencySettingRead(
        base_currency=fx.base_currency(db), available=fx.feed_currencies(db)
    )


@router.get("/base-currency", response_model=schemas.BaseCurrencySettingRead)
def get_base_currency(db: Session = Depends(get_db)) -> schemas.BaseCurrencySettingRead:
    """The currency every total is shown in, and the ones it can become: the
    currencies the ECB feed quotes, because a total can only be converted into
    a currency somebody publishes a rate for."""
    return _base_read(db)


@router.put("/base-currency", response_model=schemas.BaseCurrencySettingRead)
def put_base_currency(
    data: schemas.BaseCurrencySetting, db: Session = Depends(get_db)
) -> schemas.BaseCurrencySettingRead:
    """Change the base. Every total moves — the history's too — because it is
    the same wealth in another unit; no recorded amount is rewritten.

    422 for a currency the feed does not quote. 503, with nothing changed, when
    the rates against the new base cannot be stored first: see
    `fx.choose_base` for why a base is not chosen before its rates are in. The
    rules are `crud.change_base`'s, which the chat's card goes through too."""
    try:
        crud.change_base(db, data.base_currency)
    except fx.BaseNotQuoted as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    except fx.BaseRatesUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return _base_read(db)
