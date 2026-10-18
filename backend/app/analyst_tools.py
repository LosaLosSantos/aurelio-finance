"""What the analysis may check that its context does not hold, and nothing that
sees the person.

Brief AR (2026-10-12). The chain's analyst judged the records with no tool, so
what its context did not hold it could not check. In the brief's P0 (paid, a
test copy) it called a fund's 0.20% a year "efficient" against nothing, where
the catalogue held funds on the same index from 0.05%; it guessed what a bond
fund's overlap was; it stated a coin's history from memory; it left open what
two of the positions were. These are its tools, and the revision's, which is
the analyst answering for its figures. Read-only, every one, and none of them
reads the profile, the goals or the questionnaire:

- `get_look_through`, the chat's own (`tools._look_through`): the positions
  seen through the funds, every axis, and what could not be looked inside.
- `catalogue_same_index`: what the registry holds on a fund's index
  (`catalogue.same_index`), as counts and costs.
- `instrument_facts`: a fund's line in the registry, or what Yahoo lists under
  a symbol and its latest close.
- `weigh_change`: what a purchase, a sale or both would do to the look-through
  (`composition.weigh_change`).
- `search_web`, for Claude and GPT models: the web search the chat has, which the
  step runs itself as a separate subscription-backed request
  (`chain`).

Not offered, on purpose: `size_purchase`, whose room reads the profile and the
goals (`sizing`); `read_analysis`, a past verdict written to the person;
`search_catalogue`, which names funds the person does not hold; every write.
A call to any other name is answered as not offered and runs nothing. The
confidant and the synthesis get no tool: each of these shows a figure, and the
confidant's side of the chain is the person's own words.

A security the records do not hold is never named here. The catalogue's
answer counts and prices the other funds on an index and names none, and an
instrument not held is described without its name: the analysis says what the
catalogue holds, and the chat names one, on a card, when it is asked (the
reader's choice, 2026-10-12). What the model remembers on its own is its
prompt's to rule; no tool hands it a name.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app import advisor, catalogue, composition, dated, fx, models, prices, schemas, tools

logger = logging.getLogger(__name__)


def _held_keys(db: Session) -> set[str]:
    """Every symbol and ISIN a position the records hold is held under, upper
    case: what the tools here may name."""
    keys: set[str] = set()
    for p in composition._held(db, fx.Converter(db)):
        for key in (p.symbol, p.isin):
            if key and key.strip():
                keys.add(key.strip().upper())
    return keys


def _registry_source(rows: int, fetched_at: str | None) -> str:
    """Where a registry fact comes from, in the words the analyst's context
    uses for it."""
    when = ""
    if fetched_at:
        try:
            when = f", as the app downloaded it on {dated.local_day(fetched_at)}"
        except ValueError:
            pass
    return f"justETF's list of funds for private investors in Europe, {rows} funds{when}"


def _registry_row(db: Session, isin: str) -> models.Instrument:
    """The registry's line for an ISIN, or a refusal saying which kind it is:
    a registry not downloaded yet says nothing about the fund."""
    key = (isin or "").strip().upper()
    row = db.get(models.Instrument, key)
    if row is not None:
        return row
    state = catalogue.status(db)
    if not state["rows"]:
        raise LookupError(
            "The fund catalogue has not been downloaded yet, so it can say nothing "
            f"about {key or 'that ISIN'}: that is not a statement about the fund."
        )
    raise LookupError(
        f"The fund catalogue ({state['rows']} funds) does not hold {key or 'that ISIN'}: "
        "it lists the funds sold to private investors in Europe, and a fund outside it "
        "is not described here."
    )


# --- What the catalogue holds on a fund's index -------------------------------------


class SameIndexArgs(BaseModel):
    """What `catalogue_same_index` takes."""

    isin: str = Field(
        ...,
        min_length=12,
        max_length=12,
        description="A fund's ISIN, as its line in the figures gives it.",
    )


_SAME_INDEX_READING = (
    "Matched by name: the catalogue stores no index, so a fund counts when its "
    "name ends with the same index words as this one's, its replication, series "
    "and hedging words set aside, and none before them naming another exposure "
    "(ESG, equal weight). A fund that names its index another way is not "
    "counted, so every count is a floor; say that it was matched by name.",
    "No other fund is named here, on purpose: say what the catalogue holds (how "
    "many funds, from which cost, how many cheaper than this one) and never a "
    "fund's name. The chat names one, on a card, when it is asked.",
    "ter_pct is the ongoing charge a year as the catalogue gives it. What a "
    "difference costs in money is the difference times what is held in the fund; "
    "work it out from the figures you have, and say a TER the catalogue lacks is "
    "not known.",
)


def _costs(funds: list[dict], mine: float | None) -> dict:
    """How many funds, their TERs' range, and how many charge less than,
    as much as or more than `mine`."""
    known = sorted(f["ter"] for f in funds if f["ter"] is not None)
    out: dict = {"funds": len(funds)}
    if known:
        out["lowest_ter_pct"], out["highest_ter_pct"] = known[0], known[-1]
        if mine is not None:
            out["cheaper_than_this_fund"] = sum(1 for t in known if t < mine - 1e-9)
            out["as_cheap_as_this_fund"] = sum(1 for t in known if abs(t - mine) <= 1e-9)
            out["dearer_than_this_fund"] = sum(1 for t in known if t > mine + 1e-9)
    if len(known) < len(funds):
        out["ter_not_known"] = len(funds) - len(known)
    return out


def _same_index(db: Session, args: SameIndexArgs) -> dict:
    """What the registry holds on a fund's index, in counts and costs, with no
    fund but this one named (`catalogue.same_index`)."""
    found = catalogue.same_index(db, args.isin)
    fund, others = found["fund"], found["others"]
    mine = fund["ter"]
    hedged = bool(fund["hedged"])
    like = [
        f for f in others
        if bool(f["hedged"]) == hedged and f["distribution_policy"] == fund["distribution_policy"]
    ]
    by_replication: dict[str, list[dict]] = {}
    for f in others:
        by_replication.setdefault(f["replication"] or "not said", []).append(f)
    sizes = [f["size_meur"] for f in others if f["size_meur"] is not None]
    held = fund["isin"] in _held_keys(db)
    return {
        "fund": {
            "isin": fund["isin"],
            **({"name": fund["name"]} if held else {"name": "not held, so not named"}),
            "ter_pct": mine,
            "replication": fund["replication"],
            "currency_hedged": hedged,
            "distribution": schemas.POLICY_WORDS.get(fund["distribution_policy"] or "", "not said"),
            "size_meur": fund["size_meur"],
        },
        "index_as_the_names_give_it": found["index_words"],
        "other_funds_on_it": _costs(others, mine),
        "with_this_funds_hedging_and_dividend_policy": _costs(like, mine),
        "by_replication": {name: _costs(group, mine) for name, group in sorted(by_replication.items())},
        "currency_hedged": _costs([f for f in others if f["hedged"]], mine),
        "fund_size_meur": {"largest": max(sizes), "smallest": min(sizes)} if sizes else None,
        "catalogue": _registry_source(found["rows"], found["fetched_at"]),
        "reading": list(_SAME_INDEX_READING),
    }


# --- An instrument's facts ---------------------------------------------------------


class InstrumentFactsArgs(BaseModel):
    """What `instrument_facts` takes: a fund's ISIN, or a symbol."""

    isin: str | None = Field(
        default=None, description="A fund's ISIN, for its line in the catalogue."
    )
    symbol: str | None = Field(
        default=None,
        description=(
            "A symbol Yahoo quotes (a share, a coin, a fund's listing), for what "
            "Yahoo lists under it and its latest close."
        ),
    )

    @model_validator(mode="after")
    def _one(self):
        if bool((self.isin or "").strip()) == bool((self.symbol or "").strip()):
            raise ValueError("Name one instrument: a fund's ISIN or a symbol, not both and not neither.")
        return self


