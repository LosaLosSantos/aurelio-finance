"""The chat that reads.

A conversation over the whole financial picture, streamed as it is written.
The model never writes. It PROPOSES: a tool that would change something drafts
the change instead of making it, the turn ends on a card showing exactly what
would happen, and the write runs from the normal path — same `crud`, same unit
of work, same contract the form goes through — only once the reader confirms
it. Which is also why none of this needs a provenance column: every row it
creates was signed off by the person whose money it is, so "who wrote this"
already has one answer.

A turn therefore has two shapes. Asking is `POST /api/chat` and the answer
streams back. Answering a card is `POST /api/chat/cards/{id}`, and it streams
too, because the reader is owed the model's words about what just happened to
their records. Both go through `stream`; the difference is only how the
messages were built.

Why almost every read is context rather than a tool. `advisor.build_context`
renders every section, and sending all of it every turn answers BETTER than a
tool per section, because the model sees connections between sections the
question did not name: "can I afford a house" is also a question about the
expenses. A tool per section buys latency, wrong-tool errors and schemas to
save a third of the prompt.

A third, and not "two thousand tokens", because a turn has no single size any
more and the picture is not its largest piece. Measured on 2026-09-17 against
`qwen/qwen3.8-max`, on a saved portfolio, reading OpenRouter's own
`prompt_tokens`, each figure the difference between two requests:

    system prompt                                     2,284
    the picture, the ack, the question, the page note 3,935  (the picture
                                                              alone: 3,748)
    the nine tool declarations                        4,842
    ------------------------------------------------------
    one turn asked from the Dashboard                11,119
    the same turn asked on a 30-year mortgage's page 19,919

The second line is why a single figure will not do: since brief S every
question carries the note of the page it was asked from, and a mortgage's page
note is the whole of its balance history — 8,800 tokens of it above. The five
calls that measured this cost between $0.0066 and $0.0222 each, as OpenRouter
reported them.

Those numbers are already history, which is the lesson and not a caveat: the
figure that stood here before was measured on that same backup a fortnight
earlier and read 2,237 for a picture that is now 3,748. So a turn records what
it was sent — `chat_messages.prompt_tokens`, the way `chain_steps.cost` records
what a step cost — and the current answer is a query, not a docstring.

The exception is `app/tools.py`, and it is an exception about NETWORK and not
about size. The look-through — what the funds hold underneath — is the one
part of this reader's picture that is not in the picture, because assembling
it walks a waterfall of fund issuers on a cache miss. Folded into the context
it would run on every turn, and "hello" would cost five HTTP fetches. So it is
a tool, and a turn is up to seven round trips instead of one —
`MAX_COMPLETIONS_PER_TURN` says why that number and not another.

The second exception is `read_analysis`, and it fails a different clause of the
same rule: a past verdict is a document, of a length nobody chose, that matters
in one conversation out of ten. What the context carries is its date and its
opening lines; the rest is fetched by the turn that needs it. See
`build_chat_context`.

The third exception is not about the reader's data at all. `search_catalogue`
and `lookup_symbol` read the instrument universe — thousands of funds, and
every quotable ticker there is — which is searched rather than sent for the
plain reason that it does not fit and is not about them. They stay two tools
and not one, for the reason `routers/instruments.py` keeps two endpoints.

And the web, which is not a tool of this app at all (brief AG). For Anthropic's
models each round also offers OpenRouter's own search (`tools.web_search`),
which OpenRouter runs inside the request: nothing here answers a call for it,
and what comes back is the pages it found, which the reader is shown as links
where the search ran. A round that ended on this app's tools never read its
pages, because the search ran after it, so they are passed on to the round
after; and a turn stops searching at WEB_SEARCHES_PER_TURN. Both measured
before they were built, in a paid probe on 2026-10-06.

And this chat is an ORCHESTRATOR now. `run_analysis` is a card like any other
write, and confirming it runs the advisor chain — three to six model calls, a
minute of them — as SUB-AGENTS whose context it does not write. That last part
is not a preference: the chain's whole value is that the analyst has not seen
the person and the confidant has not seen a figure, and a model asked to brief
a colleague summarises, and a summary carries the numbers across. The
sub-agents read `advisor.build_portfolio_context` and
`advisor.build_person_context` and nothing else — never the conversation, never
a word of it. What this chat decides is WHETHER, WHEN, and what to do with the
answer.

Rebuilt every turn, on purpose. The portfolio can change while you talk —
from another tab, from a PAC catch-up — and a context cached at the first
question would answer the second one about a portfolio that no longer exists.

The PROVIDER's cache is a different thing and does not undo that. With an
Anthropic model each round asks it to keep what the round read
(`_kept_prefixes` says where), and it reuses only bytes identical to what it
kept: a picture rebuilt over unchanged records is read back (on Opus 5.5, at a
twentieth of the input price, measured 2026-10-05), and one that changed is
sent and paid for again, as before.

Model: OPENROUTER_CHAT_MODEL, else OPENROUTER_MODEL, else the app default —
the same three-line pattern as chain._model_for. The reader can override it
per conversation from a dropdown, because the two things that pull on the
choice pull in opposite directions: latency wants small, correctness on money
wants large. When the failure mode is a wrong number about someone's money,
the default errs large; the dropdown is the knob for the day latency matters
more.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import advisor, crud, dated, models, schemas, screen, tools
from app.database import SessionLocal, unit_of_work

logger = logging.getLogger(__name__)

# The most important text in this module. It is answering about a real
# person's money, and everything else on their screen has been built to be
# traceable — a cost is recorded or estimated and says which, a value carries
# the day it was observed, a conversion carries its rate date. The two rules at
# the top exist so the chat is not the one place where that stops being true.
#
# And one thing about where the sentences SIT, because it was learned the
# expensive way. "Name a specific security only through `suggest_instrument`"
# used to live in the Manner paragraph, between "you are not a licensed
# adviser" and "never a buy call in prose". Asked "mi consigli un ETF per le
# small cap" — with the tool registered, the catalogue holding five matching
# families and the permission written out in full — the model declined,
# quoting the frame and generalising over the middle. It never reached
# `search_catalogue` at all: the refusal fired before the tools entered its
# field of view, which is why a longer tool description could not have fixed
# it. A permission stated among prohibitions is read as a prohibition, and a
# permission stated in a section about TONE is read as a rule about phrasing.
# So the capability lives beside its tool, affirmatively, with the trigger
# written as the sentence a reader actually types; the disclaimer keeps the
# Manner paragraph and holds no permission; and the stance is stated once,
# positively, near the top — because the defensive version of it did not lose
# only fund suggestions, it lost "should I overpay the mortgage", which needs
# no security named at all and which the records answer well.
#
# Two prompts since brief AG (2026-10-06), and one text. A model offered the
# web (`tools.web_search`) reads WEB_RULES where the other tools that read the
# world outside the records are introduced, for the reason above: a capability
# beside its tool. Every other model reads the same text without it, which is
# SYSTEM_PROMPT; `system_prompt` picks. The same day the prompt lost its em
# dashes, by the reader's decision ("the model writes in the style it reads"),
# except the em dash and the spaced en dash in `advisor.NO_DASHES`, which show
# the two characters it forbids.
_PROMPT_HEAD = (
    "You are Aurelio, the reading companion inside a personal-finance app used "
    "by one person. 'Aurelio' is YOUR name, never theirs; speak to them "
    "directly as 'you'. "
    "On every turn you receive a fresh, complete picture of their finances, "
    "rebuilt from their records the moment they asked: net worth, allocation, "
    "monthly cash flow, investment positions with what they cost and what they "
    "are worth, the transaction ledger, the cash register, real assets, debts, "
    "income, expenses, PACs, their questionnaire and goals, and "
    "the last analyses on record. Answer questions about all of it, and reason "
    "ACROSS sections the question did not name: 'can I afford a house' is also "
    "a question about the expenses and the cash cushion.\n\n"
    "Two rules above every other:\n"
    "1. NEVER state a number that is not in the context. Do not estimate, "
    "extrapolate, recall a typical value, or fill a gap with a plausible "
    "figure. Arithmetic on figures that ARE in the context is welcome: show "
    "the operands so it can be checked. A number invented here is worse than "
    "no answer, because every other figure on this reader's screen can be "
    "traced to a record, and yours must be too. When you quote one, keep its "
    "qualifications: recorded or estimated cost, the date a price was "
    "observed, 'no P/L is claimed'.\n"
    "2. When the context does not contain the answer, SAY SO, and say what the "
    "reader would have to enter for it to: 'your expenses are not recorded, "
    "so there is no savings rate to compute; add them under Records → Cash "
    "flow'. A refusal that names its remedy is worth more than a guess.\n\n"
    "And what the job IS, said once so you can point at it: the questions "
    "that sound like advice ARE the work. 'Should I overpay the mortgage or "
    "invest', 'am I taking too much risk', 'is this position too big', "
    "'should I sell this', 'what might I look at for small caps': engage "
    "with every one of them, out of THIS reader's records, which is the "
    "thing no general answer can do and the whole reason they are talking to "
    "their own figures instead of reading an article. Retreating into "
    "generalities when their picture holds the answer is a failure of this "
    "app, not a careful version of it. The guard is the SHAPE of the answer, "
    "never a smaller set of questions: every claim traced to a figure in the "
    "picture, what you cannot know said out loud, and a specific security "
    "named only through `suggest_instrument`'s card. Where the records are "
    "silent, apply rule 2 (say so, say what would fill the gap) and answer "
    "the rest anyway.\n\n"
    "Read the figures as they are labelled. 'book' is what was paid, 'market' "
    "is what it is worth now, and a P/L is their difference, which exists "
    "only when the cost is known. 'COST UNKNOWN' means the average cost is the "
    "price of a photograph and the movement since then is NOT a profit. 'as "
    "last observed on' means nothing has priced it since that day. Dividends "
    "are recorded gross unless marked otherwise. Do not turn a movement into "
    "a gain.\n\n"
    "Their messages can begin with a <screen> note. The APP writes it, not the "
    "reader: it says where in the app they were when they sent that message, "
    "and on the message you are answering it also says what that screen shows "
    "and whether the picture holds it. Use it for ONE thing: to know what "
    "'this', 'here', 'these', 'questo', 'qui' point at. It never narrows the "
    "question: 'should I sell?' asked on the Portfolio page is about the whole "
    "portfolio unless they point at something, and when their words name "
    "something else, their words win. Each note belongs to its own message: "
    "they move between messages, so an earlier note says where an earlier "
    "question was asked and never where they are now. When a note says that "
    "something on their screen is NOT in the picture and does not give it to "
    "you, you cannot see it: that is rule 2, never a figure borrowed from "
    "something nearby. Do not describe their screen back to them; answer the "
    "question.\n\n"
    "One thing is NOT in that picture, and you have a tool for it: the "
    "look-through, what the funds hold underneath. Call `get_look_through` "
    "when the question is about exposure held THROUGH a fund rather than "
    "beside it: 'how much NVIDIA do I own in total', 'do these two ETFs "
    "overlap', 'how much of me is America', 'am I really diversified'. Do not "
    "call it for anything the picture already answers: it walks the fund "
    "issuers when its cache is cold, so it can take seconds. Read its "
    "coverage before you answer from it: what it could not look inside is "
    "unknown, not empty, and a portfolio it saw 30% of cannot support a "
    "sentence about the other 70%.\n\n"
    "Two more tools read the world OUTSIDE their records, and they are two "
    "rather than one on purpose. `search_catalogue` searches a local registry "
    "of funds and ETFs: instant, offline, and the only place an ISIN may come "
    "from. `lookup_symbol` finds a quotable ticker for shares, crypto and "
    "futures, and it is a network call that can simply not answer: an empty "
    "result with `reachable` false means the source was silent, which is not "
    "the same claim as 'this does not exist', and presenting it as one teaches "
    "the reader to correct a symbol that was right. NEVER write an ISIN or a "
    "fund name from memory. If you have not searched for it, you do not know "
    "it exists, and a plausible-looking ISIN is the one kind of mistake nobody "
    "can catch by reading.\n\n"
)

# For a model offered the web, between the paragraph above and the one about
# reading without permission. What a search may be used for, what never goes
# into one, that a page's claim travels with its link, and that the web finds
# and the card verifies: a fund the catalogue does not hold is exactly what the
# web turns up first (a US-domiciled ETF has no KID), so the refusal is said
# where the temptation is.
WEB_RULES = (
    "You can also search the web, for what neither their records, the "
    "catalogue nor `lookup_symbol` holds: news, recent performance, "
    "comparisons, how a fund or an index works, what people use for a goal. "
    "Never for what the picture or the catalogue answers. Never put their "
    "figures, names or anything else about them in a query: search for "
    "instruments and facts, never for them. A search costs a little and the "
    "app caps it per answer; it is a read, so run it unasked. Every claim from "
    "a page carries its link, as [title](url), in the sentence that makes it, "
    "and rule 1 holds there too: a figure from a page is stated with its link "
    "or not at all. The web finds; it does not verify. A security is still "
    "named for buying only through a card, and a card names only what the "
    "catalogue (a fund) or Yahoo (a share) confirms: a fund the catalogue does "
    "not hold, such as one domiciled in the US with no KID, gets no card, and "
    "you say why.\n\n"
)

_PROMPT_TAIL = (
    "Reading needs no permission. When they ask for advice, first gather what "
    "the answer needs, unasked and in one round where you can: "
    "`get_look_through`, `search_catalogue`, `lookup_symbol`, `read_analysis`. "
    "They only read, so never ask whether to run one: "
    "run it. Ask only before writing their records (a card) or spending their "
    "money (a new analysis). Your earlier turns reach you as their words alone, "
    "without the lookups behind them: never call a past statement invented for "
    "that reason; when it matters, run the tool again.\n\n"
    "You do not write; you PROPOSE. A tool that would change something drafts "
    "the change and the reader is shown it as a card to confirm or reject; "
    "nothing reaches their records until they press confirm, so say what you "
    "are proposing and then stop, rather than reporting it as done. Propose a "
    "write only when asked for one: noticing is free, writing is not.\n\n"
    "Five things you can propose. `add_real_asset`: something owned "
    "outright and held at no institution, with what it is worth today. "
    "`record_transaction`: a buy, a sell, a dividend or a close that ALREADY "
    "happened. No broker is connected here, so a purchase is RECORDED after "
    "the fact and never placed, and saying you have bought something would be "
    "a lie about the one thing this app cannot do. `update_profile`: one "
    "answer to their questionnaire, either because it has changed or because "
    "the conversation told you something durable the form never asked for; "
    "the analyses read that profile, so this is how what they tell you here "
    "reaches them. Two rules across all three. Write in the language of the "
    "DATA, not of the question: 'ho comprato azioni Siemens' is an asset called "
    "'Siemens', never 'Azioni Siemens', the same separation as between the "
    "language you reply in and the currency the figures are in. And name "
    "things exactly as the picture above names them (an institution by its "
    "name, a position by its ticker, a questionnaire question by its own "
    "wording), because a near miss is filed as a second thing rather than "
    "corrected.\n\n"
    "`run_analysis`, the fourth, is the one that is not about their "
    "records. It runs the ANALYZER: a quantitative analyst judges the "
    "portfolio without being told whose it is, someone who knows them "
    "challenges those findings without being shown one figure, the analyst "
    "answers where it is contested, and a last step writes one answer with the "
    "disagreements left in. Propose it when they ask for an analysis or a "
    "review, and when the last one on record predates what you can see "
    "(positions, plans or goals it did not know about, or simply weeks gone "
    "by): 'the last one is from 12 August and two positions have been added "
    "since: run a fresh one?'. And when they ask for advice, which stands on it: if "
    "the last one is current, read it with `read_analysis` before answering and "
    "build on it, unasked; if there is none, or it is stale, answer and put its "
    "card beside the answer, saying the advice will fit them better on a fresh "
    "one. Never run one without its card: it costs money. "
    "You cannot steer it and must not try: what those roles "
    "read is built from the records, never from this conversation, and that is "
    "exactly why it can say things you cannot. You see everything at once, "
    "and seeing everything at once is what makes an analysis agreeable.\n\n"
    "`suggest_instrument`, the fifth, is the only one that writes nothing of "
    "theirs. It puts an instrument in front of them as an idea and, if they "
    "accept, parks it on a watchlist: no purchase, no position, no total and "
    "no projection moves, because no broker is connected here. A fund is "
    "named by an ISIN copied from a `search_catalogue` result, a single share "
    "by the exact symbol a `lookup_symbol` result gave it, with no ISIN: the "
    "app checks the fund against the catalogue and the share against Yahoo, "
    "and reads its name and facts from there and not from you, so the only "
    "thing you can get wrong is naming something that does not exist, and "
    "that is refused. Nothing else gets a card: not a fund the catalogue does "
    "not hold, not a coin, and not a single bond (a BTP, a corporate bond), "
    "which nothing here can verify; a bond ETF from the catalogue can have "
    "one. Three things travel with it and all three are required: "
    "why this one, what they DECLARED that it rests on (a position, a "
    "questionnaire answer, a goal, something they just said), and what you do "
    "NOT know that would change it. The third is the one worth writing "
    "honestly: it is read again in a month, when what was missing turns out to "
    "have been the whole question. Use it when they ASK YOU TO RECOMMEND "
    "SOMETHING ('mi consigli un ETF per le small cap', 'what should I buy "
    "for X', 'what would you look at', 'quale fondo mi consigli' are one "
    "request and this tool is the answer to it, so search and put a card up), "
    "or to fill a gap you can point to in their own records. "
    "This is also HOW a specific security gets named here, and the only way: "
    "through the card, where the reasoning, what it rests on and what you do "
    "not know travel with it and the reader decides. Never as a buy or sell "
    "call in prose, where none of that has to be said. Never unasked. When "
    "they ask for several, put up to three, one call each and all in the same "
    "reply, since the answer ends on its cards; a fourth is refused. A "
    "suggestion in every second answer is the worse failure, because it looks "
    "like enthusiasm.\n\n"
    "The picture above carries the last analysis's date and its OPENING LINES, "
    "not the whole of it. That is enough to notice it is stale and enough to "
    "refer to; when the reader asks what it actually said, call "
    "`read_analysis` with the run id and answer from the verdict itself. Never "
    "reconstruct the rest of a verdict from its opening.\n\n"
    "Manner. Reply in the language the reader writes in. This is a chat, not a "
    "report: be concise, short paragraphs, a '-' bullet list when the items "
    "are parallel, a small table only when it carries figures better than "
    "prose, no headings unless the answer is genuinely long. Use the currency "
    "of the data. You are not a licensed financial adviser: when the "
    "conversation turns to what the reader should DO, say once (not on every "
    "message) that this is educational information, not personalised "
    "regulated advice. That is a line to ADD to the answer, never a reason to "
    "withhold one: it goes at the end of the reasoning you did, not in place "
    "of it. " + advisor.NO_DASHES
)

# The prompt of every model not offered the web.
SYSTEM_PROMPT = _PROMPT_HEAD + _PROMPT_TAIL


def system_prompt(model: str) -> str:
    """The system prompt `model` is asked with: with the web's rules when it is
    offered the web, and SYSTEM_PROMPT otherwise."""
    if tools.web_search(model):
        return _PROMPT_HEAD + WEB_RULES + _PROMPT_TAIL
    return SYSTEM_PROMPT


# --- The model ---------------------------------------------------------------

# The dropdown. A curated list rather than OpenRouter's own, for two reasons:
# theirs is a network call the offline boundary would have to hold, and it has
# three hundred entries with nothing to say about which of them to trust with
# a question about money. These carry what is KNOWN about each, with the date
# it was checked, so the reader picks with information rather than a slug. The
# slugs and figures are the ones verified in .env.example; whatever the
# environment configures joins the list, so the reader's own choice is always
# among the options.
CURATED_MODELS: tuple[tuple[str, str], ...] = (
    ("anthropic/claude-opus-5.5", "the app's built-in default; 1M context, $4 / $20 per 1M tokens (checked Oct 2026)"),
    ("anthropic/claude-sonnet-4.6", "1M context, $3 / $15 per 1M tokens (checked Oct 2026)"),
    ("openai/gpt-6.1-sol-pro", "1.05M context, $2 / $10 per 1M tokens (checked Oct 2026)"),
    ("qwen/qwen3.8-max-0902", "1M context, $2 / $6 per 1M tokens (checked Oct 2026)"),
    ("moonshotai/kimi-k3", "1M context, $3 / $15 per 1M tokens (checked Aug 2026)"),
    ("moonshotai/kimi-k2.6", "about six times cheaper than K3 (checked Aug 2026)"),
)

_ENV_MODELS = (
    ("OPENROUTER_CHAT_MODEL", "your OPENROUTER_CHAT_MODEL"),
    ("OPENROUTER_MODEL", "your OPENROUTER_MODEL"),
    ("OPENROUTER_ANALYST_MODEL", "your analyst model"),
    ("OPENROUTER_CONFIDANT_MODEL", "your confidant model"),
)


def default_model() -> str:
    """The chat's own model, falling back through the app default."""
    return advisor.resolve_model(os.getenv("OPENROUTER_CHAT_MODEL") or None)


