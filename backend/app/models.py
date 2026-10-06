"""ORM models (SQLAlchemy 2.x) for Aurelio — Phase 1 / MVP.

Wealth model (v2): an Institution holds dated Snapshots ("the situation at a
date"); each Snapshot holds Holdings grouped by asset class. A snapshot's value
is the SUM of its holdings (no separate, manually-entered total). There is no
"account" level.

Cash model (vB): cash is NOT stored in snapshots; it is a live "register".
Each institution has CashAnchors (a manually-entered actual balance at a date);
the projected cash at any date = latest anchor + linked income − expenses ±
Transfers between institutions − what the investment ledger spent + what it
brought back (a buy takes cash out; a sell, a dividend or a close pays it in),
counting only events after the anchor date. Snapshots are therefore
investments-only.

Liabilities (F1): debts (mortgage, loans, ...) live in their own branch with
dated outstanding balances (mirroring real-asset valuations). Net worth =
financial + real − liabilities. A liability can optionally point to the real
asset it finances (mortgage -> house) to surface the user's equity.

Tables: settings, institutions, snapshots, holdings, real_assets,
real_asset_valuations, liabilities, liability_balances, income_sources,
expenses, cash_anchors, transfers, survey_responses, goals,
accumulation_plans, transactions, price_cache, composition_cache, fx_rates,
chain_runs, chain_steps, chat_conversations, chat_messages, watchlist_items.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow_iso() -> str:
    """ISO 8601 timestamp in UTC, to the second (e.g. 2026-05-30T13:45:12+00:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Setting(Base):
    """Global app configuration as key-value pairs (e.g. base_currency)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class Institution(Base):
    """Financial institution: bank, broker, insurance, pension fund, etc."""

    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # bank | broker | insurance | pension_fund | crypto_exchange | other
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    snapshots: Mapped[list["Snapshot"]] = relationship(
        back_populates="institution",
        cascade="all, delete-orphan",
    )
    cash_anchors: Mapped[list["CashAnchor"]] = relationship(
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    @property
    def snapshot_count(self) -> int:
        """How many dated situations exist here.

        Surfaced because ONE is a meaningful state the app never named: with a
        single photograph there is nothing to compare against, the wealth chart
        has nothing to draw between, and every quantity is as old as that one
        day."""
        return len(self.snapshots)

    @property
    def latest_snapshot(self) -> str | None:
        """The date of the most recent situation, or None.

        KEPT, because it is a field of the public API (`InstitutionRead`) that
        the Wealth page reads, and rerouting it through `dated` would only move
        a one-line max onto a collection that is already in memory. What made
        it N+1 was not the property but the list endpoint loading the
        collection lazily, one institution at a time; `crud.get_institutions`
        now eager-loads it, so the whole list costs two queries.

        The anchor RULE is not here: this returns a date to display, not a
        photograph to project from. `dated.latest_per_parent` answers that
        question, for every institution at once.

        And DELIBERATELY not bounded at today, unlike everything that projects.
        This one says what is on record, and a row dated ahead of today is on
        record: the API now refuses to store a new one, so the only way to have
        one is a row written before it did, and this subtitle is where the
        reader sees that it is there. Bounding it would leave the Wealth page
        saying "latest 2026-08-07" above a list containing 2026-09-17 — the
        cue to go and delete the row, removed from the one screen that can."""
        return max((s.date for s in self.snapshots), default=None)


class Snapshot(Base):
    """A dated 'situation' of an institution: what was held there that day.
    One snapshot per institution per date.

    What it is WORTH is not a field of this class — see the note below the
    columns."""

    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("institution_id", "date", name="uq_snapshot_institution_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    institution: Mapped["Institution"] = relationship(back_populates="snapshots")
    holdings: Mapped[list["Holding"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )

    # NO `currency` HERE. A situation used to carry one, a label no total read —
    # every holding states its own — which said EUR on a dollar account because
    # every form wrote the new-row currency into it (removed by 01f722f11058).
    # `currency` is NOT NULL on the eight tables that store an amount in one
    # (holdings, real_assets, liabilities, income_sources, expenses,
    # cash_anchors, transfers, goals). An empty one used to mean EUR,
    # which was true only while EUR was the only base there could be;
    # migration a7d2e94c10b8 wrote that meaning into the rows once and the
    # columns stopped accepting the absence. `price_cache.currency` stays
    # nullable, because an empty value there says something else: the
    # listing's currency is not known yet.

    # NO `value` PROPERTY HERE, and no money property anywhere else in this
    # file. There used to be one — `sum(h.value for h in self.holdings)` — and
    # it was wrong for as long as it existed, because every Holding carries its
    # own currency and a property has no session, so it could not reach the
    # `fx.Converter` that is the only correct way to add two of them together.
    # It summed Turkish lira and the page printed a euro sign on the answer:
    # 89 lira shown as 89 EUR, fifteen pixels above the same position valued at
    # 2 EUR by the projection, which does have a session. A factor of 56.
    #
    # The rule that replaced it: **a model property may return a count, a date
    # or a stored figure; it may not do arithmetic on amounts.** The other
    # three properties in this file (`snapshot_count`, `latest_snapshot`,
    # `latest_balance`) are the first three and are fine. A total in money is
    # computed where a session is — `positions.snapshot_values_in_base` — and
    # supplied to the schema by the router.


class Holding(Base):
    """A position within a snapshot, in an asset-class bucket. Snapshots are
    investments-only now; cash lives in the CashAnchor/Transfer register, not
    here. `value` is the source of truth; if absent but quantity and unit_price
    are set, value is computed as quantity * unit_price (hybrid ingestion)."""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_name: Mapped[str] = mapped_column(String, nullable=False)
    # cash | equity | bond | fund_etf | crypto | real_estate | commodity | other
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True)
    # Two identifiers, two jobs: `symbol` is the Yahoo ticker that prices the
    # position (MVOL.MI quotes in EUR in Milan), `isin` identifies the fund
    # itself and is what the composition sources key on. One field cannot do
    # both — the same fund is MVOL in Milan and IQQ0 on Xetra.
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # What the position COST, as distinct from what it is worth. Null means
    # unknown, and unknown must stay unknown: inferring a cost from `value`
    # is what made "P/L vs recorded" measure movement since a photograph
    # instead of gain. `cost_estimated` marks a figure that was derived (from
    # a broker's reported % return, say) rather than read off a contract note.
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_estimated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    # acc | dist — distributing pays dividends to cash; accumulating reinvests.
    # Empty: the ticker's own dividend history decides (pac._follows_dividends).
    distribution_policy: Mapped[str | None] = mapped_column(String, nullable=True)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="holdings")


class RealAsset(Base):
    """A real/physical asset owned directly (not held at an institution):
    real estate, vehicle, collectible, etc. Parallel to the financial branch."""

    __tablename__ = "real_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # real_estate | vehicle | collectible | jewelry | art | other
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    acquisition_date: Mapped[str | None] = mapped_column(String, nullable=True)  # YYYY-MM-DD
    acquisition_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    valuations: Mapped[list["RealAssetValuation"]] = relationship(
        back_populates="real_asset",
        cascade="all, delete-orphan",
    )


class RealAssetValuation(Base):
    """A dated valuation of a real asset (mirrors Snapshot for institutions)."""

    __tablename__ = "real_asset_valuations"
    __table_args__ = (
        UniqueConstraint("real_asset_id", "date", name="uq_valuation_asset_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    real_asset_id: Mapped[int] = mapped_column(
        ForeignKey("real_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    value: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    real_asset: Mapped["RealAsset"] = relationship(back_populates="valuations")


class Liability(Base):
    """A debt (mortgage, personal loan, ...). The outstanding principal is
    tracked as dated balances — update it periodically from your statement.
    The monthly payment stays an Expense (the cash side): net worth then drops
    only by the interest portion, since repaid principal just moves wealth
    from cash to equity. `real_asset_id` optionally links the debt to the
    asset it finances (mortgage -> house) so the UI can show your equity."""

    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # mortgage | personal_loan | auto_loan | student_loan | credit_card | other
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    interest_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # annual %
    real_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("real_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    balances: Mapped[list["LiabilityBalance"]] = relationship(
        back_populates="liability",
        cascade="all, delete-orphan",
    )

    @property
    def latest_balance(self) -> float | None:
        """The most recent outstanding balance (None if never recorded).

        Kept for the same reason as `Institution.latest_snapshot`: it is a
        field of `LiabilityRead` that both Debts and Real assets display, and
        its N+1 was the list endpoint's lazy load, which `crud.get_liabilities`
        now eager-loads away. Analytics does not come through here — it needs
        the balance in force at a DATE, which is `dated.latest_on_or_before`,
        and asking that question one liability at a time is what this shape
        cannot do."""
        if not self.balances:
            return None
        return max(self.balances, key=lambda b: b.date).balance


class LiabilityBalance(Base):
    """A dated outstanding balance of a liability (mirrors RealAssetValuation)."""

    __tablename__ = "liability_balances"
    __table_args__ = (
        UniqueConstraint("liability_id", "date", name="uq_balance_liability_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    liability_id: Mapped[int] = mapped_column(
        ForeignKey("liabilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    liability: Mapped["Liability"] = relationship(back_populates="balances")


class CashFlowItemMixin:
    """The columns an income source and an expense have in common.

    They are TWO tables and stay two tables. What they share is the shape of a
    recurring amount — a name, a size, how often, out of or into whose cash,
    over which window — and that shape was written out twice, so the two drifted
    the moment one of them gained a column.

    What is NOT shared is the column that classifies them, and that is the whole
    reason they are not one table: an income is `active` or `passive` (does it
    keep arriving if you stop working?) and an expense is `essential` or
    `discretionary` (could you stop paying it?). Those are two different
    questions with two different answers, not one column with four values, and
    the cash register adds one while subtracting the other.

    A mixin rather than a base class: SQLAlchemy copies these columns into each
    table, so both tables keep exactly the DDL they had before this was factored
    out. `sort_order` is what keeps that true — without it a column declared on
    the subclass is emitted BEFORE the mixin's, and slot 2 is reserved here for
    precisely that column, the one each table classifies itself by."""

    id: Mapped[int] = mapped_column(primary_key=True, sort_order=0)
    name: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)
    # slot 2: `kind` on income_sources, `nature` on expenses.
    # See each table for its own vocabulary; they do not overlap.
    category: Mapped[str | None] = mapped_column(String, nullable=True, sort_order=3)
    amount: Mapped[float] = mapped_column(Float, nullable=False, sort_order=4)
    currency: Mapped[str] = mapped_column(String, nullable=False, sort_order=5)
    # monthly | quarterly | semiannual | annual | one_off
    frequency: Mapped[str | None] = mapped_column(String, nullable=True, sort_order=6)
    # Window for the cash projection. start_date = first occurrence (also the
    # date of a one_off); end_date = last occurrence (open-ended if null).
    start_date: Mapped[str | None] = mapped_column(String, nullable=True, sort_order=7)  # YYYY-MM-DD
    end_date: Mapped[str | None] = mapped_column(String, nullable=True, sort_order=8)  # YYYY-MM-DD
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        sort_order=9,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, sort_order=10)
    created_at: Mapped[str] = mapped_column(
        String, default=_utcnow_iso, nullable=False, sort_order=11
    )


class IncomeSource(CashFlowItemMixin, Base):
    """A source of income. `kind` distinguishes active (from work) vs passive
    (rents, dividends, interest, ...). `institution_id` links it to the
    institution whose cash it feeds (optional)."""

    __tablename__ = "income_sources"

    kind: Mapped[str | None] = mapped_column(String, nullable=True, sort_order=2)  # active | passive
    # salary | freelance | business | rental | dividends | interest | pension | other


class Expense(CashFlowItemMixin, Base):
    """A recurring or one-off cost. `nature` distinguishes essential (needs) vs
    discretionary (wants). `institution_id` links it to the institution whose
    cash it draws from (optional)."""

    __tablename__ = "expenses"

    nature: Mapped[str | None] = mapped_column(String, nullable=True, sort_order=2)  # essential | discretionary
    # housing | food | transport | utilities | health | insurance | debt | leisure | education | other


class CashAnchor(Base):
    """A manually-entered ACTUAL cash balance for an institution at a date.

    The live cash register starts from the latest anchor on/before a given date
    and projects forward everything that moved the balance since: linked
    income and expenses, transfers, and the investment ledger — a buy takes
    cash out, a sell, a dividend or a close pays it back in. The ledger half
    is easy to forget when reading only this file, and leaving it out turns
    every recorded purchase into cash the register still thinks is there.

    Adding a newer anchor re-bases the projection (like reconciling a bank
    statement), which is also what stops those events being counted twice:
    only the ones strictly after the anchor date are applied. One anchor per
    institution per date."""

    __tablename__ = "cash_anchors"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "date", name="uq_cash_anchor_institution_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    institution: Mapped["Institution"] = relationship(back_populates="cash_anchors")


class Transfer(Base):
    """A movement of cash from one institution to another on a date. It lowers
    the source institution's projected cash by `amount` in `currency`, and
    raises the target's by `to_amount` in `to_currency` — one sum when the two
    accounts share a currency, two when they do not. FKs use SET NULL: if an
    institution is deleted, transfers survive with a null endpoint and are
    simply ignored by the projection."""

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    from_institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    to_institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    # What reached the destination, fixed on the day. Worked out at the ECB
    # rate final for `date` when it was not copied from a statement, and then
    # `fx_as_of` is that rate's day; a figure the reader typed leaves it empty.
    to_amount: Mapped[float] = mapped_column(Float, nullable=False)
    to_currency: Mapped[str] = mapped_column(String, nullable=False)
    fx_as_of: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)


class SurveyResponse(Base):
    """One stored answer from the planning questionnaire (financial-literacy
    intro + qualitative profile). Classified by macro-topic for the advisor."""

    __tablename__ = "survey_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When the answer, as it reads now, was recorded: re-stamped when the
    # answer changes and kept when a write repeats it (both paths in crud.py).
    # The analysis and the chat read each answer with this day, so a statement
    # like "not yet entered" can be read against what was entered since.
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)


class Goal(Base):
    """A financial goal: a 'safe' qualitative type, or a concrete target
    (amount + horizon) used to compute the required return."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # protect_inflation | stable_income | long_term_growth | emergency_fund | target_amount
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    target_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[str | None] = mapped_column(String, nullable=True)  # YYYY-MM-DD
    current_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)