_FACTS_READING = (
    "Everything here was read, from the catalogue or from Yahoo just now, and "
    "nothing was inferred: a field that says not given is not known.",
    "An instrument the records do not hold is described without its name, on "
    "purpose: the analysis names no security the person does not hold.",
    "latest_close is the last session's close Yahoo gives, in the currency it "
    "names, on the day beside it: a market price, not what the records value "
    "the position at.",
)


def _facts(db: Session, args: InstrumentFactsArgs) -> dict:
    """A fund's line in the registry, or a symbol's listing and latest close
    from Yahoo, the name kept only for what the records hold."""
    held = _held_keys(db)
    if (args.isin or "").strip():
        row = _registry_row(db, args.isin)
        state = catalogue.status(db)
        return {
            "kind": "fund",
            "isin": row.isin,
            "name": row.name if row.isin in held else "not held, so not named",
            "held": row.isin in held,
            "ter_pct": row.ter,
            "distribution": schemas.POLICY_WORDS.get(row.distribution_policy or "", "not said"),
            "domicile": row.domicile,
            "replication": row.replication,
            "currency_hedged": row.hedged,
            "size_meur": row.size_meur,
            "holdings": row.holdings_count,
            "share_class_currency": row.share_class_currency,
            "catalogue": _registry_source(state["rows"], state["fetched_at"]),
            "reading": list(_FACTS_READING),
        }
    symbol = args.symbol.strip().upper()
    try:
        listed = prices.listing(symbol)
    except prices.MarketUnreachable as exc:
        raise LookupError(
            f"Yahoo did not answer just now ({exc}): that says nothing about {symbol}."
        ) from exc
    if listed is None:
        raise LookupError(f"Yahoo lists nothing under exactly {symbol}.")
    try:
        quote = prices.get_quote(symbol, fx.Converter(db).base)
        close = {"price": quote["price"], "currency": quote["currency"] or "not given", "as_of": quote["as_of"]}
    except prices.PriceError as exc:
        close = f"not given: {exc}"
    return {
        "kind": listed.get("quote_type") or "not given",
        "symbol": listed["symbol"],
        "name": (listed.get("name") or "not given") if symbol in held else "not held, so not named",
        "held": symbol in held,
        "exchange": listed.get("exchange") or "not given",
        "latest_close": close,
        "source": "Yahoo, asked just now",
        "reading": list(_FACTS_READING),
    }