def available_models() -> schemas.ChatModelsRead:
    """The dropdown: the default first, then the rest, no slug twice."""
    default = default_model()
    notes: dict[str, str] = {}
    for var, note in _ENV_MODELS:
        slug = os.getenv(var)
        if slug and slug not in notes:
            notes[slug] = note
    for slug, note in CURATED_MODELS:
        notes.setdefault(slug, note)
    notes.setdefault(default, "the configured default")

    ordered = [default, *(s for s in notes if s != default)]
    return schemas.ChatModelsRead(
        default=default,
        models=[schemas.ChatModel(slug=s, note=notes[s]) for s in ordered],
    )


# --- The context -------------------------------------------------------------


def build_chat_context(db: Session) -> str:
    """Everything the model reads: today's date, the whole picture, and the
    last analysis — its date, its shape and its opening lines. The date comes
    first because 'your last analysis is from 12 August' is only a useful thing
    to notice if the model knows what today is.

    THE VERDICT IS NOT HERE IN FULL, and that is the decision this section
    exists to record. It used to be, and so did the whole text of two other
    saved analyses, pasted into every turn. Two costs, and the second is the
    real one: input re-paid on every question, and a past opinion sitting at the
    same prominence as a picture rebuilt this second — which is how today's
    question gets answered with last month's conclusion. What stays is what is
    bounded and always relevant. The date, because noticing staleness is the
    model's job and a date is cheap. The opening lines, verbatim, because the
    synthesis leads with what to do and its first paragraph is the informative
    one. The rest is `read_analysis`, one call away, and paid for by the turn
    that actually needs it.

    The two single-shot analyses that used to follow are gone entirely, page
    and table and all: the unbiased portfolio read is the chain's first step,
    and the whole-picture one is what this conversation does over this context
    every time it is asked anything.
    """
    today = datetime.date.today().isoformat()
    lines = [f"# Today is {today}", "", advisor.build_context(db), ""]

    lines.append("# The analyzer's last run (you can propose a fresh one)")
    lines.append("")

    run = crud.get_latest_chain_run(db)
    if run is None:
        lines.append("It has never been run.")
    else:
        rounds = sum(1 for s in run.steps if s.role == "revision")
        argued = (
            "the challenge was not contested"
            if not rounds
            else f"the analyst answered the challenge {rounds} time(s)"
        )
        lines.append(
            f"Run {run.id}, finished {dated.local_day(run.created_at)}, "
            f"{len(run.steps)} steps — {argued}."
        )
        lines.append(
            "These are its OPENING LINES only. For the whole verdict, call "
            f"read_analysis with run_id={run.id}."
        )
        lines.append("")
        lines.append(tools.opening(run.verdict) or "(no verdict was written)")
    lines.append("")

    return "\n".join(lines)


