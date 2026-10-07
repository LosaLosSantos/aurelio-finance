"""AI advisor: assemble the user's financial context and ask an LLM for an
educational analysis.

Provider: OpenRouter (https://openrouter.ai), an OpenAI-compatible gateway, so
we use the `openai` SDK pointed at OpenRouter's base URL.

Configuration (from environment / backend/.env):
- OPENROUTER_API_KEY : required to call the model.
- OPENROUTER_MODEL   : model slug from https://openrouter.ai/models
                       (default: a Claude Sonnet).

PRIVACY NOTE: this sends the user's financial data to a third-party cloud LLM.

The `openai` import is done lazily (see `sdk()`), so the rest of the app keeps
working even if the package is not installed yet.

What this module does NOT do any more is run an analysis of its own. It builds
the three contexts and owns the two ways to call a model; the analysis is the
chain (`app/chain.py`), proposed and read from the chat.
"""

from __future__ import annotations

import datetime
import os
import re
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import analytics, catalogue, crud, dated, fx, planning, schemas

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-opus-5.5"

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


class Unfinished(AdvisorError):
    """The provider ended an answer on anything but a normal stop.

    An answer that did not finish is not an answer, and both ways of calling a
    model raise this rather than hand one on. The first real analysis, on
    2026-10-02, built five steps on an analyst's text that stopped at "The top
    four": `call_llm` refused only an EMPTY answer, so a cut one went through
    as a whole one, and the chat stored its own cut answers as finished.

    `reason` is OpenRouter's normalised finish reason (None when nothing said
    the answer had finished), `native` the provider's own word for it, and
    `cost` what the provider reported the call cost, or None if it did not
    say: a cut answer is billed like any other (measured on 2026-10-02), so a
    caller that keeps an account of the spend has to be able to read it."""

    def __init__(
        self, sentence: str, *, reason: str | None, native: str | None, cost: float | None
    ):
        super().__init__(sentence)
        self.reason = reason
        self.native = native
        self.cost = cost


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
    """What the provider says one call read and cost, from the last chunk of
    its stream. Each figure is None when it was not said: a zero is a
    measurement, and "it did not say" is not one.

    `prompt_tokens` counts every token the call read, whether it came from the
    cache, was written to it, or neither (on 2026-10-05, on each of six calls
    to Opus 5.5, the three parts summed to it). `cached_tokens` is how many of
    them came from the cache, and `cost` what OpenRouter says the whole call
    cost, in USD. With a cache the first figure stops saying what a call cost
    on its own: a token read from the cache was billed at a twentieth of the
    input price that day, and a token written to it at 1.25 times.

    `searches` is how many web searches OpenRouter ran inside the call, None
    for a call that said nothing about any (every call not offered the web).
    It arrives in `server_tool_use_details`, and not in the `server_tool_use`
    OpenRouter's documentation names: measured on 2026-10-06 in a paid probe,
    where `cost` also proved to be what the key was charged, the search's fee
    included whenever one was charged."""

    prompt_tokens: int | None
    cached_tokens: int | None
    cost: float | None
    searches: int | None = None


@dataclass(frozen=True)
class WebPage:
    """One page a web search found, as OpenRouter hands it to the caller: a
    `url_citation` annotation on the stream, its address, its title and an
    excerpt of what it says.

    With OpenRouter's search on Exa these are the search's RESULTS, five a
    search, and not the sources a model chose to cite: they arrive when the
    search has run, before the words written from them, or after a round that
    ended on the app's own tools and so never read them (the probe of
    2026-10-06, calls S2 and B5)."""

    url: str
    title: str
    excerpt: str




