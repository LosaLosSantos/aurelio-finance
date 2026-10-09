"""Pydantic schemas = the data "contract" for what enters/leaves the API.

For those coming from DS/ML: think of them as the expected schema of a
DataFrame (which fields, which types, which are required). Pydantic
automatically validates every incoming JSON and serializes what goes out.

Important distinction:
- ...Create  -> what the client MAY send (input). No id/created_at:
               the server generates them.
- ...Read    -> what the API returns (output). Includes id and created_at.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _must_have_happened(d: datetime.date) -> datetime.date:
    """Refuse a date that has not arrived yet."""
    today = datetime.date.today()
    if d > today:
        raise ValueError(
            f"{d} has not happened yet: today is {today}. A situation, a "
            "valuation, a balance and a cash anchor are all OBSERVATIONS, and "
            "there is nothing to observe about a future day. To correct a row "
            "that already carries a future date, move the date back or delete "
            "the row."
        )
    return d


# The date of an observation: today or earlier, never later.
#
# Attach it to a ...Create and NEVER to a ...Base or a ...Read. FastAPI
# validates the response model too, so a refusal placed on the shared base
# refuses to SERIALIZE a row that is already stored — the snapshot list of an
# account holding one legacy future row answered 500, which turns "you may not
# write this" into "you may not look at what you wrote", and takes away the
# only screen from which the row could be corrected or deleted.
#
# The four dated series this is attached to are the app's account of what is
# true, and each of them is read as "the latest one in force". A row dated
# ahead of today therefore answered for a day nobody had lived through: one
# empty snapshot dated eleven days out reported a 1,000.00 portfolio as 0.00,
# and one 999,999.00 balance on the same date took the net worth from
# 120,000.00 to -999,998.00. `dated` now refuses to read such a row; this
# refuses to store one, so the two halves cannot disagree.
#
# Not a `Field(le=...)`: that bound is evaluated once when the class is built,
# which for a server left running would freeze "today" on the day it started.
#
# Deliberately NOT applied to transactions, transfers or a plan's start/end
# date. Those are events and intentions, not observations — a plan that runs
# until 2030 is a fact about the future you are allowed to state.
ObservedDate = Annotated[datetime.date, AfterValidator(_must_have_happened)]


# A currency CODE: three letters, which is what ISO 4217 is and also what every
# minor unit this app knows is written as (`GBp`, `GBX`, `ZAC`, `ILA`). Case is
# NOT normalised here, and that is the whole reason this is a pattern rather
# than an upper-casing: `GBp` is pence and `GBP` is pounds, on the same
# exchange, and one lowercase letter separates a hundredfold (`fx._MINOR_EXACT`).
_CURRENCY_CODE = re.compile(r"^[A-Za-z]{3}$")


def _must_be_a_currency_code(code: str) -> str:
    """Refuse a currency that is only whitespace, or that is not a code at all.

    Three letters is a SHAPE check, and it is deliberately not a check that the
    currency exists or that the app can convert it — those are three different
    questions and this answers only the first:

    * `Dollari` and `EURO` are not codes, and they are what this stops. Four
      real assets of 1,000 in EUR, USD, `EURO` and `Dollari` totalled 3,800.00
      at a rate of 1.25 (measured; audit T measured 3,871.00 at the real rate),
      because an amount that cannot be converted is added AS STORED — so each
      invented code contributed its full 1,000.00.
    * `TWD` is a real currency the ECB does not quote, and a Taipei-listed fund
      is a legitimate holding, so validating against `fx.feed_currencies` would
      refuse something the reader owns. `GBp` is the same case for the same
      reason. That is why the shape is all that is checked here, and why the
      honesty of a total does not rest on this function: what carries "this
      could not be converted" to the reader is `fx.Converter.unconverted`.
    * `ABC` passes. It is a well-formed code for no currency, has no rate, and
      is reported by that same notice rather than by a list of codes here that
      would go stale and would refuse the next real one.

    Attached to each ...Create and never to a ...Base or a ...Read, for the
    reason written above `ObservedDate`: a check on the shared base runs when a
    STORED row is serialized too, and a refusal there would stop the reader
    seeing the row they need in order to correct it. The reader's own database
    holds one such row today (a real asset in `Doll`), and it stays readable and
    editable; the next save through its form is what refuses it, with this
    sentence, naming the box.
    """
    code = code.strip()
    if not code:
        raise ValueError(
            "say which currency this is in (e.g. EUR, USD). An amount with no "
            "currency cannot be added to anything, and the app will not guess "
            "one for it."
        )
    if not _CURRENCY_CODE.match(code):
        raise ValueError(
            f"'{code}' is not a currency code. Use the three-letter code (EUR, "
            "USD, GBP, CHF), because that is what the exchange-rate feed is "
            "keyed by: a code it has never heard of has no rate, and the amount "
            "is then added to your totals as if it were already in your base "
            "currency."
        )
    return code


# The currency an amount is written in: required, not blank, and a CODE.
#
# Every amount the app stores says its currency, and nothing fills one in for
# a write that leaves it out. An empty value used to mean EUR, and that was
# true only because EUR was the only base there has been; stamping "the base
# right now" on a write that omits it would keep an absence meaning one thing
# in the table and another in the request. So the field is required, and a form
# that forgets it is refused rather than guessed at. (Until `59ef644` there was
# a second reason with teeth: an update replaced every settable column, so a
# form that did not send the field rewrote the row's stated currency on every
# save. An edit now writes only what it was sent — but the requirement stands
# on the first reason alone, and the currency of an amount is not a field to
# make optional again.)
#
# Attached to each ...Create, never to a ...Base or a ...Read, for the reason
# written above `ObservedDate`: a check on the shared base also runs when a
# stored row is serialized, and a refusal there stops the reader from seeing
# the row they would need to correct. The bases require a plain string, which
# the NOT NULL columns guarantee.
StatedCurrency = Annotated[str, AfterValidator(_must_be_a_currency_code)]


# The unit of every figure a payload computed rather than copied from a row.
#
# `value_eur` carried its unit in its name, and that is what closed 0bf262b: a
# total in Turkish lira reached a screen under a euro sign because a field named
# `value` said nothing about what it was in. With a base that can be anything,
# the unit cannot live in a name — `value_base` says "the base" and not which
# one — so it travels beside the figures, from the same converter that made
# them. Declared on each payload rather than once per app: a tab left open
# across a change of base still shows each number with the unit it was computed
# in, because the two arrived together, and a row copied out of a list keeps
# its unit with it. Required, so a builder that forgets it fails validation
# instead of shipping a number without a unit.
BaseCurrency = Annotated[
    str,
    Field(
        description=(
            "The currency this payload's computed amounts are in — the database's "
            "base, as the figures were converted. Figures a row states itself "
            "(an anchor, a transaction, a valuation) keep their own `currency`."
        )
    ),
]


# Every model the API RETURNS carries this.
#
# `from_attributes` lets Pydantic read straight off the SQLAlchemy object
# (institution.id, institution.name, ...).
#
# The second half is about what the schema PROMISES. A field with a default is
# optional on the way IN — a client may leave `fees` out and the backend fills
# in 0 — but it is never absent on the way OUT, because FastAPI serializes the
# whole response model every time. Said only once, the OpenAPI document
# understates the response, and the frontend's generated types then make every
# defaulted field `| undefined`: forty call sites defending against a key that
# is always there. Pydantic keeps the two schemas separate, so the model can
# tell the truth in both directions at once.
API_OUT = ConfigDict(
    from_attributes=True,
    json_schema_serialization_defaults_required=True,
)

class InstitutionBase(BaseModel):
    """Fields shared between input and output."""

    name: str = Field(..., min_length=1, description="Institution name")
    # bank | broker | insurance | pension_fund | crypto_exchange | other
    type: str | None = Field(default=None, description="Institution type")
    notes: str | None = Field(default=None, description="Free-form notes")


class InstitutionCreate(InstitutionBase):
    """Payload to create an institution (POST)."""


class InstitutionRead(InstitutionBase):
    """Representation returned by the API (output)."""

    # from_attributes: lets Pydantic read data directly from the
    # SQLAlchemy ORM object (institution.id, institution.name, ...).
    model_config = API_OUT

    id: int
    created_at: str
    snapshot_count: int = Field(
        default=0,
        description=(
            "How much history this institution actually has. One situation is a "
            "state worth naming: nothing to compare against, and every quantity "
            "as old as that single day."
        ),
    )
    latest_snapshot: str | None = None


class SnapshotBase(BaseModel):
    """Fields shared by a snapshot (a dated 'situation' of an institution)."""

    # Pydantic validates that this is a real date (YYYY-MM-DD format).
    date: datetime.date = Field(..., description="Situation date (YYYY-MM-DD)")
    note: str | None = Field(default=None, description="Free-form notes")


class SnapshotCreate(SnapshotBase):
    """Payload to create a snapshot. institution_id comes from the URL.

    No currency: a situation has none of its own. Each holding states the
    currency it is in, and what the situation is worth is theirs converted."""

    date: ObservedDate = Field(..., description="Situation date (YYYY-MM-DD)")


class SnapshotRead(SnapshotBase):
    """Representation of a snapshot, and what it was worth.

    The figure is named for its currency because it used to be named `value`
    and was a raw sum of whatever each holding happened to be denominated in.
    A name that says nothing about its unit is how a total in lira reached a
    screen with a euro sign on it, so the unit is declared beside it."""

    model_config = API_OUT

    id: int
    institution_id: int
    value_base: float = Field(
        ...,
        description=(
            "What this situation was worth, in `base_currency`: its holdings "
            "converted at the ECB rate, by the listing currency where the ticker "
            "has one. Computed by the router, never by the model."
        ),
    )
    base_currency: BaseCurrency
    created_at: str


class PrefilledSnapshotRead(SnapshotRead):
    """A snapshot started from the previous one, plus what the app did to it.

    `needs_attention` is the point of the whole endpoint: it names the rows
    nothing could re-price, which are the only ones actually asking for the
    user. Everything else was carried over and valued at the new date."""

    model_config = API_OUT

    copied_from: str = Field(..., description="Date of the situation it started from")
    repriced: list[str] = Field(
        default_factory=list, description="Tickers valued at the new date"
    )
    needs_attention: list[str] = Field(
        default_factory=list,
        description="Rows carried over unchanged because nothing can price them",
    )


# The words for a stored dividend policy, for everything the model reads. The
# token itself stays "acc" / "dist": pac.py acts on it, and a tool result still
# carries it as stored.
POLICY_WORDS = {"acc": "accumulating", "dist": "distributing"}


class HoldingBase(BaseModel):
    """Fields shared by a holding (a detail line within a snapshot)."""

    asset_name: str = Field(..., min_length=1, description="Instrument/asset name")
    # cash | equity | bond | fund_etf | crypto | real_estate | other
    asset_class: str | None = Field(default=None, description="Asset class")
    symbol: str | None = Field(
        default=None, description="Yahoo ticker used for prices (e.g. VWCE.MI)"
    )
    isin: str | None = Field(
        default=None,
        description="Fund ISIN — what the look-through sources key on",
    )
    quantity: float | None = Field(default=None)
    unit_price: float | None = Field(default=None)
    value: float | None = Field(
        default=None,
        description="Position value. If absent but quantity and unit_price are set, it is computed.",
    )
    cost_basis: float | None = Field(
        default=None,
        description=(
            "What the position cost, in this holding's currency. Null means "
            "unknown — and unknown stays unknown rather than being inferred "
            "from `value`, which is a valuation, not a price paid."
        ),
    )
    cost_estimated: bool | None = Field(
        default=None,
        description="True when the cost was derived (e.g. from a reported % return)",
    )
    currency: str = Field(..., description="Currency, e.g. EUR")
    distribution_policy: str | None = Field(
        default=None,
        description=(
            "acc | dist (accumulating vs distributing). Left empty, the ticker's "
            "own dividend history decides: whatever it pays is recorded, as for "
            "a share, which has no policy to choose"
        ),
    )


class HoldingCreate(HoldingBase):
    """Payload to create a holding. snapshot_id comes from the URL."""

    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class HoldingRead(HoldingBase):
    """Representation of a holding returned by the API.

    Two figures for one row, and they are different facts. `value` is what the
    reader TYPED, in `currency`, and it is what the edit form must put back in
    the box. `value_base` is what that is worth in the app's base currency, and
    it is the only one of the two that may be added to another row."""

    model_config = API_OUT

    id: int
    snapshot_id: int
    value_base: float = Field(
        ...,
        description=(
            "`value` in `base_currency`, at the ECB rate — by the ticker's "
            "listing currency where it has one, by `currency` otherwise. The "
            "figure to display and to total; `value` is the one to edit."
        ),
    )
    base_currency: BaseCurrency
    last_dividend: str | None = Field(
        default=None,
        description=(
            "The latest ex-date Yahoo lists for this holding's ticker, from the "
            "dividend answers the catch-up keeps; null when it was never asked "
            "about or lists none. What the line says when no policy is stated "
            "and the ticker's own history decides its dividends."
        ),
    )


class RealAssetBase(BaseModel):
    """Fields shared by a real asset (real/physical wealth)."""

    name: str = Field(
        ..., min_length=1, description="Asset name (e.g. 'Milan flat', 'Tesla Model 3')"
    )
    # real_estate | vehicle | collectible | jewelry | art | other
    category: str | None = Field(default=None, description="Asset category")
    currency: str = Field(..., description="Currency, e.g. EUR")
    acquisition_date: datetime.date | None = Field(
        default=None, description="Acquisition date (YYYY-MM-DD)"
    )
    acquisition_value: float | None = Field(
        default=None, description="Value at acquisition time"
    )
    notes: str | None = Field(default=None, description="Free-form notes")


class RealAssetCreate(RealAssetBase):
    """Payload to create a real asset."""

    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class RealAssetRead(RealAssetBase):
    """Representation of a real asset returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str