# --- What a change would weigh --------------------------------------------------------


class WeighChangeArgs(BaseModel):
    """What `weigh_change` takes: a purchase, a sale, or both."""

    buy_isin: str | None = Field(
        default=None, description="A fund to buy, by its ISIN in the catalogue."
    )
    buy_symbol: str | None = Field(
        default=None, description="A share or another listing to buy, by the symbol Yahoo quotes it under."
    )
    buy_amount: float | None = Field(
        default=None, gt=0, description="What would go into it, in the base currency of the figures."
    )
    sell: str | None = Field(
        default=None,
        description="A position held, to sell part or all of: the symbol or the ISIN it is held under.",
    )
    sell_amount: float | None = Field(
        default=None, gt=0, description="What would come out of it, in the base currency of the figures."
    )

    @model_validator(mode="after")
    def _a_change(self):
        buying = bool((self.buy_isin or "").strip() or (self.buy_symbol or "").strip())
        if (self.buy_isin or "").strip() and (self.buy_symbol or "").strip():
            raise ValueError("Name what to buy by its ISIN or by its symbol, not both.")
        if buying != (self.buy_amount is not None):
            raise ValueError("A purchase needs both what to buy and buy_amount.")
        if bool((self.sell or "").strip()) != (self.sell_amount is not None):
            raise ValueError("A sale needs both the position (sell) and sell_amount.")
        if not buying and self.sell_amount is None:
            raise ValueError("A change is a purchase, a sale or both: give one.")
        return self


_WEIGH_READING = (
    "Every percentage is a share of the investments, before and after the "
    "change, read as the look-through reads them: a sale shrinks the "
    "investments and a purchase grows them.",
    "looked_inside false means no source could look inside the purchase, which "
    "says nothing about what it holds.",
    "This weighs a change on the records and the funds' holdings alone. It says "
    "nothing of whether the person could or should make it: that is not the "
    "analysis's to know.",
)


def _weigh(db: Session, args: WeighChangeArgs) -> dict:
    """What a purchase, a sale or both would do to the look-through
    (`composition.weigh_change`), never the room an amount stands on."""
    held = _held_keys(db)
    purchase = None
    asked = None
    if args.buy_amount is not None:
        if (args.buy_isin or "").strip():
            row = _registry_row(db, args.buy_isin)
            purchase = composition.Purchase(name=row.name, value=args.buy_amount, isin=row.isin)
            asked = row.isin
        else:
            symbol = args.buy_symbol.strip().upper()
            try:
                listed = prices.listing(symbol)
            except prices.MarketUnreachable as exc:
                raise LookupError(
                    f"Yahoo did not answer just now ({exc}): {symbol} cannot be weighed yet, "
                    "and that says nothing about it."
                ) from exc
            if listed is None:
                raise LookupError(f"Yahoo lists nothing under exactly {symbol}.")
            purchase = composition.Purchase(
                name=listed.get("name") or symbol, value=args.buy_amount, symbol=listed["symbol"]
            )
            asked = symbol
    sale = composition.Sale(key=args.sell, value=args.sell_amount) if args.sell_amount is not None else None
    weighed = composition.weigh_change(db, purchase, sale)
    if weighed["bought"] is not None:
        weighed["bought"] = {
            "instrument": purchase.name if asked in held else f"{asked}, not held, so not named",
            **weighed["bought"],
        }
    return {**weighed, "reading": list(_WEIGH_READING)}


class LookThroughArgs(BaseModel):
    """What the analysis's `get_look_through` takes: nothing. The chat's may
    ask every source again (`refresh`); a step of the analysis reads what the
    look-through holds, and a run does not refetch every position's holdings
    from the network on a model's word."""


