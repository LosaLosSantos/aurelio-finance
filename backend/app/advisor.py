"""AI advisor: assemble financial context and ask GitHub Copilot for an
educational analysis.

Model calls use the GitHub Copilot SDK and the account authenticated by the
local Copilot CLI. No API key is read by this application.

Configuration (from environment / backend/.env):
- COPILOT_MODEL            : default model (default: claude-opus-5.5)
- COPILOT_ANALYST_MODEL    : optional quantitative-analysis model
- COPILOT_CONFIDANT_MODEL  : optional personal-context model

PRIVACY NOTE: prompts send the financial context needed for the request to
GitHub Copilot and its model providers.

This module builds the three contexts and owns the two synchronous model-call
boundaries. The analysis itself is the chain in `app/chain.py`, proposed and
read from the chat.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import analytics, catalogue, copilot_provider, crud, dated, fx, planning, schemas, sizing

DEFAULT_MODEL = "claude-opus-5.5"

# One sentence of punctuation, for every prompt whose words reach a page: the
# chat's answer, and each step the Analysis page shows. The reader asked for no
# em dash anywhere they read, and a model writes them out of habit.
NO_DASHES = (
    "Never write an em dash (—) or an en dash between spaces ( – ), in any "
    "language: the person reading has asked for none. Where one would go, use "
    "a period, a colon, a comma or parentheses."
)

# The rule every role that writes a figure is given, in the same words: run 1
# called a share of the investments "at risk" without saying of what, and it
# read as a share of everything the reader holds.
WHOLE_RULE = (
    "Every percentage you write names its whole: a share of the investments, of "
    "the investments and the cash together (the liquid wealth), or of "
    "everything the person owns (the liquid wealth and the real assets). A "
    "share without its whole is not written."
)

PORTFOLIO_SYSTEM_PROMPT = (
    "You are an unbiased, quantitative analyst of a person's investments and of "
    "everything they own beside them. You receive their investment data "
    "(positions with cost basis and P/L, the look-through composition of their "
    "funds: countries, sectors, top holdings, overlap across funds; their "
    "recurring plans) and what is around it: the cash on each account, "
    "projected to today; the income and expenses in force today, with the "
    "ones that have not started listed apart; their real assets (homes, land, "
    "physical gold: what they own that is neither an account nor an "
    "investment); their debts; and the wholes every share is taken from, "
    "already computed. NO personal context is provided, on purpose: judge the "
    "figures strictly on their own merits. Analyze: TRUE diversification "
    "(look-through, not fund count) across asset classes, sectors, "
    "geographies and single-name concentration; overlap between funds (same "
    "underlying stocks bought twice); currency exposure if inferable; "
    "cost/efficiency observations; the portfolio's implicit bets (e.g. 'this "
    "is effectively a leveraged bet on US mega-cap tech'); the allocation of "
    "everything they own, where the real assets are an exposure the "
    "investments must be judged beside (a person who owns homes already holds "
    "property, one who keeps physical gold already holds gold, and neither is "
    "missing from them); and liquidity: how many months the cash covers, what "
    "is left each month, what the debts cost. Liquidity is the cash and the "
    "flows alone: a real asset is never cash and never counts in it. A real "
    "asset's value is an estimate the person typed on the date beside it, not "
    "a market price: treat it as an estimate and say how old it is when you "
    "use it. Quantify every claim with the numbers provided. A fund's cost "
    "(TER), domicile, replication and hedging are the catalogue's, on the "
    "fund's line; where the line does not give one, it is not known. Never "
    "quote a fund's cost from memory. "
    + WHOLE_RULE
    + " Be direct about weaknesses; do not flatter. Note explicitly what the "
    "data does NOT cover (undecomposed positions, stale prices). Format in "
    "clean simple Markdown: headings, short paragraphs, '-' bullets, at most "
    "one small table. End with a one-line disclaimer that this is educational "
    "information, not personalized regulated advice. Do not tell the user to "
    "buy or sell specific securities. Answer in English. " + NO_DASHES
)


class AdvisorError(Exception):
    """Raised when an analysis cannot be produced (config or call failure)."""


@dataclass(frozen=True)
class ToolCall:
    """One tool the model asked for, assembled from the fragments it arrived in.

    `arguments` is the raw JSON string the model wrote, not a parsed dict, and
    that is deliberate twice over. It has to travel back to the API verbatim
    inside the assistant turn — a re-serialised dict is a different string and
    some providers check. And whether it parses at all is not this module's
    business: a model that writes broken JSON has made a mistake the caller
    running the tool can describe back to it, which is a better answer than a
    stream that dies of a ValueError.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    """Token usage for one Copilot call.

    Copilot reports subscription usage rather than a USD call price. `cost`
    therefore remains None. `searches` is retained for the app's separate web
    retrieval accounting.
    """

    prompt_tokens: int | None
    cached_tokens: int | None
    cost: float | None
    searches: int | None = None


def _position_caveats(r: dict) -> list[str]:
    """The qualifications the screen shows and the prose did not.

    A row whose cost was never recorded still HAS an `avg_cost` — it is the
    price the snapshot happened to be taken at — and printing it bare invites
    the model to reason about a profit that is really a movement. The table
    says "cost unknown" and "since situation" for exactly this reason; the
    advisor was the only reader never told, which is backwards: it is the one
    consumer that actually reasons about the figures."""
    notes: list[str] = []
    if r.get("avg_cost") is not None and not r.get("cost_known") and r.get("book_paid"):
        # Part of it paid (brief AV): it said COST UNKNOWN of all of it,
        # purchases on record included. What was paid, what is a situation's
        # value, and which part of the P/L is a gain.
        line = (
            f"COST PARTLY PAID: {r['book_paid']:.2f} of the book "
            f"({r['book_paid'] / r['book_value'] * 100:.1f}%) is money paid, for "
            f"{r['units_paid']:g} of the {r['quantity']:g} units (buys, or a cost typed on a "
            "situation); the rest is the value a situation recorded"
        )
        if r.get("delta_paid") is not None:
            line += (
                f". Of the P/L, {r['delta_paid']:+.2f} is a gain or a loss on the units paid "
                f"for and {r['delta'] - r['delta_paid']:+.2f} is movement since that situation, "
                "NOT profit"
            )
        notes.append(line)
        if r.get("cost_estimated"):
            notes.append(
                "the part paid is ESTIMATED: some or all of it is a plan's buy priced at a "
                "market close, or a cost derived from a reported % return, not read off a "
                "contract note"
            )
    elif r.get("avg_cost") is not None and not r.get("cost_known"):
        notes.append(
            "COST UNKNOWN: no purchase on record, so the average cost above is "
            "the price the situation was recorded at, and the P/L is movement since "
            "then, NOT profit"
        )
    elif r.get("cost_estimated"):
        # Two sources since brief AI: a photographed cost derived from a
        # reported return, and a plan's buy at the close, which this line
        # used to misname as the first.
        notes.append(
            "cost ESTIMATED: some or all of it is a plan's buy priced at a market "
            "close, or a cost derived from a reported % return, not read off a "
            "contract note"
        )
    if r.get("currency_note"):
        notes.append(f"CURRENCY MISMATCH — {r['currency_note']}")
    return notes

def _plan_targets_label(plan) -> str:
    """"VWCE.MI 60% + EUNL.DE 40%" — or just the name when there is only one.

    The percentages are the normalised weights, not what the user typed: they
    may have written 3 and 2, and 60/40 is what that actually means."""
    targets = list(plan.targets)
    if not targets:
        return ""
    names = [t.asset_name or t.symbol for t in targets]
    if len(targets) == 1:
        return names[0]
    total = sum(t.weight for t in targets if t.weight > 0) or 1.0
    return " + ".join(
        f"{n} {t.weight / total * 100:.0f}%" for n, t in zip(names, targets)
    )