class RealAssetValuationBase(BaseModel):
    """Fields shared by a real-asset valuation (the dated value of a real asset)."""

    date: datetime.date = Field(..., description="Valuation date (YYYY-MM-DD)")
    value: float = Field(..., description="Asset value at that date")
    note: str | None = Field(default=None, description="Free-form notes")


class RealAssetValuationCreate(RealAssetValuationBase):
    """Payload to create a valuation. real_asset_id comes from the URL."""

    date: ObservedDate = Field(..., description="Valuation date (YYYY-MM-DD)")


class RealAssetValuationRead(RealAssetValuationBase):
    """Representation of a valuation returned by the API."""

    model_config = API_OUT

    id: int
    real_asset_id: int
    created_at: str


# --- Liabilities (debts) ----------------------------------------------------


class LiabilityBase(BaseModel):
    """Fields shared by a liability (a debt with dated outstanding balances)."""

    name: str = Field(..., min_length=1, description="Debt name (e.g. 'Home mortgage')")
    # mortgage | personal_loan | auto_loan | student_loan | credit_card | other
    kind: str | None = Field(default=None, description="Debt kind")
    currency: str = Field(..., description="Currency, e.g. EUR")
    interest_rate: float | None = Field(
        default=None, ge=0, description="Annual interest rate in % (e.g. 3.2)"
    )
    real_asset_id: int | None = Field(
        default=None, description="Real asset this debt finances (mortgage -> house)"
    )
    notes: str | None = Field(default=None, description="Free-form notes")


class LiabilityCreate(LiabilityBase):
    """Payload to create a liability."""

    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class LiabilityRead(LiabilityBase):
    """A stored liability. `latest_balance` = most recent outstanding balance."""

    model_config = API_OUT

    id: int
    latest_balance: float | None
    created_at: str


class LiabilityBalanceBase(BaseModel):
    """A dated outstanding balance of a liability."""

    date: datetime.date = Field(..., description="Balance date (YYYY-MM-DD)")
    balance: float = Field(..., ge=0, description="Outstanding principal at that date")
    note: str | None = Field(default=None, description="Free-form notes")


class LiabilityBalanceCreate(LiabilityBalanceBase):
    """Payload to create a balance. liability_id comes from the URL."""

    date: ObservedDate = Field(..., description="Balance date (YYYY-MM-DD)")


class LiabilityBalanceRead(LiabilityBalanceBase):
    """A stored balance as returned by the API."""

    model_config = API_OUT

    id: int
    liability_id: int
    created_at: str


# --- Dashboard (aggregations) ---------------------------------------------


class OmittedPosition(BaseModel):
    """Value a situation did not account for, with nothing on record saying
    where it went — a position it stopped naming, or units it stopped
    claiming."""

    model_config = API_OUT

    asset_name: str
    symbol: str | None = None
    institution_id: int | None = None
    institution: str | None = None
    last_seen: str
    dropped_on: str
    last_value: float
    units_missing: float | None = Field(
        default=None,
        description=(
            "Units the situation stopped claiming while still naming the row. "
            "Null when the whole position went unnamed, which is the "
            "difference between 'this is gone' and 'there is less of this "
            "than you had'."
        ),
    )


class ArrivedPosition(BaseModel):
    """A row a situation declared that the app was not expecting.

    Only reported for a situation that ALSO failed to account for something,
    because value arriving breaks no rule on its own — a reader may declare
    whatever they hold. Beside what went missing it is usually the same money
    described better, and the two numbers together are what tell a
    reformulation from a loss."""

    model_config = API_OUT

    asset_name: str
    symbol: str | None = None
    institution_id: int | None = None
    institution: str | None = None
    appeared_on: str
    value: float


class UnconvertedAmount(BaseModel):
    """Value that reached a total in the currency it was written in, because the
    app has no rate to convert it with.

    The fallback itself is deliberate: an amount the feed has never priced is
    kept rather than dropped, since a total quietly short by a whole account is
    as wrong as one quietly inflated (`fx.Converter.to_base_or_as_stored`). What
    was missing is this — the saying so. Two cases reach it and the reader tells
    them apart at a glance, which is why the code is printed as typed: a code
    that is a typo (`Doll`) is corrected on the row, and a real currency the ECB
    does not quote (`TWD`) cannot be converted by anybody and the figure simply
    is in another unit."""

    model_config = API_OUT

    currency: str | None = Field(
        ..., description="The code as the row states it, or null for a row with none"
    )
    amount: float = Field(
        ...,
        description=(
            "What those amounts come to in THEIR OWN unit, as they were "
            "written. A sum over rows, and not the amount any figure above is "
            "wrong by — nor a bound on it, in either direction. One converter "
            "serves several totals, so the same currency can arrive as a value "
            "and again as its cost, and a debt's balance adds here while it "
            "subtracts there; and a recurring flow is converted ONCE and "
            "multiplied afterwards. Measured: a holding worth 1,000 TWD that "
            "cost 900 reports 1,900.00 against an investments total of "
            "1,000.00; an asset and a debt of 1,000 TWD each add 2,000.00 here "
            "while the net worth does not move; and 100 TWD a month against a "
            "year-old anchor puts 1,200.00 into the net worth and reports "
            "100.00."
        ),
    )
    count: int = Field(..., description="How many amounts were passed through")


class DashboardSummary(BaseModel):
    """Net worth = financial + real − liabilities, plus the splits and counts.

    financial_total = investments_total (snapshots, ex-cash) + cash_total
    (the live cash register projected to today). liabilities_total = sum of
    the latest outstanding balance of each debt."""

    model_config = API_OUT

    net_worth: float
    financial_total: float
    investments_total: float
    # Same discipline as the look-through's coverage: never present one figure
    # as if all of it were equally solid.
    investments_at_market: float = Field(
        default=0.0,
        description="How much of the investment total the market actually priced",
    )
    investments_at_book: float = Field(
        default=0.0,
        description="How much of it is carried over from the last photograph instead",
    )
    unresolved_omissions: list[OmittedPosition] = Field(
        default_factory=list,
        description=(
            "Value that left the totals because a newer photograph did not "
            "mention it. Selling is an assertion with a date and proceeds; "
            "forgetting is the absence of one, and the app must not let the "
            "difference pass in silence."
        ),
    )
    declared_instead: list[ArrivedPosition] = Field(
        default_factory=list,
        description=(
            "What those same situations declared that the app was not "
            "expecting. Three summary rows replaced by twenty-one positions "
            "is a portfolio described better, not their value lost, and "
            "naming only the first half cannot tell the reader which it is."
        ),
    )
    unconverted: list[UnconvertedAmount] = Field(
        default_factory=list,
        description=(
            "Amounts that entered these totals without being converted, because "
            "no rate is known for the currency they are written in — said here "
            "instead of passing in silence. Each entry is a sum over ROWS and "
            "not the amount any figure above is wrong by; `UnconvertedAmount` "
            "says why, with the measured cases in both directions."
        ),
    )
    cash_total: float
    real_total: float
    liabilities_total: float
    base_currency: BaseCurrency
    institutions: int
    real_assets: int
    liabilities: int
    as_of: datetime.date | None


class AssetClassSlice(BaseModel):
    """One slice of the financial allocation (by asset class)."""

    model_config = API_OUT

    asset_class: str
    value: float


class RealCategorySlice(BaseModel):
    """One slice of the real allocation (by asset category)."""

    model_config = API_OUT

    category: str
    value: float


class DashboardAllocation(BaseModel):
    """Top-level financial-vs-real split, with per-class / per-category detail."""

    model_config = API_OUT

    financial_total: float
    real_total: float
    by_asset_class: list[AssetClassSlice]
    by_real_category: list[RealCategorySlice]
    base_currency: BaseCurrency


