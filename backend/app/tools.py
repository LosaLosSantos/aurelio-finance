"""The tools the chat can call, and the one place their schemas come from.

A tool is a function the model may ask for by name, mid-answer, and get an
answer to before it finishes writing. The registry below is the whole list.

NOTHING HERE IS TRANSCRIBED. A tool's arguments are a Pydantic model and its
JSON schema is generated from it, by the SDK's own converter. This codebase
has already paid for a hand-copied schema once — twenty-three interfaces typed
out beside the API they described, two of which had quietly drifted, which is
why `schema.d.ts` is generated now. A tool schema drifts the same way and
fails worse: the model is told the function takes a field that no longer
exists, calls it, and the failure surfaces as an argument error two layers
away from the line that lied.

Why there are read tools at all, when `chat.py` argues at length that reading
needs none. The rule there is about the reader's OWN data: the picture is
bounded, always relevant, and its value is that the model sees across sections
the question did not name — so it travels whole, every turn, and a tool per
section would buy latency and wrong-tool errors to save two thousand tokens.
A read earns a tool when one of those three stops being true.

`get_look_through` fails the first, and on NETWORK rather than on size.
`composition.get_composition` answers from the cache when it is fresh and
otherwise walks a waterfall of fund issuers — iShares, Vanguard, justETF,
Yahoo — one per position. Folded into the context it would run on every turn,
and "hello" would cost five HTTP fetches to fund issuers. As a tool it runs
when the question is actually about what is inside the funds.

`read_analysis` fails the second and the third at once, and it is the door
this module opens onto the chain. A past verdict is a document of unbounded
length that matters in one conversation out of ten; sent every turn it would be
a month-old opinion sitting at the same prominence as a picture rebuilt this
second. What the context carries instead is its date and its opening lines,
which is what noticing staleness needs, and the rest is one call away.

`search_catalogue` and `lookup_symbol` fail the FIRST in the plainest way:
what they read is not the reader's data at all. The registry is thousands of
funds and the lookup is the whole quotable universe, so they are searched
rather than sent. They stay two tools for the reason `routers/instruments.py`
already gives for keeping two endpoints — one answers from SQLite in
milliseconds and the other is a network call, and behind a single function the
instant lane waits for the slow one while an outage empties a list that had
good local results in it.

`search_web` fails the first too, and is the one read tool REGISTRY does not
hold. What it reads is the web, through a request of its own to OpenRouter
(`websearch`), and the pages it finds and what it costs belong to the turn
that ran it, so the chat loop answers it. It is declared here like the others
(`web_search`), for Anthropic's models only (brief AM).

Tools that WRITE do not run from here. They are proposed: a card the reader
confirms, and only then does the normal write path run — `crud`, a unit of
work, `_columns`, `test_write_contract`. The chat does not get a service door
the form does not have. There are five — `add_real_asset`,
`record_transaction`, `update_profile`, `run_analysis`, `suggest_instrument` —
and one action each, because a generic `propose_change(entity, action, fields)`
hands the model the job of knowing which fields fifteen entities have, and on
fifteen entities it gets that wrong.

`suggest_instrument` is the one that goes through this machinery while writing
nothing of the reader's: accepting it parks an idea on a watchlist that owns
nothing and totals nowhere. It is a card anyway, because the reader decides
what enters their app, and its accept button says "Add to watchlist" rather
than "Confirm" — `Proposal.verb` — since "Confirm" over a card naming a
security reads as approval of a purchase nobody proposed.

`run_analysis` is a write like the others and stretches the word in one
direction only: what it writes is a `ChainRun`, and what makes it a proposal is
not that it is hard to undo but that it costs the reader a minute of waiting
and a few cents before it produces anything. The card asks first and quotes the
last run's measured time and price. It is also the only tool with a `walk`
instead of a `run`, because a minute of silence is the thing a confirmation
card should not buy you.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app import advisor, catalogue, chain, composition, crud, dated, fx, models, positions, prices, questionnaire, schemas
from app.database import unit_of_work

logger = logging.getLogger(__name__)


# The words a model writes for "nothing" in a field it may leave empty. In the
# reader's test round (2026-10-08) two fund cards carried "symbol": "null", the
# word and not JSON's null, and accepting them stored the symbol "NULL" on both
# watchlist lines, which "Record a buy" then put in the ticker box. The schema
# offers a null; a word that means one is read as one.
_ABSENT = frozenset({"", "null", "none", "nil", "undefined", "n/a"})


def _absent_is_none(value):
    """`value`, or None when it is a string that says there is nothing."""
    if isinstance(value, str) and value.strip().lower() in _ABSENT:
        return None
    return value


# An optional text argument of a tool that writes: what the model wrote, or
# nothing, never the word for nothing. A validator and not a type, so the
# schema the model is shown is the one it was shown before.
MaybeText = Annotated[str | None, BeforeValidator(_absent_is_none)]


@dataclass(frozen=True)
class Proposal:
    """What a write would do, described before it does it.

    `title` is the whole change in one line, in the reader's terms and not the
    schema's — "buy 5 VWCE.MI @ 128.40 · Broker A", not a field list.

    `confirmation` is the rule the domain already has, and it is about
    REVERSIBILITY rather than size. An event — a transaction, a dated
    valuation — is a dated claim, verifiable, and undone by deleting it, so it
    gets a light confirmation. A photograph is the record OF a day: editing a
    snapshot restates what that day said, every projection anchored after it
    moves with it, and deleting the edit does not bring the old day back. That
    gets "diff", and `diff` has to be filled: an explicit line-by-line of what
    that day says now against what it would say.

    `fingerprint` is what this proposal DEPENDS ON, as it stands right now,
    reduced to a string that changes when it does. The confirmation recomputes
    it and refuses the card if it moved.

    A clock cannot do this job. A ten-second-old card can be stale — the other
    tab wrote while the reader was reading — and a three-day-old one can be
    perfectly good, because nothing touched what it was about. Any age is
    therefore both too strict and too loose at once. A fingerprint is neither:
    it goes stale exactly when the thing the card was computed against changed,
    and at no other time, which is also the only rule a test can pin.

    What goes in it is the tool's own business, because only the tool knows
    what it read. A photograph's is what that day currently says — the same
    rows the diff was built from, so a card and its diff go stale together. An
    event's is much smaller: appending a transaction overwrites nothing, so
    little more than the continued existence of what it points at can
    invalidate it. An empty fingerprint means "nothing this depends on can
    move", and that is a claim, not a default to fall into.

    `consequence` is the sentence above the diff: what confirming this costs
    that the diff itself does not show. It belongs to the TOOL because only
    the tool knows — editing a snapshot moves every figure anchored after it,
    while replacing a survey answer moves nothing and simply loses the old one
    — and the card that draws it renders every tool's proposals. One sentence
    hard-coded there was right for the one card it was written for and wrong
    for the next.

    `verb` is the accept button's label, and it is here for the same reason
    `consequence` is: the panel renders every tool's proposals and cannot know
    what pressing the button does. Empty means "Confirm", which is right for
    everything that writes to the reader's records. It is not right for a
    suggestion — that one writes nothing of theirs, and "Confirm" over a card
    naming a security reads as approval of a purchase nobody proposed.
    """

    title: str
    fingerprint: str
    confirmation: str = "light"  # light | diff
    consequence: str = ""
    verb: str = ""
    diff: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Working:
    """One thing a long tool has FINISHED, said while it is still going.

    Not a result and not a record: the result comes at the end and the record
    is whatever the tool wrote. This is the answer to "what is the silence",
    which is the same job `schemas.ChatTool` does for a tool that takes
    seconds — and a tool that takes a minute needs it said more than once.

    `label` is the step in the reader's words, because it is printed as it
    arrives and there is no table anywhere that turns a slug into a sentence.
    """

    step_no: int
    label: str
    duration_ms: int


@dataclass(frozen=True)
class Tool:
    """One callable the model may ask for.

    `arguments` is the Pydantic model the model has to fill, and it is the
    single source of the schema the model is shown — see `declarations`.
    The body receives that model already validated, so a tool never parses
    anything and never checks a type.

    `propose` is what makes a tool a WRITE tool, and it is one field rather
    than a flag because the two must not be able to disagree. A tool that has
    it does not run when the model calls it: it describes what it would do,
    the reader is shown that as a card, and the body runs from the confirm
    endpoint or not at all. A tool without it runs immediately, which is what
    reading means here.

    `run` and `walk` are the same job at two lengths, and EXACTLY ONE of them
    must be given — checked below rather than left to a comment, for the reason
    `propose` is a callable and not a boolean. `run` returns the result. `walk`
    yields a `Working` per finished step and RETURNS the result, and it exists
    because a tool that takes a minute leaves the reader in front of a spinner
    that cannot say which minute it is on. Anything that finishes while a
    person is still looking at the screen should be a `run`.

    The body must keep everything it does INSIDE the session it is handed. Two
    windows confirming the same card at once both reach it, and only one of
    them commits — the loser's transaction is rolled back under it. Which is
    the right answer for rows and no answer at all for anything else: a body
    that sent an email or wrote a file would do it twice, and there is no
    transaction to take that back.
    """

    name: str
    description: str
    arguments: type[BaseModel]
    run: Callable[[Session, BaseModel], dict] | None = None
    walk: Callable[[Session, BaseModel], Iterator[Working]] | None = None
    propose: Callable[[Session, BaseModel], Proposal] | None = None
    # What a card calls each argument, for the reader: the name is the
    # model's, the label is theirs ("based_on" was on the reader's cards,
    # 2026-10-08). Every argument of a tool that writes has one (a test), so a
    # new field cannot reach a card under its schema name.
    labels: dict[str, str] = field(default_factory=dict)
    # What was written, in words, from the tool's result: rows of (label,
    # value, kind), kind "date" for a day the panel writes in the reader's
    # language. The result itself stays as it is, for the model.
    receipt: Callable[[dict], list[tuple[str, str, str]]] | None = None
    # What a confirmed card says it is now.
    done: str = "Recorded"

    def __post_init__(self) -> None:
        if (self.run is None) == (self.walk is None):
            raise TypeError(
                f"{self.name}: a tool declares exactly one of run and walk — "
                "neither leaves it with no body, both leave two that can disagree."
            )


# --- The look-through --------------------------------------------------------


class LookThroughArgs(BaseModel):
    """What `get_look_through` takes."""

    refresh: bool = Field(
        default=False,
        description=(
            "Leave this false. False answers from the stored composition and "
            "touches no network. True re-downloads every fund's holdings from "
            "its issuer, one position at a time, and takes tens of seconds: "
            "ask for it only when the reader has said they want the figures "
            "re-fetched."
        ),
    )


# What the numbers in the payload MEAN, travelling with them. The look-through
# is the part of this app where a percentage is most easily misread: the axes
# are shares of the investments as a whole and are deliberately NOT
# renormalised to the part that could be decomposed, so "countries add up to
# 30" is a fact about coverage and not about a rounding error. Sent as data
# rather than trusted to the system prompt, because the prompt does not travel
# with the tool result into the next turn's history and this does.
#
# "Of the investments", not "of the whole portfolio": the chat reads the cash
# beside them in every turn, and "whole" read as all of it is how the first
# analysis turned a share of the investments into a share of everything
# (brief Z).
_READING = (
    "Every percentage here is a share of the investments as a whole (every "
    "position, and none of the cash on the accounts) and is never "
    "renormalised to the decomposed part: if the countries add up to 30, then "
    "30% of the investments are in those countries and the rest could not be "
    "looked inside.",
    "total_value is the denominator: the investments, without the cash, in the "
    "portfolio's own currency. An amount is pct / 100 * total_value.",
    "coverage_pct is how much of the investments the look-through could see "
    "inside. undecomposed_pct is the rest, and it is UNKNOWN, not empty.",
    "companies and overlap are the twenty largest by weight. A name that is "
    "not in them is not absent from the portfolio: it is below that cut, and "
    "saying 'you do not hold it' would be wrong.",
    "overlap lists the names held inside two or more positions, with the "
    "positions holding them. Its percentage is a share of all the investments, "
    "not of one position, and it is a floor: a fund whose source publishes only its top "
    "holdings hides everything below that rank.",
    "A row with decomposed=false carries the reason in `error`. 'No source "
    "answered' and 'this fund holds nothing there' are different claims: say "
    "which one you are making.",
)


def _look_through(db: Session, args: LookThroughArgs) -> dict:
    """The whole look-through, as `compute_portfolio_composition` computes it.

    Passed through rather than reshaped, so this cannot drift from the figures
    the Portfolio page draws from the same call — one look-through, two
    readers. What is added is `reading`: the qualifications the screen carries
    as chart labels and axis titles, which a JSON payload would otherwise drop
    on the floor."""
    look_through = composition.compute_portfolio_composition(db, refresh=args.refresh)
    return {**look_through, "reading": list(_READING)}


# --- The instrument universe: two lanes, and they do not merge -----------------
#
# The exception to "reading needs no tool" applies here for the FIRST reason
# rather than the network one: 4,544 catalogue rows are not the reader's data
# and are not bounded, so they are searched rather than sent. Everything about
# the reader still travels whole, every turn.
#
# TWO tools and not one, and the argument is already written out in
# `routers/instruments.py` where the same split was made for the picker: the
# catalogue answers from SQLite in milliseconds and the lookup is a network
# call, so putting them behind one function makes the instant lane wait for the
# slow one, and an outage empties a list that had perfectly good local results
# in it. A model that wants both asks for both, and gets the fast one's answer
# even when the other never comes back. The name `search_instruments` is the
# HTTP handler's and is not free.


class SearchCatalogueArgs(BaseModel):
    """What `search_catalogue` takes."""

    query: str = Field(
        ...,
        min_length=2,
        description=(
            "Free text: fund name, issuer, index, ticker, such as 'vanguard "
            "all-world', 'msci emerging markets', 'VWCE'. Words are matched "
            "together first and the search loosens only if that finds nothing."
        ),
    )
    limit: int = Field(
        default=8, ge=1, le=25, description="How many families to return, at most."
    )


# What a catalogue result MEANS, travelling with it. Two of these are the
# reason `catalogue.py` opens with a warning: `base_ticker` and
# `share_class_currency` are the two columns that look exactly like the fields
# they must never fill, and they have already cost this repo a phantom 17%
# gain. Sent as data rather than trusted to the system prompt, because the
# prompt does not travel with the tool result into the next turn's history and
# this does.
_CATALOGUE_READING = (
    "Every ISIN here exists in the local registry. A suggestion may name ONLY "
    "an ISIN copied verbatim from these results: that is what makes an "
    "invented fund impossible, so never type one from memory.",
    "Results are FAMILIES, not rows. A quarter of the registry arrives in "
    "pairs that share a name and differ only in what they do with dividends, "
    "so both members are always shown together and you have to say which one "
    "you mean: 'acc' accumulates dividends inside the fund, 'dist' pays them "
    "out. The picture and the reader's pages call them accumulating and "
    "distributing; these results carry the stored 'acc' / 'dist'.",
    "base_ticker is NOT a Yahoo symbol and must never be offered as one: the "
    "registry gives one code per fund (EUNL for iShares Core MSCI World), "
    "while a holding trades on a listing with its own symbol. Symbols come "
    "from `lookup_symbol` and nowhere else.",
    "share_class_currency is the share class's own currency, NOT the currency "
    "the fund trades in. It says USD for funds that quote in EUR in Milan, and "
    "reading it as a trading currency is a documented source of invented "
    "gains.",
    "ter is the annual ongoing charge as a percentage; size_meur is the fund's "
    "size in millions of euro.",
    "coverage says how the match was made. 'all' means every word was found; "
    "'partial' means the search had to loosen to find anything, which is a "
    "weaker claim about what was asked for and should be said out loud; 'none' "
    "means nothing matched, a fact about THIS registry of `rows` funds "
    "downloaded on `fetched_at`, never a claim that the instrument does not "
    "exist.",
)


# Why the registry is empty, as the reader can be told it. On 2026-10-02 a model
# given only the fields told the reader "0 righe" and "fetched_at: null", and
# that the catalogue had to be filled, not how. Nobody fills it now: the app
# downloads it by itself, so what the reader is owed is where that stands.
_WHERE_THE_DOWNLOAD_STANDS = {
    "downloading": "the app is downloading the list of funds from justETF right now, by itself",
    "failed": (
        "the app tried to download the list of funds from justETF and could not, "
        "and tries again by itself when the app is next opened or reloaded, {when}"
    ),
    "not_started": (
        "the app downloads the list of funds by itself when it is opened, and "
        "has not been asked since the server last started; reloading the page "
        "starts it"
    ),
}


def _where_the_download_stands(state: dict) -> str:
    """The middle of the sentence, for the state `catalogue.status` reports."""
    said = _WHERE_THE_DOWNLOAD_STANDS.get(state.get("state"), _WHERE_THE_DOWNLOAD_STANDS["not_started"])
    if state.get("state") != "failed":
        return said
    try:
        wait = datetime.datetime.fromisoformat(state["retry_after"]) - catalogue._now()
    except (KeyError, TypeError, ValueError):
        wait = datetime.timedelta(0)
    minutes = -(-int(wait.total_seconds()) // 60)  # rounded up
    when = (
        f"in {minutes} minute{'s' if minutes != 1 else ''} at the earliest"
        if minutes > 0
        else "which a reload now will do"
    )
    return said.format(when=when)


def _search_catalogue(db: Session, args: SearchCatalogueArgs) -> dict:
    """The local registry, searched exactly as the instrument picker searches it.

    `catalogue.search` and nothing reshaped around it, so this cannot drift
    from what the picker shows for the same words — one registry, two readers.
    What is added is `reading`, which is the part a JSON payload drops on the
    floor: the picker carries these qualifications as column labels and a
    warning in its own module docstring, and a tool result carries none of
    that unless it is sent. While the registry is empty there is nothing to
    qualify, and `reading` says instead why it is empty, in plain words."""
    found = catalogue.search(db, args.query, args.limit)
    if not found["rows"]:
        return {
            **found,
            "reading": [
                "The local fund registry is empty: "
                + _where_the_download_stands(found)
                + ". Until it arrives nothing can be searched or suggested from "
                "it, and that says nothing about whether any fund exists. Tell "
                "the reader so in plain words, never in these fields' names, and "
                "offer no card."
            ],
        }
    return {**found, "reading": list(_CATALOGUE_READING)}


class LookupSymbolArgs(BaseModel):
    """What `lookup_symbol` takes."""

    query: str = Field(
        ...,
        min_length=2,
        description=(
            "Free text: company, coin, ticker, such as 'siemens', 'bitcoin', 'SIE.DE'. "
            "This is the live lane: shares, single stocks, crypto and futures, "
            "i.e. everything the fund catalogue does not hold."
        ),
    )
    limit: int = Field(
        default=8, ge=1, le=25, description="How many candidates to return, at most."
    )


_LOOKUP_READING = (
    "A symbol PRICES a listing; it does not identify an instrument. The same "
    "company trades in five places under the same name, and only `exchange` "
    "tells the rows apart.",
    "price NEVER means anything without exchange beside it. This source "
    "returns no currency, so the same share on two exchanges comes back as two "
    "bare numbers in different money (38.60 and 33.60 for one company, which "
    "look 15% apart and are the same value). Do not compare them and do not "
    "quote one as 'the price'.",
    "reachable=false with an empty list means the source did not answer. That "
    "is NOT 'this instrument does not exist': saying so teaches the reader to "
    "correct a symbol that was right.",
    "A row whose quote_type is equity can be suggested as a share by its "
    "exact symbol, and the card asks this source about it again. Nothing else "
    "here can: a fund is suggested from `search_catalogue` by its ISIN, and a "
    "coin or a future not at all.",
)


def _lookup_symbol(db: Session, args: LookupSymbolArgs) -> dict:
    """The live lane, in the shape `/api/instruments/lookup` returns it.

    `reachable` is inferred the same way the HTTP handler infers it, and it is
    an inference rather than a measurement because `prices.lookup` swallows the
    failure and returns [] — the picker's second lane must never go dark
    because this one did. The two callers infer it identically on purpose: one
    story about what an empty list means, not two."""
    results = prices.lookup(args.query, args.limit)
    return {
        "results": results,
        "reachable": bool(results),
        "reading": list(_LOOKUP_READING),
    }


# --- The writes ---------------------------------------------------------------
#
# One tool per action, not one `propose_change(entity, action, fields)` for all
# of them: a generic tool hands the model the job of knowing which fields each
# of fifteen entities has, and on fifteen entities it gets that wrong.
#
# What that costs is sent on every turn, so it is worth having a figure rather
# than a feeling. `len(json.dumps(declarations()))` is 19,333 characters for all
# nine tools, on 2026-09-17 (17,696 on 2026-09-05, before the writes grew).
#
# In tokens — measured on 2026-09-17 against `qwen/qwen3.8-max`, as the
# difference between the same turn asked with the declarations and without
# them — they are 4,842. That is the LARGEST single piece of a turn: bigger
# than the financial picture they sit beside (3,748), and more than twice the
# system prompt (2,284). The note that used to stand here said the opposite,
# "it is real and it is not the expensive part", on the strength of a context
# figure that was stale; `chat.py` has the whole breakdown and where today's
# figures live.
#
# It is still the right trade, and now it can be stated as one rather than
# assumed: 4,842 tokens buys every write the reader can confirm from the chat,
# in a vocabulary the model does not have to guess at. What it does NOT buy is
# a free lunch — a turn that needs no write pays for them too, and the day that
# matters the lever is the number of tools, not their wording.
#
# What they do NOT do is take a `*Create` schema as their argument model, and
# the reason is `institution_id`. The picture the model reads NAMES the
# institutions and never numbers them — `build_context` prints "Broker A", not
# "3" — so an argument typed as a foreign key is a field it can only guess at,
# and a guessed foreign key records the purchase against somebody else's
# account. The arguments below are the reader's vocabulary instead: an
# institution by name, one flat list of fields per card. The `*Create` is built
# from them in one place per tool. The JSON schema the model is shown is still
# generated from these models and transcribed nowhere; what is written by hand
# is a constructor call, which is the seam between two vocabularies and has to
# be somewhere.


# What a proposal that depends on nothing says, instead of "". The two read the
# same from here and not from the other end: an empty fingerprint is also what
# a tool that never thought about staleness produces, and `Proposal` asks for
# the claim rather than letting it be defaulted into.
_DEPENDS_ON_NOTHING = "nothing-can-move: every row this writes is new"


def _institution(db: Session, name: str | None) -> models.Institution | None:
    """The institution the reader named, or None when they named none.

    A name that matches nothing RAISES rather than quietly becoming None. The
    two are opposite claims — "this is not held anywhere in particular" against
    "you said Broker A and I could not find it" — and a card showing the second
    as the first would record a purchase against no institution for a reader
    who named one. The refusal lists what does exist, because it is read by the
    model, which can correct itself on the next round trip.
    """
    if name is None or not name.strip():
        return None
    known = crud.get_institutions(db)
    wanted = name.strip().casefold()
    for inst in known:
        if inst.name.strip().casefold() == wanted:
            return inst
    have = ", ".join(i.name for i in known) or "none"
    raise LookupError(f"There is no institution called {name!r}. On record: {have}.")


# --- add_real_asset ----------------------------------------------------------


class AddRealAssetArgs(BaseModel):
    """A possession that is not held at an institution, and what it is worth."""

    name: str = Field(
        ...,
        min_length=1,
        description=(
            "What the thing is, in the language the DATA is written in rather "
            "than the language of the question: 'mia nonna mi ha regalato una "
            "collana d'oro' is a 'gold necklace', not 'una collana d'oro'."
        ),
    )
    value: float = Field(
        ...,
        ge=0,
        description="What it is worth as at `valued_on`. Not what it cost.",
    )
    # `ObservedDate`, so a future day is refused while the card is being drawn
    # rather than after the reader has confirmed it. The same refusal the REST
    # payload makes — this is the other way in.
    valued_on: schemas.ObservedDate = Field(
        default_factory=datetime.date.today,
        description=(
            "The date that valuation is true of. Today's date is the first "
            "line of the picture you were given; use it unless the reader "
            "named another day. It cannot be a day that has not happened yet: "
            "a valuation records what something was OBSERVED to be worth."
        ),
    )
    category: MaybeText = Field(
        default=None,
        description=(
            "One of: real_estate, vehicle, collectible, jewelry, art, other. "
            "Null when none of them fits."
        ),
    )
    currency: schemas.StatedCurrency = Field(
        ...,
        description=(
            "ISO code the value is in (EUR, USD). Required: the card shows it "
            "and the reader confirms it, and a value with no currency cannot "
            "be added to anything. If the reader did not say, the currency "
            "their other figures are recorded in is the one to propose."
        ),
    )
    acquisition_date: datetime.date | None = Field(
        default=None, description="When it was acquired, if the reader said."
    )
    acquisition_value: float | None = Field(
        default=None,
        ge=0,
        description=(
            "What it cost, if the reader said. A gift cost nothing and has "
            "none: leave it null rather than repeating the present value here."
        ),
    )
    notes: MaybeText = Field(default=None, description="Anything else worth keeping.")


def _stored_currency(code: str) -> str:
    """A currency code as a card stores it: upper case, except a code whose
    case is its meaning. Those are fx._MINOR_EXACT's keys (GBp, pence, where
    GBP is pounds, a hundred times more), read from that table rather than a
    list of its own, so a case-significant unit added there is kept here
    too. Everything else is upper-cased as before: a stored "usd" is the
    EUR/eur comparison problem, and GBX, ZAC and ILA mean the same in any
    case."""
    return code if code in fx._MINOR_EXACT else code.upper()


def _propose_real_asset(db: Session, args: AddRealAssetArgs) -> Proposal:
    """An asset and its first valuation, described before either exists.

    The fingerprint is the empty claim, and it is a claim: both rows are new. A
    real asset has no unique column for a second window to collide with, and
    the (asset, date) constraint on the valuation is against an asset that does
    not exist yet, so nothing anybody else does can reach it. The one thing
    another window CAN do is add a second necklace — and that is not this card
    going stale, it is two necklaces."""
    money = f"{args.value:.2f}"
    return Proposal(
        title=(
            f"add real asset: {args.name.strip()}, {money} {_stored_currency(args.currency)} "
            f"as at {args.valued_on.isoformat()}"
        ),
        fingerprint=_DEPENDS_ON_NOTHING,
    )


def _add_real_asset(db: Session, args: AddRealAssetArgs) -> dict:
    """The asset and its valuation, or neither.

    One unit of work around two writes. `chat.resume` already holds one when
    this runs from a confirmed card, and `unit_of_work` is reentrant, so this
    one costs nothing there — it is here because the guarantee belongs to the
    tool. An asset saved without the valuation that says what it is worth is a
    row every total counts as zero, and the reader was shown a figure."""
    with unit_of_work(db):
        asset = crud.create_real_asset(
            db,
            schemas.RealAssetCreate(
                name=args.name.strip(),
                category=args.category,
                currency=_stored_currency(args.currency),
                acquisition_date=args.acquisition_date,
                acquisition_value=args.acquisition_value,
                notes=args.notes,
            ),
        )
        valuation = crud.create_real_asset_valuation(
            db,
            asset.id,
            schemas.RealAssetValuationCreate(date=args.valued_on, value=args.value),
        )
    return {
        "real_asset_id": asset.id,
        "name": asset.name,
        "category": asset.category,
        "currency": asset.currency,
        "valued_on": valuation.date,
        "value": valuation.value,
    }


# What its card calls each argument, and what it says was written.
_REAL_ASSET_LABELS = {
    "name": "Asset",
    "value": "Worth",
    "valued_on": "Valued on",
    "category": "Kind",
    "currency": "Currency",
    "acquisition_date": "Acquired on",
    "acquisition_value": "Paid",
    "notes": "Notes",
}


def _real_asset_receipt(result: dict) -> list[tuple]:
    return [
        ("Worth", result.get("value"), "amount", result.get("currency")),
        ("Valued on", result.get("valued_on"), "date"),
    ]


# --- record_transaction ------------------------------------------------------


class RecordTransactionArgs(BaseModel):
    """One entry in the investment ledger, for something that ALREADY happened."""

    # The four kinds are the ledger's own, and what each of them MEANS is
    # written down in `models.Transaction`. Spelled as a Literal rather than a
    # free string so the schema the model is shown carries the enum: a fifth
    # kind cannot then be invented, only mis-chosen.
    kind: Literal["buy", "sell", "dividend", "close"] = Field(
        default="buy",
        description=(
            "buy: units in, cash out. sell: units out at their average cost, "
            "cash in. dividend: cash in only, the position untouched; "
            "`quantity` is the units held at the ex-date and `unit_price` the "
            "dividend per share. close: the whole position goes and `amount` "
            "is what came back, the only exit for something with no units to "
            "sell."
        ),
    )
    date: datetime.date = Field(
        default_factory=datetime.date.today,
        description=(
            "The day it actually happened, which is not necessarily today. No "
            "broker is connected here: this records a trade already made, it "
            "never places one."
        ),
    )
    asset_name: str = Field(
        ...,
        min_length=1,
        description=(
            "The instrument's own name, in the language of the DATA and not of "
            "the question: 'ho comprato azioni Siemens' is 'Siemens', never "
            "'Azioni Siemens'. On a sell or a close this is not a label: the "
            "ledger matches the entry back to the position it settles by "
            "symbol OR by this string."
        ),
    )
    symbol: MaybeText = Field(
        default=None,
        description=(
            "Yahoo ticker, e.g. VWCE.MI. Required for a buy, a sell and a "
            "dividend; a close may have none, because the rows that most need "
            "an exit are the ones no ticker describes. Use the ticker exactly "
            "as it appears in the positions you were given."
        ),
    )
    isin: MaybeText = Field(default=None, description="ISIN, when the reader gave one.")
    asset_class: MaybeText = Field(
        default=None,
        description="equity | bond | fund_etf | crypto | commodity | real_estate | other",
    )
    quantity: float = Field(
        default=0.0,
        ge=0,
        description="Units moved; for a dividend, the units held at the ex-date.",
    )
    unit_price: float = Field(
        default=0.0,
        ge=0,
        description="Price per unit; for a dividend, the dividend per share.",
    )
    fees: float = Field(
        default=0.0, ge=0, description="Broker fees, if any were said, in `currency`."
    )
    currency: schemas.StatedCurrency = Field(
        ...,
        description=(
            "ISO code of the cash that moved: what the account was debited or "
            "credited in, and what `amount` and `fees` are in. Required: the "
            "card shows it. Usually the currency of the account's cash on record."
        ),
    )
    price_currency: schemas.StatedCurrency | None = Field(
        default=None,
        description=(
            "ISO code `unit_price` is in: the listing's currency, e.g. USD for "
            "a New York share, EUR for VWCE.MI. Required for a buy, a sell and a "
            "dividend; null for a close. When it differs from `currency` and "
            "`amount` is null, the amount is worked out at the ECB rate of `date`. "
            "A London price in pence is GBp, written exactly so: GBP is pounds, a "
            "hundred times more, and 'gbp' is read as pounds too."
        ),
    )
    amount: float | None = Field(
        default=None,
        ge=0,
        description=(
            "The cash that actually moved, never negative, in `currency`. Leave "
            "it null and it is derived: quantity*unit_price + fees for a buy, "
            "minus fees for a sell or a dividend, converted at the rate of `date` "
            "when the price is in another currency. If the reader quoted what "
            "their statement shows, put that here: it is the real figure. A close "
            "has no units to derive it from, so it must state it; 0 is allowed, "
            "silence is not."
        ),
    )
    institution: MaybeText = Field(
        default=None,
        description=(
            "The institution holding the position, BY NAME and exactly as it "
            "appears in the cash register and the positions you were given. "
            "Required for a buy and for a dividend: the cash has to move "
            "against a real account. On a sell or a close it may be left null "
            "when the position being settled is unambiguous: it is then taken "
            "from that position."
        ),
    )
    cash_institution: MaybeText = Field(
        default=None,
        description=(
            "The institution whose cash moved, by name, when it is not the one "
            "holding the position. Null means the same one."
        ),
    )
    note: MaybeText = Field(default=None, description="Anything else worth keeping.")


@dataclass(frozen=True)
class _Ledger:
    """One ledger entry resolved against the records, shared by propose and run.

    Both need the same three answers — which rows these names are, which
    position a disposal settles, and what `amount` the ledger will actually
    store — and they must not answer them differently: the card quotes the
    first two, and `settle` recomputes the fingerprint from them a moment
    before the row is written."""

    create: schemas.TransactionCreate
    institution: models.Institution | None
    cash_institution: models.Institution | None
    settles: positions.Position | None
    amount: float
    fx_as_of: str | None


# The two kinds that dispose of something already held. A buy and a dividend
# append; these two settle, and only they need to find what they settle.
_DISPOSALS = ("sell", "close")


def _settled_position(
    db: Session, args: RecordTransactionArgs, institution: models.Institution | None
) -> positions.Position:
    """The position a sell or a close would settle, as the records project it.

    Matched the way the ledger itself matches one — by symbol, or by name where
    there is no symbol (`models.Transaction`) — so a card cannot bind to a row
    the projection would then read differently.

    A disposal that matches NOTHING is refused rather than recorded, and this
    is the one place a write tool is stricter than the form. `positions.replay`
    sells at the running average cost, so a sell against a position with no
    units books its whole proceeds as realized profit: a gain the reader never
    made, on a position that does not exist. The form is driven by somebody
    looking at the row; the model is not.

    Holding FEWER units than the entry disposes of is not refused, and that
    difference is deliberate. Nobody here knows whether you still own what the
    last photograph said you owned — the app says so rather than pretending
    otherwise — so records that are behind is exactly the case the reader is
    correcting. It goes on the card instead, where they can see it."""
    wanted_symbol = (args.symbol or "").strip().casefold()
    wanted_name = args.asset_name.strip().casefold()
    pool = positions.project(db)
    if institution is not None:
        pool = [p for p in pool if p.institution_id == institution.id]
    hits = [
        p
        for p in pool
        if (wanted_symbol and (p.symbol or "").strip().casefold() == wanted_symbol)
        or p.asset_name.strip().casefold() == wanted_name
    ]
    if len(hits) == 1:
        return hits[0]
    what = args.symbol or args.asset_name
    where = f" at {institution.name}" if institution is not None else ""
    if not hits:
        held = ", ".join(sorted(p.symbol or p.asset_name for p in pool)) or "nothing"
        raise LookupError(
            f"No open position{where} matches {what!r}, so there is nothing for "
            f"a {args.kind} to settle. Held{where}: {held}. If the purchase is "
            "simply missing, record that first."
        )
    raise LookupError(
        f"{len(hits)} open positions match {what!r}. Say which institution this "
        "one is at."
    )


def _ledger_entry(db: Session, args: RecordTransactionArgs) -> _Ledger:
    """One entry, resolved: the names turned into rows, the shape checked by
    the same schema the form posts through, and the cash figure taken from the
    same function that will store it.

    That last one is `crud._transaction_payload`, reached across a module
    boundary on purpose. It holds the rule that a buy costs price*units PLUS
    fees while a sell nets them off, and a card that computed its own copy of
    that would be right until the day the rule moved — and would then quote a
    figure the row it created does not carry.

    Both callers go through here, which is what makes the institution check
    below hold on both sides: `propose` cannot draw a card the ledger would
    refuse, and `run` cannot write one after the last institution was deleted
    out from under a card already drawn."""
    institution = _institution(db, args.institution)
    cash_institution = _institution(db, args.cash_institution)
    settles = _settled_position(db, args, institution) if args.kind in _DISPOSALS else None
    # A disposal that named no institution and matched exactly one position:
    # that position's institution is the answer, and leaving it null instead
    # would take the cash out of nowhere.
    if institution is None and settles is not None and settles.institution_id is not None:
        institution = crud.get_institution(db, settles.institution_id)
    # And when nothing supplied one, the entry is refused rather than drawn.
    #
    # This closes the same hole the form's required select closes, at the other
    # door. A row with no institution on either column is skipped by the cash
    # register — it keeps the entries belonging to the institution it is
    # computing, and null matches none of them — while the position it creates
    # is counted in full, so the purchase adds its own cost to the net worth
    # instead of moving it. Measured at 1000 cash: a 100 buy naming nobody took
    # the net worth to 1100.
    #
    # Refused the way `_institution` refuses a name it does not know, and for
    # the same reason: the model reads this and can correct itself on the next
    # round trip, which it cannot do with a card that was never wrong enough to
    # stop. Until now the guarded path was the HARSHER one going in — a name
    # not on record was refused while silence was accepted — which is backwards.
    #
    # It catches one case beyond the buy: a disposal of a position that is
    # itself held at no institution (the PAC makes those) has nothing for the
    # adoption above to adopt, so it is refused too. That leaves such a
    # position with no exit through the chat — it had one before, and it wrote
    # a double-null row that destroyed value the same way a buy created it, so
    # the refusal is the better of the two. Giving those positions a real home
    # is the separate decision this commit deliberately did not take.
    if institution is None:
        have = ", ".join(i.name for i in crud.get_institutions(db)) or (
            "none yet, and one has to exist before an entry can name it"
        )
        raise LookupError(
            f"A {args.kind} has to say where the position is held: the cash "
            f"moves against a real account, and an entry that names none "
            f"spends money nothing ever loses. On record: {have}."
        )
    create = schemas.TransactionCreate(
        kind=args.kind,
        date=args.date,
        institution_id=institution.id if institution else None,
        cash_institution_id=cash_institution.id if cash_institution else None,
        asset_name=args.asset_name.strip(),
        symbol=(args.symbol.strip() if args.symbol else None),
        isin=args.isin,
        asset_class=args.asset_class,
        quantity=args.quantity,
        unit_price=args.unit_price,
        fees=args.fees,
        amount=args.amount,
        currency=_stored_currency(args.currency),
        price_currency=_stored_currency(args.price_currency) if args.price_currency else None,
        note=args.note,
    )
    try:
        payload = crud._transaction_payload(db, create)
    except crud.LedgerRateUnknown as exc:
        # Refused the way an unknown institution is: the model reads it and
        # can ask the reader for the figure on their statement.
        raise LookupError(str(exc)) from exc
    return _Ledger(
        create=create,
        institution=institution,
        cash_institution=cash_institution,
        settles=settles,
        amount=payload["amount"],
        fx_as_of=payload["fx_as_of"],
    )


def _propose_transaction(db: Session, args: RecordTransactionArgs) -> Proposal:
    """The entry as the reader will read it, and what it depends on.

    The fingerprint carries the two institutions by id and, for a disposal,
    what the records currently say is held — the same figure the title quotes,
    so the card and the sentence the reader believed go stale together. A buy
    or a dividend appends and overwrites nothing, so there is no held figure in
    either the title or the fingerprint, and saying so is the claim.

    A rename or a deletion needs no entry of its own. `_institution` and
    `_settled_position` simply stop resolving, `settle` cannot redraw the card
    at all, and a card that can no longer be drawn is the strongest form of
    stale there is."""
    entry = _ledger_entry(db, args)
    what = entry.create.symbol or entry.create.asset_name
    cash = f"{entry.amount:.2f} {entry.create.currency}"
    if entry.fx_as_of:
        # A debit worked out here, not read off a statement: the card says so,
        # and says which day's rate, so the reader can check it against theirs.
        cash += f" (at the ECB rate of {entry.fx_as_of})"
    if args.kind == "close":
        body = f"{what} — {cash} back"
    elif args.kind == "dividend":
        body = f"{what} — {cash} on {args.quantity:g} units"
    else:
        body = (
            f"{args.quantity:g} {what} @ {args.unit_price:.2f} "
            f"{entry.create.price_currency} = {cash}"
        )
    where = f" · {entry.institution.name}" if entry.institution else ""
    parts = [
        f"inst={entry.institution.id if entry.institution else None}",
        f"cash={entry.cash_institution.id if entry.cash_institution else None}",
    ]
    held = ""
    if entry.settles is not None:
        qty = entry.settles.quantity
        held = (
            f" (the records show {qty:g} units held)"
            if qty is not None
            else " (the records do not say how many units are held)"
        )
        parts.append(f"settles={entry.settles.symbol or entry.settles.asset_name}")
        parts.append(f"held={'none' if qty is None else format(qty, '.6f')}")
    return Proposal(
        title=f"record {args.kind}: {body}{where} · {args.date.isoformat()}{held}",
        fingerprint="|".join(parts),
    )


def _record_transaction(db: Session, args: RecordTransactionArgs) -> dict:
    """The row, through the same door the form posts through.

    Resolved a second time rather than carried over from the proposal.
    `settle` redraws the card immediately before this runs and refuses if
    anything it depends on moved, so both resolutions read the same records —
    and nothing has to be smuggled from one call to the other through a
    dataclass that would then be the real argument list."""
    entry = _ledger_entry(db, args)
    tx = crud.create_transaction(db, entry.create)
    return {
        "transaction_id": tx.id,
        "kind": tx.kind,
        "date": tx.date,
        "asset_name": tx.asset_name,
        "symbol": tx.symbol,
        "quantity": tx.quantity,
        "unit_price": tx.unit_price,
        "fees": tx.fees,
        "amount": tx.amount,
        "currency": tx.currency,
        "price_currency": tx.price_currency,
        "fx_as_of": tx.fx_as_of,
        "institution": entry.institution.name if entry.institution else None,
    }


_TRANSACTION_LABELS = {
    "kind": "Entry",
    "date": "Date",
    "asset_name": "Asset",
    "symbol": "Ticker",
    "isin": "ISIN",
    "asset_class": "Class",
    "quantity": "Units",
    "unit_price": "Price",
    "fees": "Fees",
    "currency": "Cash in",
    "price_currency": "Price in",
    "amount": "Amount",
    "institution": "Held at",
    "cash_institution": "Cash from",
    "note": "Note",
}


def _transaction_receipt(result: dict) -> list[tuple]:
    """The amount the app worked out and the day of the rate it took, which
    the card's own fields cannot show."""
    return [
        ("Amount", result.get("amount"), "amount", result.get("currency")),
        ("At the ECB rate of", result.get("fx_as_of"), "date"),
        ("Held at", result.get("institution"), "text"),
    ]