def _plan_budget(plan) -> str:
    """How one occurrence of `plan` spends its money, in a sentence.

    The reader's second test round (2026-10-08): the picture gave the plan's
    weights, and the chat expected each fund's buy at exactly its weight's
    share of the amount. A whole-unit plan spends the amount, with what the
    occurrence before it left, as ONE budget (`pac.allocate`), so each fund's
    figure follows the prices, and what no whole unit fits waits for the next
    one (`carried_remainder`)."""
    amount = f"{plan.amount:.2f} {plan.currency}"
    if (plan.execution or "whole_units") == "fractional":
        return f"Each occurrence invests exactly {amount}, in fractional units, split by the weights."
    carried = f"carried now: {plan.carried_remainder or 0.0:.2f} {plan.currency}"
    if len(plan.targets) > 1:
        return (
            f"Each occurrence spends {amount} and what the one before left as ONE "
            "budget, in whole units across its funds: a fund's figure follows the "
            "prices, not its weight exactly, and what no whole unit fits waits for "
            f"the next occurrence ({carried})."
        )
    return (
        f"Each occurrence buys whole units only, as many as {amount} and what the "
        "one before left can pay for; what no whole unit fits waits for the next "
        f"occurrence ({carried})."
    )


def _plan_executed(db: Session, plan, txs: list) -> str:
    """Which occurrences of `plan` have run, the last with the day it was
    bought, and what its buys are.

    The occurrence and the day can differ: an occurrence on a Sunday is bought
    at Monday's close and dated Monday (brief AJ). The picture said the last
    execution was the Sunday and listed buys on the Monday with nothing tying
    them, and the chat offered to delete "one of the two" as a duplicate.

    An occurrence settled without a buy is one of two things since brief AO:
    it ran and could not buy a unit, its money carried; or the reader deleted
    its buy, and the plan does not buy it again (`crud.delete_transaction`).
    Said apart, since the first sentence is false of the second."""
    executed = crud.get_plan_occurrences_executed(db, plan.id)
    settled = [u for u in plan.unfilled_occurrences if u.occurrence not in executed]
    deleted = sorted(u.occurrence for u in settled if crud.deleted_from_the_ledger(u.reason))
    unfilled = len(settled) - len(deleted)
    nothing = (
        f"{unfilled} occurrence{'' if unfilled == 1 else 's'} ran and bought nothing, "
        "their money waiting with what is carried."
    )
    gone = ""
    if len(deleted) == 1:
        gone = (
            f" The buy of its occurrence of {deleted[0]} was deleted from the ledger, so it "
            "does not buy that occurrence again."
        )
    elif deleted:
        gone = (
            f" The buys of its occurrences of {', '.join(deleted)} were deleted from the "
            "ledger, so it does not buy those occurrences again."
        )
    if not executed:
        return "No occurrence has bought anything yet." + (f" {nothing}" if unfilled else "") + gone
    last = max(executed)
    bought = ", ".join(
        sorted({t.date for t in txs if t.plan_id == plan.id and t.plan_occurrence == last})
    )
    said = (
        f"{len(executed)} occurrence{'' if len(executed) == 1 else 's'} executed; "
        f"the last is that of {last}, bought {bought}. Its buys are the ledger "
        "entries made by this PAC: each occurrence's own execution, never a "
        "second purchase of the same thing."
    )
    return said + (f" Besides, {nothing}" if unfilled else "") + gone


def _settles(t, named: dict[int, str]) -> str:
    """What a buy a PAC made says about it on its ledger line: the plan, the
    occurrence it settles and the day it was bought, which is the occurrence's
    own day or the first session after it. A dividend dated on another day
    than its ex-date (the day its money arrived, brief AZ) says its ex-date.
    Nothing for any other entry."""
    if t.kind == "dividend" and t.ex_date and t.ex_date != t.date:
        return f", the dividend with ex-date {t.ex_date}"
    if not t.plan_occurrence:
        return ""
    plan = f'the PAC "{named[t.plan_id]}"' if t.plan_id in named else "a PAC no longer on record"
    return f", made by {plan} for its occurrence of {t.plan_occurrence}, bought {t.date}"


def _render_rates(db: Session, base: str, portfolio: dict) -> list[str]:
    """The ECB's rates the app keeps, those in force today, for every currency
    on record that is not the base and every listing a position is priced in:
    one line, or none when everything is in the base.

    The totals were always converted at these and never said what they were:
    in the reader's second test round (2026-10-08) the chat answered that it
    had no exchange rate for a dollar figure, with the app holding the ECB's."""
    listings = {r["currency"] for r in portfolio["rows"] if r["currency"]}
    published, rates, missing = fx.rates_for(db, crud.get_currencies_on_record(db) | listings)
    said = []
    if rates:
        listed = ", ".join(f"{rate:.10g} {code}" for code, rate in rates.items())
        said.append(
            f"Exchange rates: the ECB's reference rates, which the app keeps; those "
            f"in force today were published on {published}: 1 {base} = {listed}."
        )
    if missing:
        said.append(f"The ECB publishes no rate for {', '.join(missing)}.")
    return [" ".join(said)] if said else []


def _isin(row: dict) -> str:
    """A row's ISIN as the fund catalogue stores it, or "" for none."""
    return (row["isin"] or "").strip().upper()


def _funds_held(db: Session, portfolio: dict) -> dict:
    """What the fund catalogue says about the funds in `portfolio`, for
    `_render_positions`: one read of the registry, no download."""
    return catalogue.facts(db, (_isin(r) for r in portfolio["rows"]))


def _render_fund(row: dict, funds: dict) -> str | None:
    """A fund's facts as the catalogue gives them, read by the ISIN on its
    row, or why they are not known.

    Run 2 of the analysis (2026-10-03) found no charge in its context and
    quoted four from the model's memory; the catalogue held them. What earns a
    place beside the charge: the domicile (it decides the tax the fund itself
    pays on the dividends it receives, which the charge does not show), the
    replication (a swap-based fund's return comes through a counterparty),
    the hedging (a hedged class has none of the currency exposure its
    holdings suggest) and the size (a small fund can be closed, which forces a
    sale). The dividend policy only where the row has none: the holding's own
    is already on the line, and it is the one the app collects dividends by.

    A row the catalogue describes is described whatever its asset class: a
    fund filed as a bond is still a fund. A row filed as a fund that it
    cannot describe says why, in words. Anything else gets nothing: a charge
    does not apply to a share, a coin or a gold bar, and "not known" would
    claim one exists."""
    isin = _isin(row)
    fund = funds["funds"].get(isin) if isin else None
    if fund is None:
        if row["asset_class"] != "fund_etf":
            return None
        if not isin:
            return "TER not known: no ISIN is recorded for it"
        why = (
            "the fund catalogue does not hold it"
            if funds["rows"]
            else "the fund catalogue has not been downloaded yet"
        )
        return f"ISIN {isin}, TER not known: {why}"
    said = [f"TER {fund['ter']:g}% a year" if fund["ter"] is not None else "TER not known"]
    policy = fund["distribution_policy"]
    if policy and not row["distribution_policy"]:
        said.append(schemas.POLICY_WORDS.get(policy, policy))
    if fund["domicile"]:
        said.append(f"domicile {fund['domicile']}")
    if fund["replication"]:
        said.append(f"replication {fund['replication']}")
    if fund["hedged"] is not None:
        said.append("currency-hedged" if fund["hedged"] else "not currency-hedged")
    if fund["size_meur"] is not None:
        said.append(f"fund size {int(fund['size_meur'])} M EUR")
    return f"ISIN {isin}, catalogue: {', '.join(said)}"