class Transaction(Base):
    """One recorded event in the investment ledger: a buy, a sell, a dividend
    or a close.

    Transactions are the LEDGER of what actually happened; snapshots stay the
    periodic reconciliation photos. A position's current quantity = the latest
    snapshot's quantity + the entries AFTER that snapshot's date (mirroring the
    cash register's anchor + flows model), so a fresh snapshot re-bases and
    nothing is counted twice.

    `kind` decides what the columns mean, and they are not the same row four
    times over:
      buy       quantity units at unit_price; `amount` is cash out.
      sell      quantity units leave at their AVERAGE COST, so the difference
                against the proceeds is the realized P/L; `amount` is cash in.
      dividend  the position is untouched. quantity is the shares held at the
                ex-date and unit_price the dividend per share — they multiply
                out to `amount`, cash in, and describe no change in units.
      close     the position goes in its entirety and `amount` is what came
                back. The only exit for a row with no units to sell, which is
                why `symbol` is nullable (see the column below).
    The cash side is always `amount`, never negative, in `currency`, against
    the paying — or receiving — institution's projected cash. `unit_price` is
    in `price_currency`, and the two differ for a purchase paid in one currency
    and listed in another: the account is debited a FIXED sum on the day, at
    that day's rate, and it is that sum the register takes out. Deriving it
    again at today's rate would make the account's balance move by itself.

    `asset_name` is not just a label on a sell or a close: those are matched
    back to the position they settle by symbol OR by asset_name, and a close
    is the one kind allowed no symbol. For that row the string IS the binding,
    and one that does not match leaves the position both still held and
    reported as having vanished.

    `plan_id`/`plan_occurrence` link an auto-generated buy to the PAC schedule
    slot it fulfils (idempotency key for the catch-up). `estimated` marks
    prices taken from the market close instead of a real broker fill; editing
    the row clears it."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String, default="buy", nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    # Institution holding the bought position.
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Institution whose cash paid (defaults to institution_id when null).
    cash_institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True
    )
    asset_name: Mapped[str] = mapped_column(String, nullable=False)
    # Nullable for `close`: the rows that most need an exit are exactly the
    # ones no ticker describes. The shape rule lives in the schema — a close
    # states its proceeds; a buy/sell/dividend still requires a ticker.
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    # cash | equity | bond | fund_etf | crypto | real_estate | commodity | other
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Actual cash out (quantity * unit_price + fees unless overridden), in
    # `currency`, as are the fees.
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    # What `unit_price` is in. Empty only for a close, which has no price.
    price_currency: Mapped[str | None] = mapped_column(String, nullable=True)
    # The ECB day whose rate turned quantity * unit_price into `amount`, when
    # the app derived it across two currencies. Empty when there was nothing to
    # convert, or when the figure is the reader's own — which is how a debit
    # copied from a statement is told apart from one worked out here.
    fx_as_of: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("accumulation_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_occurrence: Mapped[str | None] = mapped_column(String, nullable=True)  # YYYY-MM-DD
    estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)


class ChainRun(Base):
    """One run of the advisor chain: several model roles arguing in sequence
    (see app/chain.py). `verdict` denormalizes the final synthesis so the UI
    can show the answer without loading every step."""

    __tablename__ = "chain_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    steps: Mapped[list["ChainStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ChainStep.step_no",
    )


class ChainStep(Base):
    """One role's turn inside a chain run, kept so the reasoning stays
    inspectable after the fact (and survives a reload)."""

    __tablename__ = "chain_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("chain_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_no: Mapped[int] = mapped_column(nullable=False)
    # analyst | confidant | revision | synthesis
    role: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    # What this step cost, in USD, as OpenRouter reported it on the final
    # chunk's `usage`. Nullable because it is what the provider SAID and not
    # what we computed: a model that answers without a usage figure leaves this
    # empty rather than a zero, and a zero is a price. Sibling of duration_ms
    # for the same reason — the card that asks the reader to spend a minute and
    # a few cents quotes both from the last run, and neither may be a guess.
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    run: Mapped["ChainRun"] = relationship(back_populates="steps")


class CompositionCache(Base):
    """The look-through composition of a fund/ETF, keyed by the holding's
    symbol: countries, sectors and top holdings as a JSON blob, plus the
    resolved ISIN/name and which source provided it. Composition changes
    slowly, so entries are reused for 15 days (see app/composition.py)."""

    __tablename__ = "composition_cache"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Whichever won the waterfall: issuer | justetf | trackinsight | yfinance,
    # or equity for a share that is its own composition. 'undecomposable' is
    # the fifth answer — nothing could place it, cached so the waterfall is not
    # re-run for it on every page load. (mstarpy is gone; it opened a browser.)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON payload
    # How old `data` is, and nothing else.
    fetched_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)
    # When a refresh of this entry was last refused as poorer than it
    # (composition._poorer), or null. Its own column, so fetched_at never
    # moves forward on a failed try: it only spaces the next attempt.
    refused_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Instrument(Base):
    """One instrument in the local registry, keyed by ISIN.

    Identity, never quotation. Two columns here are actively dangerous if
    mistaken for the latter: `share_class_currency` says USD for funds that
    quote in EUR in Milan (the phantom 17% gain in analytics.py), and
    `base_ticker` is not a Yahoo symbol: the catalogue gives EUNL for iShares
    Core MSCI World, one code for a fund with many listings. Both are carried
    to help tell two similar rows apart,
    and neither may fill the field it resembles."""

    __tablename__ = "instruments"

    isin: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Groups the accumulating fund with its distributing twin: they share a
    # name and differ only in what they do with dividends, so neither may be
    # shown without the other.
    family_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    base_ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    distribution_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    ter: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_meur: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replication: Mapped[str | None] = mapped_column(String, nullable=True)
    domicile: Mapped[str | None] = mapped_column(String, nullable=True)
    share_class_currency: Mapped[str | None] = mapped_column(String, nullable=True)
    holdings_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hedged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    fetched_at: Mapped[str] = mapped_column(String, nullable=False)


class PriceCache(Base):
    """The last market price fetched per symbol. Refreshing the portfolio
    updates it; non-live reads (initial page load, future dashboard uses)
    reuse it instead of calling Yahoo, always alongside its `as_of` close
    date so staleness stays visible to the user. `currency` is the listing's
    trading currency (a listing never changes currency, so once learned it
    sticks); null means not yet known, and a price in it is not converted
    into the base as if it were in it."""

    __tablename__ = "price_cache"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[str] = mapped_column(String, nullable=False)  # market close date
    fetched_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)


class FxRate(Base):
    """One ECB reference rate: units of `currency` per 1 `base`, as published
    for the day `as_of`. Fetched from frankfurter.app (see app/fx.py).

    A row per DAY, kept: a refresh adds the days after the newest one rather
    than overwriting it, so the table is the history of the rates as well as
    today's. Three readers need another day's rate — the net worth history,
    a purchase paid in another currency, the plan and dividend catch-up — and
    they read it here, from the one place that knows what a rate was on a day.

    `base` is part of the key because a rate is not a number without it. The
    feed answers for whatever base it is asked, and it never lists the base
    among its own rates, so a table of rates that did not say which base they
    were fetched against would be read against whichever base asked next —
    1.1592 dollars per euro served as dollars per dollar. Two bases' rows sit
    side by side and neither is ever read for the other."""

    __tablename__ = "fx_rates"

    base: Mapped[str] = mapped_column(String, primary_key=True)
    currency: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[str] = mapped_column(String, primary_key=True)  # the ECB day
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)


class AccumulationPlan(Base):
    """A recurring savings plan (PAC): every period, `amount` of cash from the
    source institution is used to buy the target investment at the target
    institution.

    Plans AUTO-EXECUTE via the catch-up (see app/pac.py): on demand, every
    elapsed occurrence without a matching Transaction gets a Buy at that day's
    market close, marked `estimated` so the user can correct it with the real
    broker fill. `execution` picks the broker's fill model (whole units vs
    fractional)."""

    __tablename__ = "accumulation_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # What `amount` is paid in: the source account's cash. Each target is
    # priced in its listing's currency and converted into this one at the rate
    # of its close day before the budget is spent on it.
    currency: Mapped[str] = mapped_column(String, nullable=False)
    # monthly | quarterly | semiannual | annual
    frequency: Mapped[str | None] = mapped_column(String, nullable=True)
    # whole_units (default: floor(amount/price), remainder stays in cash, as a
    # whole-unit broker's plan does) | fractional (exactly `amount` invested,
    # as a broker that sells fractions does).
    execution: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[str | None] = mapped_column(String, nullable=True)  # YYYY-MM-DD
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)  # YYYY-MM-DD
    source_institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # What a whole-unit contribution could not spend, waiting for the next one.
    # A real standing order does not throw its change away: without this, a
    # target priced above its share of ONE contribution is never bought at all.
    # Bookkeeping about intent, not about where money sits — cash is only ever
    # debited by what was actually spent.
    carried_remainder: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    targets: Mapped[list["PlanTarget"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanTarget.position",
    )
    unfilled_occurrences: Mapped[list["PlanUnfilledOccurrence"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanUnfilledOccurrence.occurrence",
    )


class PlanUnfilledOccurrence(Base):
    """An occurrence that ran, put its contribution into the carry, and bought
    nothing.

    Being finished used to be DERIVED: an occurrence was done if a Transaction
    carried its key. That is the right question for "did this occurrence buy"
    and the wrong one for "did this occurrence run". A contribution that cannot
    reach one whole unit of any target is folded into carried_remainder and
    writes no transaction — so the occurrence read as never having run, came
    back on the next catch-up with a FRESH contribution on top of a carry a
    later occurrence had already spent, and bought a 150 unit twice out of two
    100 contributions. The catch-up runs at every app start, so the trigger was
    restarting the app.

    Only unfilled occurrences live here. One that bought is still recognised by
    its transactions, so deleting an auto-created buy still puts its occurrence
    back in the queue — which is how a user asks for it to be done again.

    A priced failure records NOTHING, deliberately: it did not run, it could
    not. Its contribution was never touched and it must come back. Those two
    outcomes looked the same to the old rule, and that is what made this.

    `reason` is the sentence the run reported at the time, kept because without
    it the fix would leave the app knowing less than the bug did: the
    occurrence is settled on the first run, so it never appears in a later
    run's `skipped` again and nothing else remembers why that month was
    empty."""

    __tablename__ = "plan_unfilled_occurrences"
    __table_args__ = (
        UniqueConstraint("plan_id", "occurrence", name="uq_unfilled_plan_occurrence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("accumulation_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    plan: Mapped["AccumulationPlan"] = relationship(back_populates="unfilled_occurrences")


class PlanTarget(Base):
    """One instrument bought by a plan, and its share of the budget.

    A plan holds several of these because that is how people actually save:
    one standing order, split across a few funds. Modelling it as one plan per
    fund forced the budget to be split by hand and left each slice with its own
    unspendable remainder — with whole-unit brokers, several small remainders
    are much worse than one, since none of them can ever buy a unit."""

    __tablename__ = "plan_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("accumulation_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)  # Yahoo ticker
    # Carried so a position first created BY this plan still knows which fund
    # it is, and therefore still gets a look-through.
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Share of the plan's budget, in percent. Normalised at execution, so the
    # user can type 1/1/1 or 40/30/30 and both mean what they look like.
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    plan: Mapped["AccumulationPlan"] = relationship(back_populates="targets")


class ChatConversation(Base):
    """One conversation with the chat, kept the way a chain run is kept: an
    answer that said something about this person's money is a dated record,
    not a browser tab's memory. `title` is the first question, cut short, so
    the history list can name it; `updated_at` moves with every message so the
    list can put the live one on top."""

    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )


class ChatMessage(Base):
    """One turn. `blocks` is the message's structured content as JSON — a list
    of {kind, ...} entries, text today, cards later — stored as the frontend
    shows it, so a card is a new kind and not a new column.

    `status` is for the assistant's turns and says how the answer ENDED:
    done (complete), error (the backend stopped it, or the provider did not
    finish it, and `detail` says why), or
    cut (the connection closed before `done` — the reader's Stop, or a break;
    the server cannot tell the two apart and does not pretend to). A user turn
    has no status."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(nullable=False)
    # user | assistant
    role: Mapped[str] = mapped_column(String, nullable=False)
    blocks: Mapped[str] = mapped_column(Text, nullable=False)
    # done | error | cut — assistant turns only
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    # What the provider says it RECEIVED for this turn, summed over its rounds
    # — a turn is up to `chat.MAX_COMPLETIONS_PER_TURN` calls and each one
    # re-sends the conversation. None when the provider did not say, which is
    # not zero: a zero is a measurement.
    #
    # Recorded for the same reason `chain_steps.cost` is: a number about what a
    # turn costs belongs in the record of that turn, measured, and not in a
    # docstring where it was true once. The figure this replaces sat in
    # `chat.py` for a fortnight, measured on a portfolio that had since gone
    # and on a prompt that had since grown by half.
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    # Of those, how many the provider read from its cache, summed the same way.
    # Since the chat asks Anthropic's models to cache (2026-10-05), the token
    # count alone stopped saying what a turn cost: on Opus 5.5 a cached token
    # was billed at a twentieth of the input price. A zero is kept as zero,
    # since it is an answer (nothing read from the cache); None means the
    # provider did not say.
    cached_tokens: Mapped[int | None] = mapped_column(nullable=True)
    # What OpenRouter says the turn's rounds cost, in USD, summed: the chat's
    # own figure beside `chain_steps.cost`. None when any round's price was not
    # reported, never a partial sum, because a cost that is low without saying
    # so is the worse mistake. An analysis the turn ran records its steps in
    # `chain_steps`, not here.
    cost: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)

    conversation: Mapped["ChatConversation"] = relationship(back_populates="messages")