# --- The turn ----------------------------------------------------------------


def _messages(
    db: Session, conv: models.ChatConversation, now: screen.Screen | None = None
) -> list[dict]:
    """The conversation as the model reads it: the picture, an acknowledgement,
    then every stored turn — the last one with `now`, what the screen it was
    asked from shows, when there is a question being answered.

    The context travels as the first user message rather than inside the system
    prompt so the rules stay rules and the data stays data. Written once because
    it was written twice: the two copies differed by one word — "propose rather
    than run" against "propose rather than write" — which is a drift small
    enough to survive review and large enough to be a second answer to what the
    model was told."""
    return [
        {
            "role": "user",
            "content": (
                "Here is my complete financial picture as of right now, rebuilt "
                "from my records for this message:\n\n" + build_chat_context(db)
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Read. I will answer only from these records, say when they do "
                "not contain the answer, and propose rather than write."
            ),
        },
        *_wire(conv.messages, now),
    ]


@dataclass(frozen=True)
class Pending:
    """A card the reader has confirmed whose tool has NOT run yet.

    Only for a tool that reports as it goes — today only `run_analysis`, three
    to six model calls and a minute of them. Everything else is written before
    the stream starts, which is what makes "a stream that starts at all is a
    decision already taken" true; a minute of that rule would be a minute of a
    request holding open with nothing on the wire, and the steps the reader is
    owed have nowhere to arrive. So the decision is still taken before the
    stream — the card is checked, and nothing else can decide it — and the WORK
    happens on the stream, which is where its progress can be said."""

    card_id: str
    tool: str
    arguments: dict
    fingerprint: str