def _catalogue_source(funds: dict) -> str:
    """Where the facts after "catalogue:" come from, and how old they are: a
    fund's charge changes, and the registry is downloaded once a week."""
    try:
        when = f", as the app downloaded it on {dated.local_day(funds['fetched_at'])}"
    except (TypeError, ValueError):
        when = "; the day it was downloaded is not recorded"
    return f'- The facts after "catalogue:" are from justETF\'s list of funds{when}.'


def _age(day: str) -> str:
    """How long before today a market date is, in words the model does not
    have to work out: "today", "1 day before today", "6 days before today"."""
    days = (
        datetime.date.fromisoformat(dated.today()) - datetime.date.fromisoformat(day)
    ).days
    if days <= 0:
        return "today"
    return f"{days} day{'' if days == 1 else 's'} before today"


# The window of the realized and dividend TOTAL lines (brief AW): every stretch
# since each account's first situation, while each position's own figures
# cover only what follows its situation. Both said in one clause, so a model
# adding up the rows is not surprised by the total.
_TOTALS_WINDOW = "since each account's first situation; each row's own figure since its situation"


def _render_positions(portfolio: dict, funds: dict) -> list[str]:
    """The investment positions as prose: one line per row, then the totals.

    This is the one way the app describes a portfolio to a model. It was
    written out twice, and the copies had already drifted — one printed the
    price it valued the row at and the other only the date, one said
    "dividends collected" and the other "dividends" — which meant one of the
    two contexts was always the stale copy of a block nobody had decided to
    change. Where they disagreed the fuller wording won: a model reading
    "price as of 2026-05-30" cannot check the market value against anything.

    Takes what `analytics.compute_portfolio` returns and what the fund
    catalogue says about the funds in it (`_funds_held`), and nothing else, so
    it is coupled to no caller's locals. The section heading and the empty-
    portfolio line stay with the caller: each context says "no investment
    positions" or "(none)" in its own voice, and only the caller knows what
    it is heading."""
    lines: list[str] = []
    for r in portfolio["rows"]:
        parts = [
            f"- {r['asset_name']} [{r['asset_class'] or 'n/a'}] {r['symbol'] or ''}"
            # `institution` is null for a position held at none — the PAC
            # makes those — and "None" in the picture would read as a gap in
            # the data rather than as the answer it is.
            f" @ {r['institution'] or 'no institution'}: book {r['book_value']:.2f}"
        ]
        if r["quantity"] is not None:
            parts.append(f"qty {r['quantity']:g}")
        if r["avg_cost"] is not None:
            # In the base, like the book it is divided from: beside a price in
            # the listing's currency, a bare figure read as the same money.
            parts.append(f"avg cost {r['avg_cost']:.2f} {portfolio['base_currency']}")
        if r["live_price"] is not None:
            # The price with its currency and its age. Without the first the
            # chat wrote a dollar price with no unit (the reader's test round,
            # 2026-10-08); the second is a subtraction the model had to do,
            # and a price days old read like today's.
            parts.append(
                f"market {r['market_value']:.2f} "
                f"(price {r['live_price']:.2f} {r['currency']} as of {r['as_of']}, "
                f"{_age(r['as_of'])}, P/L {r['delta']:+.2f})"
            )
        elif r["observed_value"] != r["book_value"]:
            # Nothing priced this row, and its cost is not its value: the
            # screen shows both and the totals count the observation, so the
            # advisor gets both too. Told only the cost, the one consumer that
            # reasons arithmetically would compute a portfolio that disagrees
            # with the totals printed three lines below it.
            parts.append(
                f"worth {r['observed_value']:.2f} as last observed on "
                f"{r['observed_on']} (nothing can price it; no P/L is claimed)"
            )
        if r["realized_movement"]:
            # Brief AV: a sale or a close of a row partly or wholly a
            # situation's value with no cost realizes a gain only on the units
            # paid for; the rest is said as what it is.
            parts.append(
                f"realized P/L {r['realized_pl']:+.2f} on the units paid for, and "
                f"movement {r['realized_movement']:+.2f} on a situation's value with no "
                "purchase price on record (NOT profit)"
            )
        elif r["realized_pl"]:
            parts.append(f"realized P/L {r['realized_pl']:+.2f}")
        if r["dividends"]:
            parts.append(f"dividends collected {r['dividends']:.2f}")
        if r["distribution_policy"]:
            policy = r["distribution_policy"]
            parts.append(schemas.POLICY_WORDS.get(policy, policy))
        fund = _render_fund(r, funds)
        if fund:
            parts.append(fund)
        parts.extend(_position_caveats(r))
        lines.append("; ".join(parts))
    if any(_isin(r) in funds["funds"] for r in portfolio["rows"]):
        lines.append(_catalogue_source(funds))
    # Called "what was paid" whatever it held (brief AV): on the demo with an
    # invented fund, 22,246.00 of which 1,066.00 had been paid.
    if abs(portfolio["total_book"] - portfolio["total_book_paid"]) >= 0.005:
        lines.append(
            f"- TOTAL book: {portfolio['total_book']:.2f}, of which "
            f"{portfolio['total_book_paid']:.2f} is money paid and the rest situations' "
            "values with no purchase price on record"
        )
    else:
        lines.append(f"- TOTAL cost (what was paid): {portfolio['total_book']:.2f}")
    if portfolio["total_market"] is not None:
        carried = sum(
            r["observed_value"] for r in portfolio["rows"] if r["market_value"] is None
        )
        # Named for what it is. It is not all market: the rows nothing could
        # price contribute their last observed value, and a model told
        # "TOTAL market value" would read a photograph as a quote.
        line = (
            f"- TOTAL current value: {portfolio['total_market']:.2f} "
            f"(market prices as of {portfolio['prices_as_of']}, "
            f"{_age(portfolio['prices_as_of'])})"
        )
        if carried:
            line += f", of which {carried:.2f} is carried from situations, not priced"
        lines.append(line)
    if portfolio["total_realized_movement"]:
        lines.append(
            f"- TOTAL realized P/L ({_TOTALS_WINDOW}): {portfolio['total_realized']:+.2f} on "
            f"the units paid for; realized movement {portfolio['total_realized_movement']:+.2f} "
            "on situations' values with no purchase price on record (NOT profit, and no tax is "
            "estimated on it)"
        )
    elif portfolio["total_realized"]:
        lines.append(f"- TOTAL realized P/L ({_TOTALS_WINDOW}): {portfolio['total_realized']:+.2f}")
    if portfolio["total_dividends"]:
        line = f"- TOTAL dividends collected ({_TOTALS_WINDOW}): {portfolio['total_dividends']:.2f}"
        gross = portfolio["total_dividends_estimated"]
        if gross:
            line += (
                f", of which {gross:.2f} is still the GROSS figure the market "
                "declared (no withholding taken out yet)"
            )
        lines.append(line)
    lines.extend(_render_tax(portfolio["tax_estimate"]))
    return lines