class WatchlistItem(Base):
    """An instrument the reader is CONSIDERING, and why it was put in front of
    them. Nothing here is owned: this table touches no total, no allocation and
    no cash projection.

    It is the other end of a suggestion card. The chat may not name a fund out
    of its own memory — a suggestion is built from a row `search_catalogue`
    returned, so `isin` is a key that exists in `instruments` at the moment it
    is written rather than a plausible-looking string — and accepting the card
    parks it here instead of buying anything, because no broker is connected to
    this app and never will be.

    THE THREE TEXT COLUMNS ARE THE POINT, and they are three rather than one on
    purpose. A suggestion has to say why it suggests this (`reason`), on the
    basis of what the reader declared (`based_on`), and what it does not know
    (`unknowns`) — and the third is the one a single free-text field quietly
    loses, because it is the uncomfortable one. In a month the useful question
    about a line here is not what it was, it is what it rested on and what it
    was blind to. An idea with no provenance is the same defect as a figure
    with no provenance, and this app refuses that everywhere else.

    `symbol` is a hint and never the identity on a FUND's line. It comes from
    `lookup_symbol`, the live lane, and nothing offline can confirm it,
    which is why the ISIN is the half that identifies a fund. It is
    emphatically NOT the catalogue's `base_ticker`, which is not a Yahoo
    symbol.

    A SHARE's line is the other way round (brief AG, 2026-10-06): no ISIN,
    because nothing this app can ask gives a share's, and the symbol is the
    identity, the exact one Yahoo listed as a share when the card was drawn and
    again when it was accepted. So exactly one of the two identifies a line:
    the ISIN when there is one, else the symbol. `schemas.WatchlistItemBase`
    refuses a line with neither.
    """

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A fund's identity, from the catalogue; null on a share's line, which is
    # named by its symbol (migration 5a4336780500). Not a foreign key onto
    # `instruments`: that table is REPLACED wholesale on every refresh, so a
    # constraint would make a fund leaving the market delete the reasoning
    # about it, and what the idea rested on stays worth reading after the row
    # it named is gone.
    isin: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    based_on: Mapped[str] = mapped_column(Text, nullable=False)
    unknowns: Mapped[str] = mapped_column(Text, nullable=False)
    # `added_at` and not `created_at`, which every other table calls it: a
    # watchlist line is read as "added on", and the identity check in
    # tests/test_write_contract.py knows both names for the same reason.
    added_at: Mapped[str] = mapped_column(String, default=_utcnow_iso, nullable=False)