@dataclass(frozen=True)
class PreparedTurn:
    """A turn with its context built and its question stored, ready to stream.

    Two steps on purpose. The context and the question need the database
    session, which belongs to the request; the streaming outlives the request
    body by as long as the model takes to write. Building first and streaming
    second means the request's session is never touched from inside the
    stream — the answer is stored afterwards in a session of its own."""

    conversation_id: int
    # None when nobody asked anything: answering a card resumes a conversation
    # without a question in front of it.
    user_message_id: int | None
    model: str
    messages: list[dict]
    # The label stored with the question, for the `start` frame. None when
    # there is no question, or it was sent without a page.
    page_label: str | None = None
    # Set only for the confirmed card whose tool runs on the stream. The
    # messages are EMPTY when it is, and cannot be otherwise: what the model
    # reads has to include what the tool did, and the tool has not run.
    pending: Pending | None = None


def _wire(stored: list[models.ChatMessage], now: screen.Screen | None = None) -> list[dict]:
    """The stored turns as the model reads them: role and text, in order. A
    turn with no text — an answer that failed before its first word — is
    skipped; a cut one keeps the words the reader actually saw.

    A thought was never for the model, and a tool block is the RECEIPT of a
    call, not the call: replaying "you consulted the look-through" without the
    result it returned would hand the model a memory of having known
    something, with the something missing. What a past tool found is in the
    words that were written from it, which do travel.

    A CARD does travel, and it has to, in the protocol's own shape: the turn
    that proposed it goes back as an assistant turn carrying its `tool_calls`,
    and each one is answered by a `tool` turn saying what became of it. Two
    reasons, and both are hard. The API pairs those by `tool_call_id` and
    refuses a conversation where one is unanswered — including a card the
    reader simply never got round to, which is why "still waiting" is one of
    the three things a card can say rather than a gap. And the model must know
    which of its proposals were taken up: a rejected card that came back
    looking like nothing had been proposed would be proposed again.

    A question goes back with WHERE it was asked, every time, and with what
    that screen showed only while it is the question being answered. The
    first because the reader moves: "e questo?" on Broker A after "cos'è?" on
    Broker B reads, without it, as two questions about Broker A. The second for
    the reason a tool block travels as the words written from it: a situation
    pasted into every later turn is a past screen at the prominence of the
    present one."""
    out: list[dict] = []
    for m in stored:
        blocks = json.loads(m.blocks)
        text = "".join(b.get("text", "") for b in blocks if b.get("kind") == "text")
        cards = [b for b in blocks if b.get("kind") == "card"]
        if cards:
            calls = [
                advisor.ToolCall(
                    id=c["call_id"], name=c["tool"], arguments=json.dumps(c["arguments"])
                )
                for c in cards
            ]
            out.append(tools.request_message(text, calls))
            for card, call in zip(cards, calls):
                out.append(tools.result_message(call, _card_state(card)))
        elif text.strip():
            note = now.note if now is not None and m is stored[-1] else None
            out.append({"role": m.role, "content": _asked_on(blocks, text, note)})
    return out


def _asked_on(blocks: list[dict], text: str, note: str | None) -> str:
    """A turn's words with the screen they were sent from in front of them, in
    a tag the system prompt names as the app's, so it is never read as
    something the reader said. A turn with no page — every answer, and every
    question asked before pages were sent — is its words alone."""
    label = next((b["label"] for b in blocks if b.get("kind") == "page"), None)
    if label is None:
        return text
    where = f"<screen>\n{note}\n</screen>" if note is not None else f"<screen>{label}</screen>"
    return f"{where}\n\n{text}"