def _render_tax(est: dict) -> list[str]:
    """The declared tax estimate, in the ONE document three readers share —
    the advisor chain, the chat, and since `cec3023` any outside assistant
    through the MCP server.

    Every figure here is computed before it is written. A model asked to work
    out a tax will invent a rule — it has read a thousand pages of them and no
    page saying which one this reader is under — whereas a model handed
    "estimated at 26%, the reader's own setting" quotes it. So the rate, the
    base, the product and the reasons it is approximate all arrive as text, and
    nothing is left for the other side to compute.

    It is rendered under the positions and outside every TOTAL line above it,
    which is the golden rule of app/tax.py made literal in the prose: the
    reader's net worth has not moved because a tax was estimated."""
    # A realized LOSS is worth saying even though it is no base: silence would
    # leave a reader — or a model — to assume the rate had been applied to it.
    # So is a realized movement (brief AV), which no rate is applied to.
    movement = est["realized_movement"]
    has_something = bool(
        est["realized_gain"] or est["dividends_gross_estimated"] or movement
    )
    if not est["configured"]:
        # Silence would be read as "no tax applies", and a zero would be worse.
        # "Nobody answered" and "there is nothing there" are different claims —
        # the same distinction `c906ccb` was a whole commit about — so the
        # absence is stated, with what it is an absence OF.
        if has_something:
            return [
                "- TAX: no rate set, so no estimate is made. The realized result "
                f"is {est['realized_gain']:+.2f}"
                + (" on the units paid for" if movement else "")
                + f" and {est['dividends_gross_estimated']:.2f} of dividends are still "
                "the market's gross figure."
                + (
                    f" A further {movement:+.2f} realized on situations' values with no "
                    "purchase price on record is movement, not a gain."
                    if movement else ""
                )
                + " The user sets a rate in Profile; do not estimate a tax yourself."
            ]
        return []

    if not has_something:
        # Nothing realized and no gross dividend, but the rate is still worth
        # carrying: "what would I pay if I sold this" is a question the model
        # gets asked, and one it will answer with an invented rule unless the
        # reader's own figure is already in front of it. The screen makes the
        # opposite choice and hides the panel — a zero row there is noise.
        rates = " / ".join(
            f"{label} {rate:g}%"
            for label, rate in (
                ("capital gains", est["capital_gains_rate"]),
                ("dividend withholding", est["dividend_withholding_rate"]),
            )
            if rate is not None
        )
        where = f" ({est['country']})" if est["country"] else ""
        return [
            f"- TAX: nothing realized and no gross dividends to estimate on yet. "
            f"The user's declared rates{where} are {rates} — use these if they ask "
            f"what something would cost them, and do not substitute your own."
        ]

    lines = ["- TAX (declared estimate, NOT in any total above):"]
    where = f" ({est['country']})" if est["country"] else ""
    # Each line is gated on its OWN base, not merely on a rate existing: with a
    # dividend to estimate and nothing sold, "realized gain 0.00 at 26% = 0.00"
    # is a true sentence that gives a model one more number to misread.
    if est["capital_gains_rate"] is not None and est["realized_gain"]:
        lines.append(
            f"  - realized LOSS of {-est['realized_gain']:.2f}; nothing estimated on it"
            if est["realized_gain"] < 0
            else f"  - realized gain {est['taxable_gain']:.2f} at "
            f"{est['capital_gains_rate']:g}%{where} = {est['capital_gains_tax']:.2f}"
        )
    if movement:
        lines.append(
            f"  - realized movement {movement:+.2f} on situations' values with no purchase "
            "price on record: NOT a gain, and no rate is applied to it"
        )
    if est["dividend_withholding_rate"] is not None and est["dividends_gross_estimated"]:
        line = (
            f"  - gross dividends {est['dividends_gross_estimated']:.2f} at "
            f"{est['dividend_withholding_rate']:g}%{where} = "
            f"{est['dividend_withholding']:.2f}"
        )
        if est["dividends_recorded_net"]:
            line += (
                f" (a further {est['dividends_recorded_net']:.2f} was corrected by "
                "hand and is already net — no rate applied)"
            )
        lines.append(line)
    if est["total"] is not None:
        lines.append(
            f"  - estimated total: {est['total']:.2f}"
            + (
                f" (it leaves out any tax on the movement of {movement:+.2f} above, "
                "which no rate can be applied to)"
                if movement else ""
            )
        )
    elif est["missing_rates"]:
        lines.append(
            "  - NO total: the user has not set a rate for "
            f"{' and '.join(est['missing_rates'])}, and a sum of only the half "
            "that could be computed would understate it."
        )
    lines.extend(f"  - caveat: {c}" for c in est["caveats"])
    return lines


def _render_survey(rows: list, heading: str = "##") -> list[str]:
    """The questionnaire grouped by topic — ANSWERED rows only.

    The two copies of this block disagreed on that filter, and dropping the
    blanks is the deliberate half of merging them: "- Your age?: None" reads
    to a model as something the user said, not as a question they passed
    over, and this codebase does not print a value it cannot stand behind.
    The UI never stores a blank (Profile.tsx drops them before saving), so in
    practice this only filters what came in through the API directly.

    The filter runs BEFORE the grouping, so a topic the user skipped entirely
    produces no heading rather than an empty one.

    `heading` is the level the topic headings sit at: this block is the whole
    document in the confidant's context and one section of a larger one in
    the full picture.

    Each answer carries the day it was recorded, in front of the question.
    Run 2 (2026-10-03) read an answer saying a spending was "not yet entered"
    in the register as true that day, after a line of the same amount had
    been entered, and the synthesis told the person to enter it again. A
    statement is about the day it was made; the records may have moved since,
    and the roles can only weigh that if they can see the day."""
    by_topic: dict[str, list] = {}
    for r in rows:
        if r.answer:
            by_topic.setdefault(r.topic or "Other", []).append(r)
    if not by_topic:
        return []

    lines: list[str] = [ANSWER_DAYS, ""]
    for topic, topic_rows in by_topic.items():
        lines.append(f"{heading} {topic}")
        for r in topic_rows:
            lines.append(
                f"- [{dated.local_day(r.created_at)}] {r.question or r.question_key}: {r.answer}"
            )
        lines.append("")
    return lines


# What the day in front of each answer means, said once wherever the
# questionnaire is read: by the confidant, the synthesis, the chat and the MCP
# server.
ANSWER_DAYS = (
    "The day in brackets is when each answer was recorded: it says what was true "
    "for them then, and their records may have changed since."
)


def _render_cash(positions: list[dict]) -> list[str]:
    """The cash register, one line per account, as `compute_all_cash_positions`
    projects it to today.

    Shared by the chat and the analyst for the reason `_render_positions` is:
    two copies of one block drift, and the analyst was the reader that had no
    copy at all. Run 1 asked the reader how much cash they could reach
    tomorrow, with the answer on this list. The heading and any total stay
    with each caller.

    Every term of the projection is on the line, so its parts add up to the
    figure in front of them. The ledger's two were missing until brief AI:
    with a buy or a dividend after the anchor, the line printed parts that
    did not make its own total."""
    if not positions:
        return ["- (no institutions)"]
    lines: list[str] = []
    for p in positions:
        if p["anchor_date"] is None:
            lines.append(f"- {p['institution_name']}: no cash anchor set yet")
        else:
            lines.append(
                f"- {p['institution_name']}: {p['projected']:.2f} "
                f"(anchor {p['anchor_amount']:.2f} on {p['anchor_date']}; "
                f"+income {p['income']:.2f} −expenses {p['expenses']:.2f}; "
                f"transfers +{p['transfers_in']:.2f}/−{p['transfers_out']:.2f}; "
                f"−buys {p['buys']:.2f} +sells, dividends and closes {p['sells']:.2f})"
            )
    return lines


def _render_debts(db: Session) -> list[str]:
    """Each debt's latest outstanding balance, in its own currency, with its
    rate and the real asset it finances.

    One renderer for the chat and the analyst, names included: the reader
    chose on 2026-10-02 that the analyst reads the records as the chat does.
    What keeps the analyst blind to the person is that it is given no profile
    and no goals, not that a debt is left unnamed."""
    liabs = crud.get_liabilities(db)
    if not liabs:
        return ["- (none)"]
    lines: list[str] = []
    for li in liabs:
        bals = crud.get_balances_for_liability(db, li.id)
        latest = bals[-1] if bals else None
        shown = (
            f"{latest.balance:.2f} {li.currency} ({latest.date})" if latest else "no balance yet"
        )
        rate = f", rate {li.interest_rate:.2f}%/yr" if li.interest_rate is not None else ""
        linked = ""
        if li.real_asset_id is not None:
            ra = crud.get_real_asset(db, li.real_asset_id)
            if ra is not None:
                linked = f", finances '{ra.name}'"
        lines.append(f"- {li.name} [{li.kind or 'n/a'}]: {shown}{rate}{linked}")
    return lines