class NetWorthPoint(BaseModel):
    """One point of the net-worth-over-time series (net = fin + real − debts)."""

    model_config = API_OUT

    date: datetime.date
    net_worth: float
    financial: float
    real: float
    liabilities: float
    base_currency: BaseCurrency
    fx_as_of: str | None = Field(
        ...,
        description=(
            "The ECB day whose rates converted this point — the latest published "
            "on or before `date`. Null when nothing in the point needed converting."
        ),
    )


class TaxEstimate(BaseModel):
    """A declared tax estimate, never a tax calculation — see app/tax.py for
    what is deliberately not being built here.

    It rides on the portfolio payload because the two figures it is derived
    from are computed there, and a number that travels apart from its base
    drifts from it. It is in NO total on that payload: not the book value, not
    the market value, not the net worth. Beside them, labelled, carrying the
    rate it used — which is what separates an aid to deciding from something
    impersonating a return.

    Every field may be null, and null means the reader has not said, which this
    app treats as a different claim from zero."""

    model_config = API_OUT

    country: str | None = Field(
        ...,
        description=(
            "What the reader called their tax country. A LABEL on the estimate "
            "and the seed for the pre-filled rates — nothing downstream branches "
            "on it, so a country with no shipped default is not a lesser case."
        ),
    )
    regime: str | None = Field(
        ...,
        description=(
            "The named regime behind a shipped default (e.g. 'Abgeltungsteuer "
            "25% + 5.5% Solidaritätszuschlag'), so the reader can check the "
            "number against something. Null for a country this app ships no "
            "default for, including when the rates are set by hand."
        ),
    )
    capital_gains_rate: float | None = Field(
        ..., description="PERCENT, not a fraction. Null when the reader has not set it."
    )
    dividend_withholding_rate: float | None = Field(
        ..., description="PERCENT, not a fraction. Null when the reader has not set it."
    )
    configured: bool = Field(
        ...,
        description=(
            "Whether either rate is set at all. False is the state where the "
            "screen must say nobody has answered rather than show a zero — the "
            "bases below are still real and still worth reading."
        ),
    )
    realized_gain: float = Field(
        ...,
        description=(
            "The ledger's realized result as-is, which may be NEGATIVE. Kept "
            "signed and separate from `taxable_gain` so a loss is visible as a "
            "loss instead of disappearing into a zero tax."
        ),
    )
    taxable_gain: float = Field(
        ...,
        description=(
            "max(realized_gain, 0) — the base the rate is applied to. A loss "
            "produces no negative tax here: it is not a refund, it is a "
            "carry-forward in most regimes, and this tracks neither."
        ),
    )
    capital_gains_tax: float | None = Field(
        ..., description="taxable_gain x the rate. Null when no rate is set."
    )
    dividends_gross_estimated: float = Field(
        ...,
        description=(
            "The dividend base: ONLY the rows still marked estimated, which are "
            "the only ones still carrying a gross figure."
        ),
    )
    dividends_recorded_net: float = Field(
        ...,
        description=(
            "The dividends the reader corrected by hand, which are already net "
            "of whatever their broker withheld. Named rather than omitted, "
            "because 'no rate was applied here' is a fact about the estimate."
        ),
    )
    dividend_withholding: float | None = Field(
        ...,
        description="dividends_gross_estimated x the rate. Null when no rate is set.",
    )
    total: float | None = Field(
        ...,
        description=(
            "The two halves summed, and NULL whenever a base with something in "
            "it has no rate to apply. A total that quietly omitted half of "
            "itself would read as 'my tax' while being an understatement."
        ),
    )
    missing_rates: list[str] = Field(
        default_factory=list,
        description="Which rates a non-empty base is waiting on, so the screen can ask for exactly those.",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description=(
            "Why this figure is approximate, in words, generated beside the "
            "number. The page, the advisor and any outside assistant read the "
            "same list — a caveat kept only in the UI is one the chat would "
            "confidently omit."
        ),
    )


class TaxSettings(BaseModel):
    """The three settings the reader controls, as they are written and read.

    Rates are PERCENT (26 means 26%), matching `Liability.interest_rate`, the
    one rate this app already stored. Null clears the key."""

    country: str | None = Field(
        default=None, max_length=80, description="Free text: any country, listed or not"
    )
    capital_gains_rate: float | None = Field(default=None, ge=0, le=100)
    dividend_withholding_rate: float | None = Field(default=None, ge=0, le=100)


class TaxCountryDefault(BaseModel):
    """One row of the shipped default table, offered to the reader as a
    starting point and never applied behind their back."""

    model_config = API_OUT

    country: str
    capital_gains_rate: float
    dividend_withholding_rate: float
    regime: str = Field(..., description="The named regime the rate comes from")
    omits: str = Field(
        ...,
        description=(
            "The carve-outs this flat rate knowingly flattens. Shipped WITH the "
            "number because it is what makes a three-country table honest "
            "rather than merely short."
        ),
    )


class BaseCurrencySetting(BaseModel):
    """The currency every total is shown in."""

    base_currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="An ISO code the ECB reference-rate feed quotes, e.g. EUR, USD",
    )


class BaseCurrencySettingRead(BaseCurrencySetting):
    """The base, and the currencies it may be changed to."""

    model_config = API_OUT

    available: list[str] = Field(
        ...,
        description=(
            "The currencies the ECB feed quotes today, which are the only ones a "
            "total can be converted into. Just the current base when the feed "
            "has never been reached."
        ),
    )


class TaxSettingsRead(TaxSettings):
    """What the reader set, plus the defaults they could choose from.

    The known list travels with the current values so the screen has one round
    trip and one source of truth for the rates — a table duplicated into the
    frontend is a table that goes stale on one side."""

    model_config = API_OUT

    known_countries: list[TaxCountryDefault]


class PortfolioRow(BaseModel):
    """One investment position in the portfolio view, with its TWO readings
    kept apart: `book_value` is what the position cost, `observed_value` is
    what it is worth. They differ whenever a purchase price was recorded, and
    answering a question about worth with the cost is the defect this pair
    exists to end.

    `market_value`/`delta` are filled only for quantity-based, symboled
    positions with a market price (live or cached); `as_of` is the close date
    that price refers to. An unpriced row still has an `observed_value` — the
    figure its last photograph recorded — and that is what it contributes to
    `total_market`."""

    model_config = API_OUT

    institution_id: int | None = Field(
        default=None,
        description=(
            "The id of the institution holding this position, for a caller "
            "that already has one and should not have to match on a name."
        ),
    )
    institution: str | None = Field(
        ...,
        description=(
            "The institution holding this position, or null when it is held at "
            "none. Null is a real answer, not a missing name: a PAC target that "
            "names no institution creates positions like this, and they can "
            "never be photographed by a situation or reconciled against one. It "
            "used to arrive as the string '?', which a bank actually called "
            "that is indistinguishable from."
        ),
    )
    asset_name: str
    symbol: str | None
    asset_class: str | None
    distribution_policy: str | None
    last_dividend: str | None = Field(
        default=None,
        description=(
            "The latest ex-date Yahoo lists for this ticker, from the dividend "
            "answers the catch-up keeps; null when it was never asked about or "
            "lists none. What the row says when no policy is stated and the "
            "ticker's own history decides its dividends."
        ),
    )
    quantity: float | None
    book_value: float = Field(
        ...,
        description=(
            "What this position COST, in the base currency: the recorded purchase price on "
            "a quantity-based holding where there is one, otherwise the value "
            "its photograph was taken at (and then cost_known is False, which "
            "is how a reader tells the two apart). A value-only lump keeps its "
            "photograph's figure here even when a cost was recorded against "
            "it — the projection has no units to merge a cost into, and the "
            "row says cost_known False rather than claim one. The base the P/L "
            "is measured against; never an answer to 'what is it worth'."
        ),
    )
    observed_value: float = Field(
        ...,
        description=(
            "What this position was last OBSERVED to be worth: the figure its "
            "photograph recorded, carried forward through the ledger. Equal to "
            "book_value whenever the projection has only one figure to work "
            "from: no purchase price was recorded, or no value was (a quantity "
            "typed with no price is not an observation of zero), or the "
            "position was born in the ledger and no photograph ever saw it."
        ),
    )
    avg_cost: float | None = Field(
        ..., description="book_value / quantity (average-cost accounting)"
    )
    cost_known: bool = Field(
        default=False,
        description=(
            "False when the book comes from a snapshot with no recorded "
            "purchase: the 'average cost' is then a photograph's price, not "
            "money you paid, and 'P/L vs recorded' measures movement since you "
            "wrote it down."
        ),
    )
    cost_estimated: bool = Field(
        default=False,
        description=(
            "True when that recorded cost was DERIVED (e.g. from a broker's "
            "reported % return) rather than read off a contract note. A real "
            "number, but not a verified one, and the reader is entitled to know "
            "which."
        ),
    )
    observed_on: str | None = Field(
        default=None,
        description=(
            "The date this position was last CONFIRMED — the photo it sits in, "
            "or its most recent ledger entry. Two different things age: on a "
            "priced row the value is today's and only 'I hold N units' is this "
            "old; on an unpriced one, everything is. Callers must say which, "
            "not just 'stale'."
        ),
    )
    quantity_age_days: int | None = None
    closed_on: str | None = Field(
        default=None,
        description=(
            "Set when a `close` disposed of this position: it is shown so the "
            "exit is visible, rather than the row simply ceasing to exist."
        ),
    )
    currency_note: str | None = Field(
        default=None,
        description="Set when the hand-typed currency disagrees with the listing's own",
    )
    realized_pl: float = Field(
        ..., description="Gains locked in by sells since the snapshot anchor"
    )
    dividends: float = Field(
        ..., description="Dividends collected since the snapshot anchor"
    )
    dividends_estimated: float = Field(
        ...,
        description=(
            "The part of `dividends` still carrying the market's GROSS figure. "
            "An auto-recorded dividend is the declared amount per share, from "
            "which no withholding has been taken; correcting the row with the "
            "broker's real credit replaces it with the net figure and clears "
            "`estimated` in the same gesture. There is no gross/net column, so "
            "this is the only thing separating the rows a withholding estimate "
            "may be applied to from the rows where applying one would tax the "
            "same money twice."
        ),
    )
    live_price: float | None
    currency: str | None = Field(
        ...,
        description=(
            "Listing currency of the live price; null while it is not known, and "
            "then the row has no market value — a price in an unknown currency is "
            "not converted as if it were the base"
        ),
    )
    as_of: str | None = Field(..., description="Market close date the price refers to")
    market_value: float | None = Field(
        ..., description="In the base currency (converted at the ECB reference rate)"
    )
    delta: float | None = Field(
        ...,
        description=(
            "market_value − book_value: what the market says today against "
            "what was paid. NULL when no quote priced the row — a photograph's "
            "own figure is not a price the market made, and putting the "
            "difference here would present a month-old statement as "
            "performance in the column that means 'a live market versus what "
            "you paid' on every other row. The movement is still visible: it "
            "is observed_value − book_value, from two named facts."
        ),
    )
    delta_pct: float | None = Field(
        ..., description="delta / book_value — a return measured against cost"
    )