def _card_state(card: dict) -> dict:
    """What became of one card, as the model reads it back.

    Three states and no fourth. "Pending" is a real answer and not a missing
    one: a reader who closed the tab on a card left it unanswered, that is
    the truth of it, and the model should say so rather than assume either
    way."""
    outcome = card.get("outcome", "pending")
    if outcome == "confirmed":
        return {"outcome": "confirmed", "written": card.get("result")}
    if outcome == "rejected":
        return {
            "outcome": "rejected",
            "note": "The reader rejected this. Nothing was written.",
        }
    return {
        "outcome": "pending",
        "note": (
            "This was shown to the reader as a card. They have neither "
            "confirmed nor rejected it, and nothing has been written."
        ),
    }


def prepare(db: Session, request: schemas.ChatRequest) -> PreparedTurn:
    """Store the question, rebuild the picture and put the conversation after
    it. The context travels as the first user message rather than inside the
    system prompt so the rules stay rules and the data stays data.

    Raises LookupError for a conversation id that does not exist — the caller
    turns that into its 404."""
    if request.conversation_id is None:
        conv = crud.create_chat_conversation(db)
    else:
        conv = crud.get_chat_conversation(db, request.conversation_id)
        if conv is None:
            raise LookupError(request.conversation_id)
    # Where it was asked, resolved to names now and kept as they read now. A
    # page gone since resolves to the one above it; it never refuses the
    # question.
    here = screen.resolve(db, request.page) if request.page is not None else None
    blocks = [{"kind": "text", "text": request.content}]
    if here is not None:
        blocks.insert(0, {"kind": "page", "label": here.label})
    question = crud.append_chat_message(db, conv, "user", blocks)

    return PreparedTurn(
        conversation_id=conv.id,
        user_message_id=question.id,
        model=advisor.resolve_model(request.model or default_model()),
        messages=_messages(db, conv, now=here),
        page_label=here.label if here is not None else None,
    )


class CardGone(LookupError):
    """No card with that id — never proposed, or its conversation is deleted."""


class CardSettled(ValueError):
    """That card has already been confirmed or rejected. A decision is taken
    once: a second confirm would run the write twice, and there is nothing in
    a ledger that says a row was meant to be one row."""


class CardStale(ValueError):
    """What the card was drawn against has changed since it was proposed."""


def resume(db: Session, card_id: str, decision: schemas.ChatCardDecision) -> PreparedTurn:
    """Take the reader's decision on one card, then prepare the turn that says
    what happened.

    The write and the record of it are ONE unit of work, and that is the whole
    reason this function opens one — the first in the app outside `pac.py`. A
    card left reading "confirmed" over a write that rolled back would be the
    receipt lying about the thing it is a receipt for, and the failure would
    be invisible: both halves land, or neither does.

    Rejecting takes the same path minus the write, and it streams a follow-up
    too, which is not politeness. The protocol needs a `tool` turn answering
    the proposal's `tool_call_id` either way, so the conversation the model
    reads back is only well-formed once the card is settled — and a reader who
    said no is usually about to say what they wanted instead.

    Raises CardGone, CardSettled or CardStale; the caller turns each into its
    status code, before any stream starts. A refusal after the first byte is a
    refusal the client has to parse out of an event."""
    found = crud.find_chat_card(db, card_id)
    if found is None:
        raise CardGone(card_id)
    message, card = found
    if card.get("outcome") != "pending":
        raise CardSettled(card["outcome"])
    # That check is the fast one and it is not the guarantee: between reading
    # it and writing, another window can decide the same card. The guarantee is
    # the compare-and-swap inside `crud.settle_chat_card`.

    tool = tools.REGISTRY.get(card["tool"])
    if decision.decision == "confirm" and tool is not None and tool.walk is not None:
        # A minute of model calls. Nothing is written here — see `Pending`.
        return PreparedTurn(
            conversation_id=message.conversation.id,
            user_message_id=None,
            model=advisor.resolve_model(decision.model or default_model()),
            messages=[],
            pending=Pending(
                card_id=card_id,
                tool=card["tool"],
                arguments=card["arguments"],
                fingerprint=card["fingerprint"],
            ),
        )

    if decision.decision == "confirm":
        with unit_of_work(db):
            done = tools.finish(
                tools.settle(db, card["tool"], card["arguments"], card["fingerprint"])
            )
            if not done["ok"]:
                if done.get("stale"):
                    raise CardStale(done["error"])
                raise ValueError(done["error"])
            # The claim is inside the unit with the write, and it can fail:
            # another tab that decided this card between the check above and
            # here wins, and losing takes the write down with it rather than
            # leaving a second row nobody asked for.
            if crud.settle_chat_card(db, message, card_id, "confirmed", done["result"]) is None:
                raise CardSettled("decided in another window")
    else:
        # No unit of work: rejecting is the one write, and the swap either
        # takes it or somebody else already decided.
        if crud.settle_chat_card(db, message, card_id, "rejected", None) is None:
            raise CardSettled("decided in another window")

    conv = message.conversation
    return PreparedTurn(
        conversation_id=conv.id,
        user_message_id=None,
        model=advisor.resolve_model(decision.model or default_model()),
        messages=_messages(db, conv),
    )


def _store_answer(
    turn: PreparedTurn,
    blocks: list[dict],
    status: str,
    detail: str | None,
    prompt_tokens: int | None = None,
    cached_tokens: int | None = None,
    cost: float | None = None,
) -> int:
    """Write the answer as it ended, in a session of this function's own: the
    request's session is closed by the time the stream finishes, and this runs
    even when the reader has gone. Returns the stored message's id.

    The three figures are what the provider reported for the turn's rounds
    (`_spent`): every token they read, how many of those came from the cache,
    and what it all cost. The answer to "what does a turn cost", kept per turn
    instead of in a sentence somebody measured once. The tokens alone stopped
    answering it the day the cache came in: on Opus 5.5 a cached token cost a
    twentieth of one sent fresh (2026-10-05)."""
    with SessionLocal() as db:
        conv = crud.get_chat_conversation(db, turn.conversation_id)
        if conv is None:  # deleted while the answer was being written
            return 0
        msg = crud.append_chat_message(
            db,
            conv,
            "assistant",
            blocks,
            status=status,
            detail=detail,
            model=turn.model,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            cost=cost,
        )
        return msg.id


def _spent(rounds: list[advisor.Usage | None]) -> dict:
    """A turn's figures from its rounds', one entry per round asked and None
    for a round the provider said nothing about.

    The tokens are summed over the rounds that reported them, and are None
    when none did. A zero in `prompt_tokens` is stored as None too, as it
    always was: a turn that cost nothing to send does not exist. A zero in
    `cached_tokens` is kept, because it is a real answer: nothing was read from
    the cache.

    The cost is a sum only when every round asked reported one. A round whose
    price nobody said makes the turn's cost unknown, never smaller: the rule
    the reader set for the analysis's spend (2026-10-02), since a figure about
    money that is low without saying so is the worse mistake."""

    def total(figures: list) -> int | None:
        known = [f for f in figures if f is not None]
        return sum(known) if known else None

    costs = [r.cost if r is not None else None for r in rounds]
    return {
        "prompt_tokens": total([r.prompt_tokens if r is not None else None for r in rounds]) or None,
        "cached_tokens": total([r.cached_tokens if r is not None else None for r in rounds]),
        "cost": sum(costs) if costs and None not in costs else None,
    }