def _render_real_assets(db: Session) -> list[str]:
    """Each real asset with its latest valuation, in the asset's own currency:
    a figure as the reader TYPED it, so it says what it is in.

    One renderer for the chat and the analyst. The analyst was not given these
    until the reader's choice of 2026-10-02: a home or physical gold is an
    exposure the investments have to be judged beside, and an analyst that
    cannot see them can propose buying what the reader already holds. The
    heading stays with each caller, and so does saying that a valuation is the
    reader's own estimate on a date."""
    lines: list[str] = []
    for ra in crud.get_real_assets(db):
        vals = crud.get_valuations_for_real_asset(db, ra.id)
        latest = vals[-1] if vals else None
        shown = (
            f"{latest.value:.2f} {ra.currency} ({latest.date})" if latest else "no valuation"
        )
        lines.append(f"- {ra.name} [{ra.category or 'n/a'}]: {shown}")
    return lines


def _flow_text(name, classified, category, amount, currency, frequency) -> str:
    """One income source or expense as the chat and the analyst read it: the
    name, how it is classified (active or passive, essential or discretionary),
    its category, the amount in its own currency and how often. Its notes are
    not here, for either of them. `_flow_line` adds the dates."""
    return (
        f"{name} [{classified or 'n/a'}/{category or 'n/a'}] "
        f"{amount:.2f} {currency} {frequency or ''}"
    )


def build_context(db: Session) -> str:
    """Assemble the full financial picture as a structured text for the LLM."""
    summary = analytics.compute_summary(db)
    allocation = analytics.compute_allocation(db)
    flows = analytics.compute_flows_in_force(db, dated.today())
    portfolio = analytics.compute_portfolio(db)  # cached prices only, no network

    lines: list[str] = [
        "# User financial situation",
        "",
        # The unit of every total below, from the computation that made them. A
        # model reading "Total: 455.69" cannot see a currency the screen shows
        # beside it; it has to be written down.
        f"Totals are in {summary['base_currency']}, the base currency. Figures a "
        "record states itself are given with their own currency.",
        *_render_rates(db, summary["base_currency"], portfolio),
        "",
    ]

    lines.append("## Net worth")
    lines.append(
        f"- Total: {summary['net_worth']:.2f} "
        f"(financial {summary['financial_total']:.2f} + real {summary['real_total']:.2f} "
        f"- debts {summary['liabilities_total']:.2f})"
    )
    # The newest photograph on record — a snapshot, a real-asset valuation or a
    # liability balance — and there may be none: cash anchors do not count
    # towards it, so a register-only net worth carries no date at all. The
    # screen drops the clause entirely when that happens (Dashboard.tsx); this
    # line printed "As of: None", which a model reads as a value rather than as
    # an absence. Same rule as the questionnaire blanks above.
    lines.append(
        f"- As of: {summary['as_of']}"
        if summary["as_of"]
        else "- As of: no situation, valuation or balance on record yet"
    )
    lines.append(
        f"- Counts: {summary['institutions']} institutions, "
        f"{summary['real_assets']} real assets, "
        f"{summary['liabilities']} liabilities"
    )
    lines.append("")

    lines.append("## Allocation")
    for s in allocation["by_asset_class"]:
        lines.append(f"- [financial] {s['asset_class']}: {s['value']:.2f}")
    for s in allocation["by_real_category"]:
        lines.append(f"- [real] {s['category']}: {s['value']:.2f}")
    lines.append("")

    # The analyst's block, from the same renderer: every flow with its dates,
    # the ones in force counted, the ones still to start and the ones that
    # have ended listed apart. A run-rate and two dateless lists stood here,
    # and they counted and printed a salary starting next month as running.
    # With, for the chat only, what the PACs and the goals take each month.
    lines.extend(_render_flows_in_force(flows, *sizing.commitments(db, flows["on"])))

    lines.append("## Investment positions (latest situation + recorded buys/sells)")
    if not portfolio["rows"]:
        lines.append("- (no investment positions)")
    lines.extend(_render_positions(portfolio, _funds_held(db, portfolio)))
    lines.append("")

    plans = crud.get_accumulation_plans(db)
    txs = crud.get_transactions(db)
    if txs:
        lines.append("## Transaction ledger (most recent first, up to 15)")
        named = {p.id: p.name for p in plans}
        for t in txs[:15]:
            est = " (estimated)" if t.estimated else ""
            # Each figure with its currency: the price is the listing's, the
            # amount the account's, and for a purchase across two currencies
            # the amount is a sum fixed at one day's rate — which the line says.
            rate = f" at the ECB rate of {t.fx_as_of}" if t.fx_as_of else ""
            price = (
                f"@ {t.unit_price:.2f} {t.price_currency} "
                if t.price_currency
                else ""
            )
            lines.append(
                f"- {t.date} {t.kind} {t.quantity:g} x {t.symbol} "
                f"{price}= {t.amount:.2f} {t.currency}{rate}{est}{_settles(t, named)}"
            )
        if len(txs) > 15:
            lines.append(f"- ... and {len(txs) - 15} older entries")
    lines.append("")

    lines.append("## Cash register (live, projected to today)")
    lines.extend(_render_cash(analytics.compute_all_cash_positions(db)))
    lines.append("")

    # The rows below are figures as the reader TYPED them, each in its own
    # currency, while every total above is converted. Printed without a unit,
    # "real 200000.00" over "a house: 250000.00" reads as a contradiction or as
    # two numbers in the same money — so each typed figure says what it is in.
    lines.append("## Real assets (latest valuation each, in the asset's own currency)")
    lines.extend(_render_real_assets(db))
    lines.append("")

    lines.append("## Debts (latest outstanding balance each, in the debt's own currency)")
    lines.extend(_render_debts(db))
    assets_total = summary["financial_total"] + summary["real_total"]
    if summary["liabilities_total"] > 0 and assets_total > 0:
        ratio = summary["liabilities_total"] / assets_total
        lines.append(f"- Debt-to-asset ratio: {ratio * 100:.1f}%")

    if plans:
        lines.append("")
        lines.append("## PACs (recurring contributions)")
        inames = {i.id: i.name for i in crud.get_institutions(db)}
        for p in plans:
            src = inames.get(p.source_institution_id, "external/cash")
            # A plan can split its budget across several funds, so name them
            # all with their share: "which funds, in what proportion" is the
            # part an advisor actually needs.
            tgt = _plan_targets_label(p) or "an investment"
            insts = sorted({inames[t.institution_id] for t in p.targets
                            if t.institution_id in inames})
            at = f" @ {', '.join(insts)}" if insts else ""
            window = ""
            if p.start_date:
                window = f" from {p.start_date}" + (f" to {p.end_date}" if p.end_date else "")
            lines.append(
                f"- {p.name}: {p.amount:.0f} {p.currency} {p.frequency or ''} from {src} "
                f"-> {tgt}{at}{window}. {_plan_budget(p)} {_plan_executed(db, p, txs)}"
            )

    survey = _render_survey(crud.get_survey_responses(db), heading="###")
    if survey:
        lines.append("")
        # The questionnaire holds no goals; the section below does. Headed "profile
        # & goals" until brief AL, and the chat filed a goal as an answer here.
        lines.append("## Personal profile (from the questionnaire)")
        lines.extend(survey)

    goals = crud.get_goals(db)
    lines.append("")
    lines.append("## Goals")
    if not goals:
        # Said rather than left out, under its own heading: a goal asked for
        # in the chat was once filed in the questionnaire instead (brief AL),
        # and goals are written with their own tool (`write_goal`, brief AN).
        lines.append("- (none recorded)")
    else:
        for g in goals:
            entry = f"- {g.name} [{g.type or 'n/a'}]"
            if g.type == "target_amount" and g.target_amount and g.target_date:
                res = planning.compute_required_return(
                    g.current_amount or 0.0,
                    g.monthly_contribution or 0.0,
                    g.target_amount,
                    datetime.date.fromisoformat(g.target_date),
                )
                rr = res["required_annual_return"]
                rr_str = f"{rr * 100:.1f}%/yr" if rr is not None else "unreachable"
                entry += (
                    f": target {g.target_amount:.0f} {g.currency} by {g.target_date} "
                    f"(current {g.current_amount or 0:.0f}, "
                    f"+{g.monthly_contribution or 0:.0f}/mo, ~{res['years']}y) "
                    f"-> requires {rr_str} ({res['assessment']})"
                )
            lines.append(entry)

    return "\n".join(lines)