class Portfolio(BaseModel):
    """The investment portfolio (latest snapshot of each institution).
    `priced` says whether any market prices are shown (freshly fetched or from
    the cache); `prices_as_of` is the OLDEST close date among the priced rows,
    so the user knows how stale the view can be. `total_realized` /
    `total_dividends` sum the gains locked in by sells and the dividends
    collected since each position's snapshot anchor."""

    model_config = API_OUT

    rows: list[PortfolioRow]
    total_book: float = Field(..., description="Sum of what the positions COST")
    total_market: float | None = Field(
        ...,
        description=(
            "Sum of what they are WORTH: the market price where there is one, "
            "the last observed value where there is not. Null when nothing at "
            "all is priced. It is deliberately not the sum of the delta "
            "column: the rows the market could not price contribute their "
            "observation here, and no P/L."
        ),
    )
    priced: bool
    prices_as_of: str | None
    base_currency: BaseCurrency
    total_realized: float
    total_dividends: float
    total_dividends_estimated: float = Field(
        ...,
        description=(
            "How much of `total_dividends` is still the market's gross figure "
            "(see PortfolioRow.dividends_estimated). The remainder is what the "
            "reader corrected by hand and is already net."
        ),
    )
    tax_estimate: TaxEstimate
    unresolved_omissions: list[OmittedPosition] = Field(
        default_factory=list,
        description=(
            "Positions a newer photograph stopped mentioning: their value left "
            "these totals without a line saying where it went."
        ),
    )
    declared_instead: list[ArrivedPosition] = Field(
        default_factory=list,
        description=(
            "What those same situations declared that the app was not "
            "expecting. Three summary rows replaced by twenty-one positions "
            "is a portfolio described better, not their value lost, and "
            "naming only the first half cannot tell the reader which it is."
        ),
    )
    unconverted: list[UnconvertedAmount] = Field(
        default_factory=list,
        description=(
            "Amounts that entered these totals without being converted, because "
            "no rate is known for the currency they are written in. The pair to "
            "`fx_as_of`: that says which rate was applied, this says what no "
            "rate could be applied to."
        ),
    )
    fx_as_of: str | None = Field(
        ...,
        description="ECB reference-rate date, present when any FX conversion was applied",
    )



# --- Instrument registry (the picker) ---------------------------------------


class CatalogueStatus(BaseModel):
    """What the local registry holds and how old it is. Shown, not assumed: a
    picker searching a catalogue downloaded months ago is a different tool from
    one searching today's.

    `state` is where the app's own download stands: "downloading"; "failed",
    tried again at a page load from `retry_after` on; "ready"; or
    "not_started", an empty registry nobody has asked about since the server
    started (a reload asks)."""

    model_config = API_OUT

    rows: int = 0
    fetched_at: str | None = None
    source: str | None = None
    state: Literal["ready", "downloading", "failed", "not_started"] = "ready"
    retry_after: str | None = None


class InstrumentMember(BaseModel):
    """One instrument in the registry.

    `base_ticker` is NOT a Yahoo symbol and `share_class_currency` is NOT the
    currency a holding trades in: the catalogue says EUNL and USD for iShares
    Core MSCI World, which Xetra trades in EUR. They are shown to help tell
    two similar rows apart, never to fill those fields."""

    model_config = API_OUT

    isin: str
    name: str
    base_ticker: str | None = None
    distribution_policy: str | None = Field(default=None, description="acc | dist")
    ter: float | None = None
    size_meur: int | None = None
    replication: str | None = None
    domicile: str | None = None
    share_class_currency: str | None = None
    holdings_count: int | None = None
    hedged: bool | None = None


class InstrumentFamily(BaseModel):
    """The same fund in its accumulating and distributing forms, together."""

    model_config = API_OUT

    key: str
    members: list[InstrumentMember] = Field(default_factory=list)


class InstrumentSearch(CatalogueStatus):
    """`coverage` says how the match was made: 'all' means every word was
    found, 'partial' means the search had to loosen to find anything — a
    weaker claim about what was asked for, and the caller is expected to say
    so rather than present both the same way."""

    model_config = API_OUT

    families: list[InstrumentFamily] = Field(default_factory=list)
    coverage: str = "none"



class QuotableInstrument(BaseModel):
    """A candidate from the live lookup — a share, ETF, coin or futures
    contract, i.e. everything the fund catalogue does not hold.

    `price` NEVER travels without `exchange`, and for a measured reason: the
    lookup does not return a currency, so the same company on two exchanges
    comes back as two bare numbers in different money — one in dollars on NMS
    and one in euros on FRA, apart by the exchange rate and the same value. The
    currency arrives from a real quote once something is chosen."""

    model_config = API_OUT

    symbol: str
    name: str | None = None
    quote_type: str | None = Field(
        default=None, description="equity | etf | cryptocurrency | future | index"
    )
    exchange: str | None = None
    price: float | None = None


class SymbolLookup(BaseModel):
    """The live lane. Empty when nothing matched OR the source was unreachable —
    `reachable` tells the caller which, so an outage is never presented as
    'this instrument does not exist'."""

    model_config = API_OUT

    results: list[QuotableInstrument] = Field(default_factory=list)
    reachable: bool = True


# --- The watchlist: ideas, not holdings -----------------------------------


class WatchlistItemBase(BaseModel):
    """An instrument the reader is considering, and what the idea rested on.

    Nothing here is owned, so nothing here reaches a total. What makes it worth
    a table is the three text fields: a suggestion has to say WHY it suggests
    this, on the basis of WHAT the reader declared, and WHAT IT DOES NOT KNOW.
    They are three fields rather than one because the third is the one a single
    free-text box loses — it is the uncomfortable half, and it is the half that
    is worth having in a month.

    On a fund's line `isin` identifies and `symbol` prices, and they are not
    interchangeable here any more than anywhere else in this app: the ISIN
    comes from the local catalogue and can be checked against it, while the
    symbol comes from the live lookup and nothing offline can confirm it.

    A share's line has no ISIN, because nothing this app can ask gives a
    share's, and its symbol is the identity: the exact one Yahoo listed as a
    share when the card was drawn and when it was accepted (brief AG). A line
    with neither identifies nothing, and is refused."""

    isin: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "A fund's ISIN, from the catalogue: its identity. Null on a share's "
            "line, which the symbol identifies"
        ),
    )
    symbol: str | None = Field(
        default=None,
        description=(
            "On a fund's line, a quotable symbol from the live lookup if one "
            "was found, never the catalogue's `base_ticker`, which is not a "
            "Yahoo symbol. On a share's line, the identity: the symbol Yahoo "
            "lists it under."
        ),
    )
    name: str = Field(
        ...,
        min_length=1,
        description="The instrument's name, as the catalogue or Yahoo writes it",
    )
    reason: str = Field(..., min_length=1, description="Why this was suggested")
    based_on: str = Field(
        ..., min_length=1, description="What the reader declared that this rests on"
    )
    unknowns: str = Field(
        ..., min_length=1, description="What the suggestion does NOT know about them"
    )

    @model_validator(mode="after")
    def _names_something(self):
        if not self.isin and not (self.symbol or "").strip():
            raise ValueError(
                "A watchlist line names a fund by its ISIN or a share by its symbol, "
                "and this one names neither."
            )
        return self


class WatchlistItemCreate(WatchlistItemBase):
    """Payload to park one idea on the watchlist."""


class WatchlistItemRead(WatchlistItemBase):
    """A stored watchlist line as the API returns it."""

    model_config = API_OUT

    id: int
    added_at: str


# --- Cash flow: income sources & expenses ---------------------------------


class CashFlowItemBase(BaseModel):
    """The fields an income source and an expense have in common.

    Everything about a recurring amount except the one field that says what
    KIND of thing it is — and that field is exactly why these stay two
    resources: `kind` (active | passive) asks whether the money keeps arriving
    if you stop working, `nature` (essential | discretionary) asks whether you
    could stop paying. Two questions, two vocabularies, opposite signs in the
    cash register."""

    name: str = Field(..., min_length=1, description="Name")
    category: str | None = Field(default=None, description="Category")
    amount: float = Field(..., ge=0, description="Amount per occurrence")
    currency: str = Field(..., description="Currency, e.g. EUR")
    frequency: str | None = Field(
        default=None, description="monthly | quarterly | semiannual | annual | one_off"
    )
    institution_id: int | None = Field(
        default=None, description="Institution whose cash this belongs to"
    )
    start_date: datetime.date | None = Field(
        default=None, description="First occurrence / one-off date (YYYY-MM-DD)"
    )
    end_date: datetime.date | None = Field(
        default=None, description="Last occurrence (optional; open-ended if null)"
    )
    notes: str | None = Field(default=None, description="Free-form notes")


class IncomeSourceBase(CashFlowItemBase):
    """Fields shared by an income source (input/output)."""

    name: str = Field(
        ..., min_length=1, description="Income source name (e.g. 'Salary', 'Apartment rent')"
    )
    kind: str | None = Field(default=None, description="active | passive")
    category: str | None = Field(
        default=None,
        description="salary | freelance | business | rental | dividends | interest | pension | other",
    )
    institution_id: int | None = Field(
        default=None, description="Institution whose cash this income feeds"
    )


class IncomeSourceCreate(IncomeSourceBase):
    """Payload to create an income source."""

    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class IncomeSourceRead(IncomeSourceBase):
    """Representation of an income source returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str


class ExpenseBase(CashFlowItemBase):
    """Fields shared by an expense (input/output)."""

    name: str = Field(
        ..., min_length=1, description="Expense name (e.g. 'Rent', 'Groceries')"
    )
    nature: str | None = Field(default=None, description="essential | discretionary")
    category: str | None = Field(
        default=None,
        description="housing | food | transport | utilities | health | insurance | debt | leisure | education | other",
    )
    institution_id: int | None = Field(
        default=None, description="Institution whose cash this expense draws from"
    )


class ExpenseCreate(ExpenseBase):
    """Payload to create an expense."""

    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class ExpenseRead(ExpenseBase):
    """Representation of an expense returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str


class FlowNotCounted(BaseModel):
    """An income or an expense the monthly figures leave out, with the dates
    that say why: its first payment is after today, or it has ended. The Cash
    flow page marks its own row by `side` and `id`."""

    model_config = API_OUT

    side: Literal["income", "expense"]
    id: int
    name: str
    frequency: str | None
    start_date: datetime.date | None
    end_date: datetime.date | None