# --- update_profile ----------------------------------------------------------

# The Profile form's own questions as the model is told them: each one's key,
# its wording and what it takes, from the list the form draws itself from. A
# question nobody has answered yet is nowhere in the picture, so without this
# the model could neither name it nor know that it takes yes or no.
_FORM_QUESTIONS = "; ".join(
    f'{q.key} "{q.text}" ({questionnaire.takes(q)})' for q in questionnaire.QUESTIONS
)


class UpdateProfileArgs(BaseModel):
    """One answer in the reader's questionnaire, written by key."""

    question: str = Field(
        ...,
        min_length=1,
        description=(
            "The question this answers. For a question of the Profile form, its "
            "wording as listed under question_key. To CHANGE something already "
            "on record, copy its wording from the profile section of the picture "
            "you were given, exactly: a paraphrase files a second copy of the "
            "same question under a new name. To record something the form never "
            "asked, write the question you actually put to the reader."
        ),
    )
    answer: str = Field(
        ...,
        min_length=1,
        description=(
            "What they said, in their words, not summarised into a category. "
            "The questionnaire is already full of boxes; what it is missing is "
            "what a box cannot hold. A question of the Profile form takes only "
            "what its entry under question_key says, written as it is written "
            "there, and anything else is refused."
        ),
    )
    topic: MaybeText = Field(
        default=None,
        description=(
            "Which heading to file a NEW question under: reuse one already in "
            "the profile section when it fits. Ignored for a question that is "
            "already on record, and for one of the Profile form's: those keep "
            "the topic they have."
        ),
    )
    question_key: MaybeText = Field(
        default=None,
        description=(
            "For a question of the Profile form, its key; null for any other "
            "question, which the question above then identifies. The form's "
            "questions, as key, wording and what each takes: " + _FORM_QUESTIONS + "."
        ),
    )