def build_portfolio_context(db: Session) -> str:
    """The analyst's whole world: the investments and everything the person
    owns beside them, and nothing about the person.

    The investments: positions with cost basis and P/L, the look-through
    composition (countries, sectors, overlap), accumulation plans and a ledger
    digest. Beside them, since brief Z (2026-10-02): the cash on each account
    projected to today, the income and expenses in force today with the ones
    still to start and the ones that have ended listed apart (the chat's own
    block since brief AI), the real assets, the debts, and the wholes
    every share is taken from. Run 1 had only the first half: it called a share
    of the investments "at risk" as if it were a share of everything, and
    asked the reader how much cash they could reach tomorrow.

    The records arrive as the chat reads them, names included; their notes do
    not, as they do not reach the chat either. That was the reader's choice
    (2026-10-02). What keeps the analyst blind to the person is that it gets
    no profile and no goals. The real assets are here for the allocation of
    everything the person owns: an analyst that cannot see a home can propose
    buying property to someone who holds it. Liquidity is computed from the
    cash and the flows alone, and a real asset never counts in it."""
    from app import composition  # local import: keeps module load light

    today = dated.today()
    portfolio = analytics.compute_portfolio(db)  # cached prices only, no network
    lines: list[str] = [
        "# The investments, and everything owned beside them (no personal context)",
        "",
        f"Values are in {portfolio['base_currency']}, the base currency, unless a "
        "line names another.",
        "",
    ]
    lines.append("## Positions")
    if not portfolio["rows"]:
        lines.append("- (none)")
    lines.extend(_render_positions(portfolio, _funds_held(db, portfolio)))
    lines.append("")

    # Every weight below is a share of the INVESTMENTS: the composition is
    # computed over the positions alone (`total_value` in
    # `compute_portfolio_composition`). It said "whole portfolio", which was
    # true while nothing else was in this context and stops being true beside
    # the cash.
    comp = composition.compute_portfolio_composition(db)
    lines.append("## Look-through composition (weights on recorded values)")
    lines.append(
        f"- Coverage: {comp['coverage_pct']:.1f}% of the investments decomposed; "
        "the rest is single stocks / crypto / lumps with no fund data"
    )
    if comp["countries"]:
        lines.append("### Countries (% of the investments)")
        for c in comp["countries"][:15]:
            lines.append(f"- {c['name']}: {c['pct']:.2f}%")
    if comp["sectors"]:
        lines.append("### Sectors (% of the investments)")
        for s in comp["sectors"][:15]:
            lines.append(f"- {s['name']}: {s['pct']:.2f}%")
    if comp["overlap"]:
        lines.append("### Overlapping top holdings (same stock inside 2+ funds)")
        for o in comp["overlap"][:12]:
            lines.append(
                f"- {o['name']}: {o['pct']:.2f}% of the investments via {', '.join(o['funds'])}"
            )
    undec = [r for r in comp["rows"] if not r["decomposed"]]
    if undec:
        lines.append("### Not decomposed")
        for r in undec:
            lines.append(
                f"- {r['asset_name']} ({r['symbol'] or 'no symbol'}): "
                f"{r['weight_pct']:.2f}% of the investments"
            )
    lines.append("")

    plans = crud.get_accumulation_plans(db)
    if plans:
        lines.append("## Recurring plans (PAC)")
        for p in plans:
            executed = crud.get_plan_occurrences_executed(db, p.id)
            lines.append(
                f"- {p.name}: {p.amount:.0f} {p.currency} {p.frequency or ''} -> "
                f"{_plan_targets_label(p) or '?'} "
                f"({len(executed)} executions recorded)"
            )
        lines.append("")

    txs = crud.get_transactions(db)
    if txs:
        # Counted up to today and no further — the bound the positions above
        # were projected at. This digest reads the ledger itself rather than
        # the projection, so it has to say so for itself: it summed every buy
        # on record, and a buy dated ahead reached the analyst as money
        # already invested. An entry dated after today is still a fact the
        # reader stated, so it stays in front of the model, with its date, and
        # outside the count.
        happened = [t for t in txs if t.date <= today]
        scheduled = sorted((t for t in txs if t.date > today), key=lambda t: (t.date, t.id))
        buys = [t for t in happened if t.kind == "buy"]
        sells = [t for t in happened if t.kind == "sell"]
        divs = [t for t in happened if t.kind == "dividend"]
        # Summed across entries in different currencies, so each amount goes
        # through the converter first, at today's rate like the positions above.
        conv = fx.Converter(db)

        def total(entries) -> float:
            return sum(conv.to_base_or_as_stored(t.amount, t.currency) for t in entries)

        lines.append(f"## Ledger digest (amounts converted to {conv.base})")
        lines.append(
            f"- {len(buys)} buys ({total(buys):.2f} invested), "
            f"{len(sells)} sells ({total(sells):.2f} proceeds), "
            f"{len(divs)} dividends ({total(divs):.2f} collected)"
        )
        if scheduled:
            lines.append(
                f"- Dated after today ({today}), so they have NOT happened and are "
                "NOT counted above or in any position:"
            )
            for t in scheduled:
                units = "" if t.kind == "close" else f"{t.quantity:g} x "
                lines.append(
                    f"  - {t.date} {t.kind} {units}{t.symbol or t.asset_name} = "
                    f"{t.amount:.2f} {t.currency}"
                )
        lines.append("")

    summary = analytics.compute_summary(db)
    flows = analytics.compute_flows_in_force(db, today)
    accounts = analytics.compute_all_cash_positions(db)
    # Named where a total leaves them out: a record with no figure yet is not
    # a figure of zero, and the total has to say what it is missing.
    unvalued = [
        ra.name for ra in crud.get_real_assets(db)
        if not crud.get_valuations_for_real_asset(db, ra.id)
    ]
    debts = crud.get_liabilities(db)
    unbalanced = [li.name for li in debts if not crud.get_balances_for_liability(db, li.id)]

    lines.extend(_render_cash_beside(accounts, summary))
    lines.extend(_render_flows_in_force(flows))

    lines.append("## Real assets (latest valuation each, in the asset's own currency)")
    valued = _render_real_assets(db)
    lines.extend(valued or ["- (none)"])
    if valued:
        lines.append(
            "- Each value above is the person's own estimate, typed on the date beside "
            f"it, not a market price. Today is {today}."
        )
        lines.append(
            f"- TOTAL real assets: {summary['real_total']:.2f}"
            + _not_counting(unvalued, "no valuation is entered there, so that value is not known")
        )
    lines.append("")

    lines.append("## Debts (latest outstanding balance each, in the debt's own currency)")
    lines.extend(_render_debts(db))
    if debts:
        lines.append(
            f"- TOTAL debts: {summary['liabilities_total']:.2f}"
            + _not_counting(unbalanced, "no balance is entered there, so what is owed is not known")
        )
    lines.append("")
    lines.extend(_render_wholes(summary, flows, accounts, unvalued, unbalanced))

    return "\n".join(lines)