class CashFlowSummary(BaseModel):
    """The income and expenses IN FORCE today as a monthly run-rate, one-offs
    excluded, and the flows those figures leave out
    (`analytics.compute_flows_in_force`, the analysis's own computation)."""

    model_config = API_OUT

    on: datetime.date = Field(..., description="The day the flows are in force on: today")
    incomes_in_force: int = Field(..., description="So 'none in force' can be told from a sum of zero")
    expenses_in_force: int
    monthly_income: float
    monthly_expenses: float
    monthly_net: float
    savings_rate: float | None  # fraction 0..1, or None if there is no income
    active_income: float
    passive_income: float
    essential_expenses: float
    discretionary_expenses: float
    undated: int = Field(
        ..., description="Flows with no start date, counted as in force: nothing says they have not started"
    )
    scheduled: list[FlowNotCounted] = Field(
        ..., description="First payment after today: not counted until then"
    )
    ended: list[FlowNotCounted] = Field(..., description="Ended before today: no longer counted")
    base_currency: BaseCurrency


# --- Cash register: anchors, transfers, projected positions ---------------


class CashAnchorBase(BaseModel):
    """A manually-entered actual cash balance for an institution at a date."""

    date: datetime.date = Field(..., description="Balance date (YYYY-MM-DD)")
    amount: float = Field(..., ge=0, description="Actual cash at that date")
    currency: str = Field(..., description="Currency, e.g. EUR")
    note: str | None = Field(default=None, description="Free-form notes")


class CashAnchorCreate(CashAnchorBase):
    """Payload to create an anchor. institution_id comes from the URL."""

    date: ObservedDate = Field(..., description="Balance date (YYYY-MM-DD)")
    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class CashAnchorRead(CashAnchorBase):
    """A stored anchor as returned by the API."""

    model_config = API_OUT

    id: int
    institution_id: int
    created_at: str


class TransferBase(BaseModel):
    """A cash movement from one institution to another on a date."""

    date: datetime.date = Field(..., description="Transfer date (YYYY-MM-DD)")
    from_institution_id: int | None = Field(
        default=None, description="Source institution id"
    )
    to_institution_id: int | None = Field(
        default=None, description="Target institution id"
    )
    amount: float = Field(..., gt=0, description="Amount that left the source, in `currency`")
    currency: str = Field(..., description="Currency of the source side, e.g. EUR")
    to_amount: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Amount that reached the destination, in `to_currency`, from its "
            "statement. Left out, it is `amount` when the two currencies are the "
            "same, and otherwise worked out at the ECB rate final for `date`."
        ),
    )
    to_currency: str = Field(..., description="Currency of the destination side, e.g. EUR")
    note: str | None = Field(default=None, description="Free-form notes")


class TransferCreate(TransferBase):
    """Payload to create a transfer."""

    currency: StatedCurrency = Field(..., description="Currency of the source side, e.g. EUR")
    to_currency: StatedCurrency = Field(
        ..., description="Currency of the destination side, e.g. EUR"
    )


class TransferRead(TransferBase):
    """A stored transfer as returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str
    to_amount: float
    fx_as_of: str | None = Field(
        default=None,
        description=(
            "The ECB day whose rate `to_amount` was worked out at; null when it "
            "was stated, or when both sides share a currency"
        ),
    )


class CashPosition(BaseModel):
    """Projected cash for one institution at `as_of`, with its breakdown:
    projected = anchor_amount + income − expenses + transfers_in − transfers_out
    − buys (events counted only AFTER the anchor date, up to as_of)."""

    model_config = API_OUT

    institution_id: int
    institution_name: str
    as_of: datetime.date
    anchor_date: datetime.date | None
    anchor_amount: float
    income: float
    expenses: float
    transfers_in: float
    transfers_out: float
    buys: float = Field(
        ..., description="Investment purchases paid by this institution's cash"
    )
    sells: float = Field(
        ..., description="Sale proceeds and dividends credited to this institution"
    )
    projected: float
    base_currency: BaseCurrency


# --- Market prices --------------------------------------------------------


class PriceQuote(BaseModel):
    """A market price for a symbol (the latest available close).

    `name` is what the ticker actually resolved to. It is the check that
    catches a ticker pointing at the wrong fund — a plausible price never
    does, because the wrong fund has one too."""

    model_config = API_OUT

    symbol: str
    name: str | None = None
    price: float
    currency: str | None = None
    as_of: datetime.date


class IsinSuggestion(BaseModel):
    """A best-effort ISIN -> ticker suggestion from OpenFIGI."""

    model_config = API_OUT

    ticker: str | None = None
    name: str | None = None
    exchange: str | None = None
    type: str | None = None


class SurveyAnswer(BaseModel):
    """One questionnaire answer (financial-literacy intro or qualitative profile)."""

    question_key: str = Field(..., min_length=1)
    topic: str | None = None
    question: str | None = None
    answer: str | None = None


class SurveyAnswerRead(SurveyAnswer):
    """A stored survey answer as returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str


class SurveyQuestionCondition(BaseModel):
    """Show a question only while another question's answer is `equals`."""

    model_config = API_OUT

    key: str
    equals: str


class SurveyQuestionNote(BaseModel):
    """A few words shown under a question while its answer is `equals`."""

    model_config = API_OUT

    equals: str
    text: str


class SurveyQuestion(BaseModel):
    """One question of the Profile form: what it asks, and the kind of answer
    it takes. The form draws itself from these (`app/questionnaire.py`), and
    the chat's `update_profile` is checked against them.

    `type` is how it is answered: "boolean" by yes or no ("unsure" too when
    `unsure`), "single" by one of `options`, "number" by digits, "text" and
    "longtext" by any words."""

    model_config = API_OUT

    key: str
    topic: str
    text: str
    type: Literal["boolean", "single", "text", "longtext", "number"]
    options: list[str] = Field(default_factory=list)
    unsure: bool = False
    show_if: SurveyQuestionCondition | None = None
    explain_when: SurveyQuestionNote | None = None


class GoalBase(BaseModel):
    """A financial goal. The target_* fields are used only for type 'target_amount'."""

    name: str = Field(..., min_length=1)
    # protect_inflation | stable_income | long_term_growth | emergency_fund | target_amount
    type: str | None = None
    currency: str = Field(..., description="Currency, e.g. EUR")
    target_amount: float | None = Field(default=None, ge=0)
    target_date: datetime.date | None = None
    current_amount: float | None = Field(default=None, ge=0)
    monthly_contribution: float | None = Field(default=None, ge=0)
    notes: str | None = None


class GoalCreate(GoalBase):
    """Payload to create a goal."""

    currency: StatedCurrency = Field(..., description="Currency, e.g. EUR")