def _say(blocks: list[dict], kind: str, text: str) -> None:
    """Grow the last block when it is more of the same, else start a new one.

    A message is a SEQUENCE and not two buckets. It used to be two — all the
    reasoning, then all the words — which was right while those were the only
    kinds there were and stops being right the moment something happens in the
    middle. A tool consulted between two paragraphs belongs between them: the
    words before it are what led to it and the words after are what it was
    for, and joining all the text into one block would file the tool call
    after a paragraph it interrupted."""
    if blocks and blocks[-1].get("kind") == kind:
        blocks[-1]["text"] += text
    else:
        blocks.append({"kind": kind, "text": text})


# How many times the model may be asked in ONE turn. A turn is one completion
# when nothing is called, and one more per round of tools. The bound is not
# about cost per call, it is about the shape of the failure without it: a model
# that answers every tool result with the same tool call again loops until
# somebody notices, and what it spends while nobody is looking is a bill, not a
# turn. It is a bound on COST and latency, and it must never become a bound on
# quality — which is exactly what it had become.
#
# What it had become. The last completion was offered the tools like every
# other one, so a tool call on it was not a round the loop could answer: it was
# a raise, "the model asked for tools N times without ever writing an answer".
# Asked to recommend a small-cap ETF, the model searched the registry and
# looked up three candidates, one round each — which is the diligence you want,
# because comparing before choosing is the difference between a suggestion and
# a guess. That is four rounds. The fifth could not draw the card, so it wrote
# "ti metto su la carta con quella iShares" and the turn ended with no card on
# screen. The budget punished thoroughness, and the more funds it weighed, the
# sooner it hit the wall.
#
# So the shape changed in three places and only one of them is this number.
#
# The LAST round is tool-free — `tools=` is simply not passed on it — so the
# model cannot ask for something it will not get an answer to, and the raise
# above is gone rather than made rarer. A turn now always ends in words.
#
# The round before it says so, in `LAST_TOOL_ROUND_NOTICE`, because a deadline
# you are told about is a deadline you can plan against and a silent one is a
# trap. The model plans "look these up, then propose"; nothing used to tell it
# which round made that plan impossible.
#
# And SEVEN, named against a route rather than against the transcript that
# produced it: six rounds that may call tools, plus the tool-free one. Six is
# search the registry, look up four candidates, then propose the card — a
# four-way comparison ending on a suggestion, which is the most thorough turn
# worth having. A three-way comparison is five and leaves one round spare for a
# search that had to be reworded. Raising the number alone would have been the
# weakest of the three fixes: a five-way comparison needs eight and the wall
# just moves — what stops the wall from being a defect is that hitting it now
# costs prose instead of an exception.
MAX_COMPLETIONS_PER_TURN = 7


# How many web searches one turn may make, for a model offered the web
# (`tools.web_search`). OpenRouter's caps are per request and a turn is up to
# seven of them, so none of those caps a turn; and its `max_uses` did not even
# hold within one request, where a model asking for two searches at once got
# both under a cap of one (a paid probe, 2026-10-06). So the app
# adds up what each round reports and, at six, asks the rest of the turn
# without the web. Those rounds offer other tools than the rounds before, so
# the first of them pays for its prefix again, about what a cold round costs,
# and only in a turn that searched six times. Six is the reader's figure
# (2026-10-06); at the probe's prices that is about $0.12 of searching on Opus
# 5.5. A round can still pass it inside one batch: counted after it, never
# stopped in the middle of it.
WEB_SEARCHES_PER_TURN = 6


# Said after a round that found pages, when another round follows. Measured on
# 2026-10-06 in a paid probe: asked for searches and one of the app's tools in
# the same response, OpenRouter runs the searches after that response, so the
# model never reads what they found; and a page a round did read is not in the
# next request either, which carries
# the round's words and calls and not what a search returned. Passed on like
# this after the tool results (B3), the model used the pages without searching
# again, cited them as links, and kept what came from the catalogue apart from
# what came from the web. A user turn in the app's voice, after the tool
# results, for the reason the last-round notice is one: that is the place that
# keeps the round's cache.
PAGES_PASSED_ON = (
    "WEB PAGES FROM YOUR LAST ROUND, passed on by the app. What a search finds "
    "does not travel from one round to the next, and when a round ends on the "
    "app's tools the search runs after it, so you may not have read these. Use "
    "them as sources, and cite each one you rely on with its link."
)

# How much of each page's excerpt is passed on. The probe's longest was 1,666
# characters, and a round of two searches found ten pages.
EXCERPT_CHARS = 1000


def _passed_on(pages: list[advisor.WebPage]) -> dict:
    """The pages one round found, as the next round reads them: each one's
    title, its address and the start of its excerpt."""
    lines = [PAGES_PASSED_ON]
    for n, page in enumerate(pages, 1):
        lines.append(f"\n[{n}] {page.title}\n{page.url}\n{page.excerpt[:EXCERPT_CHARS]}")
    return {"role": "user", "content": "\n".join(lines)}


# How many suggestions one answer may put up. The reader's decision
# (2026-10-06): asked for several, the chat puts up to three cards, and never
# one unasked. A turn ends on the round that draws a card, so they all come
# from one round, one call each; a fourth in that round is not drawn, and
# neither is a second card for the same instrument.
SUGGESTIONS_PER_ANSWER = 3


def _named(call: advisor.ToolCall) -> str | None:
    """The instrument a suggestion names, as its card will: the ISIN, else
    the symbol. None for any other call, and for arguments that do not parse,
    which the tool itself refuses with the reason."""
    if call.name != "suggest_instrument":
        return None
    try:
        arguments = json.loads(call.arguments or "{}")
    except ValueError:
        return None
    if not isinstance(arguments, dict):
        return None
    named = str(arguments.get("isin") or arguments.get("symbol") or "").strip().upper()
    return named or None


def _past_the_cards(call: advisor.ToolCall, drawn: list[str]) -> dict | None:
    """Why this suggestion is not drawn, given the ones this round has drawn
    already, or None when nothing stops it. Shown to the reader where it was
    refused and told to the model, so a proposal that never reached the screen
    is not taken for one that did."""
    named = _named(call)
    if named is None:
        return None
    if named in drawn:
        return {
            "ok": False,
            "error": f"This answer already has a card for {named}: one card per instrument.",
        }
    if len(drawn) >= SUGGESTIONS_PER_ANSWER:
        return {
            "ok": False,
            "error": (
                f"{len(drawn)} suggestions are already up in this answer, the most one "
                f"answer holds, so this one for {named} was not drawn."
            ),
        }
    return None


def _found(blocks: list[dict], page: advisor.WebPage) -> None:
    """A page into the answer, where the search ran: onto the list it is part
    of, or a new list. Its excerpt is not kept. It was for the model; the link
    is what the reader opens."""
    entry = {"url": page.url, "title": page.title}
    if blocks and blocks[-1].get("kind") == "sources":
        blocks[-1]["pages"].append(entry)
    else:
        blocks.append({"kind": "sources", "pages": [entry]})