def _key(text: str) -> str:
    """A question reduced to the shape a `question_key` has.

    Two jobs, and them being one function is the point: it mints the key for a
    question the form never asked, and it is the comparison that finds the row
    a question already has. So "Your age?" and "your age" reach the same row,
    and a new key cannot be minted for a question that is already there under a
    spelling differing only in punctuation."""
    letters = "".join(c if c.isalnum() else " " for c in text.casefold())
    return "_".join(letters.split())[:60].strip("_")


def _profile_row(
    db: Session, args: UpdateProfileArgs
) -> tuple[str, models.SurveyResponse | None]:
    """The key this answer belongs under, and the row already there, if any.

    A question of the Profile form is found by its key, or by its wording even
    while nobody has answered it: it has no row to be found by then, and a
    first answer to "Your age?" used to be filed under a key minted from those
    words, which the form never shows and nothing checks. The form's question
    wins over a row of the chat's that happens to read the same."""
    rows = crud.get_survey_responses(db)
    if (args.question_key or "").strip():
        key = _key(args.question_key)
    else:
        wanted = _key(args.question)
        form = next((q.key for q in questionnaire.QUESTIONS if _key(q.text) == wanted), None)
        match = next((r for r in rows if r.question and _key(r.question) == wanted), None)
        key = form or (match.question_key if match is not None else wanted)
    if not key:
        raise ValueError(f"{args.question!r} has no letters or digits to make a key from.")
    return key, next((r for r in rows if r.question_key == key), None)