class GoalRead(GoalBase):
    """A stored goal as returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str


class RequiredReturnRequest(BaseModel):
    """Inputs to compute the annual return needed to reach a target."""

    current_amount: float = Field(0, ge=0)
    monthly_contribution: float = Field(0, ge=0)
    target_amount: float = Field(..., gt=0)
    target_date: datetime.date


class RequiredReturnResult(BaseModel):
    """The computed required return (fraction; None if unreachable) + a note."""

    model_config = API_OUT

    years: float
    required_annual_return: float | None
    assessment: str


# --- Accumulation plans (PAC) ---------------------------------------------


class PlanTargetBase(BaseModel):
    """One instrument a plan buys, and its share of the budget."""

    symbol: str = Field(..., min_length=1, description="Ticker of the bought instrument")
    isin: str | None = Field(
        default=None, description="ISIN of the bought fund, for the look-through"
    )
    asset_name: str | None = Field(
        default=None, description="Name of the bought instrument (e.g. 'iShares World')"
    )
    institution_id: int | None = Field(
        default=None, description="Institution holding the bought investment"
    )
    weight: float = Field(
        default=1.0,
        gt=0,
        description="Share of the budget. Relative, not absolute: 1/1/1 and 40/30/30 both work.",
    )


class PlanTargetCreate(PlanTargetBase):
    """Payload for one plan target (plan_id comes from the parent)."""


class PlanTargetRead(PlanTargetBase):
    """A stored plan target as returned by the API."""

    model_config = API_OUT

    id: int
    position: int


class AccumulationPlanBase(BaseModel):
    """A recurring savings plan: amount of cash moved from a source institution
    to buy one or more target investments, at a frequency."""

    name: str = Field(..., min_length=1, description="Plan name (e.g. 'PAC All-World')")
    amount: float = Field(..., gt=0, description="Amount contributed per occurrence")
    currency: str = Field(
        ...,
        description="Currency the contribution is paid in: the source account's cash, e.g. EUR",
    )
    frequency: str | None = Field(
        default=None, description="monthly | quarterly | semiannual | annual"
    )
    execution: str | None = Field(
        default=None,
        description=(
            "How the broker fills the order: whole_units (floor(amount/price), "
            "remainder stays in cash — default) | fractional (exactly `amount`)"
        ),
    )
    start_date: datetime.date | None = Field(default=None, description="First contribution")
    end_date: datetime.date | None = Field(default=None, description="Last contribution (optional)")
    source_institution_id: int | None = Field(
        default=None, description="Institution whose cash funds the plan"
    )
    notes: str | None = Field(default=None, description="Free-form notes")


class AccumulationPlanCreate(AccumulationPlanBase):
    """Payload to create an accumulation plan."""

    currency: StatedCurrency = Field(
        ...,
        description="Currency the contribution is paid in: the source account's cash, e.g. EUR",
    )
    targets: list[PlanTargetCreate] = Field(
        default_factory=list, description="Instruments this plan buys, with their weights"
    )


class PlanTargetWrite(PlanTargetCreate):
    """One target of a plan a PERSON is writing. See `AccumulationPlanWrite`:
    `institution_id` is required here and required nowhere else."""

    institution_id: int = Field(
        ...,
        description=(
            "Where the bought position will be held. Required: a target that "
            "names no institution creates a position no situation can ever "
            "photograph and no close can settle."
        ),
    )


class AccumulationPlanWrite(AccumulationPlanCreate):
    """What a PERSON may post to `/api/accumulation-plans` — which is not the
    same thing as what the tables are able to store.

    Both ends of the sentence are required here, and both are optional
    everywhere else. Money moves FROM an account INTO a holding, and a plan
    that names neither end describes a purchase nobody made:

    - No SOURCE and no target institution is the defect `TransactionWrite`
      already closed on the ledger, reached through a second door. `pac.py`
      writes `cash_institution_id=plan.source_institution_id`, so with no
      source both institution columns of every buy it creates are null — and
      the cash register keeps only the entries belonging to the institution it
      is computing, where null equals no id there is. The cash side is skipped
      everywhere, the position side counts in full, and the plan's spending
      adds itself to the net worth. Measured on a scratch database: 1000.00 of
      cash, two elapsed occurrences of 100.00 each, net worth 1000.00 ->
      1200.00 with the cash untouched at 1000.00.

    - No TARGET institution alone does not move a total: the source names the
      cash side and the arithmetic stays right to the cent. It creates a
      position held at no institution, which no situation can photograph, no
      snapshot can reconcile, and — since a `close` is matched to its position
      by institution — no disposal can settle. `ca4858d` called requiring this
      a separate decision; this is that decision.

    The columns stay nullable and `AccumulationPlanCreate` stays loose on
    purpose. `crud` is the internal door, nothing migrates, and a plan already
    saved without either end stays readable through the GET rather than
    becoming a row the app refuses to show. What it cannot do is run: see
    `pac.execute_due`, which skips a source-less plan with the reason instead
    of spending money it cannot take from anywhere."""

    source_institution_id: int = Field(
        ...,
        description=(
            "The account whose cash funds the plan. Required: a plan that does "
            "not say where the money comes from cannot take it from anywhere, "
            "and every buy it writes spends money no account loses."
        ),
    )
    targets: list[PlanTargetWrite] = Field(
        default_factory=list,
        description="Instruments this plan buys, with their weights",
    )


class AccumulationPlanRead(AccumulationPlanBase):
    """A stored accumulation plan as returned by the API."""

    model_config = API_OUT

    id: int
    created_at: str
    targets: list[PlanTargetRead] = Field(default_factory=list)
    carried_remainder: float = Field(
        default=0.0,
        description=(
            "What the last whole-unit contribution could not place, waiting for "
            "the next one. Shown because money set aside and not yet invested is "
            "a fact the saver is entitled to see, not an implementation detail."
        ),
    )


# --- Transactions (the investment ledger) ----------------------------------


class TransactionBase(BaseModel):
    """A ledger entry. buy: adds units, cash out. sell: removes units at their
    average cost (the difference vs proceeds is the realized P/L), cash in.
    dividend: cash in only (quantity = shares held at the ex-date, unit_price
    = dividend per share); the position is untouched. close: the position is
    gone in its entirety and `amount` came back — the only exit for a row that
    has no units to sell. Positions = latest snapshot + ledger entries after
    that snapshot."""

    kind: str = Field(
        default="buy",
        pattern="^(buy|sell|dividend|close)$",
        description="buy | sell | dividend | close",
    )
    date: datetime.date = Field(..., description="Actual execution date")
    institution_id: int | None = Field(
        default=None, description="Institution holding the position this entry moves"
    )
    cash_institution_id: int | None = Field(
        default=None,
        description="Institution whose cash paid (defaults to institution_id)",
    )
    # Not only a label: a sell or a close is matched back to the position it
    # settles by symbol OR by asset_name, and a close is the one kind allowed
    # no symbol — so for those rows this string is the whole binding.
    asset_name: str = Field(..., min_length=1, description="Instrument name")
    # Required for anything measured in units; a `close` may have none, because
    # the rows that need an exit most are exactly the ones no ticker describes.
    symbol: str | None = Field(default=None, description="Yahoo ticker (e.g. VWCE.MI)")
    isin: str | None = Field(default=None, description="Fund ISIN, when known")
    asset_class: str | None = Field(
        default=None, description="equity | bond | fund_etf | crypto | ..."
    )
    quantity: float = Field(
        default=0.0, ge=0,
        description="Units moved; for a dividend, the units held at the ex-date",
    )
    unit_price: float = Field(
        default=0.0, ge=0,
        description="Price per unit; for a dividend, the dividend per share",
    )
    fees: float = Field(
        default=0.0, ge=0, description="Broker fees/commissions, in `currency`"
    )
    amount: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Actual cash moved, never negative, in `currency`. Defaults to "
            "quantity*unit_price + fees for a buy, and quantity*unit_price - "
            "fees (net proceeds) for a sell or dividend — with quantity*unit_price "
            "converted from `price_currency` at the rates of `date` when the two "
            "currencies differ. A close has no units to derive it from, so it "
            "must state it — 0 is allowed, silence is not."
        ),
    )
    currency: str = Field(
        ...,
        description=(
            "Currency of `amount` and `fees`: the cash that left or reached the "
            "account, e.g. EUR"
        ),
    )
    price_currency: str | None = Field(
        default=None,
        description=(
            "Currency of `unit_price` — the listing's, e.g. USD. Required for a "
            "buy, a sell and a dividend; a close has no price and leaves it empty."
        ),
    )
    note: str | None = Field(default=None, description="Free-form notes")

    @model_validator(mode="after")
    def _check_shape(self) -> "TransactionBase":
        """A unit-based entry needs a ticker and a quantity; a close needs
        proceeds. Loosening the fields for `close` must not loosen them for
        everything else — a buy without a ticker would create a position no
        price could ever reach."""
        if self.kind == "close":
            if self.amount is None:
                raise ValueError(
                    "a close must state its proceeds (0 is allowed, but it has "
                    "to be said: value cannot leave without saying where it went)"
                )
            return self
        if not (self.symbol or "").strip():
            raise ValueError(f"a {self.kind} needs a ticker")
        if self.quantity <= 0:
            raise ValueError(f"a {self.kind} needs a quantity above zero")
        if not (self.price_currency or "").strip():
            raise ValueError(
                f"a {self.kind} needs the currency its price is in (price_currency, "
                "e.g. the listing's USD): quantity x price is an amount in that "
                "currency, and the app will not assume it is the account's"
            )
        return self


class TransactionCreate(TransactionBase):
    """Payload to record a buy manually."""

    currency: StatedCurrency = Field(
        ...,
        description=(
            "Currency of `amount` and `fees`: the cash that left or reached the "
            "account, e.g. EUR"
        ),
    )
    price_currency: StatedCurrency | None = Field(
        default=None,
        description=(
            "Currency of `unit_price` — the listing's, e.g. USD. Required for a "
            "buy, a sell and a dividend; a close has no price and leaves it empty."
        ),
    )


class TransactionWrite(TransactionCreate):
    """What a PERSON may post to `/api/transactions` — which is not the same
    thing as what the ledger is able to store.

    `institution_id` is required here and required nowhere else. A row with
    NEITHER institution column set is skipped by the cash register, which keeps
    only the entries belonging to the institution it is computing and finds
    that `None` equals no id there is; the position the same row creates is
    bucketed under `None` and counted in full. One half of the transaction is
    addressed to an institution and the other half to nobody, so the money
    spent never leaves an account and the purchase adds its own cost to the net
    worth. Measured: one institution holding 1000, a buy of 10 units at 10.00
    with no institution named, and the net worth went from 1000.00 to 1100.00.

    It is the CASH side that makes this required rather than any preference of
    the schema's — the money came from somewhere, and with no institution named
    the app has nowhere to take it from.

    The column stays nullable and `TransactionCreate` stays loose on purpose:
    the PAC writes rows with no HOLDING institution (a plan target that names
    none) while always naming the PAYING one, and those rows are unreachable
    but arithmetically right. Requiring the field of them is a separate
    decision. This subclass narrows the one door a reader posts through, and
    leaves the internal one alone."""

    institution_id: int = Field(
        ...,
        description=(
            "Where the position is held — and, unless cash_institution_id says "
            "otherwise, whose cash moves. Required: an entry naming no "
            "institution spends money no account ever loses."
        ),
    )


class TransactionRead(TransactionBase):
    """A stored transaction as returned by the API."""

    model_config = API_OUT

    id: int
    amount: float
    fx_as_of: str | None = Field(
        ...,
        description=(
            "The ECB day whose rate turned quantity x unit_price into `amount`, "
            "when the app derived it across two currencies. Null when there was "
            "nothing to convert, or when the amount is the reader's own figure."
        ),
    )
    plan_id: int | None
    plan_occurrence: str | None
    estimated: bool = Field(
        ..., description="Priced at the market close, not a real broker fill"
    )
    created_at: str
    currency_note: str | None = Field(
        default=None,
        description=(
            "Set when `price_currency` disagrees with the currency the listing "
            "actually trades in, so the entry is worth opening and correcting."
        ),
    )


class CatchUpSkip(BaseModel):
    """One catch-up item that could NOT be executed, and why. `label` names
    the source (a PAC plan or a dividend-paying symbol)."""

    model_config = API_OUT

    label: str
    occurrence: datetime.date | None
    reason: str


class CatchUpResult(BaseModel):
    """Outcome of a catch-up run: transactions created for every elapsed,
    still-unrecorded PAC occurrence and dividend ex-date, plus what was
    skipped (retried on the next run)."""

    model_config = API_OUT

    created: list[TransactionRead]
    skipped: list[CatchUpSkip]


# --- FX rates ---------------------------------------------------------------


class FxRateRead(BaseModel):
    """One ECB reference rate: units of `currency` per 1 `base` on `as_of`."""

    model_config = API_OUT

    base: str
    currency: str
    rate: float
    as_of: str
    fetched_at: str


# --- ETF look-through composition ------------------------------------------


class AllocationSlice(BaseModel):
    """One country/sector with its weight (percent, 0-100)."""

    model_config = API_OUT

    name: str
    pct: float


class OverlapItem(BaseModel):
    """A stock held inside 2+ funds: combined portfolio weight and the funds."""

    model_config = API_OUT

    name: str
    pct: float
    funds: list[str]


class MatrixCell(BaseModel):
    """One asset class x region cell of the look-through, as a percent of the
    whole portfolio."""

    model_config = API_OUT

    asset_class: str
    region: str
    pct: float


class CompositionRow(BaseModel):
    """Look-through status of one portfolio position: what it resolved to,
    which source decomposed it, or why it stayed whole."""

    model_config = API_OUT

    symbol: str | None
    asset_name: str
    asset_class: str | None = None
    weight_pct: float
    resolved_name: str | None
    isin: str | None
    source: str | None = Field(..., description="justetf | mstarpy | yfinance")
    fetched_at: str | None
    holdings_count: int | None
    decomposed: bool
    error: str | None


class PortfolioComposition(BaseModel):
    """The portfolio's REAL exposure: per-position resolution rows plus
    aggregated country/sector weights and cross-fund holding overlap.
    `coverage_pct` = share of the portfolio the look-through decomposed."""

    model_config = API_OUT

    rows: list[CompositionRow]
    countries: list[AllocationSlice]
    sectors: list[AllocationSlice]
    companies: list[AllocationSlice] = Field(
        default=[],
        description=(
            "Single-company exposure through the funds — the same data `overlap` "
            "is derived from, but complete instead of only the shared names."
        ),
    )
    currencies: list[AllocationSlice] = Field(
        default=[],
        description=(
            "Currency the exposure really sits in, derived from the country "
            "weights (see app/geo.py for the stated limits — country of listing, "
            "no hedging)."
        ),
    )
    matrix: list[MatrixCell] = Field(default=[], description="Asset class x region")
    overlap: list[OverlapItem]
    coverage_pct: float
    undecomposed_pct: float = Field(
        default=0.0,
        description=(
            "The share no source could decompose. Kept explicit so a chart can "
            "show it as its own slice instead of quietly normalising it away."
        ),
    )
    total_value: float = Field(
        ...,
        description=(
            "What the looked-through portfolio is worth — the denominator the "
            "weights are shares of. Market where the market can price a "
            "position, its last observed value where it cannot."
        ),
    )
    base_currency: BaseCurrency
    notes: list[str] = Field(
        default=[],
        description=(
            "Why an axis is missing, when it is — so an empty chart never passes "
            "for 'you own nothing there'."
        ),
    )


# --- Advisor chain ---------------------------------------------------------


class ChainStepRead(BaseModel):
    """One role's turn in a chain run, with the model that produced it."""

    model_config = API_OUT

    step_no: int
    role: str  # analyst | confidant | revision | synthesis
    title: str
    model: str | None
    output: str
    duration_ms: int | None
    # In USD, as the provider reported it. Null where it did not, which is not
    # the same as free — the page says nothing rather than nothing-per-step.
    cost: float | None