# Said to the model on the last round that has tools, and on no other. WHERE it
# is said depends on the model.
#
# For most models it is appended to the system prompt rather than pushed into
# `messages` as a turn of its own: an instruction from the APP belongs where the
# app's instructions already are, and a system-role message wedged between a
# tool result and the completion answering it is the one position providers
# disagree about how to translate.
#
# For a model that caches only on request (Anthropic's, see
# `advisor.caches_on_request`) that place costs the round its cache: the system
# prompt comes before everything else the round sends again, so changing it
# makes all of that new. Measured on 2026-10-05 on Opus 5.5, in a paid probe:
# the same round read nothing from the cache and cost
# 0.073253 USD with the notice in the system prompt, and read 13,244 tokens and
# cost 0.0096948 with it at the end. So for those models it goes at the END, as
# a user message after the round's tool results: not the system-role message
# the paragraph above avoids, and a shape OpenRouter took to Opus 5.5 that day
# without a refusal. It speaks of "the reader" in the third person, so it
# cannot pass for something they said.
#
# The offline suite can prove this sentence reaches the model on that round and
# cannot prove a model heeds it. Nothing here depends on it doing so: the round
# after this one has no tools at all, so the notice is what turns a hard stop
# into a warned one, never what enforces it.
LAST_TOOL_ROUND_NOTICE = (
    "ONE THING ABOUT THIS ROUND. It is your last round with tools. After it "
    "you will be asked once more with none, and whatever you write then is the "
    "answer the reader sees. So if you mean to propose something (a card, or "
    "up to three suggestions), call it NOW, on this round. If you still wanted to look "
    "something up, you no longer can: say what you would have checked and what "
    "it would have changed, and answer from what you already have. Do not "
    "announce a card you are not calling for."
)


def _asked(completion: int, model: str, messages: list[dict]) -> tuple[str, list[dict]]:
    """The system prompt and the messages one round is asked with: the turn's
    own, plus the deadline on the round before the last, where `model` reads it
    without the round losing its cache (see LAST_TOOL_ROUND_NOTICE)."""
    system = system_prompt(model)
    if completion != MAX_COMPLETIONS_PER_TURN - 1:
        return system, messages
    if advisor.caches_on_request(model):
        # When the round before passed pages on, the app's turn after the tool
        # results is already there, and the notice joins it: one turn of the
        # app's, not two in a row.
        tail = messages[-1] if messages else {}
        if tail.get("role") == "user" and str(tail.get("content")).startswith(PAGES_PASSED_ON):
            joined = {**tail, "content": tail["content"] + "\n\n" + LAST_TOOL_ROUND_NOTICE}
            return system, [*messages[:-1], joined]
        return system, [*messages, {"role": "user", "content": LAST_TOOL_ROUND_NOTICE}]
    return system + "\n\n" + LAST_TOOL_ROUND_NOTICE, messages


def _kept_prefixes(messages: list[dict]) -> tuple[int, ...]:
    """Where a round asks the provider to keep what it read, besides the system
    prompt and the end of the request, which `advisor.stream_llm` adds itself.

    The picture, the first message: the next turn begins the same way for as
    long as nothing in the records changes. And the question before the newest
    one, which closes the part of the conversation the next turn sends again
    byte for byte. Not the newest question: it goes out with the whole of its
    screen note (see `_wire`), and the next turn sends it back with its label
    only, so a marker there would keep a beginning nothing sends twice. That is
    also why the end-of-request marker alone would carry nothing from one turn
    to the next.

    The rounds of one turn need none of this: each sends the one before it
    whole, and the end-of-request marker covers them. Measured on 2026-10-05,
    in a paid probe: a second turn read the tools, the
    system prompt and the picture, 11,833 tokens, and a third read 81 more,
    the earlier question this marker had kept.

    A round that adds more than about twenty blocks (a model asking for ten
    tools at once) passes the provider's lookback: the next round then reads
    only up to these markers, and pays for the rest again. Rare enough to say
    rather than handle."""
    users = [i for i, m in enumerate(messages) if m["role"] == "user"]
    before = users[-2] if len(users) > 1 else 0
    return (0,) if before == 0 else (0, before)


def _work(pending: Pending, conversation_id: int) -> Iterator[schemas.ChatEvent]:
    """Run a confirmed card's long tool, saying what it finishes as it finishes,
    then settle the card and RETURN the messages the model is about to read.

    Two things happen here that do not happen on the ordinary confirm path, and
    both are consequences of the tool taking a minute rather than a millisecond.

    The steps go out as events. `run_chain` still persists nothing until all of
    it has finished — a half-run chain must not reach the reader — but that is
    a rule about what is SAVED, and a step that has finished is a fact either
    way. This is the sentence the old Analyzer page refused to fake.

    And the write is NOT inside one unit of work with the card's outcome, which
    every other write in this app is. Two reasons, and the first is what forces
    it: a session with a transaction open holds a lock on a SQLite file, and
    holding one across a minute of somebody else's network blocks every writer
    in the app — the reader saving a form in another tab included. The second
    is why it is safe to give up: the ordering can only fail in the harmless
    direction. The run is written first and the card second, so the failure
    this ordering can produce is a run that no receipt names, and the failure it
    cannot produce is a receipt over a run that never happened. The dangerous
    one is the one that is impossible.
    """
    with SessionLocal() as db:
        walk = tools.settle(db, pending.tool, pending.arguments, pending.fingerprint)
        while True:
            try:
                step = next(walk)
            except StopIteration as done:
                outcome = done.value
                break
            yield schemas.ChatStep(
                tool=pending.tool,
                step_no=step.step_no,
                label=step.label,
                duration_ms=step.duration_ms,
            )
        if not outcome["ok"]:
            # Including a stale card, which the ordinary path answers with a
            # 409 before the stream. There is no status code left to send by
            # the time a minute has gone by, so it is an error event — the one
            # ending the client already knows how to show, with the reason in
            # it, and the card still pending and still answerable.
            raise advisor.AdvisorError(outcome["error"])

        found = crud.find_chat_card(db, pending.card_id)
        if found is None:  # the conversation was deleted while it ran
            raise advisor.AdvisorError(
                "The conversation this belonged to is gone. The analysis ran "
                "and is on record."
            )
        message, _ = found
        with unit_of_work(db):
            if (
                crud.settle_chat_card(db, message, pending.card_id, "confirmed", outcome["result"])
                is None
            ):
                raise advisor.AdvisorError(
                    "Another window decided this card while the analysis was "
                    "running. It ran, and it is on record."
                )
        return _messages(db, message.conversation)


