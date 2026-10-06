"""A declared tax estimate — deliberately not a tax engine.

WHAT THIS IS NOT, AND WHY THAT IS THE DESIGN. A real engine for Italy alone
would need: 26% on capital gains but 12.5% on white-list government bonds,
harmonised versus non-harmonised funds, losses that cannot offset gains from
harmonised ETFs, a four-year basket, stamp duty, IVAFE, administered versus
declarative regime. Multiply that by every country this app is meant to serve.
The failure mode of building it is being PRECISE AND WRONG, which in tax
matters is worse than being openly approximate: a reader shown "roughly 26%,
stated as an estimate" checks it against their broker, and a reader shown a
confident figure does not.

So there is exactly ONE rule here, applied flat, and it is the reader's own:
a percentage they can see and overwrite. If a future edit ever adds a second
rule for a special kind of instrument — a bond rate, a fund wrapper, a holding
period — that is the line being crossed, and the honest move is to delete this
module rather than grow it.

WHERE IT APPLIES. Two places, both of which already hold the number:
the realized capital gain the ledger computed, and the dividends the ledger
collected. Nowhere else.

THE GOLDEN RULE. The figure this module produces never enters a total. Not
the net worth, not the book value, not a position's value. It travels BESIDE
them, carrying the rate it used and the word estimated, which is what keeps it
an aid to deciding instead of something impersonating a tax return.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

# The three keys, in `settings` — already a key->value table, so this needs no
# schema of its own (the same reason the catalogue's two entries live there).
COUNTRY = "tax_country"
CAPITAL_GAINS = "capital_gains_rate"
DIVIDEND_WITHHOLDING = "dividend_withholding_rate"

# Rates are stored and handled as PERCENT, never as a fraction. The app already
# has one rate on a model — `Liability.interest_rate`, printed as "%/yr" — and
# a codebase where 26 means 26% in one table and 0.26 means 26% in another has
# a factor-of-100 bug waiting in whichever direction a reader guesses wrong.


@dataclass(frozen=True, slots=True)
class Default:
    """A country's headline rate, and what it leaves out.

    `omits` is not a disclaimer bolted on afterwards — it is the reason this
    table is allowed to be this short. Each entry names the carve-outs it is
    knowingly flattening, so a reader can see whether the flat number is close
    enough for them before they trust it, and correct it when it is not."""

    capital_gains: float
    dividend_withholding: float
    regime: str
    omits: str


# WHICH DEFAULTS SHIP, AND WHY SO FEW. Every country here is a claim this
# project maintains, and a stale rate is worse than an absent one: France's
# moved 1.4 points on 1 January 2026 when the CSG rose, which is exactly how a
# table like this goes quietly wrong. So it holds only countries whose headline
# rate is genuinely ONE flat number for both gains and dividends. Spain's
# savings scale (19-28%), the UK's allowances and bands, the Netherlands' box 3
# (a deemed-return wealth tax, not a gains tax at all) are all shapes this
# module cannot represent, and inventing a single number for them would be the
# precise-and-wrong failure this whole file exists to avoid.
#
# A country that is NOT here loses nothing but the pre-fill. The rates are what
# every reader downstream reads; the country is a label on the estimate. Typing
# your own two figures gives you the identical feature, and a rate you looked
# up yourself is better than any table shipped here — which is why even a
# listed country's defaults are only a starting point.
#
# Each rate is the statutory headline rate as of 2026.
DEFAULTS: dict[str, Default] = {
    "Italy": Default(
        26.0,
        26.0,
        "imposta sostitutiva, 26% on both",
        "White-list government bonds are taxed at 12.5%, and crypto at 33% from "
        "2026. Neither carve-out is applied: this is one flat rate.",
    ),
    "Germany": Default(
        26.375,
        26.375,
        "Abgeltungsteuer 25% + 5.5% Solidaritätszuschlag",
        "Church tax (a further 8-9% of the tax) is not included, and the first "
        "€1,000 of investment income (Sparer-Pauschbetrag) is exempt, so a small "
        "portfolio is over-estimated here.",
    ),
    "France": Default(
        31.4,
        31.4,
        "PFU 12.8% income tax + 18.6% prélèvements sociaux",
        "The PFU rose from 30% to 31.4% on 1 January 2026 with the CSG. Electing "
        "the progressive scale instead can cost less, and life insurance keeps "
        "the older 17.2% social rate.",
    ),
}


def default_for(country: str | None) -> Default | None:
    """The shipped default for a country name, matched loosely on case and
    spacing. None for every country not in the table, which is not an error
    state — see the note above `DEFAULTS`."""
    if not country:
        return None
    wanted = country.strip().casefold()
    for name, d in DEFAULTS.items():
        if name.casefold() == wanted:
            return d
    return None


@dataclass(frozen=True, slots=True)
class Rates:
    """What the reader declared. Any of the three may be unset, and unset is a
    real answer — distinct from zero, which would be a reader claiming they pay
    no tax."""

    country: str | None
    capital_gains: float | None
    dividend_withholding: float | None

    @property
    def any_set(self) -> bool:
        return self.capital_gains is not None or self.dividend_withholding is not None


def _get(db: Session, key: str) -> str | None:
    row = db.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key}).first()
    return row[0] if row and row[0] not in (None, "") else None


def _set(db: Session, key: str, value: str | None) -> None:
    """Store a value, or remove the key entirely when there is none.

    Clearing DELETES rather than writing an empty string, so "the reader never
    set this" has one representation instead of three that read the same on
    screen and differently in a query."""
    if value is None or value == "":
        db.execute(text("DELETE FROM settings WHERE key = :k"), {"k": key})
        return
    db.execute(
        text(
            "INSERT INTO settings (key, value) VALUES (:k, :v)"
            " ON CONFLICT(key) DO UPDATE SET value = :v"
        ),
        {"k": key, "v": value},
    )


def _rate(raw: str | None) -> float | None:
    """A stored rate as a number, or None if it is absent or unreadable.

    Unreadable is treated as absent on purpose: `settings.value` is free text
    that nothing but this app writes, but a row hand-edited into "26%" must not
    take down the portfolio page for a figure that sits beside the totals."""
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def read_rates(db: Session) -> Rates:
    """The three settings, as they stand."""
    return Rates(
        country=_get(db, COUNTRY),
        capital_gains=_rate(_get(db, CAPITAL_GAINS)),
        dividend_withholding=_rate(_get(db, DIVIDEND_WITHHOLDING)),
    )


def write_rates(
    db: Session,
    *,
    country: str | None,
    capital_gains: float | None,
    dividend_withholding: float | None,
) -> Rates:
    """Replace all three. Each is independently clearable — a reader who knows
    their dividend rate and not their gains rate is in a legitimate state, and
    the estimate says which half it could not compute."""
    _set(db, COUNTRY, (country or "").strip() or None)
    _set(db, CAPITAL_GAINS, None if capital_gains is None else str(capital_gains))
    _set(
        db,
        DIVIDEND_WITHHOLDING,
        None if dividend_withholding is None else str(dividend_withholding),
    )
    db.commit()
    return read_rates(db)


# What every reader of this figure is told, always, because none of it stops
# being true once a rate is set. These live here rather than in the screen and
# the advisor prompt separately: the same caveats reach the page, the chat and
# any outside assistant, and there is one place to correct them.
BASIS_CAVEATS = (
    "This is a flat percentage you declared applied to two figures the ledger "
    "already holds. It is not a tax calculation and no return should be filed "
    "from it.",
    "The realized gain is computed at AVERAGE cost. Tax authorities generally "
    "are not: Italy matches disposals LIFO, Germany FIFO, so the gain a real "
    "return reports will differ from this one even at the same rate.",
    "It covers the whole recorded ledger, not a tax year, and nothing here "
    "carries losses forward or offsets them against gains across years.",
)


def estimate(
    rates: Rates,
    *,
    realized: float,
    dividends_estimated: float,
    dividends_recorded: float,
) -> dict:
    """The estimate, from the two bases the portfolio already computed.

    Pure: it takes numbers, not a session, so what it claims can be checked
    without a database.

    `dividends_estimated` is the gross subset — the rows still carrying the
    market's figure. `dividends_recorded` is the rest, which the reader
    replaced with the credit their broker actually paid. THE WITHHOLDING IS
    APPLIED ONLY TO THE FIRST. Applying it to the sum would tax a second time
    exactly the rows somebody took the trouble to correct, which is the
    diligent reader being punished for their diligence — a bug this project has
    already paid for once under that name.
    """
    taxable_gain = max(realized, 0.0)
    realized_loss = max(-realized, 0.0)

    cg_tax = (
        taxable_gain * rates.capital_gains / 100.0
        if rates.capital_gains is not None
        else None
    )
    div_tax = (
        dividends_estimated * rates.dividend_withholding / 100.0
        if rates.dividend_withholding is not None
        else None
    )

    # A total only when every base that has something in it has a rate to
    # apply. Summing the halves that happen to be computable would produce a
    # figure the reader reads as "my tax" while it silently omits the other
    # half — the same claim-shaped absence the app refuses everywhere else.
    missing: list[str] = []
    if taxable_gain > 0 and rates.capital_gains is None:
        missing.append("capital gains")
    if dividends_estimated > 0 and rates.dividend_withholding is None:
        missing.append("dividend withholding")
    total = (
        (cg_tax or 0.0) + (div_tax or 0.0)
        if not missing and (cg_tax is not None or div_tax is not None)
        else None
    )

    # NO AMOUNTS IN THIS PROSE. Every figure here is already a field on the
    # result, and only the caller knows how to punctuate one: the frontend has
    # exactly one currency formatter and it follows the reader's locale, so a
    # "177.60" baked in here would land beside a "EUR 178" it was supposed to
    # match. The rule the app already runs on — the currency is designed, the
    # locale is whatever the reader has — applies to a sentence as much as to
    # a column.
    caveats = list(BASIS_CAVEATS)
    if realized_loss > 0:
        caveats.append(
            "The ledger's realized result is a LOSS, so no gain is estimated on "
            "it. Most regimes let a loss offset later gains; this does not track "
            "that."
        )
    if dividends_recorded > 0:
        caveats.append(
            "Some of the dividends collected are figures you corrected by hand, "
            "so they are already net of whatever your broker withheld. No rate is "
            "applied to them."
        )
    known = default_for(rates.country)
    if known is not None:
        caveats.append(f"{rates.country}: {known.omits}")

    return {
        "country": rates.country,
        "capital_gains_rate": rates.capital_gains,
        "dividend_withholding_rate": rates.dividend_withholding,
        "configured": rates.any_set,
        "realized_gain": realized,
        "taxable_gain": taxable_gain,
        "capital_gains_tax": cg_tax,
        "dividends_gross_estimated": dividends_estimated,
        "dividends_recorded_net": dividends_recorded,
        "dividend_withholding": div_tax,
        "total": total,
        "missing_rates": missing,
        "regime": known.regime if known is not None else None,
        "caveats": caveats,
    }