def _stored_answer(key: str, answer: str) -> str:
    """The answer as it is written under `key`: as the form stores it when the
    Profile form asks that question (`questionnaire.fit`, which refuses what
    the question does not take), else the words as they were given."""
    form = questionnaire.BY_KEY.get(key)
    return questionnaire.fit(form, answer) if form is not None else answer.strip()


# What an overwritten answer costs, said on the card. Not the snapshot
# sentence: a survey answer carries the day it was recorded and no history,
# and nothing is anchored after it to move. There is only the previous answer
# and its day, and afterwards there is not.
_PROFILE_CONSEQUENCE = (
    "This replaces the answer on record and the day it was recorded. Answers are "
    "not kept in history, so the previous one does not survive anywhere."
)


def _propose_profile(db: Session, args: UpdateProfileArgs) -> Proposal:
    """A new answer is an append; a changed one is a rewrite, and the two do
    not get the same confirmation.

    The rule is `Proposal`'s own and it is about REVERSIBILITY, not about size
    or about which table is touched. Answering a question nobody had answered
    adds a row and takes nothing away — light. Changing one destroys the only
    copy of what the reader used to say, and the confidant reads exactly this
    text to work out who they are, so it gets the diff.

    The fingerprint is what that question says NOW, which is also what the diff
    was drawn from: the two go stale together, so a card can never be confirmed
    against a sentence other than the one the reader was shown.

    A question of the Profile form is drawn with the form's own wording, and
    only with an answer it takes: anything else is refused before any card is
    drawn (`questionnaire.AnswerRefused`)."""
    key, row = _profile_row(db, args)
    answer = _stored_answer(key, args.answer)
    form = questionnaire.BY_KEY.get(key)
    if row is not None and row.question:
        asked = row.question.strip()
    else:
        asked = (form.text if form is not None else args.question).strip()
    if row is None or not (row.answer or "").strip():
        return Proposal(
            title=f"profile · {asked}: {answer}",
            fingerprint=f"{key}=<unanswered>",
        )
    return Proposal(
        title=f"profile · {asked}: {row.answer} → {answer}",
        fingerprint=f"{key}={row.answer}",
        confirmation="diff",
        consequence=_PROFILE_CONSEQUENCE,
        diff=[{"field": asked, "now": row.answer, "proposed": answer}],
    )