def _and(names: list[str]) -> str:
    """Join names with an English final conjunction."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _not_counting(names: list[str], why: str) -> str:
    """", not counting X and Y: <why>", or nothing when no record is left out."""
    return f", not counting {_and(names)}: {why}" if names else ""


def _render_cash_beside(positions: list[dict], summary: dict) -> list[str]:
    """The cash register for the analyst: the chat's own lines, then the
    total, with the accounts it leaves out named. An account with no anchor
    has no cash the app knows of, which is not the same as none: the total
    counts nothing for it, and says so.

    And an account below zero is said to be netted in the total already. Brief
    AR's P0 (2026-10-12): the revision and the synthesis called the cash one
    could use "a little lower than the total" because one account stood at
    -250.00, though the total had already taken those 250 off; covering them
    from another account moves cash between the person's accounts and leaves
    the total as it is. Brief AQ's P1 bis saw the same reading in the chat."""
    lines = ["## Cash register (live, projected to today)", *_render_cash(positions)]
    unset = [p["institution_name"] for p in positions if p["anchor_date"] is None]
    total = f"- TOTAL cash on the accounts: {summary['cash_total']:.2f}" + _not_counting(
        unset, "no cash anchor is set there, so that cash is not known"
    )
    below = [
        p["institution_name"]
        for p in positions
        if p["anchor_date"] is not None and p["projected"] < -0.005
    ]
    netted = []
    if below:
        netted.append(
            f"- Netted in the total above: {_and(below)}, below zero. Covering "
            f"{'it' if len(below) == 1 else 'them'} from another of these accounts moves cash "
            "between them and leaves the total, and every share and month of cover worked "
            "out from it, as they are."
        )
    return [*lines, total, *netted, ""]


def _flow_line(flow: dict, *, scheduled: bool) -> str:
    """One flow from `compute_flows_in_force`, as `_flow_text` prints it, with
    the account its cash moves on (brief AN: the chat could not point at the
    right line, nor add one to the right account, without it) and its dates:
    when it started (or that nobody said) for one in force or ended, when it
    starts for one still to come, and when it ends if it does."""
    text = _flow_text(
        flow["name"], flow["classified"], flow["category"],
        flow["amount"], flow["currency"], flow["frequency"],
    ).rstrip()
    account = flow.get("account")
    if account is None:
        where = ", on no account"
    elif flow["side"] == "income":
        where = f", credited to {account}"
    else:
        where = f", paid from {account}"
    start = flow["start_date"]
    if scheduled:
        when = f", from {start}"
    else:
        when = f", since {start}" if start else ", no start date"
    until = f", until {flow['end_date']}" if flow["end_date"] else ""
    return f"{text}{where}{when}{until}"


def _render_commitments(
    flows: dict, committed: tuple[sizing.Commitment, ...], later: tuple[sizing.Commitment, ...]
) -> list[str]:
    """What the reader already puts away every month beside the expenses, and
    what is left after it (`sizing`), for the chat's picture.

    The reader's third test round (2026-10-12): a reply called a sum small
    beside the monthly surplus and forgot that the PAC takes its share of it
    first. The surplus line above is the flows' alone, so this one says what
    the PACs and the goals' recorded contributions take, and what is left once
    they have. Not in the analyst's picture: a goal is the person's, and the
    analyst is not told who the person is."""

    def named(c: sizing.Commitment) -> str:
        what = "PAC" if c.kind == "pac" else "goal"
        whose = ", its recorded contribution" if c.kind == "goal" else ""
        return f'the {what} "{c.name}" {c.monthly:.2f} ({c.recorded}{whose})'

    lines = []
    if committed:
        left = sizing.left_after(flows, committed)
        lines.append(
            "- Already committed each month beside the expenses: "
            + "; ".join(named(c) for c in committed)
            + "."
            + (f" Left each month after them: {left:.2f}" if left is not None else "")
        )
    if later:
        lines.append(
            "- Starting after today, so NOT taken out above: "
            + "; ".join(f"{named(c)} from {c.starts}" for c in later)
        )
    return lines


def _render_flows_in_force(
    flows: dict,
    committed: tuple[sizing.Commitment, ...] = (),
    later: tuple[sizing.Commitment, ...] = (),
) -> list[str]:
    """The income and expenses running today, as `compute_flows_in_force`
    counts them: the totals first, then each flow as the chat used to list
    it, with its dates, then the ones that have not started and the ones that
    have ended, each listed apart and outside every figure.

    One renderer for the chat and the analyst (brief AI). The chat had a
    run-rate of its own and two lists with no dates, so a salary starting
    next month was counted and printed as running, and an ended expense as
    still paid. The chat's picture also says what is committed each month
    beside the expenses, and what is left after it (`_render_commitments`)."""

    def split(total: float, **parts: float) -> str:
        """" (active 1.00, passive 2.00)", with what no part claims named."""
        text = ", ".join(f"{name} {amount:.2f}" for name, amount in parts.items())
        unclassified = total - sum(parts.values())
        if unclassified >= 0.005:
            text += f", not classified {unclassified:.2f}"
        return f" ({text})"

    income = f"- Income: {flows['monthly_income']:.2f} a month" + split(
        flows["monthly_income"], active=flows["active_income"], passive=flows["passive_income"]
    )
    expenses = f"- Expenses: {flows['monthly_expenses']:.2f} a month" + split(
        flows["monthly_expenses"],
        essential=flows["essential_expenses"],
        discretionary=flows["discretionary_expenses"],
    )
    rate = flows["savings_rate"]
    left = f"- Left each month (income minus expenses): {flows['monthly_net']:.2f}" + (
        f", a savings rate of {rate * 100:.1f}%" if rate is not None else ""
    )
    # "None in force" and a sum of zero are different claims: a reader who
    # has recorded no income has not said they earn nothing, and a monthly net
    # computed against nothing would read as a loss they never stated.
    earning, spending = flows["incomes_in_force"], flows["expenses_in_force"]
    missing = [side for side, n in (("income", earning), ("expense", spending)) if not n]
    lines = [
        f"## Income and expenses in force today ({flows['on']}), as a monthly run-rate",
        income if earning else "- Income: none in force today",
        expenses if spending else "- Expenses: none in force today",
        left
        if not missing
        else f"- What is left each month cannot be said: no {' and no '.join(missing)} "
        "is in force today.",
        *_render_commitments(flows, committed, later),
    ]
    undated = flows["undated"]
    if undated == 1:
        lines.append("- 1 of these flows has no start date, so it is counted as in force.")
    elif undated:
        lines.append(
            f"- {undated} of these flows have no start date, so they are counted as in force."
        )
    for side, heading in (("income", "- Income in force today:"),
                          ("expense", "- Expenses in force today:")):
        running = [f for f in flows["in_force"] if f["side"] == side]
        if running:
            lines.append(heading)
            lines.extend(f"  - {_flow_line(f, scheduled=False)}" for f in running)
    if flows["scheduled"]:
        lines.append("- Starting after today, so NOT counted above:")
        lines.extend(
            f"  - {f['side']}: {_flow_line(f, scheduled=True)}" for f in flows["scheduled"]
        )
    if flows["ended"]:
        lines.append("- Ended before today, so NOT counted above:")
        lines.extend(
            f"  - {f['side']}: {_flow_line(f, scheduled=False)}" for f in flows["ended"]
        )
    return [*lines, ""]