class ChainRunRead(BaseModel):
    """A chain run: the final verdict plus every step, so the reasoning stays
    inspectable."""

    model_config = API_OUT

    id: int
    verdict: str | None
    created_at: str
    steps: list[ChainStepRead]


class ChainRunSummary(BaseModel):
    """One run as a LIST reads it: when it ran, how deep it went, and whether
    the confidant actually argued.

    No text. The verdict is a document and the steps are four more of them, and
    a list that carried them would download every word four models ever wrote
    so the reader could choose a date.

    `challenge` is the whole point of the shape. The chain's value is that the
    confidant is adversarial, and a mandate that never bites is an expensive
    way to agree with yourself — so whether it bit has to be readable from
    outside the run, and across runs it is a count. It is the confidant's own
    `VERDICT:` marker and not an inference from how many steps there were: the
    two can disagree, and the marker is the one that says what was meant.

    'unstated' is a third answer and not a quiet 'fits'. It means no turn of
    that run ended on a marker this code recognises, so the run says nothing
    about the mandate either way and must not be counted as if it did."""

    model_config = API_OUT

    id: int
    created_at: str
    step_count: int = Field(..., description="How many turns the run took, 3 to 7")
    revisions: int = Field(
        ...,
        description=(
            "How many times the analyst was asked to answer the challenge — "
            "the depth the argument actually bought"
        ),
    )
    challenge: Literal["contested", "fits", "unstated"] = Field(
        ...,
        description=(
            "The confidant's own VERDICT marker for the run: whether it "
            "challenged something that mattered, waved the findings through, "
            "or ended on no marker at all"
        ),
    )


# --- The chat -----------------------------------------------------------------


class ChatTextBlock(BaseModel):
    """A run of text in a message."""

    kind: Literal["text"] = "text"
    text: str


class ChatThoughtBlock(BaseModel):
    """The model's reasoning before it answered — kept, folded, so the reader
    can see how the answer was reached, and never sent back to the model."""

    kind: Literal["thought"] = "thought"
    text: str


class ChatPageBlock(BaseModel):
    """Where in the app the reader was when they asked — kept on the question,
    before its words.

    A NAME and not an id, fixed at the moment of asking: "Records → Wealth →
    Broker B". The reader moves between messages, so where they are now says
    nothing about where an earlier question was asked, and a conversation that
    renamed its past when an account was renamed would be rewriting what was
    said. The same reason a sum fixed on a day is never restated.

    It is the APP's sentence, never the reader's, which is why it is a block of
    its own rather than a line pasted into their text. See `app/screen.py`."""

    kind: Literal["page"] = "page"
    label: str


class ChatToolBlock(BaseModel):
    """A tool the model consulted while writing this answer, kept in the place
    it was consulted.

    It is here for provenance, which is the same reason every figure on this
    reader's screen carries where it came from. An answer that says "counting
    inside your funds, NVIDIA is 4.2% of the portfolio" got that from
    somewhere, and a stored answer that does not say so is the one number on
    the screen that cannot be traced. `ok` is false when the tool refused or
    broke, and `detail` says why: an answer written after a tool failed was
    written with less than it asked for, and the reader is owed that."""

    kind: Literal["tool"] = "tool"
    name: str
    ok: bool
    detail: str | None = None


class ChatCardChange(BaseModel):
    """One line of a card's diff: what a field says now, and what it would say.

    Both sides are TEXT and not numbers, because a diff is read and not
    computed with. `now` is null where the record says nothing yet, which is a
    different thing from a zero and has to look different."""

    field: str
    now: str | None = None
    proposed: str | None = None


class ChatCardField(BaseModel):
    """One line of a card as the reader reads it: a label in their words and a
    value, never a schema name, a row id or a timestamp (brief AJ: the
    reader's cards said "based_on", "symbol null", a row's id, and an ISO
    timestamp under "added_at"). `kind` says how the panel writes
    the value in the reader's language: a day ("date", YYYY-MM-DD), a number,
    or an amount in `currency`."""

    label: str
    value: str
    kind: Literal["text", "date", "number", "amount"] = "text"
    currency: str | None = None


class ChatCardBlock(BaseModel):
    """A write the model PROPOSED, and what became of it.

    Nothing has happened when this is written. The model never calls `crud`;
    it drafts a change, this is how the change is shown, and the write runs
    from the normal path only after the reader confirms it — same `crud`, same
    unit of work, same contract the form goes through. The chat does not get a
    service door the form does not have, and a wrong field is corrected on the
    card rather than in the database.

    `outcome` and `result` are why the block is rewritten in place instead of
    a second block being appended: a history that shows what was proposed and
    not what happened is a "done!" with no receipt, and a rejected card has to
    stay visible as a rejected card. Both states are on record.

    `card_id` exists because a block otherwise has no address — the JSON list
    has no key and its index is not promised to be stable — and the endpoint
    that settles this one has to be able to name it.

    `call_id` is the id the MODEL's tool call carried, kept so the exchange can
    be replayed to it: the API pairs an assistant turn's `tool_calls` with the
    `tool` turns that answer them by exactly this string, and a conversation
    missing one is refused.

    `confirmation` is the rule from the domain and not a UI preference, and it
    is about REVERSIBILITY. An event — a transaction, a dated valuation — is
    verifiable and undone by deleting it, so it gets a light confirmation.
    Anything that OVERWRITES gets `diff` and the field-by-field of what would
    be replaced: a snapshot, because editing it rewrites what that day said and
    every projection anchored after it moves, and equally a questionnaire
    answer, which is not kept in history, and after this says something else
    and carries another day.

    `fingerprint` is what the proposal depended on when it was made, so the
    confirmation can tell whether the ground moved under it. See
    `tools.Proposal`."""

    kind: Literal["card"] = "card"
    card_id: str
    call_id: str
    tool: str
    title: str
    arguments: dict = Field(default_factory=dict)
    confirmation: Literal["light", "diff"] = "light"
    consequence: str = Field(
        default="",
        description=(
            "What confirming this costs that the diff does not show, in the "
            "proposing tool's own words. Only the tool knows: editing a "
            "snapshot moves every figure anchored after it, while replacing a "
            "questionnaire answer moves nothing and simply loses the old one. "
            "Empty falls back to the one thing true of every diff card — that "
            "it replaces what is on record and the old value does not come "
            "back."
        ),
    )
    verb: str = Field(
        default="",
        description=(
            "What pressing the accept button DOES, in the proposing tool's own "
            "words — 'Add to watchlist' rather than 'Confirm'. Empty means "
            "Confirm, which is right for everything that writes to the "
            "reader's records. It is the tool's word for the same reason "
            "`consequence` is: a suggestion changes nothing about their money, "
            "and 'Confirm' over a card naming a security reads as approval of "
            "a purchase that is not being proposed."
        ),
    )
    diff: list[ChatCardChange] = Field(default_factory=list)
    fingerprint: str = ""
    outcome: Literal["pending", "confirmed", "rejected"] = "pending"
    result: dict | None = Field(
        default=None,
        description=(
            "What the write produced, once it ran — the fields as the tool "
            "returned them, not a sentence about them. Two readers want this "
            "and they want it in the same shape: the model, which is handed it "
            "back as the answer to its call, and the card, which shows it "
            "under the diff in the same field-by-field form the diff used. "
            "Rendered to a string here it would have to be parsed back for "
            "one of them."
        ),
    )
    # The card in the reader's words, worked out by `tools.present` whenever a
    # card is sent or read back, and never stored: the cards of a conversation
    # held since before these existed read the same way.
    fields: list[ChatCardField] = Field(
        default_factory=list,
        description="The proposal's arguments in the reader's words, the absent ones left out",
    )
    receipt: list[ChatCardField] = Field(
        default_factory=list,
        description="What a confirmed card wrote, in the reader's words; empty until then",
    )
    done: str = Field(
        default="",
        description="What a confirmed card says it is now: 'Recorded', 'Added to your watchlist'",
    )


class ChatWebPage(BaseModel):
    """One page a web search found: its address and its title. An http or https
    address only, checked where it entered (`advisor._page`), because it is
    shown as a link the reader can press."""

    url: str
    title: str


class ChatSourcesBlock(BaseModel):
    """The pages a web search found, kept where the search ran.

    Provenance, for the reason a `ChatToolBlock` is kept: an answer that says
    "Vanguard gives 0.03%" got that from somewhere, and the reader is owed the
    page. These are what the search RETURNED (OpenRouter's search on Exa hands
    back every page it found, five a search), so they are the pages the model
    was given to read, not a claim about which of them it used; the sentence
    that uses one carries its link. A page found twice in a turn is listed
    once. Never sent back to the model with a later turn: past turns travel as
    their words, and a link the model wrote travels inside them."""

    kind: Literal["sources"] = "sources"
    pages: list[ChatWebPage]


# What a message is MADE OF: blocks, each with a `kind`, never a bare string.
# Text, thought, the tools consulted between them, the pages a web search
# found, and the cards proposed; and on a question, the page it was asked
# from.
# An instrument suggested from the catalogue is a new member of this union
# later, stored in the same column and rendered by the same panel, not a
# rewrite of what a message is.
#
# `ChatStep` is deliberately NOT one of these. It is an event and not a block,
# because what it narrates — a run of the analyzer — is already a record of its
# own, and the card that proposed it is already the receipt.
#
# The order is the record: a tool consulted halfway through an answer belongs
# between the paragraph that led to it and the paragraph that used it, not
# appended after both.
ChatBlock = Annotated[
    ChatTextBlock
    | ChatThoughtBlock
    | ChatPageBlock
    | ChatToolBlock
    | ChatSourcesBlock
    | ChatCardBlock,
    Field(discriminator="kind"),
]


# Where the reader is, as the frontend says it: which page is on screen when the
# question is sent. One kind per level of the app a question can be ABOUT — the
# object a page is titled after, never a row inside it, because nothing in the
# app selects a row and a hover is not an intent.
#
# Ids, not names, and that is safe HERE: they come from the app's own state and
# never from a model, and the server turns every one of them into a name before
# a model reads anything. A situation carries its account too, so that when the
# situation is gone the page can fall back one level to the account instead of
# to nothing.