def _update_profile(db: Session, args: UpdateProfileArgs) -> dict:
    """One answer, by key, leaving the other twenty-six where they are.

    `crud.upsert_survey_response` is the only write path that can say that.
    The other one deletes the whole questionnaire and reinserts it, which is
    right for a form rendering every question and wrong for anything that knows
    about one.

    A question already on record keeps its own wording and its own topic: the
    form owns those, and letting a paraphrase from a conversation rewrite the
    label would change the question under an answer given to the old one. A
    question of the Profile form answered for the first time takes the form's
    wording and topic, and only an answer the form would store."""
    key, row = _profile_row(db, args)
    answer = _stored_answer(key, args.answer)
    form = questionnaire.BY_KEY.get(key)
    fresh = row is None or not row.question
    # Read off the row BEFORE the write. `upsert_survey_response` mutates this
    # same identity-mapped instance, so asking it afterwards what it used to
    # say returns what it says now — a receipt that reports the change as
    # having replaced itself.
    replaced = row.answer if row is not None else None
    if form is not None:
        question, topic = form.text, form.topic
    else:
        question, topic = args.question.strip(), (args.topic or "").strip() or None
    saved = crud.upsert_survey_response(
        db,
        key,
        answer,
        question=question if fresh else None,
        topic=topic if fresh else None,
    )
    return {
        "question_key": saved.question_key,
        "topic": saved.topic,
        "question": saved.question,
        "answer": saved.answer,
        "replaced": replaced,
    }


_PROFILE_LABELS = {
    "question": "Question",
    "answer": "Answer",
    "topic": "Topic",
    # The app's key for a question, not a word of the reader's: not shown.
    "question_key": "",
}


def _profile_receipt(result: dict) -> list[tuple]:
    return [
        ("Answer now", result.get("answer"), "text"),
        ("It replaced", result.get("replaced") or "nothing, it is a new answer", "text"),
    ]


# --- suggest_instrument -------------------------------------------------------
#
# The one card that is NOT a write to the reader's records. Accepting it moves
# no total, no allocation and no cash projection: it parks an idea, with what
# the idea rested on, on a list that owns nothing. That is why a model is
# allowed to raise it at all — and why its accept button says what it does
# rather than "Confirm".
#
# The identity comes from the CATALOGUE and the argument model is built so that
# it cannot come from anywhere else. The tool takes an ISIN and no name: the
# name, the charge, the domicile and the distribution policy are all read off
# the row here, so the worst a model can do is name a fund that does not exist,
# which is refused, rather than attach a real ISIN to a wrong description. The
# hallucinated ticker — the classic defect of a chatbot that talks about funds
# — has nowhere to enter.
#
# `symbol` is the exception and it is optional, unverified, and labelled as
# such. Nothing offline can confirm that a Yahoo symbol exists, and verifying
# it with a network call would make the card go "stale" every time Yahoo is
# slow, which is a lie about what staleness means. So it travels as a hint
# beside a checkable ISIN, and never as the thing being watched.


class SuggestInstrumentArgs(BaseModel):
    """One instrument worth looking at, and the three things that have to
    travel with it: a fund by its ISIN from the catalogue, or a single share by
    the symbol Yahoo lists it under."""

    isin: MaybeText = Field(
        default=None,
        min_length=12,
        max_length=12,
        description=(
            "For a FUND: its ISIN, copied EXACTLY from a `search_catalogue` "
            "result. Never written from memory: an ISIN that is not in the "
            "local registry is refused, which is the point. Search first. Null "
            "for a single share."
        ),
    )
    reason: str = Field(
        ...,
        min_length=1,
        description=(
            "Why THIS one, in a sentence or two. Not a description of the "
            "fund (the card already carries its charge, domicile and policy "
            "from the registry) but what it would do in this reader's "
            "situation."
        ),
    )
    based_on: str = Field(
        ...,
        min_length=1,
        description=(
            "What the reader has DECLARED that this rests on: a position they "
            "hold, an answer in their questionnaire, a goal, something they "
            "said in this conversation. Name it specifically. If nothing in "
            "the picture supports the idea, do not propose it."
        ),
    )
    unknowns: str = Field(
        ...,
        min_length=1,
        description=(
            "What you do NOT know that would change this: their tax "
            "situation, a horizon they never gave, whether they already hold "
            "something equivalent elsewhere. This is the field a suggestion "
            "gets wrong by leaving comfortable: it is read again in a month, "
            "when what was missing is the whole question."
        ),
    )
    symbol: MaybeText = Field(
        default=None,
        description=(
            "For a single SHARE: the exact symbol of a `lookup_symbol` result "
            "whose quote_type is equity, with `isin` null. The app asks Yahoo "
            "about it again and takes the name from there. For a FUND: "
            "optional, a quotable symbol from `lookup_symbol` and ONLY from "
            "there, never the registry's `base_ticker`, which is not a Yahoo "
            "symbol; it is stored as a hint for the reader to check."
        ),
    )

    @model_validator(mode="after")
    def _names_one_instrument(self):
        if not self.isin and not (self.symbol or "").strip():
            raise ValueError("Name a fund by its ISIN, or a single share by its symbol.")
        return self


_POLICY_WORDS = schemas.POLICY_WORDS

# What accepting a suggestion does, said on the card. The whole sentence is
# that nothing happens to their money: this is the one card whose confirmation
# writes no record of theirs, and the reader has spent four other cards
# learning that pressing the button changes the figures.
_WATCH_CONSEQUENCE = (
    "Nothing about your money changes. This parks the idea, with the reasoning "
    "above, on your watchlist: no position, no total and no projection moves, "
    "and no broker is connected to this app in any case."
)


def _catalogue_row(db: Session, isin: str) -> models.Instrument:
    """The registry row for an ISIN, or a refusal that says which kind it is.

    Two different refusals, because they have two different remedies and
    presenting one as the other is the mistake this app names everywhere else:
    an empty registry means nothing has been downloaded yet, and a missing row
    in a full registry means this ISIN is not among the funds it holds. Neither
    is "that fund does not exist"."""
    key = (isin or "").strip().upper()
    row = db.get(models.Instrument, key)
    if row is not None:
        return row
    state = catalogue.status(db)
    if not state["rows"]:
        raise LookupError(
            "The local fund registry is empty: "
            + _where_the_download_stands(state)
            + ". Nothing can be suggested from it until it arrives, and this is "
            "not a statement about the fund. Say so in plain words and offer "
            "no card."
        )
    raise LookupError(
        f"{key!r} is not in the local registry ({state['rows']} funds, "
        f"downloaded {state['fetched_at']}). A suggestion may only name a row "
        "`search_catalogue` returned: search for it by name and copy the ISIN "
        "from the result. Do not write one from memory."
    )


def _twin(db: Session, row: models.Instrument) -> models.Instrument | None:
    """The same fund's other share class, if it has one.

    `catalogue.search` returns families precisely so a twin is never shown
    alone — showing one of a pair invites picking the wrong one without ever
    revealing there was a choice — and a card is the narrowest result list
    there is, so the pair has to be named on it too."""
    siblings = (
        db.query(models.Instrument)
        .filter(
            models.Instrument.family_key == row.family_key,
            models.Instrument.isin != row.isin,
        )
        .order_by(models.Instrument.isin)
        .all()
    )
    return siblings[0] if siblings else None


def _registry_facts(row: models.Instrument) -> list[str]:
    """The card's figures, all of them read off the row and none of them
    written by the model."""
    facts = []
    policy = _POLICY_WORDS.get((row.distribution_policy or "").strip().lower())
    if policy:
        facts.append(policy)
    if row.ter is not None:
        facts.append(f"TER {row.ter}%")
    if row.domicile:
        facts.append(row.domicile)
    if row.size_meur:
        facts.append(f"{int(row.size_meur):,} M EUR".replace(",", " "))
    return facts


# A symbol shaped like an ISIN, with or without an exchange's suffix. On
# 2026-10-06 Yahoo listed two Eni bonds only as IT0005521171.SG and
# XS1023703090.SG, on Stuttgart, typed "equity" and with no name; a share
# trades under a ticker, never under its ISIN.
_ISIN_SYMBOL = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9](\.[A-Z]+)?")

# What a share's card says beside what accepting it does.
_SHARE_NAMED = (
    " Yahoo lists it under this symbol, asked just now, and gives no ISIN, so "
    "the symbol is what names it on your watchlist. A charge and a domicile "
    "are a fund's, and a share has neither."
)


def _listed_share(symbol: str | None) -> dict:
    """The share Yahoo lists under exactly `symbol`, asked now, or a refusal
    that says which kind of no it is.

    Each refusal has its own remedy. Yahoo did not answer: that says nothing
    about the share, so no card until it does. It lists nothing there: look it
    up and copy the symbol. It lists a fund there: a fund's card comes from the
    catalogue, by ISIN, which is what keeps out a fund a saver in Europe cannot
    buy. It lists something that is not a share: a coin, a future, an index, or
    a bond quoted under its ISIN, none of which gets a card.

    Yahoo's own type is not taken alone. On 2026-10-06 it typed VOOY, named
    "XFUNDS Large Cap Income ETF", as an equity, and the two bonds above too;
    so a name that says ETF, a symbol that is an ISIN and a listing with no
    name are refused as well."""
    wanted = (symbol or "").strip().upper()
    try:
        found = prices.listing(wanted)
    except prices.MarketUnreachable as exc:
        raise LookupError(
            f"Yahoo did not answer just now ({exc}). That says nothing about "
            f"whether {wanted} exists: offer no card for it until Yahoo answers, "
            "and say so in plain words."
        ) from exc
    if found is None:
        raise LookupError(
            f"Yahoo lists nothing under {wanted!r}. A card for a share takes the "
            "exact symbol a `lookup_symbol` result gave: look it up and copy it."
        )
    kind = (found.get("quote_type") or "").lower()
    name = found.get("name") or ""
    if kind in ("etf", "mutualfund") or re.search(r"\bETF\b", name, re.IGNORECASE):
        raise LookupError(
            f"Yahoo lists {wanted} ({name or 'no name'}) as a fund, not a share. "
            "A fund gets a card only from the catalogue, by its ISIN: search for "
            "it there. One the catalogue does not hold (a fund domiciled outside "
            "the EU has no KID, so a saver in Europe cannot buy it) gets no card, "
            "and the reader is told why."
        )
    if _ISIN_SYMBOL.fullmatch(wanted):
        raise LookupError(
            f"{wanted} is an ISIN, which is how Yahoo quotes bonds and funds on "
            "some exchanges, never a share's ticker. A single bond gets no card: "
            "nothing in this app can verify one."
        )
    if kind != "equity":
        raise LookupError(
            f"Yahoo lists {wanted} as {kind or 'something it does not name'}, not "
            "as a share. A card names a fund from the catalogue or a share; a "
            "coin, a future or an index gets none."
        )
    if not name:
        raise LookupError(
            f"Yahoo lists {wanted} with no name, so a card could not say what it "
            "is. Offer no card for it."
        )
    return found