def _position_caveats(r: dict) -> list[str]:
    """The qualifications the screen shows and the prose did not.

    A row whose cost was never recorded still HAS an `avg_cost` — it is the
    price the snapshot happened to be taken at — and printing it bare invites
    the model to reason about a profit that is really a movement. The table
    says "cost unknown" and "since situation" for exactly this reason; the
    advisor was the only reader never told, which is backwards: it is the one
    consumer that actually reasons about the figures."""
    notes: list[str] = []
    if r.get("avg_cost") is not None and not r.get("cost_known"):
        notes.append(
            "COST UNKNOWN — no purchase on record, so the average cost above is "
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
            parts.append(f"avg cost {r['avg_cost']:.2f}")
        if r["live_price"] is not None:
            parts.append(
                f"market {r['market_value']:.2f} "
                f"(price {r['live_price']:.2f} as of {r['as_of']}, "
                f"P/L {r['delta']:+.2f})"
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
        if r["realized_pl"]:
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
            f"(market prices as of {portfolio['prices_as_of']})"
        )
        if carried:
            line += f", of which {carried:.2f} is carried from situations, not priced"
        lines.append(line)
    if portfolio["total_realized"]:
        lines.append(f"- TOTAL realized P/L: {portfolio['total_realized']:+.2f}")
    if portfolio["total_dividends"]:
        line = f"- TOTAL dividends collected: {portfolio['total_dividends']:.2f}"
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
    has_something = bool(
        est["realized_gain"] or est["dividends_gross_estimated"]
    )
    if not est["configured"]:
        # Silence would be read as "no tax applies", and a zero would be worse.
        # "Nobody answered" and "there is nothing there" are different claims —
        # the same distinction `c906ccb` was a whole commit about — so the
        # absence is stated, with what it is an absence OF.
        if has_something:
            return [
                "- TAX: no rate set, so no estimate is made. The realized result "
                f"is {est['realized_gain']:+.2f} and "
                f"{est['dividends_gross_estimated']:.2f} of dividends are still "
                "the market's gross figure. The user sets a rate in Profile; do "
                "not estimate a tax yourself."
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
        lines.append(f"  - estimated total: {est['total']:.2f}")
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

    lines: list[str] = [
        "# User financial situation",
        "",
        # The unit of every total below, from the computation that made them. A
        # model reading "Total: 455.69" cannot see a currency the screen shows
        # beside it; it has to be written down.
        f"Totals are in {summary['base_currency']}, the base currency. Figures a "
        "record states itself are given with their own currency.",
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
    lines.extend(_render_flows_in_force(flows))

    lines.append("## Investment positions (latest situation + recorded buys/sells)")
    portfolio = analytics.compute_portfolio(db)  # cached prices only, no network
    if not portfolio["rows"]:
        lines.append("- (no investment positions)")
    lines.extend(_render_positions(portfolio, _funds_held(db, portfolio)))
    lines.append("")

    txs = crud.get_transactions(db)
    if txs:
        lines.append("## Transaction ledger (most recent first, up to 15)")
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
                f"{price}= {t.amount:.2f} {t.currency}{rate}{est}"
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

    plans = crud.get_accumulation_plans(db)
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
            executed = crud.get_plan_occurrences_executed(db, p.id)
            status = (
                f" — {len(executed)} executions recorded (last {max(executed)})"
                if executed
                else " — no executions recorded yet"
            )
            lines.append(
                f"- {p.name}: {p.amount:.0f} {p.currency} {p.frequency or ''} from {src} "
                f"-> {tgt}{at}{window}{status}"
            )

    survey = _render_survey(crud.get_survey_responses(db), heading="###")
    if survey:
        lines.append("")
        lines.append("## Personal profile & goals (from the questionnaire)")
        lines.extend(survey)

    goals = crud.get_goals(db)
    if goals:
        lines.append("")
        lines.append("## Goals")
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


def _not_counting(names: list[str], why: str) -> str:
    """", not counting X and Y: <why>", or nothing when no record is left out."""
    return f", not counting {_and(names)}: {why}" if names else ""


def _render_cash_beside(positions: list[dict], summary: dict) -> list[str]:
    """The cash register for the analyst: the chat's own lines, then the
    total, with the accounts it leaves out named. An account with no anchor
    has no cash the app knows of, which is not the same as none: the total
    counts nothing for it, and says so."""
    lines = ["## Cash register (live, projected to today)", *_render_cash(positions)]
    unset = [p["institution_name"] for p in positions if p["anchor_date"] is None]
    total = f"- TOTAL cash on the accounts: {summary['cash_total']:.2f}" + _not_counting(
        unset, "no cash anchor is set there, so that cash is not known"
    )
    return [*lines, total, ""]


def _flow_line(flow: dict, *, scheduled: bool) -> str:
    """One flow from `compute_flows_in_force`, as `_flow_text` prints it, with
    its dates: when it started (or that nobody said) for one in force or
    ended, when it starts for one still to come, and when it ends if it
    does."""
    text = _flow_text(
        flow["name"], flow["classified"], flow["category"],
        flow["amount"], flow["currency"], flow["frequency"],
    ).rstrip()
    start = flow["start_date"]
    if scheduled:
        when = f", from {start}"
    else:
        when = f", since {start}" if start else ", no start date"
    until = f", until {flow['end_date']}" if flow["end_date"] else ""
    return f"{text}{when}{until}"


def _render_flows_in_force(flows: dict) -> list[str]:
    """The income and expenses running today, as `compute_flows_in_force`
    counts them: the totals first, then each flow as the chat used to list
    it, with its dates, then the ones that have not started and the ones that
    have ended, each listed apart and outside every figure.

    One renderer for the chat and the analyst (brief AI). The chat had a
    run-rate of its own and two lists with no dates, so a salary starting
    next month was counted and printed as running, and an ended expense as
    still paid."""

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


def sdk():
    """The `openai` package, or an AdvisorError saying how to get it.

    Imported on use and not at module load, so the rest of the app keeps
    working without it. Shared with `tools.declarations`, which renders the
    tool schemas through the same SDK and would otherwise carry a second copy
    of this sentence — and, being the thing a turn reaches first, would be the
    copy the reader actually saw."""
    try:
        import openai
    except ImportError as exc:
        raise AdvisorError(
            "The 'openai' package is not installed. Run: uv add openai"
        ) from exc
    return openai


def _client():
    """The configured OpenRouter client, or an AdvisorError saying what is
    missing. Shared by the one-shot call and the streaming one so the two
    cannot disagree about what "configured" means."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise AdvisorError(
            "OPENROUTER_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )

    return sdk().OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        default_headers={"X-Title": "Aurelio"},
    )


def resolve_model(model: str | None = None) -> str:
    """The slug a call will actually use: the caller's choice, else the app
    default from the environment, else the built-in one."""
    return model or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL


# --- A model OpenRouter no longer serves -----------------------------------------

# Every variable that can name a model, in the order the chat reads them; the
# two roles' come after, since only the analysis reads those.
MODEL_VARIABLES = (
    "OPENROUTER_CHAT_MODEL",
    "OPENROUTER_MODEL",
    "OPENROUTER_ANALYST_MODEL",
    "OPENROUTER_CONFIDANT_MODEL",
)

# OpenRouter's public list of the models it serves. Asked only after it has
# refused a call, with no key and nothing of the reader's in the request.
MODEL_LIST_URL = "https://openrouter.ai/api/v1/models"


class ModelGone(AdvisorError):
    """OpenRouter refused a model that its public list no longer has."""


def _fetch_model_list() -> set[str]:
    """The ids OpenRouter lists today. Network, so the tests fake it."""
    import httpx

    response = httpx.get(MODEL_LIST_URL, timeout=10)
    response.raise_for_status()
    return {entry["id"] for entry in response.json()["data"]}


def _dated(model: str, listed: set[str]) -> list[str]:
    """The names OpenRouter lists as a dated version of `model`: the name, a
    hyphen and digits, which is how it dates one (qwen/qwen3.8-max-0902).
    Anything else after the hyphen is a different model, not a date:
    qwen/qwen3.8-max-prime is one."""
    dated = re.compile(re.escape(model) + r"-\d+")
    return sorted(slug for slug in listed if dated.fullmatch(slug))


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _where_set(model: str) -> str:
    """Where the reader changes `model`: every variable in backend/.env that
    names it, else the app's own default, else the chat's menu, which is the
    only other way a name reaches a call."""
    named = [var for var in MODEL_VARIABLES if os.getenv(var) == model]
    if named:
        return f"It is set by {_and(named)} in backend/.env."
    if model == DEFAULT_MODEL:
        return "It is the app's built-in default (DEFAULT_MODEL in backend/app/advisor.py)."
    return "It was picked in the chat's model menu."


def _refused(error: Exception, model: str) -> AdvisorError:
    """What the reader is told when a call to OpenRouter fails.

    A refusal (400 or 404) of a model that OpenRouter's public list no longer
    has is a model that is gone, and the sentence says which, where it is set,
    and what dated versions of it are still listed. Neither sign alone is
    proof: the documentation gives no wording for this case, and the reader's
    short name had left the list while still answering (2026-09-24). Any
    other refusal is OpenRouter's own status and message, in words, where the
    SDK would print a dictionary. A failure that is not a refusal (no network,
    a timeout) keeps the SDK's words.
    """
    openai = sdk()
    if not isinstance(error, openai.APIStatusError):
        return AdvisorError(f"LLM call failed: {error}")
    body = error.body if isinstance(error.body, dict) else {}
    said = str(body.get("message") or error.message).strip().rstrip(".")
    refused = f"OpenRouter refused the call to {model} with {error.status_code}: {said}."
    if error.status_code not in (400, 404):
        return AdvisorError(refused)
    try:
        listed = _fetch_model_list()
    except Exception as unreachable:
        return AdvisorError(
            f"{refused} Whether it still serves {model} could not be checked: its "
            f"public list of models did not answer ({unreachable})."
        )
    if model in listed:
        return AdvisorError(refused)
    gone = (
        f"The model {model} is no longer served by OpenRouter: it refused the call "
        f"({said}), and its public list of models no longer has it. {_where_set(model)}"
    )
    dated = _dated(model, listed)
    if dated:
        versions = "a dated version" if len(dated) == 1 else "dated versions"
        gone += f" OpenRouter still lists {_and(dated)}, {versions} of it."
    return ModelGone(gone)


# How an answer ended, in OpenRouter's normalised words, said for the reader.
# Its documentation names five: stop, length, tool_calls, content_filter,
# error. Only "stop" is an answer that finished, and "tool_calls" too in the
# chat, whose rounds end by asking for tools.
_WHY = {
    "length": "it reached its length limit",
    "content_filter": "a content filter stopped it",
    "error": "the provider failed while it was writing",
    "tool_calls": "it asked for a tool, and this call offers none",
}


def _unfinished(
    reason: str | None, native: str | None, cost: float | None, *, wrote: bool
) -> Unfinished:
    """The sentence for an answer that ended on anything but a normal stop:
    why, in words, then what OpenRouter and the provider reported, verbatim.

    `wrote` tells "before finishing its answer" from "before writing" it.
    Measured on 2026-10-02: a model that spends its whole limit reasoning ends
    on `length` with no text at all, and was refused as "an empty response",
    which said nothing about why."""
    if reason is None:
        why = "the provider never said it had finished"
    else:
        why = _WHY.get(reason, f'it stopped for a reason OpenRouter calls "{reason}"')
    reported = ""
    if reason is not None:
        provider = f", the provider {native}" if native and native != reason else ""
        reported = f" (OpenRouter reported {reason}{provider})"
    before = "finishing" if wrote else "writing"
    return Unfinished(
        f"The model stopped before {before} its answer: {why}{reported}.",
        reason=reason,
        native=native,
        cost=cost,
    )


def _failed_partway(failure, cost: float | None) -> Unfinished:
    """OpenRouter's documented answer to a provider failing partway through a
    plain request: a 200 whose body holds an `error` object and no text. It was
    refused already, as "an empty response", with the provider's words
    dropped."""
    said = failure.get("message") if isinstance(failure, dict) else getattr(failure, "message", None)
    detail = f": {str(said).strip().rstrip('.')}" if said else ""
    return Unfinished(
        "The provider failed partway through the answer, and OpenRouter sent its "
        f"error instead of the text{detail}.",
        reason="error",
        native=None,
        cost=cost,
    )


def call_llm(system_prompt: str, user_content: str, model: str | None = None) -> dict:
    """Shared OpenRouter call. `model` overrides the configured default, so a
    chain can give each role its own model. Returns {"analysis", "model",
    "cost"}; raises AdvisorError, and `Unfinished` for an answer that did not
    end on a normal stop.

    How the answer ended is read before what it says. A token cap ends it on
    `length` (measured on 2026-10-02, on Anthropic and on Alibaba), and the
    text that comes back with it reads like any other: the analysis of run 1
    stopped at "The top four" and nothing downstream could tell.

    It asks the provider for no cache, unlike the chat (`stream_llm`), and on
    purpose. The chain's steps each have a system prompt of their own, and the
    system prompt comes first in what a provider caches, so no step can read
    what another wrote: a marker would have every step pay for its input 1.25
    times over, for an entry nothing reads. The one prefix two steps share is
    the second revision repeating the first's figures, which pays only on the
    runs that get that far."""
    client = _client()
    model = resolve_model(model)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as exc:  # network / auth / model errors -> a sentence (_refused)
        raise _refused(exc, model) from exc

    failure = getattr(completion, "error", None)
    if failure:
        raise _failed_partway(failure, _cost(completion))
    choice = completion.choices[0] if completion.choices else None
    content = choice.message.content if choice is not None else None
    ended = getattr(choice, "finish_reason", None)
    if choice is not None and ended != "stop":
        raise _unfinished(
            ended,
            getattr(choice, "native_finish_reason", None),
            _cost(completion),
            wrote=bool(content),
        )
    if not content:
        raise AdvisorError("The model returned an empty response.")
    return {"analysis": content, "model": model, "cost": _cost(completion)}


def _cost(completion) -> float | None:
    """What the provider says this call cost, in USD, or None if it did not say.

    OpenRouter puts it on `usage` as an extra field the OpenAI SDK does not
    declare — verified live on 2026-09-03: `CompletionUsage(..., cost=0.00225,
    ...)` for one small call. Read with getattr for exactly that reason, and
    kept as None rather than 0.0 when it is absent: a zero is a price, and the
    card that quotes the last run's spend must be able to say nothing instead
    of saying free.
    """
    usage = getattr(completion, "usage", None)
    cost = getattr(usage, "cost", None)
    return float(cost) if isinstance(cost, (int, float)) else None


def _usage(reported) -> Usage:
    """The figures on a stream's usage chunk. `cached_tokens` sits one level
    down, in `prompt_tokens_details`, and `cost` is OpenRouter's own field,
    which the SDK keeps as an extra attribute (see `_cost`). So is the count
    of web searches, which arrives as a plain dict."""
    prompt = getattr(reported, "prompt_tokens", None)
    details = getattr(reported, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None)
    cost = getattr(reported, "cost", None)
    used = getattr(reported, "server_tool_use_details", None)
    searches = (
        used.get("web_search_requests")
        if isinstance(used, dict)
        else getattr(used, "web_search_requests", None)
    )
    return Usage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        cached_tokens=cached if isinstance(cached, int) else None,
        cost=float(cost) if isinstance(cost, (int, float)) else None,
        searches=searches if isinstance(searches, int) else None,
    )


# How long a page's title may be, as kept and shown. A title is a label for a
# link; the probe's longest was 55 characters.
_TITLE_CHARS = 200


def _page(annotation) -> WebPage | None:
    """The page one annotation names, or None when it is not a `url_citation`
    or its address is not http or https.

    What is kept here becomes a link the reader can press, so the scheme is
    checked where it enters: an address a page or a model made up as
    `javascript:` is not a page, and neither is anything else a browser would
    run or hand to another program. A page with no title is named by its host,
    which is what its link would show anyway."""
    found = annotation if isinstance(annotation, dict) else annotation.model_dump()
    if found.get("type") != "url_citation":
        return None
    cited = found.get("url_citation") or {}
    url = str(cited.get("url") or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    title = " ".join(str(cited.get("title") or "").split())[:_TITLE_CHARS]
    return WebPage(
        url=url,
        title=title or parts.netloc,
        excerpt=str(cited.get("content") or "").strip(),
    )


# --- The provider's cache --------------------------------------------------------

# Anthropic's models cache a prompt only when the request asks for it, and only
# at the points the request marks. The other families in the chat's menu are
# left alone, and their requests are what they were: on OpenRouter's page (read
# 2026-10-05) OpenAI's GPT-5.6 and later already cache unasked, and charge the
# write; Moonshot caches unasked; Alibaba caches only at markers, for the models
# it names, and not on dated snapshots. What a marker would do to any of them
# has not been measured, and a model the reader can pick is not where to find
# out.
_EPHEMERAL = {"type": "ephemeral"}

# Anthropic's limit, four markers in a request, with a fifth refused with a 400.
# The system prompt takes one and the end of the request another, so the caller
# names two messages at most.
_MARKED_MESSAGES = 2


def caches_on_request(model: str) -> bool:
    """Whether `model` caches a prompt only when the request asks: Anthropic's,
    by its slug, an OpenRouter `~` alias included."""
    return model.removeprefix("~").startswith("anthropic/")


def _kept(message: dict) -> dict:
    """`message` with a cache marker at its end: the same words, as the
    one-part list a marker has to sit on. A message with no words of its own
    (an assistant turn that only asked for tools) is left as it is."""
    content = message.get("content")
    if not isinstance(content, str) or not content:
        return message
    return {**message, "content": [{"type": "text", "text": content, "cache_control": _EPHEMERAL}]}


def stream_llm(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    tools: list[dict] | None = None,
    cache_at: tuple[int, ...] | None = None,
) -> Iterator[tuple[str, str | ToolCall | Usage | WebPage]]:
    """The streaming sibling of `call_llm`: yields the answer as it is written,
    one `(kind, piece)` pair at a time, for a whole conversation rather than a
    single question. Three kinds:

      "thought"    the model's reasoning — models that think stream it first,
                   for seconds, on a separate field. `piece` is text.
      "text"       the answer itself. `piece` is text.
      "tool_call"  a tool the model wants run before it can answer. `piece` is
                   a completed `ToolCall`, not a string.
      "usage"      what the provider says this call read and cost: a `Usage`,
                   at most once, at the end. Asked for with `stream_options`,
                   because a stream reports usage only when the request says
                   it should: the final chunk then carries no choice and only
                   that. The tokens are what `_cost` reads beside on a
                   non-streamed completion, and they are the reason `chat.py`
                   no longer has to believe a docstring about what a turn
                   costs.
      "page"       a page a web search found: a `WebPage`, one per
                   `url_citation` annotation, in the order they arrive. Only
                   a call offered OpenRouter's web search gets any. The
                   searches themselves never arrive as tool calls: OpenRouter
                   runs them and leaves a gap in the calls' numbering where
                   they were (measured 2026-10-06), which the assembly by
                   index below already takes in its stride.

    `cache_at` asks the provider to keep what this call read, so that the next
    call that begins the same way pays a fraction for it. None asks for
    nothing. A tuple asks, for a model that caches only on request
    (`caches_on_request`), at three kinds of point: the system prompt, which
    keeps the tool declarations with it since they come first in what is
    cached; each message the tuple names, by its index in `messages`; and the
    end of the request, through the top-level marker, where the provider
    places it on the last block. For every other model the request is the one
    it would be without the argument. Measured on 2026-10-05 through OpenRouter
    on Opus 5.5, in a paid probe: a round that adds a tool
    exchange read all 12,035 tokens the round before it had written, and a
    read was billed at a twentieth of the input price.

    Raises AdvisorError — before the first piece if nothing is configured or
    the call is refused, in the middle if the stream breaks. A stream that
    thinks but never answers is an empty response; a stream that asks for a
    tool is NOT, which is why `produced` counts tool calls too. Getting that
    backwards would turn every tool-using turn into "the model returned an
    empty response", since a turn that only calls tools writes no content at
    all.

    And `Unfinished` at the END, after the words have gone out, when the
    stream ended on anything but `stop`, or `tool_calls` for a round that asks
    for tools: a token cap ends it on `length` (measured on 2026-10-02), and
    a stream that closes without saying how it ended has not said it finished.
    The words are not taken back; they are what the reader saw. What changes
    is that the turn cannot end as `done`. The tool calls of such a round are
    not handed on: their arguments may have stopped mid-JSON, and nothing
    finished asking for them.

    Why the tool calls come out at the END, after the last chunk. They arrive
    in fragments — the name once, the JSON arguments a few characters at a
    time — and the only thing tying the fragments together is `index`, an int
    on each fragment. Nothing in the protocol marks a call as finished; you
    only learn it was, from the stream stopping. So the fragments are
    accumulated by index and each call is yielded when nothing is left that
    could still belong to it. Yielding earlier would mean yielding an argument
    string that does not parse yet.

    `tools` is passed straight through and omitted entirely when it is empty:
    "no tools" and "an empty list of tools" are not the same request, and only
    the first is what a call with nothing to offer means.

    `call_llm` stays as it is. The chain stores whole steps and has no reason to
    change; only a chat needs the words as they come.

    Closing this generator early closes the upstream connection, which is how
    a reader who leaves mid-answer stops the model: OpenRouter bills the tokens
    it generates, and it generates until the socket goes away. Starlette closes
    the generator when the browser disconnects; the `with` below is what turns
    that into a closed socket rather than a thread still reading an answer
    nobody will see."""
    client = _client()
    model = resolve_model(model)
    system: str | list[dict] = system_prompt
    asked = messages
    cache: dict = {}
    if cache_at is not None and caches_on_request(model):
        if len(cache_at) > _MARKED_MESSAGES:
            raise ValueError(
                f"{len(cache_at)} messages named for the cache; Anthropic refuses a "
                f"request with more than four markers, so {_MARKED_MESSAGES} at most"
            )
        system = [{"type": "text", "text": system_prompt, "cache_control": _EPHEMERAL}]
        asked = [_kept(m) if i in cache_at else m for i, m in enumerate(messages)]
        # The top level is not a parameter the SDK knows, so it travels in
        # extra_body, which the SDK merges into the request as it is.
        cache = {"extra_body": {"cache_control": _EPHEMERAL}}
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, *asked],
            stream=True,
            stream_options={"include_usage": True},
            **({"tools": tools} if tools else {}),
            **cache,
        )
    except Exception as exc:
        raise _refused(exc, model) from exc

    produced = False
    # index -> the call being assembled. A dict rather than a list: `index` is
    # the protocol's own numbering and nothing promises it starts at zero or
    # arrives without gaps.
    building: dict[int, dict] = {}
    received: Usage | None = None
    # How the answer ended, which only its last chunks say: on OpenRouter the
    # last two both carried it (measured on 2026-10-02). None until one does.
    ended: str | None = None
    native: str | None = None
    try:
        with stream:
            for chunk in stream:
                # The usage chunk is the one with no choices in it, so this is
                # read BEFORE the line that skips those — which is where it
                # would otherwise be dropped, silently and for good.
                usage = getattr(chunk, "usage", None)
                if usage:
                    received = _usage(usage)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if getattr(choice, "finish_reason", None):
                    ended = choice.finish_reason
                    native = getattr(choice, "native_finish_reason", None)
                delta = choice.delta
                # OpenRouter puts reasoning on its own delta field, which the
                # SDK keeps as an extra attribute. Measured on qwen3.8-max: six
                # seconds of these before the first word of the answer.
                thought = getattr(delta, "reasoning", None)
                if thought:
                    yield ("thought", thought)
                if delta.content:
                    produced = True
                    yield ("text", delta.content)
                # Another extra field, one annotation a chunk in the probe.
                # Not `produced`: a page is not an answer, and a call that
                # found pages and then said nothing still said nothing.
                for annotation in getattr(delta, "annotations", None) or ():
                    page = _page(annotation)
                    if page is not None:
                        yield ("page", page)
                for fragment in delta.tool_calls or ():
                    call = building.setdefault(
                        fragment.index, {"id": "", "name": "", "arguments": ""}
                    )
                    # Each field is written only where the fragment carries
                    # one. The id and the name arrive once, on a call's first
                    # fragment, and every fragment after it holds None there —
                    # copying those across would erase what the first said.
                    if fragment.id:
                        call["id"] = fragment.id
                    if fragment.function:
                        if fragment.function.name:
                            call["name"] = fragment.function.name
                        if fragment.function.arguments:
                            call["arguments"] += fragment.function.arguments
    except Exception as exc:
        # GeneratorExit is a BaseException, so a reader leaving is not caught
        # here: it passes through, the `with` closes the stream, and no error
        # is invented for something that was a choice.
        raise AdvisorError(f"LLM stream failed: {exc}") from exc
    if ended not in ("stop", "tool_calls"):
        # The usage first, for the reason the empty case below gives: a turn
        # that was cut still cost what it was sent.
        if received is not None:
            yield ("usage", received)
        raise _unfinished(ended, native, None, wrote=produced)
    for index in sorted(building):
        produced = True
        yield ("tool_call", ToolCall(**building[index]))
    # Before the raise below, not after: a turn that ended empty still cost
    # what it was sent, and the record of what a turn costs must not be the
    # record of the turns that went well.
    if received is not None:
        yield ("usage", received)
    if not produced:
        raise AdvisorError("The model returned an empty response.")