class ChatPageDashboard(BaseModel):
    kind: Literal["dashboard"]


class ChatPagePortfolio(BaseModel):
    kind: Literal["portfolio"]


class ChatPageProfile(BaseModel):
    kind: Literal["profile"]


class ChatPageRecords(BaseModel):
    """A sub-page of Records with nothing opened inside it."""

    kind: Literal["records"]
    section: Literal["wealth", "real", "debts", "cash"]


class ChatPageAccount(BaseModel):
    """One institution's page: its cash register and its situations."""

    kind: Literal["account"]
    institution_id: int


class ChatPageSituation(BaseModel):
    """One dated situation, opened from its account's page."""

    kind: Literal["situation"]
    institution_id: int
    snapshot_id: int


class ChatPageRealAsset(BaseModel):
    """One real asset's page: its dated valuations."""

    kind: Literal["real_asset"]
    real_asset_id: int


class ChatPageDebt(BaseModel):
    """One debt's page: its outstanding balance over time."""

    kind: Literal["debt"]
    liability_id: int


class ChatPageAnalyses(BaseModel):
    """The list of every analysis run."""

    kind: Literal["analyses"]


class ChatPageAnalysis(BaseModel):
    """One analysis run, open in the main column."""

    kind: Literal["analysis"]
    run_id: int


ChatPage = Annotated[
    ChatPageDashboard
    | ChatPagePortfolio
    | ChatPageProfile
    | ChatPageRecords
    | ChatPageAccount
    | ChatPageSituation
    | ChatPageRealAsset
    | ChatPageDebt
    | ChatPageAnalyses
    | ChatPageAnalysis,
    Field(discriminator="kind"),
]


class ChatRequest(BaseModel):
    """One more question in a conversation.

    The server holds the conversation, so the client sends only the new
    question and which conversation it belongs to — none, and a new one is
    opened for it. The financial context is rebuilt from the database on each
    request, so what the model reads is never older than the question."""

    conversation_id: int | None = Field(
        default=None, description="Continue this conversation; null opens a new one"
    )
    content: str = Field(..., min_length=1)
    model: str | None = Field(
        default=None,
        description="OpenRouter slug; empty means the configured chat default",
    )
    page: ChatPage | None = Field(
        default=None,
        description=(
            "The page on screen when this was sent. A hint about what 'this' "
            "refers to, never a narrowing of the question; null says nothing"
        ),
    )


class ChatMessageRead(BaseModel):
    """One stored turn. `status` is how an assistant turn ENDED — done, error
    (with `detail`), or cut, the connection closed before it finished — and
    null on a user turn."""

    model_config = API_OUT

    id: int
    seq: int
    role: str  # user | assistant
    blocks: list[ChatBlock]
    status: str | None = None
    detail: str | None = None
    model: str | None = None
    created_at: str

    @field_validator("blocks", mode="before")
    @classmethod
    def _blocks_from_json(cls, v):
        # The column is JSON text; the API speaks in blocks.
        return json.loads(v) if isinstance(v, str) else v


class ChatConversationRead(BaseModel):
    """A conversation as the history list shows it: its first question as the
    title, and when it was last spoken to."""

    model_config = API_OUT

    id: int
    title: str | None
    created_at: str
    updated_at: str


class ChatConversationDetail(ChatConversationRead):
    """The conversation with every turn, oldest first."""

    messages: list[ChatMessageRead]


class ChatModel(BaseModel):
    """One entry of the model dropdown."""

    model_config = API_OUT

    slug: str
    note: str | None = Field(
        default=None, description="What is known about it, with the date it was checked"
    )


class ChatModelsRead(BaseModel):
    """What the dropdown offers, and which of them answers when nothing is picked."""

    model_config = API_OUT

    default: str
    models: list[ChatModel]


class ChatStart(BaseModel):
    """The first frame: which conversation this turn landed in — the id a new
    conversation was given — and the stored id of the question.

    Null where there was no question. Answering a card resumes a conversation
    without anybody asking anything: the reader pressed confirm, and inventing
    a user turn to hang the id on would put a sentence in their mouth that
    they never wrote.

    `page_label` is where the question was stored as asked from, as the server
    resolved it — a page gone since has already climbed a level. It arrives
    before the answer so the panel can print it under the question while the
    answer is still being written, from the one authority on it rather than
    from a guess of its own."""

    kind: Literal["start"] = "start"
    conversation_id: int
    user_message_id: int | None = None
    page_label: str | None = None


class ChatThought(BaseModel):
    """A piece of the model's reasoning, in order, before the answer starts.
    Shown folded and quiet: it is how the wait is spent, not the answer."""

    kind: Literal["thought"] = "thought"
    text: str


class ChatDelta(BaseModel):
    """A piece of the answer, in order. Concatenate them."""

    kind: Literal["delta"] = "delta"
    text: str


class ChatTool(BaseModel):
    """A tool has been asked for and is running.

    Sent BEFORE the tool runs, not after, because its whole job is to say what
    the silence is. The look-through reads a cache in milliseconds and walks
    four fund issuers when the cache is cold, and the difference between those
    two is the difference between a pause and a minute — the same argument
    that put the model's own thinking on the wire rather than leaving a
    spinner. How it WENT is not here: it is in the stored `ChatToolBlock`, and
    in the answer the model writes next.

    Except a failure, since brief AG (2026-10-06). The loop answers a call
    before it sends this, so a refusal is known by then, and `detail` carries
    its reason, as the stored block keeps it: a suggestion past the third in
    one answer, or one Yahoo could not vouch for, arrives in a round that ends
    on the cards it did draw, where the model never gets to say why it is
    missing. Null when nothing failed, which is not a claim that anything
    succeeded."""

    kind: Literal["tool"] = "tool"
    name: str
    detail: str | None = None


class ChatStep(BaseModel):
    """A long tool has finished one of its steps, and is going on.

    Sent while it runs, and never stored. Its job is `ChatTool`'s job said more
    than once: to be what the silence IS. The analyzer is three to six model
    calls and a minute of them, and the page it used to live on refused to fake
    a progress bar for exactly the right reason — `run_chain` wrote nothing
    until all of it had finished, so "step 2 of 4" would have been invented.
    Now each finished step is a fact the orchestrator was told, so it can be
    said without inventing anything.

    Nothing here is a record. What is persisted is the run itself, whole, at
    the end — and the card that proposed it becomes the receipt. A second copy
    of "the analyst finished at 12s" inside the message blocks would be a third
    place the same run lives.
    """

    kind: Literal["step"] = "step"
    tool: str
    step_no: int
    label: str
    duration_ms: int


class ChatCard(BaseModel):
    """A card has been proposed, and the turn is about to end on it.

    It carries the block itself rather than repeating its fields, so the panel
    renders one shape whether the card just arrived or was read back from the
    history — and so the two cannot come to disagree, which nine fields
    written out twice eventually do.

    The turn ENDS here, and ends on `done`. SSE is one-directional and the
    confirmation is a new request, so holding the stream open while a person
    decides would leave a call billing to nobody — and would need a fourth
    ending called "waiting for you", which `cut` would then be indistinguishable
    from. A closed browser leaves nothing pending: the card is a stored block,
    so it is still there when the reader comes back, and so is the fact that
    they never answered it."""

    kind: Literal["card"] = "card"
    card: ChatCardBlock


class ChatDecided(BaseModel):
    """A card has been decided, and this is the card as it is now stored.

    Sent the moment the decision is on record: right after `start` for every
    card but the analyzer's, whose decision is stored when its run is, after
    its steps. The panel swaps the card it shows for this one there and then,
    so the card reads as decided whatever the turn that follows does. Until
    brief AJ the panel coloured it only once that turn had ended well: the
    reader's second confirmation, on 2026-10-08, was stored, its follow-up
    failed, and the card kept its buttons; pressing again was refused as a
    decision already taken. The block itself, for the reason `ChatCard`
    carries one: one shape, whether it arrived now or is read back later."""

    kind: Literal["decided"] = "decided"
    card: ChatCardBlock


class ChatSource(BaseModel):
    """A page a web search found, as it arrives.

    Sent when OpenRouter hands it over: once the search has run, which is
    before the words written from it, or at the end of a round that ended on
    the app's own tools. The panel lists it where it arrived, as the stored
    `ChatSourcesBlock` will when the conversation is read back."""

    kind: Literal["source"] = "source"
    url: str
    title: str


class ChatCardDecision(BaseModel):
    """The reader's answer to one card.

    Deliberately not named `...Create`: it creates nothing, and the contract
    test parametrizes every schema whose name ends that way. `ChatRequest` set
    that precedent for a chat body already.

    Only a decision, and no corrected arguments. Deferred once already,
    against the fake tool, and now decided
    against the three real ones, so it is a decision rather than a gap.

    A card's `arguments` are an untyped dict, because one block type carries
    every tool's proposal. An editor over that can only guess its widget from
    the runtime type of the JSON value, and every field that is worth
    correcting is exactly where that guess fails: a date is a string, a
    currency is a string, an asset class is a string with six legal values, and
    an institution is a name that has to resolve against a row. So an editable
    card either asks the reader to hand-type what the tool exists to resolve
    for them, or the card has to carry per-field metadata — which is the
    argument schema, declared a second time, in the one place `tools.py` opens
    by refusing to declare anything twice.

    The correction that does work today costs one round trip and has a single
    author: "no, 450" and the model draws a fresh card. When editing is built
    it should come from the argument model's own JSON schema, generated where
    the tool schema is generated, and that is a design and not a field."""

    decision: Literal["confirm", "reject"]
    model: str | None = Field(
        default=None,
        description="OpenRouter slug for the follow-up; empty means the chat default",
    )


class ChatDone(BaseModel):
    """The answer is complete and stored. Its ABSENCE is the signal: a stream
    that ends without this event broke off, and the client must say so rather
    than show a truncated answer as though it were the whole one."""

    kind: Literal["done"] = "done"
    model: str
    message_id: int


class ChatError(BaseModel):
    """The answer cannot continue, and why. Sent in place of `done`."""

    kind: Literal["error"] = "error"
    detail: str


# Every event the chat stream can carry, discriminated on `kind`. The SSE
# `event:` line repeats the kind so a client can route without parsing, and
# the `data:` line is one of these as JSON. Anything added is a new kind here.
#
# `done` and `error` are the only two that END a turn, and a stream that
# carries neither was cut — see ChatDone. A new kind must never be a third
# ending, or that inference stops working: a turn that ends on a tool, or
# later on a card, still finishes with `done`.
ChatEvent = Annotated[
    ChatStart
    | ChatThought
    | ChatDelta
    | ChatTool
    | ChatSource
    | ChatStep
    | ChatCard
    | ChatDecided
    | ChatDone
    | ChatError,
    Field(discriminator="kind"),
]