def _propose_suggestion(db: Session, args: SuggestInstrumentArgs) -> Proposal:
    """An idea, drawn from the registry row or the Yahoo listing it names.

    Refuses outright when the ISIN is already on the watchlist: suggesting
    something that is already there is not a second idea, it is the same one,
    and a duplicate whose only difference is which day it was written makes the
    list worse to read in exactly the month it exists to help.

    The fingerprint is what the registry says about this fund RIGHT NOW — the
    same fields the title quotes. The catalogue is replaced wholesale on every
    refresh, so a fund can leave the market or change its charge between the
    proposal and the confirmation, and when it does the card stops describing
    what the reader was shown. Card and title go stale together, which is the
    only rule a test can pin. A share has its own: `_propose_share`."""
    if not args.isin:
        return _propose_share(db, args)
    row = _catalogue_row(db, args.isin)
    watched = crud.find_watchlist_item(db, isin=row.isin)
    if watched is not None:
        raise ValueError(
            f"{row.name} ({row.isin}) is already on the watchlist, added "
            f"{watched.added_at}, because: {watched.reason}"
        )
    facts = _registry_facts(row)
    twin = _twin(db, row)
    consequence = _WATCH_CONSEQUENCE
    if twin is not None:
        other = _POLICY_WORDS.get(
            (twin.distribution_policy or "").strip().lower(), "another"
        )
        consequence += (
            f" The same fund also exists as {'an' if other[0] in 'aeiou' else 'a'} "
            f"{other} share class ({twin.isin}); this card is for the one named "
            "above."
        )
    return Proposal(
        title=(
            f"watch: {row.name}, {row.isin}"
            + (" · " + " · ".join(facts) if facts else "")
        ),
        fingerprint=(
            f"{row.isin}|{row.name}|{row.ter}|{row.distribution_policy}|{row.domicile}"
        ),
        consequence=consequence,
        verb="Add to watchlist",
    )


def _propose_share(db: Session, args: SuggestInstrumentArgs) -> Proposal:
    """A single share, drawn from what Yahoo lists under its symbol now.

    The fingerprint is Yahoo's answer: confirming asks again, as a fund's
    confirmation reads the registry again, so a listing that changed in
    between refuses the card, and one Yahoo is silent about leaves it pending.
    Refused outright when the share is already on the watchlist, for the
    reason a fund is."""
    share = _listed_share(args.symbol)
    watched = crud.find_watchlist_item(db, symbol=share["symbol"])
    if watched is not None:
        raise ValueError(
            f"{watched.name} ({watched.symbol}) is already on the watchlist, added "
            f"{watched.added_at}, because: {watched.reason}"
        )
    where = f" · {share['exchange']}" if share.get("exchange") else ""
    return Proposal(
        title=f"watch: {share['name']}, {share['symbol']} · share{where}",
        fingerprint=(
            f"{share['symbol']}|{share['name']}|{share.get('exchange')}|"
            f"{share.get('quote_type')}"
        ),
        consequence=_WATCH_CONSEQUENCE + _SHARE_NAMED,
        verb="Add to watchlist",
    )


def _suggest_instrument(db: Session, args: SuggestInstrumentArgs) -> dict:
    """Park the idea. One row, and every identifying field on it read off the
    registry, or off Yahoo for a share, rather than off the arguments: the
    model chose which instrument, not what it is called.

    A share asks Yahoo once more here, a second or so after the confirmation's
    own check. Nothing is written before it answers, and the transaction opens
    at the first write (`database.unit_of_work`), so no lock is held while it
    waits."""
    if args.isin:
        row = _catalogue_row(db, args.isin)
        isin, symbol, name = row.isin, ((args.symbol or "").strip().upper() or None), row.name
    else:
        share = _listed_share(args.symbol)
        isin, symbol, name = None, share["symbol"], share["name"]
    item = crud.create_watchlist_item(
        db,
        schemas.WatchlistItemCreate(
            isin=isin,
            symbol=symbol,
            name=name,
            reason=args.reason.strip(),
            based_on=args.based_on.strip(),
            unknowns=args.unknowns.strip(),
        ),
    )
    return {
        "watchlist_id": item.id,
        "isin": item.isin,
        "symbol": item.symbol,
        "name": item.name,
        "added_at": item.added_at,
    }


_SUGGESTION_LABELS = {
    "isin": "ISIN",
    "symbol": "Ticker",
    "reason": "Why this one",
    "based_on": "Rests on",
    "unknowns": "Not known",
}


def _suggestion_receipt(result: dict) -> list[tuple]:
    return [
        ("On your watchlist since", result.get("added_at"), "date"),
        ("Ticker", result.get("symbol"), "text"),
    ]


# --- The analysis, run as sub-agents and read back ----------------------------
#
# The chat is the ORCHESTRATOR of the chain now, and the rule it orchestrates
# under is the one thing about the chain that cannot bend: the analyst sees the
# portfolio and not the person, the confidant sees the person and not one
# figure. `chain.run_chain` guarantees that by construction — two builder
# functions, `advisor.build_portfolio_context` and `advisor.build_person_context`
# — and nothing here may add a third door. In particular NOTHING FROM THE
# CONVERSATION reaches a sub-agent: a model asked to brief a colleague
# summarises, a summary carries the numbers across, and two models that have
# seen the same things converge into the agreeable mush the chain exists to
# prevent. Which is also why `run_analysis` takes no arguments at all — a
# `focus` field would be the orchestrator writing the sub-agents' prompts, one
# sentence at a time.


class RunAnalysisArgs(BaseModel):
    """What `run_analysis` takes: NOTHING, and that is a decision.

    Every argument this could have (what to look at, what to weigh, what the
    reader is worried about) is the orchestrator telling the sub-agents what
    to think, and their whole value is that they were not told. What they read
    comes from a builder function or it does not come at all.
    """


def _seconds(run: models.ChainRun | None) -> int | None:
    """How long a run took, from the steps it persisted. None when nothing has
    run, or when a run predates the durations being recorded — an absence, not
    a zero."""
    if run is None:
        return None
    known = [s.duration_ms for s in run.steps if s.duration_ms is not None]
    return round(sum(known) / 1000) if known else None


def _spent(run: models.ChainRun | None) -> float | None:
    """What a run cost, in USD, or None if any step did not say.

    All or nothing on purpose. A sum over only the steps that reported a price
    is a number smaller than the truth printed with the confidence of a total,
    and the one thing this app does not do is show a figure that is missing
    part of itself without saying so.
    """
    if run is None or not run.steps:
        return None
    costs = [s.cost for s in run.steps]
    return round(sum(costs), 4) if all(c is not None for c in costs) else None


def _propose_analysis(db: Session, args: RunAnalysisArgs) -> Proposal:
    """The card that asks before the spend, quoting measurements only.

    Three things the reader is owed before a minute of their attention goes:
    how many model calls, how long the last one took, and what it cost. The
    first is a fact about the code; the other two are read off the last run and
    left out entirely when there has never been one — "about a minute, a few
    cents" would be a guess printed as a fact, and the reader would have no way
    to tell it from the measured version of the same sentence.
    """
    run = crud.get_latest_chain_run(db)
    took, spent = _seconds(run), _spent(run)
    engines = sorted(
        {
            advisor.resolve_model(chain._model_for("analyst")),
            advisor.resolve_model(chain._model_for("confidant")),
        }
    )

    measured = []
    if took is not None:
        measured.append(f"took {took}s")
    if spent is not None:
        measured.append(f"cost ${spent:g}")
    last = (
        f"The last run {' and '.join(measured)}."
        if measured
        else "Nothing has run yet, so there is no measured time or cost to quote."
    )

    return Proposal(
        title="Run the analyzer over everything on record",
        fingerprint=_DEPENDS_ON_NOTHING,
        consequence=(
            f"{chain.MIN_STEPS} model calls, up to {chain.MAX_STEPS} if the "
            f"disagreement is real, on {' and '.join(engines)}. {last} A step "
            "OpenRouter turns away with 500, 502 or 503, which it says it does not "
            "bill, is asked once more."
        ),
    )


def _walk_analysis(db: Session, args: RunAnalysisArgs) -> Iterator[Working]:
    """The chain, reported step by step, returning what the orchestrator gets
    back.

    What comes back is deliberately NOT the verdict. The verdict is a document
    — the synthesis is written to be one — and a document in a tool result is a
    document in the card, in a 32%-wide column, and then in the history of
    every turn after it for as long as the conversation lives, sitting at the
    same prominence as the picture rebuilt this second. A past opinion at full
    length is how today's question gets answered with last month's conclusion.
    So the result carries what is bounded and always relevant — when it ran,
    how deep it went, what it cost — plus its opening lines and the id to read
    the rest with. `read_analysis` is the door to the whole of it, and a turn
    that walks through it pays for the document once and never again.
    """
    walk = chain.run_chain(db)
    while True:
        try:
            step = next(walk)
        except StopIteration as done:
            run = done.value
            break
        # A step OpenRouter turned away once and that was asked again says so
        # on its own line, where the reader reads the run as it goes.
        label = f"{step.title} ({step.asked_again})" if step.asked_again else step.title
        yield Working(step_no=step.step_no, label=label, duration_ms=step.duration_ms)

    return {
        "run_id": run.id,
        "finished": run.created_at,
        "steps": len(run.steps),
        "revision_rounds": sum(1 for s in run.steps if s.role == "revision"),
        "seconds": _seconds(run),
        "cost_usd": _spent(run),
        "opening": opening(run.verdict),
        "read_in_full": (
            f"That is the opening of it. Call read_analysis with "
            f"run_id={run.id} for the whole verdict."
        ),
    }


def _analysis_receipt(result: dict) -> list[tuple]:
    """How deep, how long and how much: the verdict itself is a link away."""
    seconds = result.get("seconds")
    return [
        ("Steps", result.get("steps"), "number"),
        ("Took", f"{seconds} s" if seconds is not None else None, "text"),
        ("Cost", result.get("cost_usd"), "amount", "USD"),
    ]


# How much of a verdict travels as its digest. Enough for the opening claim of
# a document that leads with what to do; short enough that a conversation
# carrying it on every turn is carrying a paragraph and not a report.
OPENING_CHARS = 400