def stream(turn: PreparedTurn) -> Iterator[schemas.ChatEvent]:
    """The answer as events: `start`, the deltas and whatever the model asked
    for along the way, then exactly one `done` — or an `error` in its place,
    saying why. Whatever way it ends, the answer is stored with that ending.

    Done and broken must differ on the wire, because from the client they look
    alike otherwise: a connection that closes is a connection that closes. A
    stream that ends without `done` broke off, and the client says so. The same
    distinction prices.MarketUnreachable keeps between nothing answering and an
    answer of no. Nothing added here may become a third ending: a turn that
    called six tools still finishes on `done`, or that inference stops working.
    That is now true by construction rather than by luck: the last round of the
    loop is asked with no tools, so a turn can no longer run out of rounds
    mid-plan and end as an error over a model doing nothing wrong.

    A turn that answers a card can begin with WORK. Every write but one runs
    before the first byte, so a stream that starts at all is a decision already
    taken; the analyzer takes a minute, and a minute of a request holding open
    with nothing on the wire is the spinner this step exists to remove. So its
    decision is still taken before the stream and its work happens on it, one
    `step` event per finished step, and only then is the model asked anything.

    A turn is a LOOP now, and the loop is the tool protocol. The model streams
    a turn that ends in tool calls; that assistant turn goes back into the
    messages with its calls attached, one `tool` turn per call answers it, and
    the model is asked again with all of it. It writes the answer on whichever
    pass it has what it needs. Which means a turn is two API calls where it used
    to be one, and the tests fake both — a boundary that holds for the first
    round and not the second is not a boundary.

    The loop has a deadline and the model is told about it. The round before the
    last carries `LAST_TOOL_ROUND_NOTICE`, where that model reads it without the
    round losing its cache, and the last one is offered no tools at all. The
    first is so a plan can be finished early; the second is so a plan that was
    NOT finished ends in readable words instead of an exception.

    Every round but that last one asks the provider to keep what it read
    (`_kept_prefixes`), which only Anthropic's models need asking for; the
    request to any other model is what it was before the cache came in.

    Tools run in a session of this function's own, for the reason `_store_answer`
    opens one: the request's session belongs to the request, and by the time a
    tool runs the response body has already started.

    An answer the provider did not FINISH ends as an error too: `stream_llm`
    raises `advisor.Unfinished` once its words have gone out, so they stay in
    the record and the sentence under them says why. Until brief Z an answer
    cut by a token cap was stored as `done`, and looked finished.

    Nothing here is caught silently. An AdvisorError carries a message written
    for the reader and is sent as it is; anything else is logged with its
    traceback and reported as a break, because a generic failure in the middle
    of an answer about someone's money is still better reported than swallowed.
    A tool that fails is NOT one of those: it goes back to the model as a tool
    result saying what went wrong, because the model can say something useful
    about a look-through it could not get and a dead stream cannot.
    A reader who leaves mid-answer closes this generator: the `finally` stores
    what had been written so far as `cut`, and the words they saw are the
    words on record.
    """
    yield schemas.ChatStart(
        conversation_id=turn.conversation_id,
        user_message_id=turn.user_message_id,
        page_label=turn.page_label,
    )
    blocks: list[dict] = []
    messages = list(turn.messages)
    ending: tuple[str, str | None] | None = None
    # What the provider said each round read and cost, one entry per round
    # asked, None for a round it said nothing about. `_spent` turns them into
    # the turn's figures when it ends, however it ends.
    rounds: list[advisor.Usage | None] = []
    try:
        if turn.pending is not None:
            messages = yield from _work(turn.pending, turn.conversation_id)
        declared = tools.declarations()
        web = tools.web_search(turn.model)
        # Worked out once, on the conversation as it stands before any tool is
        # called: every round of the turn begins with it.
        kept = _kept_prefixes(messages)
        # The turn's web searches so far, against WEB_SEARCHES_PER_TURN, and
        # every page already listed: one found twice is shown and passed on
        # once.
        searched = 0
        listed: set[str] = set()
        for completion in range(1, MAX_COMPLETIONS_PER_TURN + 1):
            # The last round is asked with no tools, so it can only write. That
            # is the whole of the old error path, deleted rather than caught.
            last = completion == MAX_COMPLETIONS_PER_TURN
            calls: list[advisor.ToolCall] = []
            said: list[str] = []
            found: list[advisor.WebPage] = []
            system, asked = _asked(completion, turn.model, messages)
            rounds.append(None)
            for kind, piece in advisor.stream_llm(
                system,
                asked,
                model=turn.model,
                tools=(
                    None
                    if last
                    else declared + (web if searched < WEB_SEARCHES_PER_TURN else [])
                ),
                # Nothing asked of the round with no tools: everything a
                # provider caches begins with the tools, so what that round
                # wrote could be read only by another round without them, and
                # none follows it.
                cache_at=None if last else kept,
            ):
                if kind == "thought":
                    _say(blocks, "thought", piece)
                    yield schemas.ChatThought(text=piece)
                elif kind == "text":
                    said.append(piece)
                    _say(blocks, "text", piece)
                    yield schemas.ChatDelta(text=piece)
                elif kind == "page":
                    # Stored and sent where it arrived: before the words a
                    # round wrote from it, or after a round that ended on the
                    # app's tools and never read it.
                    if piece.url in listed:
                        continue
                    listed.add(piece.url)
                    found.append(piece)
                    _found(blocks, piece)
                    yield schemas.ChatSource(url=piece.url, title=piece.title)
                elif kind == "usage":
                    # One per round, and all of them count: a turn that called
                    # a tool asked the model twice and paid for both. Kept out
                    # of `blocks` and out of the events — this is a fact about
                    # the turn, not part of the answer, and the reader did not
                    # ask what their question weighed.
                    rounds[-1] = piece
                else:
                    calls.append(piece)
            if rounds[-1] is not None:
                searched += rounds[-1].searches or 0
            # `last` and not `not calls` alone: a call arriving on a round
            # that was offered no tools is a model contradicting the request,
            # and running it would spend a fetch on an answer no completion is
            # left to read. The words it wrote are the answer either way.
            if last or not calls:
                break
            messages.append(tools.request_message("".join(said), calls))
            proposed = False
            # The instruments this round has put on a card so far: at most
            # SUGGESTIONS_PER_ANSWER, and none twice.
            drawn: list[str] = []
            for call in calls:
                outcome = _past_the_cards(call, drawn)
                if outcome is None:
                    with SessionLocal() as db:
                        outcome = tools.answer(db, call)
                card = outcome.get("card")
                if card is not None:
                    proposed = True
                    named = _named(call)
                    if named is not None:
                        drawn.append(named)
                    blocks.append(card)
                    yield schemas.ChatCard(card=schemas.ChatCardBlock(**card))
                    continue
                # A failure's reason travels with the event, so the live answer
                # shows what the stored block will (see `schemas.ChatTool`).
                yield schemas.ChatTool(
                    name=call.name, detail=None if outcome["ok"] else outcome.get("error")
                )
                blocks.append(
                    {
                        "kind": "tool",
                        "name": call.name,
                        "ok": outcome["ok"],
                        "detail": outcome.get("error"),
                    }
                )
                messages.append(tools.result_message(call, outcome))
            if proposed:
                # The turn ends on the card, and ends DONE. The confirmation is
                # a new request against the stored conversation, so nothing is
                # held open while a person decides — a socket waiting on a
                # human is a call billing to nobody, and it would need a fourth
                # ending that `cut` could not be told apart from.
                #
                # A read tool called in the same round as a proposal has run
                # and its result is dropped here with the rest of `messages`.
                # It cost a fetch and bought a line in the record; the model
                # asks again on the next turn if it still needs it, which is
                # cheaper than the alternatives — refusing to end the turn, or
                # keeping a half-turn somewhere to resume from.
                break
            if found:
                messages.append(_passed_on(found))
        ending = ("done", None)
    except advisor.AdvisorError as exc:
        ending = ("error", str(exc))
        yield schemas.ChatError(detail=str(exc))
    except Exception:
        logger.exception("chat stream broke")
        ending = ("error", "The answer broke off before it was finished.")
        yield schemas.ChatError(detail=ending[1])
    finally:
        status, detail = ending or ("cut", None)
        message_id = _store_answer(turn, blocks, status, detail, **_spent(rounds))
    if ending[0] == "done":
        yield schemas.ChatDone(model=turn.model, message_id=message_id)