def _render_wholes(
    summary: dict,
    flows: dict,
    accounts: list[dict],
    unvalued: list[str],
    unbalanced: list[str],
) -> list[str]:
    """The totals every share is taken from, and the shares within them,
    computed here so the model never has to, and valued as the Dashboard
    values them.

    The share "at risk" in run 1 was true of the investments and false of
    everything the reader holds, and nothing in front of the model said which
    whole it was looking at. So there are three wholes, each named: the
    investments; the investments and the cash (the liquid wealth); and
    everything the person owns, the real assets included. Then the debts and
    the net worth. The months of cover come from the cash alone: a real asset
    is part of what the person owns and never part of what they can spend.

    Cash the app does not know is not cash of zero. An account with no anchor
    is named beside the figure, and with no account known at all no total that
    includes the cash is stated, since each would be a guess printed as a
    measurement. A real asset with no valuation and a debt with no balance are
    named beside theirs the same way, and none recorded at all is said as
    none, not as 0.00. An amount in a currency the app cannot convert is added
    as written, as on the Dashboard, and the currency is named; its amount is
    not, since it bounds no error in either direction
    (`fx.Converter.unconverted_amounts`)."""
    investments = summary["investments_total"]
    cash = summary["cash_total"]
    liquid = summary["financial_total"]
    real = summary["real_total"]
    owned = liquid + real
    unset = [p["institution_name"] for p in accounts if p["anchor_date"] is None]
    lines = [
        "## The wholes every share is taken from (valued as the Dashboard values them)",
        f"- The investments: {investments:.2f} (every position above, at its market "
        "price where one is known, else at its last observed value)",
    ]
    real_line = (
        f"- The real assets: {real:.2f}, each at its latest valuation, the person's "
        "own estimate" + _not_counting(unvalued, "no valuation is entered there")
        if summary["real_assets"]
        else "- The real assets: none recorded"
    )
    debts_line = (
        f"- The debts: {summary['liabilities_total']:.2f}"
        + _not_counting(unbalanced, "no balance is entered there")
        if summary["liabilities"]
        else "- The debts: none recorded"
    )
    inexact = []
    if summary["unconverted"]:
        codes = _and([u["currency"] for u in summary["unconverted"]])
        inexact.append(
            f"- Amounts in {codes} cannot be converted to {summary['base_currency']} and "
            "are added as written, so the totals that hold them are not exact."
        )
    if len(unset) == len(accounts):
        return [
            *lines,
            "- The cash on the accounts is not known: no account has a cash anchor set, "
            "so no total that includes it (the liquid wealth, everything the person "
            "owns, the net worth), no share of one, and no number of months the cash "
            "covers can be stated.",
            real_line,
            debts_line,
            *inexact,
        ]
    lines.append(
        f"- The cash on the accounts: {cash:.2f}"
        + _not_counting(unset, "no cash anchor is set there")
    )
    together = (
        "- The investments and the cash together, the liquid wealth (the Dashboard "
        f"calls it Financial): {liquid:.2f}"
    )
    if liquid > 0:
        together += (
            f". The investments are {investments / liquid * 100:.1f}% of it, "
            f"the cash {cash / liquid * 100:.1f}%."
        )
    if not summary["real_assets"]:
        everything = (
            f"- Everything the person owns: {owned:.2f}, the liquid wealth alone, "
            "since no real asset is recorded."
        )
    else:
        everything = (
            "- Everything the person owns, the liquid wealth and the real assets "
            f"together: {owned:.2f}"
        )
        if owned > 0:
            everything += (
                f". The investments are {investments / owned * 100:.1f}% of it, the cash "
                f"{cash / owned * 100:.1f}%, the real assets {real / owned * 100:.1f}%."
            )
    net_worth = (
        "- Net worth, everything the person owns minus the debts: "
        f"{summary['net_worth']:.2f}"
    )
    essential = flows["essential_expenses"]
    if essential <= 0:
        cover = (
            "- No essential expense is in force today, so how many months the cash "
            "covers cannot be said."
        )
    elif cash > 0:
        cover = (
            f"- The cash covers {cash / essential:.1f} months of the essential expenses "
            f"in force today ({essential:.2f} a month)."
        )
    else:
        cover = (
            f"- The cash on the accounts is {cash:.2f}, so it covers no month of the "
            f"essential expenses in force today ({essential:.2f} a month)."
        )
    cover += " A real asset is never cash and is not counted in it."
    return [*lines, together, real_line, everything, debts_line, net_worth, *inexact, cover]


def build_person_context(db: Session) -> str:
    """Who the user is, with NO portfolio figures: the questionnaire (including
    what they wrote in their own words) and their stated goals. This is the
    confidant's whole world — the information asymmetry against the analyst is
    the point of the chain, so nothing quantitative about their holdings, cash
    or net worth belongs here.

    Today's date comes first, so the day in front of each answer can be read
    as recent or old; the chat's context opens with its own."""
    lines: list[str] = [
        "# Who this person is (their own words and answers)",
        "",
        f"Today is {dated.today()}.",
        "",
    ]

    survey = _render_survey(crud.get_survey_responses(db))
    if not survey:
        lines.append("- (the questionnaire is empty)")
    lines.extend(survey)

    goals = crud.get_goals(db)
    if goals:
        lines.append("## Their stated goals")
        for g in goals:
            entry = f"- {g.name} [{g.type or 'n/a'}]"
            if g.target_amount and g.target_date:
                entry += f": {g.target_amount:.0f} {g.currency} by {g.target_date}"
            lines.append(entry)

    return "\n".join(lines)


def resolve_model(model: str | None = None) -> str:
    """The Copilot model a call uses: caller, configured default, then built-in."""
    return model or os.getenv("COPILOT_MODEL") or DEFAULT_MODEL


def call_llm(system_prompt: str, user_content: str, model: str | None = None) -> dict:
    """Ask one GitHub-hosted Copilot model for a complete analysis step."""
    selected = resolve_model(model)
    try:
        result = copilot_provider.complete(system_prompt, user_content, selected)
    except copilot_provider.CopilotError as exc:
        raise AdvisorError(str(exc)) from exc
    return {
        "analysis": result.content,
        "model": result.model,
        # Copilot subscription usage is not a dollar price. Keep the existing
        # nullable cost contract honest rather than relabeling quota as USD.
        "cost": None,
    }


# --- A step of the analysis that looks things up -----------------------------


@dataclass(frozen=True)
class Round:
    """One Copilot request that may return text, terminal tool calls, or both."""

    content: str
    calls: tuple[ToolCall, ...]
    usage: Usage
    model: str


def call_round(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    tools: list[dict] | None = None,
) -> Round:
    """Ask one Copilot round, capturing terminal tool requests for the caller."""
    selected = resolve_model(model)
    content: list[str] = []
    calls: list[ToolCall] = []
    usage = Usage(None, None, None)
    resolved = selected
    try:
        for kind, piece in copilot_provider.stream(
            system_prompt, messages, selected, tools
        ):
            if kind == "text":
                content.append(piece)
            elif kind == "tool_call":
                calls.append(ToolCall(piece.id, piece.name, piece.arguments))
            elif kind == "usage":
                usage = Usage(piece.input_tokens, piece.cached_tokens, None)
            elif kind == "model":
                resolved = piece
    except copilot_provider.CopilotError as exc:
        raise AdvisorError(str(exc)) from exc
    return Round(
        content="".join(content),
        calls=tuple(calls),
        usage=usage,
        model=resolved,
    )




def stream_llm(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    tools: list[dict] | None = None,
) -> Generator[tuple[str, str | ToolCall | Usage], None, None]:
    """Stream one GitHub Copilot SDK turn in Aurelio's existing event shape."""
    selected = resolve_model(model)
    try:
        with closing(copilot_provider.stream(
            system_prompt, messages, selected, tools
        )) as response:
            for kind, piece in response:
                if kind == "tool_call":
                    yield kind, ToolCall(piece.id, piece.name, piece.arguments)
                elif kind == "usage":
                    yield kind, Usage(piece.input_tokens, piece.cached_tokens, None)
                else:
                    yield kind, piece
    except copilot_provider.CopilotError as exc:
        raise AdvisorError(str(exc)) from exc