def opening(verdict: str | None) -> str:
    """The first lines of a verdict, cut at a line boundary, saying it was cut.

    An excerpt and never a summary. Summarising an analysis is another model
    call with another chance to move a number; the opening of a document
    written to lead with what to do is the informative part of it anyway, and
    it can be quoted because it is quoted verbatim.
    """
    text = (verdict or "").strip()
    if len(text) <= OPENING_CHARS:
        return text
    cut = text[:OPENING_CHARS]
    line = cut.rfind("\n")
    return (cut[:line] if line > OPENING_CHARS // 2 else cut).rstrip() + " […]"


class ReadAnalysisArgs(BaseModel):
    """What `read_analysis` takes: which run to read."""

    run_id: int = Field(
        description=(
            "The id of the run, as the picture or a confirmed card names it. "
            "The picture in this conversation carries the id of the latest one."
        )
    )


def _read_analysis(db: Session, args: ReadAnalysisArgs) -> dict:
    """One run's verdict, whole, plus what it took to get there.

    The second deliberate exception to "reading needs no tools", and it is the
    same exception as the look-through reached by a different road. That rule
    is about the reader's OWN data: bounded, always relevant, worth sending
    every turn. A past analysis fails "always relevant" — it matters in one
    conversation out of ten — and fails "bounded", because it is a document
    somebody's model wrote at whatever length it liked.

    The steps come back as titles and measurements, not as their text. What
    each role wrote is four more documents, and the reader can open the whole
    argument on the page; a model that pulled all of it into its context would
    be paying for the chain's reasoning to answer a question about its
    conclusion.
    """
    run = db.get(models.ChainRun, args.run_id)
    if run is None:
        latest = crud.get_latest_chain_run(db)
        raise LookupError(
            f"There is no analysis run with id {args.run_id}. "
            + (f"The most recent one is {latest.id}." if latest else "None has ever been run.")
        )
    return {
        "run_id": run.id,
        "finished": run.created_at,
        "verdict": run.verdict,
        "steps": [
            {
                "step_no": s.step_no,
                "role": s.role,
                "title": s.title,
                "model": s.model,
                "seconds": None if s.duration_ms is None else round(s.duration_ms / 1000, 1),
            }
            for s in run.steps
        ],
        "reading": (
            "The verdict is what was written to the reader. The steps are the "
            "argument behind it: the analyst judged the portfolio without "
            "knowing whose it was, someone who knows them challenged it "
            "without seeing a figure, and a revision step exists only where "
            "that challenge was contested."
        ),
    }


REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            name="get_look_through",
            description=(
                "What the reader's funds are made of underneath: the country, "
                "sector and currency weights of the investments as a whole "
                "(not the cash on the accounts) seen through the funds, the "
                "largest single companies held, and "
                "which companies sit inside more than one position. Use it "
                "when the question is about exposure held THROUGH a fund "
                "('how much NVIDIA do I own in total', 'do these two ETFs "
                "overlap', 'how much of me is America'), none of which the "
                "financial picture in the conversation can answer, because it "
                "lists positions and not what is inside them. Always reports "
                "what it could NOT look inside."
            ),
            arguments=LookThroughArgs,
            run=_look_through,
        ),
        Tool(
            name="search_catalogue",
            description=(
                "Search the LOCAL registry of UCITS funds and ETFs by name, "
                "issuer, index or ticker. Instant and offline (it is a SQLite "
                "table, not a web search), and it is the only place an ISIN "
                "may come from: a fund you name from memory is a fund that "
                "might not exist, and this is what makes the difference "
                "checkable. Use it when the reader asks what is available, "
                "what a fund's charge or domicile is, or before suggesting "
                "anything. Results come back as FAMILIES: the accumulating "
                "fund and its distributing twin share a name and are always "
                "shown together, so say which one you mean."
            ),
            arguments=SearchCatalogueArgs,
            run=_search_catalogue,
        ),
        Tool(
            name="lookup_symbol",
            description=(
                "Find a quotable SYMBOL for shares, single stocks, crypto and "
                "futures: everything the fund registry does not hold, and the "
                "only source of a ticker that actually prices. A network call "
                "of a few seconds, and deliberately separate from "
                "`search_catalogue` so a slow or dead source can never empty a "
                "result the local registry already had. Use it when the reader "
                "asks what something trades as, to attach a symbol to a fund "
                "you are suggesting, or to find the exact symbol of a share "
                "before you suggest it. An empty answer can mean the source "
                "did not reply: check `reachable` before saying an "
                "instrument does not exist."
            ),
            arguments=LookupSymbolArgs,
            run=_lookup_symbol,
        ),
        Tool(
            name="add_real_asset",
            description=(
                "Propose recording something the reader owns OUTRIGHT, held "
                "at no institution (a piece of jewellery, a car, a flat, a "
                "painting), together with what it is worth today. Two rows: "
                "the asset, and the dated valuation that says what it is "
                "worth, because a possession with no valuation counts as zero "
                "everywhere it is totalled. Use it when the reader tells you "
                "they have or were given something that is not in the picture. "
                "It does not write: it draws a card they confirm."
            ),
            arguments=AddRealAssetArgs,
            run=_add_real_asset,
            propose=_propose_real_asset,
            labels=_REAL_ASSET_LABELS,
            receipt=_real_asset_receipt,
        ),
        Tool(
            name="record_transaction",
            description=(
                "Propose one entry in the investment ledger for something that "
                "has ALREADY happened: a purchase, a sale, a dividend "
                "received, or the closing of a position. No broker is "
                "connected to this app, so nothing here places a trade: "
                "'buying from the chat' means recording the purchase you "
                "already made, after the fact. Use it when the reader says "
                "they bought, sold, closed something or were paid a dividend. "
                "It does not write: it draws a card they confirm."
            ),
            arguments=RecordTransactionArgs,
            run=_record_transaction,
            propose=_propose_transaction,
            labels=_TRANSACTION_LABELS,
            receipt=_transaction_receipt,
        ),
        Tool(
            name="update_profile",
            description=(
                "Propose writing ONE answer to the reader's questionnaire, "
                "the profile the analyses read to know who they are. Two uses, "
                "and the second is the one that matters: correcting an answer "
                "that has changed, and recording something the form never "
                "thought to ask, in the reader's own words. The form is 27 "
                "boxes; a temperament does not fit in a box. Use it when the "
                "conversation tells you something durable about them (how "
                "they behaved when the market fell, what they would never give "
                "up), not for a passing remark. It does not write: it draws a "
                "card they confirm, and changing an answer that already exists "
                "shows them what it would replace. A question of the Profile "
                "form takes only the kind of answer the form offers (listed "
                "under question_key); anything else is refused. Never a goal: "
                "goals are a list of their own, which no tool writes yet, so "
                "say that instead of filing one as an answer here."
            ),
            arguments=UpdateProfileArgs,
            run=_update_profile,
            propose=_propose_profile,
            labels=_PROFILE_LABELS,
            receipt=_profile_receipt,
        ),
        Tool(
            name="suggest_instrument",
            description=(
                "Put one instrument in front of the reader as an idea, and "
                "park it on their watchlist if they accept. This buys nothing "
                "and records nothing about their money: no broker is connected "
                "to this app, so accepting moves no position, no total and no "
                "projection; it keeps the idea, with your reasoning, where "
                "they can find it in a month. A FUND comes from a "
                "`search_catalogue` result and is named by its ISIN; its name, "
                "charge, domicile and distribution policy are read from the "
                "registry. A single SHARE comes from a `lookup_symbol` result "
                "whose quote_type is equity and is named by that exact symbol, "
                "with no ISIN; the app asks Yahoo about it again and reads its "
                "name from there. Nothing else gets a card: not a fund the "
                "catalogue lacks, not a coin, not a single bond. Three things "
                "travel with it and all three are required: why this one, what "
                "they DECLARED that it rests on, and what you do not know that "
                "would change it. Use it when the reader ASKS YOU TO RECOMMEND "
                "SOMETHING ('mi consigli un ETF per le small cap', 'what should "
                "I buy for X', 'what would you look at' are the same request "
                "and this is the answer to it), or to fill a gap you can point "
                "to in their own records. It is also the ONLY way to name a "
                "specific security: the card carries the reasoning a buy call "
                "in prose would leave unsaid. Never unasked. When they ask for "
                "several, up to three: one call each, all in the same reply, "
                "because the answer ends on its cards."
            ),
            arguments=SuggestInstrumentArgs,
            run=_suggest_instrument,
            propose=_propose_suggestion,
            labels=_SUGGESTION_LABELS,
            receipt=_suggestion_receipt,
            done="Added to your watchlist",
        ),
        Tool(
            name="run_analysis",
            description=(
                "Propose running the ANALYZER over everything on record: a "
                "quantitative analyst judges the portfolio without being told "
                "whose it is, someone who knows the reader challenges those "
                "findings without being shown a single figure, the analyst "
                "answers point by point where the challenge is contested, and "
                "a final step writes one answer with the remaining "
                "disagreements left visible. That asymmetry is why it says "
                "things you cannot: you see everything at once, and seeing "
                "everything at once is what makes an analysis agreeable. "
                "Propose it when the reader asks for an analysis or a review, "
                "or when the last one on record predates what you can see: "
                "positions, plans or goals it did not know about, or simply "
                "weeks gone by. It costs the reader a minute of waiting and a "
                "few cents, which is why it is a card they confirm and not "
                "something you can start. You cannot steer it and must not "
                "try: what it reads is built from the records, never from "
                "this conversation."
            ),
            arguments=RunAnalysisArgs,
            walk=_walk_analysis,
            propose=_propose_analysis,
            receipt=_analysis_receipt,
        ),
        Tool(
            name="read_analysis",
            description=(
                "The full verdict of one analysis run, by id. The picture in "
                "this conversation carries the latest run's date and its "
                "opening lines only, because a whole analysis in every turn is "
                "a past opinion sitting where the present picture should be. "
                "Call this when the reader asks what an analysis actually "
                "said, or when you need more of it than its opening to answer "
                "them, not to check that one exists, which the picture "
                "already tells you."
            ),
            arguments=ReadAnalysisArgs,
            run=_read_analysis,
        ),
    )
}


# --- What the model is shown, and what comes back ----------------------------


def declarations() -> list[dict]:
    """Every tool as the API's `tools=` parameter wants it.

    The conversion is `openai.pydantic_function_tool`, the SDK's own — so the
    schema is generated twice over, once by Pydantic from the model and once
    by the SDK into the strict dialect, and this module contributes no copy of
    either. Written out by hand it would be the fourth place a field name
    lives, after the model, the crud function and the column.

    Through `advisor.sdk` rather than importing the package here, so a missing
    `openai` says the one sentence that tells you how to fix it. This is the
    first thing a turn touches, so a bare ImportError here would be caught as
    an unexpected failure and reported as "the answer broke off" — a true
    statement that helps nobody, in front of the specific one.
    """
    return [
        advisor.sdk().pydantic_function_tool(
            t.arguments, name=t.name, description=t.description
        )
        for t in REGISTRY.values()
    ]


# --- The web --------------------------------------------------------------------
#
# A tool of this app since brief AM (2026-10-09), and not one of REGISTRY's: a
# search's pages and its cost belong to the turn that ran it (the reader is
# shown the pages where the search ran, and the turn's cost includes the
# search's), so the chat loop answers it (`chat._searches`), and the search is
# a request of its own (`websearch`). Until then it was OpenRouter's server
# tool, declared on every request of the chat, and brief AL's paid probe P1
# (2026-10-08) found that a request declaring it keeps none of the cache's
# markers but the last: no turn read the one before it.

SEARCH_WEB = "search_web"


class SearchWebArgs(BaseModel):
    """What `search_web` takes."""

    query: str = Field(
        ...,
        min_length=2,
        # A query is words for a search engine, not a paragraph: a bound keeps
        # the conversation from being pasted into one.
        max_length=300,
        description=(
            "What to search for, as you would type it into a search engine: "
            "words about instruments and facts, such as 'S&P 500 UCITS ETF "
            "lowest ongoing charge' or 'ECB rate decision September 2026'."
        ),
    )


_SEARCH_WEB_DESCRIPTION = (
    "Search the web for ONE query and read what it finds: up to five pages, "
    "each with its title, its address and an excerpt. For what neither the "
    "reader's records, the catalogue nor `lookup_symbol` holds: news, recent "
    "performance, comparisons, how a fund or an index works. The query leaves "
    "this app for a search engine, and the reader is shown it above the pages "
    "it found: write it about instruments and facts, and never put the "
    "reader's figures, names or anything else about them in it. Each search "
    "costs a little, and the app caps how many one answer runs."
)


def web_search(model: str) -> list[dict]:
    """`search_web`'s declaration for a model that is offered it, else nothing.

    Anthropic's models only, the line brief AD drew for the cache and brief AG
    for the web, and for the same reason: the web was measured with Opus 5.5
    and Sonnet 4.6 and with no other family, and a model the reader can pick
    from a menu is not where to find out what it does with a tool it has never
    been measured with. A plain function since brief AM, so the other families
    could be offered it as it is, once it has been measured with them.

    Fixed, so the tools never change inside the prefix the provider caches."""
    if not model.removeprefix("~").startswith("anthropic/"):
        return []
    return [
        advisor.sdk().pydantic_function_tool(
            SearchWebArgs, name=SEARCH_WEB, description=_SEARCH_WEB_DESCRIPTION
        )
    ]


def search_query(call: advisor.ToolCall) -> str | dict:
    """The query a `search_web` call asks for, or the outcome that says why its
    arguments do not fit, for the model to correct on its next round."""
    args = _parse(SearchWebArgs, call)
    return args if isinstance(args, dict) else args.query


# --- A card, in the reader's words -------------------------------------------

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?")


def _humanized(name: str) -> str:
    """A field name as words, for a tool that names no label: only a tool the
    registry does not hold (a test's) ever needs it."""
    return name.replace("_", " ").strip().capitalize()