def _look_through(db: Session, args: LookThroughArgs) -> dict:
    return tools._look_through(db, tools.LookThroughArgs())


REGISTRY: dict[str, tools.Tool] = {
    t.name: t
    for t in (
        tools.Tool(
            name="get_look_through",
            description=(
                "What the funds held are made of underneath, for the investments "
                "as a whole: the country, sector and currency weights, the largest "
                "companies, the companies inside more than one position (a "
                "company's stock only, never its bonds), and what could not be "
                "looked inside. More than the figures' summary of it gives."
            ),
            arguments=LookThroughArgs,
            run=_look_through,
        ),
        tools.Tool(
            name="catalogue_same_index",
            description=(
                "What the fund catalogue holds on the index a held fund tracks: how "
                "many other funds, their ongoing charges (lowest, highest, how many "
                "cheaper than this one), by replication, hedging and dividend policy, "
                "and their sizes. Call it before judging what a fund costs. It names "
                "no other fund, on purpose."
            ),
            arguments=SameIndexArgs,
            run=_same_index,
        ),
        tools.Tool(
            name="instrument_facts",
            description=(
                "What an instrument IS, read and not inferred: a fund's line in the "
                "catalogue (by ISIN), or what Yahoo lists under a symbol (its kind, "
                "its exchange) and its latest close with its day and currency. Call "
                "it before saying what a position is or what it trades at now. A "
                "network call of a few seconds for a symbol."
            ),
            arguments=InstrumentFactsArgs,
            run=_facts,
        ),
        tools.Tool(
            name="weigh_change",
            description=(
                "What a change would do to the look-through, before against after: "
                "a purchase (a fund by ISIN or a listing by symbol, and a sum), a "
                "sale of part or all of a held position (by the symbol or ISIN it is "
                "held under, and a sum), or both. Its weights, the countries, "
                "sectors, currencies and companies that move most, and how much the "
                "look-through sees inside. Call it before saying what a change "
                "would do to the exposure; it can take seconds when a purchase's "
                "holdings have to be fetched."
            ),
            arguments=WeighChangeArgs,
            run=_weigh,
        ),
    )
}

SEARCH_WEB = tools.SEARCH_WEB


def _search_description(searches: int) -> str:
    return (
        "Search the web for ONE query and read what it finds: up to five pages, "
        "each with its title, its address and an excerpt. For what the figures, "
        "the catalogue and an instrument's facts do not hold: what an instrument "
        "you are judging is doing (its results, valuation, risks and news), how "
        "an index or a fund works, and any fact you would otherwise state from "
        "memory (a past fall, a history). The query leaves this app for a search "
        "engine: write it about instruments, markets and facts, and never put in "
        "it an amount, an account, an entry or any other figure or name from the "
        f"records. At most {searches} a step, and each costs a little."
    )


def declarations(model: str, searches: int) -> list[dict]:
    """Every read-only analyst tool, plus bounded web search when supported."""
    declared = [
        tools._declaration(t.name, t.description, t.arguments)
        for t in REGISTRY.values()
    ]
    if tools.web_search(model):
        declared.append(
            tools._declaration(
                SEARCH_WEB, _search_description(searches), tools.SearchWebArgs
            )
        )
    return declared


def answer(db: Session, call: advisor.ToolCall, offered: list[str] | None = None) -> dict:
    """What one call of the analysis's comes to, in the shape the model reads
    back: `{"ok": True, "result": ...}`, or `{"ok": False, "error": ...}` in
    words. Never raises. A name this module does not hold is not offered and
    runs nothing, whatever the chat's tools are called: the analysis reaches
    nothing the person wrote through a door its list does not have. The web
    search is not answered here: the step runs it (`chain`). `offered` is the
    names the step declared, said back when a call names another."""
    tool = REGISTRY.get(call.name)
    if tool is None:
        names = offered if offered is not None else [*REGISTRY, SEARCH_WEB]
        return {
            "ok": False,
            "error": (
                f"There is no tool called {call.name!r} in the analysis, and it ran "
                f"nothing. Its tools are: {', '.join(names)}."
            ),
        }
    args = tools._parse(tool.arguments, call)
    if isinstance(args, dict):
        return args
    try:
        return {"ok": True, "result": tool.run(db, args)}
    except (LookupError, ValueError) as exc:
        # A refusal in words (a fund the catalogue does not hold, a sale larger
        # than the position, Yahoo silent): the model reads it and goes on.
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("the analysis's tool %s failed", call.name)
        return {"ok": False, "error": f"{call.name} failed: {type(exc).__name__}: {exc}"}