def _card_field(label: str, value, kind: str = "text", currency: str | None = None) -> dict | None:
    """One line of a card, or None for a value that says nothing: absent, or
    one of the words for nothing (`_ABSENT`). A day stays a day and a moment
    becomes the reader's day (`dated.local_day`), so no timestamp reaches a
    card; a number is left for the panel to write in the reader's language."""
    value = _absent_is_none(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return {"label": label, "value": "yes" if value else "no", "kind": "text"}
    if isinstance(value, (int, float)):
        if kind == "amount" and currency:
            return {"label": label, "value": str(value), "kind": "amount", "currency": currency}
        return {"label": label, "value": str(value), "kind": "number"}
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    text = value.strip()
    if _INSTANT.fullmatch(text):
        try:
            return {"label": label, "value": dated.local_day(text), "kind": "date"}
        except ValueError:
            pass
    if _DAY.fullmatch(text):
        return {"label": label, "value": text, "kind": "date"}
    return {"label": label, "value": text, "kind": "text"}


def present(card: dict) -> dict:
    """`card` as the reader reads it: with `fields`, its arguments under its
    tool's labels (`Tool.labels`), the absent ones left out; `receipt`, what a
    confirmed card wrote, in words (`Tool.receipt`); and `done`, what it is
    called once confirmed.

    Worked out whenever a card is sent or read back, and never stored, so the
    cards of a conversation kept since before this read the same way, and the
    model goes on reading the stored arguments and result as they are (the
    run's id, which `read_analysis` takes, is in the result and on no card).
    Brief AJ: the reader's cards showed "based_on", "unknowns", "symbol null",
    and after a confirmation the row's id and an ISO timestamp under
    "added_at"."""
    tool = REGISTRY.get(card.get("tool") or "")
    arguments = card.get("arguments") or {}
    labels = tool.labels if tool is not None else {}
    order = list(tool.arguments.model_fields) if tool is not None else []
    order += [name for name in arguments if name not in order]
    fields = []
    for name in order:
        if name not in arguments:
            continue
        label = labels.get(name, _humanized(name))
        line = _card_field(label, arguments[name]) if label else None
        if line is not None:
            fields.append(line)
    receipt = []
    result = card.get("result")
    if card.get("outcome") == "confirmed" and isinstance(result, dict):
        if tool is not None and tool.receipt is not None:
            rows = tool.receipt(result)
        else:
            rows = [
                (_humanized(name), value)
                for name, value in result.items()
                if name != "id" and not name.endswith("_id")
            ]
        receipt = [line for line in (_card_field(*row) for row in rows) if line is not None]
    return {
        **card,
        "fields": fields,
        "receipt": receipt,
        "done": tool.done if tool is not None else "Recorded",
    }


def answer(db: Session, call: advisor.ToolCall) -> dict:
    """What one tool call becomes: a card to be confirmed, or a result to feed
    straight back to the model.

    `{"card": {...}}` for a tool that writes — nothing has happened, and
    nothing will until the reader says so. `{"ok": ...}` for a tool that
    reads, and for any call that could not be made at all, since a name that
    does not exist is not a write proposal either.
    """
    tool = REGISTRY.get(call.name)
    if tool is None or tool.propose is None:
        return invoke(db, call)

    args = _parse(tool.arguments, call)
    if isinstance(args, dict):  # it did not parse; the model is told why
        return args

    try:
        proposal = tool.propose(db, args)
    except questionnaire.AnswerRefused as exc:
        # A rule refusing an answer, not a failure of the tool's: its sentence
        # goes to the model and under the tool's line as it is, with no
        # traceback logged and no exception's name in front of it.
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("drafting %s failed", call.name)
        return {"ok": False, "error": f"{call.name} could not be drafted: {type(exc).__name__}: {exc}"}

    try:
        card = schemas.ChatCardBlock(
            # Ours, not the provider's: the endpoint has to name one block out
            # of a JSON list that has no keys, and a tool_call_id is only
            # promised to be unique within the turn that produced it.
            card_id=uuid.uuid4().hex,
            call_id=call.id,
            tool=call.name,
            title=proposal.title,
            arguments=args.model_dump(mode="json"),
            confirmation=proposal.confirmation,
            consequence=proposal.consequence,
            verb=proposal.verb,
            diff=proposal.diff,
            fingerprint=proposal.fingerprint,
        )
    except ValidationError as exc:
        # Built through the schema, and here rather than at the panel, because
        # a card is written into a JSON column and read back out through this
        # same model. A tool that draws a malformed one — a `confirmation` the
        # union does not have, a diff whose sides are numbers — would otherwise
        # store a block that every later read of that conversation chokes on,
        # and the conversation becomes permanently unreadable over a mistake
        # made once. Refused at the boundary the mistake enters instead.
        logger.exception("%s drew a card that could not be stored", call.name)
        return {"ok": False, "error": f"{call.name} drew a card that cannot be stored: {exc}"}
    # Stored without the reader's words, which `present` works out each time
    # the card is shown.
    return {"card": card.model_dump(mode="json", exclude={"fields", "receipt", "done"})}


_STALE = (
    "What this card was drawn against has changed since it was proposed, so "
    "what it says would happen is no longer what would happen. Ask again and a "
    "fresh one will be drawn."
)


def finish(walk: Iterator[Working]) -> dict:
    """Drive a `walk` to its end with nobody watching, and hand back what it
    returned. The steps it reports are dropped, which is what "nobody watching"
    means — a caller that wants them iterates instead."""
    while True:
        try:
            next(walk)
        except StopIteration as done:
            return done.value


def settle(
    db: Session, tool_name: str, arguments: dict, fingerprint: str
) -> Iterator[Working]:
    """Run a confirmed card's tool, having checked the ground did not move.

    A GENERATOR: it yields what the tool has finished while it is still going,
    and RETURNS `{"ok": True, "result": ...}` or `{"ok": False, "error": ...}`
    with `stale` set when the refusal is that the world changed. A tool that
    takes milliseconds yields nothing at all and the caller's loop runs zero
    times; the one that takes a minute is the whole reason the caller has a
    loop — see `finish` for the callers that do not want one.

    The caller runs this inside its own unit of work when the tool is a `run`,
    so a tool that raises leaves nothing behind — including the card's own
    outcome, which must not read "confirmed" over a write that did not happen.
    A `walk` cannot be held inside one: it is a minute of model calls, and a
    transaction open across that is a lock held on a database for the length of
    somebody else's network. It writes at its end, in the session it was
    handed, and the caller closes the unit around the settling instead.
    """
    tool = REGISTRY.get(tool_name)
    if tool is None or tool.propose is None:
        return {"ok": False, "error": f"There is no write tool called {tool_name!r}."}

    try:
        args = tool.arguments.model_validate(arguments)
    except ValidationError as exc:
        return {"ok": False, "error": f"The stored arguments no longer fit {tool_name}: {exc}"}

    try:
        proposal = tool.propose(db, args)
    except Exception as exc:
        # A card that can no longer be DRAWN is the strongest form of the
        # ground having moved: the institution it named has been renamed, the
        # position it settles has been closed from another tab. Reported as
        # stale because that is the same answer — what this card says would
        # happen is no longer what would happen — and because the alternative
        # is an exception escaping into `chat.resume`'s unit of work, where a
        # merely out-of-date card becomes a 500.
        logger.info("%s could not be redrawn, so the card is stale: %s", tool_name, exc)
        return {"ok": False, "stale": True, "error": f"{_STALE} ({exc})"}
    if proposal.fingerprint != fingerprint:
        return {"ok": False, "stale": True, "error": _STALE}
    try:
        if tool.walk is not None:
            produced = yield from tool.walk(db, args)
        else:
            produced = tool.run(db, args)
    except advisor.AdvisorError as exc:
        # Written for the reader already (a model that is gone says which one
        # and where it is set), so it goes on as it is, not under the tool's
        # name and an exception class.
        logger.warning("write tool %s stopped: %s", tool_name, exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("write tool %s failed", tool_name)
        return {"ok": False, "error": f"{tool_name} failed: {type(exc).__name__}: {exc}"}
    if not isinstance(produced, dict):
        logger.error("%s returned %s, not a dict", tool_name, type(produced).__name__)
        return {"ok": False, "error": f"{tool_name} returned a {type(produced).__name__}, not fields."}
    return {"ok": True, "result": _storable(produced)}


def _storable(produced: dict) -> dict:
    """A tool's own output, reduced to what the blocks column can hold.

    That column is JSON text and a card is read back through
    `schemas.ChatCardBlock`, so a value JSON cannot carry does not just fail
    here — it lands in the row, and every later read of that conversation
    raises. A write tool returning a dated valuation is not a hypothesis, it is
    the next thing this brief builds, and `datetime.date` is exactly such a
    value.

    Coerced rather than refused, unlike a malformed card: a date in a result is
    a reasonable thing for a tool to return and its ISO string is the right way
    to keep it, whereas a diff whose sides are numbers is a mistake with no
    correct reading. The two are different errors and get different answers.
    """
    return json.loads(json.dumps(produced, ensure_ascii=False, default=str))


def _parse(arguments: type[BaseModel], call: advisor.ToolCall):
    """The call's arguments as `arguments`, the model its tool takes, or the
    outcome that says why not: told apart by the caller with an isinstance,
    since a validated model is never a dict."""
    try:
        return arguments.model_validate_json(call.arguments or "{}")
    except ValidationError as exc:
        # Pydantic reports "this is not JSON at all" as one more validation
        # error in the list, and the two are different mistakes for the model:
        # text that does not parse has to be rewritten, a field of the wrong
        # type has to be corrected. Told apart here so the tool result says
        # which, because "those arguments do not fit" is unhelpful advice about
        # a string that was never arguments.
        if any(e["type"] == "json_invalid" for e in exc.errors()):
            return {
                "ok": False,
                "error": f"The arguments for {call.name} were not valid JSON: {exc}",
            }
        return {"ok": False, "error": f"Those arguments do not fit {call.name}: {exc}"}


def invoke(db: Session, call: advisor.ToolCall) -> dict:
    """Run one tool call and say how it went, in the shape the model reads back.

    Always returns `{"ok": bool, ...}` and never raises. Every way this can go
    wrong is a mistake the MODEL made and can correct on the next round trip —
    a name it invented, arguments that are not JSON, a field of the wrong type
    — so each becomes a tool result that says what was wrong, rather than an
    exception that kills the answer. A stream that dies of a ValueError leaves
    the reader with "the answer broke off" and gives the model nothing to fix.

    The exception to that generosity is a tool body that raises. That is OUR
    bug, not the model's, so it is logged with its traceback before being
    reported — the reader still gets an answer, and the traceback still gets
    read.
    """
    tool = REGISTRY.get(call.name)
    if tool is None:
        return {
            "ok": False,
            "error": (
                f"There is no tool called {call.name!r}. The tools that exist "
                f"are: {', '.join(sorted(REGISTRY)) or '(none)'}."
            ),
        }
    args = _parse(tool.arguments, call)
    if isinstance(args, dict):
        return args

    try:
        # A read tool that reports as it goes is allowed by `Tool` and none
        # exists yet; drained here rather than refused, so the day one does the
        # failure is a missing progress line and not a 'there is no tool called'.
        produced = tool.run(db, args) if tool.run is not None else finish(tool.walk(db, args))
    except Exception as exc:
        logger.exception("tool %s failed", call.name)
        return {"ok": False, "error": f"{call.name} failed: {type(exc).__name__}: {exc}"}
    return {"ok": True, "result": produced}


def result_message(call: advisor.ToolCall, outcome: dict) -> dict:
    """The `tool` turn that answers one `tool_call`, as the API needs it.

    One of these per call in the assistant turn, or the next completion is
    refused: the protocol pairs them by `tool_call_id` and a call left
    unanswered is a malformed conversation. Which is why `invoke` never
    raises — there is no shape of this loop where a call gets no reply."""
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(outcome, ensure_ascii=False, default=str),
    }


def request_message(said: str, calls: list[advisor.ToolCall]) -> dict:
    """The assistant turn that ASKED for the tools, put back in the history.

    It carries the calls verbatim — the same ids and the same argument strings
    the model wrote — because the tool turns after it answer those ids. A
    model that wrote words before asking keeps them here too: dropping them
    would delete a paragraph of its own answer from the history it is about to
    read back."""
    return {
        "role": "assistant",
        "content": said or None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in calls
        ],
    }
