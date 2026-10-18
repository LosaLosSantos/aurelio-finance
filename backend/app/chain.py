"""The advisor chain: model roles that argue before anything reaches the user.

One model asked once tends to agree with itself. The chain gets a second
opinion out of **information asymmetry**, not out of more models:

1. **Analyst** sees the records and nothing else (the investments and, since
   brief Z, everything the person owns beside them: cash, flows in force, real
   assets, debts; no profile, no goals), so it cannot bend the numbers to
   flatter the person.
2. **Confidant** sees the person and the analyst's findings, but never the
   figures — so it can only argue about fit, temperament and framing.
3. **Analyst revision** answers the challenge point by point, and must label
   each one REVISE or HOLD. Silently dropping a point is forbidden.
4. **Synthesis** writes the answer, and is required to surface any remaining
   disagreement instead of averaging it away.

The mandates are deliberately adversarial. Two polite models converge into
agreeable mush that carries no information; the value of the chain is the
friction, so the prompts ask for friction and the revision step has to state
what it refuses to change.

THE ANALYST CAN CHECK, since brief AR (2026-10-12). With no tool, what its
context did not hold it could not check: in the brief's P0 it called a fund's
0.20% a year "efficient" against nothing, guessed what a bond fund held, and
stated a coin's history from memory. The analyst and its revision now have
read-only tools (`analyst_tools`): the look-through, what the catalogue holds
on a fund's index, what an instrument is, what a change would weigh, and for
Anthropic's models the web. None of them reads the profile, the goals or the
questionnaire, and a test plants markers there to hold that line; the
confidant and the synthesis have none. A step that may look things up asks in
rounds (`_looked_up`): at most ROUNDS_PER_STEP requests and SEARCHES_PER_STEP
searches, its cost every one of them.

THE DEPTH IS VARIABLE, and that is what makes this an orchestration rather than
a pipeline. Steps 1, 2 and 4 always run: the asymmetry is the chain, and the
synthesis is the only thing written to the person. Step 3 runs only when the
confidant's challenge actually DISAGREES — which is cheap to know, because the
confidant's own mandate already tells it to dismiss a finding that fits in one
line and move on, and it now ends by saying which of the two it did. When the
disagreement is real the loop goes round again: the confidant reads the
revision and says whether it still stands, and the analyst answers once more.
So a run is three steps where there is nothing to argue about and up to six
where there is — deeper than the old fixed four, exactly where depth earns it.
An analyst's step is one request when it looks nothing up, and up to
ROUNDS_PER_STEP when it does.

What that saves is the WAIT, not the money. Four steps writing full analyses
land in the low cents; a minute of a person's attention is the expensive part.
Which is also why the cost is now measured per step instead of estimated:
`ChainStep.cost` is what the provider reported, and the card that asks the
reader to spend it quotes the last run rather than a feeling.

Models per role (env, all optional, falling back to OPENROUTER_MODEL):
    OPENROUTER_ANALYST_MODEL    — quantitative work
    OPENROUTER_CONFIDANT_MODEL  — reading a person, choosing words
Different models add genuinely different blind spots, which is the point of a
panel; the same model in both seats still works because the asymmetry is in
the *context*, not the weights.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import advisor, crud, models

# How the confidant reports whether it is actually arguing. A marker and not a
# judgement made by reading the prose: "does this text disagree" is a question
# a second model call would have to answer, and a second call to decide whether
# to make a third one is the wait this step exists to cut.
CONTESTED = "CONTESTED"
FITS = "FITS"

CONFIDANT_SYSTEM_PROMPT = (
    "You know this person from what they have told us about themselves. You "
    "have NOT seen their portfolio, their balances or any figure about their "
    "holdings — do not pretend otherwise and never invent numbers. "
    "You are given: (a) what the person said about themselves, in their own "
    "words and through a questionnaire, and (b) an independent analyst's "
    "findings about their investments. "
    "Your job is ADVERSARIAL, not supportive: find where this analysis would "
    "fail THIS person. Consider their temperament and stated attitude to risk "
    "and loss, their commitments and plans, what they said they would never "
    "give up, and how they asked to be spoken to. "
    "For each point you challenge: name the analyst's finding, then say what "
    "about this person makes it wrong, risky, or merely badly framed — "
    "distinguish those three. If a finding fits them well, say so in one line "
    "and move on. Do NOT restate or summarise the analysis, and do not add "
    "your own portfolio advice. "
    "If something important about them is missing, say what you would need to "
    "ask rather than assuming it. "
    "Their answers are dated, and their records may have changed since. When "
    "something they said may be about a figure the analyst used (an amount, or "
    "something they said was not yet recorded), do not correct the figure with "
    "it: raise it as a question to ask them, with its date. "
    "Be concise and specific. Markdown, short bullets. Answer in English. "
    + advisor.NO_DASHES
    + "\n\n"
    "END your reply with one line, on its own, and nothing after it:\n"
    f"VERDICT: {CONTESTED}   — you are challenging something that matters: a "
    "finding you say is wrong or risky for them, not merely worded badly.\n"
    f"VERDICT: {FITS}   — nothing here needs the analyst to answer: the "
    "findings fit this person, or your remarks are about framing only.\n"
    "That line decides whether the analyst is asked to answer you, which costs "
    "this person another wait. Say CONTESTED when you mean it and FITS when "
    "you do not."
)

REVISION_SYSTEM_PROMPT = (
    "You are the same quantitative analyst who wrote the analysis below. A "
    "colleague who knows the person — but has never seen the numbers — has "
    "challenged it. "
    "Go through their challenge point by point. Label each one exactly "
    "**REVISE** or **HOLD**. "
    "REVISE: you change a conclusion or the way it is framed — say what it "
    "becomes. HOLD: the numbers stand — say why, and do not soften it to be "
    "agreeable. "
    "You must not silently drop any challenged point, and you must not invent "
    "new findings here. "
    "Keep the distinction sharp: a preference cannot move an arithmetic fact. "
    "Nor can something the person said. Where the challenge sets a stated "
    "figure against the records, HOLD the recorded figure, name the conflict "
    "and what to ask them; the stated one is at most a second case, "
    "conditional on their answer, never the headline. "
    "If the challenge is about how something should be said rather than "
    "whether it is true, say exactly that — the figure holds, the framing "
    "changes. "
    "The figures you analysed come first, above your analysis: answer from "
    "them, not from memory. " + advisor.WHOLE_RULE + " "
    "Markdown, one short block per point. Answer in English. " + advisor.NO_DASHES
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You are Aurelio, writing the final answer to the person. 'Aurelio' is "
    "YOUR name, never theirs; speak to them directly as 'you'. "
    "You are given a structural analysis of their investments and of everything "
    "they own beside them (cash, income and expenses, real assets, debts), a "
    "challenge from the point of view of who they are, and the analyst's "
    "revision. "
    "Every percentage you write names its whole, as the analysis named it: a "
    "share of the investments, of the investments and the cash together (the "
    "liquid wealth), or of everything they own (the liquid wealth and the real "
    "assets). Their real assets count in what they own and in how it is "
    "allocated, never in what they can spend: a home is not cash. "
    "Write the answer: lead with what to do and why, in priority order. "
    "Where the analyst and the challenge still DISAGREE, say so explicitly "
    "and explain the trade-off — never average two positions into a bland "
    "middle, and never present a contested point as settled. "
    "Where something they said may already be in their records, the recorded "
    "figure is the one you give, with the open question beside it. Never tell "
    "them to enter what may already be there: tell them what to check. "
    "Speak to them the way they said they want to be spoken to. Do not "
    "mention roles, steps, or that several models were involved: this is one "
    "answer. "
    "Clean simple Markdown, no horizontal rules. Close with a one-line "
    "disclaimer that this is educational information, not personalized "
    "regulated advice. Answer in English. " + advisor.NO_DASHES
)

# What the analyst and its revision are told about their tools (brief AR), after
# the role's own prompt: that one says what to judge, this how to check it.
TOOLS_RULES = (
    "\n\nYOU CAN CHECK WHAT THE FIGURES DO NOT HOLD, with tools that read the "
    "records, the fund catalogue and the market, and nothing about the person: "
    "`get_look_through` (every axis of the funds' holdings, the companies and "
    "the currencies), `catalogue_same_index` (what the catalogue holds on a held "
    "fund's index: how many funds, at which costs), `instrument_facts` (what a "
    "position is, from the catalogue or Yahoo, and its latest close) and "
    "`weigh_change` (what a purchase, a sale or a switch would do to the "
    "exposure). Use them before you state what they can check, never your "
    "memory: judge a fund's cost only against what the catalogue holds on its "
    "index, say what a position is only once it is read, and give a change's "
    "effect only from `weigh_change`. Ask for several in one round when you need "
    "several: you have a few rounds, then you answer. Say where each fact you "
    "checked comes from (the catalogue, Yahoo, the look-through). Never name a "
    "fund or a share the person does not hold: say what the catalogue holds "
    "(how many funds on the index, from which cost), and they can ask the chat "
    "to name one."
)

# Said only to a model that is offered the web (`analyst_tools.declarations`).
WEB_RULES = (
    " `search_web` searches the web: for what an instrument you judge is doing "
    "(its results, valuation, risks and news), how an index works, or a fact you "
    "would otherwise state from memory. Never put a figure or a name from the "
    "records in a query. Every claim from a page carries its link, as "
    "[title](url), in the sentence that makes it, and a figure from a page is "
    "stated with its link or not at all. The web finds; it does not verify."
)


def tools_prompt(model: str) -> str:
    """The tools' rules for the model a step runs on, the web's only where it
    is offered the web."""
    from app import tools  # here: tools imports this module

    return TOOLS_RULES + (WEB_RULES if tools.web_search(model) else "")


# How many times the analyst may be asked to answer a challenge in one run.
# The loop is confidant -> revision -> confidant again, and it stops when the
# confidant stops contesting or when this bound is reached, whichever is first.
# Two, because the third round of the same argument is two models restating
# themselves at the reader's expense — and because the bound has to be a number
# somebody chose rather than a model's stamina.
MAX_REVISION_ROUNDS = 2

# The whole chain at its narrowest and at its widest: analyst + confidant +
# synthesis, and the same with MAX_REVISION_ROUNDS × (confidant + revision) in
# the middle. Written here so the card can quote the range without counting the
# loop by hand, and so the two cannot drift.
MIN_STEPS = 3
MAX_STEPS = 2 + MAX_REVISION_ROUNDS * 2

# How many requests one step that may look things up sends at most: three that
# may call tools, then one with none, which has to answer in words. In brief AR's
# P0 (2026-10-12) what the analyst could not check came to about nine lookups
# (three funds against the catalogue, four positions, two searches); a round asks
# for several at once, so two rounds of checks and one to write fit, and the
# fourth is the spare and the close, as the chat's seventh is
# (`chat.MAX_COMPLETIONS_PER_TURN`). A bound on cost and on the wait, never on
# what a step may answer: its last round always ends in words.
ROUNDS_PER_STEP = 4

# How many web searches one step may run: three, about $0.022 at brief AM's
# measured $0.0073 a search. One past them is answered in words and runs
# nothing, the tools left as they are, so the cache holds
# (`chat.WEB_SEARCHES_PER_TURN`).
SEARCHES_PER_STEP = 3

SEARCHES_SPENT = (
    f"This step has already run {SEARCHES_PER_STEP} web searches, the most one step "
    "may, so this one did not run: work from what you have."
)

# The round before the last says so, as the chat's does
# (`chat.LAST_TOOL_ROUND_NOTICE`): a deadline told is one the model can plan
# against. For Anthropic's models it is a user message after the round's tool
# results, so the round still reads the one before it from the cache; for the
# others, a line of the round's system prompt.
LAST_TOOL_ROUND_NOTICE = (
    "ONE THING ABOUT THIS ROUND. It is your last round with tools. After it you "
    "will be asked once more with none, and what you write then is your whole "
    "answer for this step. If you still mean to check something, ask for it on "
    "this round. Whatever you could not check, say so in the answer, and what it "
    "would have changed."
)


@dataclass(frozen=True)
class Step:
    """One step that has FINISHED, said while the run is still going.

    The chain used to report nothing until all of it was done, because a
    half-run chain must not reach the reader — and that constraint is about
    what is SAVED, not about what is said. A step that has finished is a fact,
    and "the analyst is done, the confidant is reading it now" is a true
    sentence somebody was waiting to hear. Nothing here is persisted: the run
    is, whole, at the end.
    """

    step_no: int
    role: str
    title: str
    model: str
    duration_ms: int
    cost: float | None
    # Words for the step's line when OpenRouter turned its first ask away and
    # it was asked once more (`advisor.call_llm`, ASKED_AGAIN_ON); else None.
    asked_again: str | None = None
    # Words for the step's line when it looked things up: its rounds, its
    # lookups and its web searches (`_looked_up`); None when it looked up
    # nothing. Said while the run goes, never stored: no column of a step's
    # holds it, and none was added for it (the reader's choice, 2026-10-12).
    looked_up: str | None = None


def _steps(numbers: list[int]) -> str:
    """"step 2", "steps 1 and 3", "steps 1, 2 and 4"."""
    if len(numbers) == 1:
        return f"step {numbers[0]}"
    return f"steps {', '.join(map(str, numbers[:-1]))} and {numbers[-1]}"


def _what_it_cost(costs: list[float | None]) -> str:
    """What a run that stopped had cost, one entry per step it reached, the
    stopped one included, as OpenRouter reported each.

    A step whose price was not reported is said as unknown and never summed as
    zero (the reader's rule, 2026-10-02). A run that is not saved is recorded
    nowhere else, so this sentence is the only place its spend is written."""
    known = [n for n, cost in enumerate(costs, start=1) if cost is not None]
    unknown = [n for n, cost in enumerate(costs, start=1) if cost is None]
    total = f"${sum(cost for cost in costs if cost is not None):.4g}"
    if not unknown:
        return f"Until it stopped it had cost {total}, as OpenRouter reported it."
    if not known:
        return (
            f"OpenRouter reported no price for {_steps(unknown)}, so what the run "
            "cost is not known."
        )
    return (
        f"OpenRouter reported {total} for {_steps(known)} and no price for "
        f"{_steps(unknown)}, so what the run cost is not known."
    )


def _stopped(error: advisor.AdvisorError, step_no: int, title: str, costs: list[float | None]) -> str:
    """The sentence the reader is shown when a step does not give the chain an
    answer: the cause first, in the words it already carries (a model that is
    gone says which one and where it is set), then where the analysis stopped,
    that nothing was kept, and what it had spent."""
    cause = str(error).strip()
    if not cause.endswith((".", "!", "?")):
        cause += "."
    return (
        f'{cause} The analysis stopped at step {step_no}, "{title}", and nothing from '
        f"this run was kept. {_what_it_cost(costs)}"
    )


# The variables each role reads for its model, in order, before the app's
# built-in default: its own, then everything's (`advisor.resolve_model`). What
# the analysis's card names as where a role's model is set (brief BB).
ROLE_READS = {
    "analyst": ("OPENROUTER_ANALYST_MODEL", "OPENROUTER_MODEL"),
    "confidant": ("OPENROUTER_CONFIDANT_MODEL", "OPENROUTER_MODEL"),
}


def _model_for(role: str) -> str | None:
    """Per-role model override, or None to use the app default."""
    own = ROLE_READS.get(role)
    return (os.getenv(own[0]) if own else None) or None


def _total(costs: list[float | None]) -> float | None:
    """What a step cost: every request and every search it ran, summed, and
    unknown when any one of them is (the reader's rule, 2026-10-02)."""
    return sum(costs) if costs and None not in costs else None


def _said(rounds: int, lookups: int, searches: int) -> str | None:
    """A step's lookups in words, for its line, or None when it looked up
    nothing: "looked up 6 things in 2 rounds, 1 of them a web search"."""
    if not lookups:
        return None
    things = f"{lookups} thing{'' if lookups == 1 else 's'}"
    asked = f"{rounds} round{'' if rounds == 1 else 's'}"
    if searches == 0:
        web = ""
    elif searches == 1:
        web = ", 1 of them a web search"
    else:
        web = f", {searches} of them web searches"
    return f"looked up {things} in {asked}{web}"


def _answered(
    db: Session, calls: tuple[advisor.ToolCall, ...], allowed: int, offered: list[str]
) -> tuple[list[dict], list]:
    """What each call of one round comes to, in the round's order, and the web
    searches that ran. A search past the `allowed` the step has left is
    answered in words (SEARCHES_SPENT) and runs nothing; the ones that run go
    at once, each a request of its own that waits for nothing else, as the
    chat's do (`chat._searches`). Every other call is the analysis's tools'
    (`analyst_tools.answer`), a name it does not offer included."""
    from concurrent.futures import ThreadPoolExecutor

    from app import analyst_tools, tools, websearch  # here: tools imports this module

    outcomes: list[dict | None] = [None] * len(calls)
    queued: list[tuple[int, str]] = []
    for place, call in enumerate(calls):
        if call.name != tools.SEARCH_WEB or call.name not in offered:
            outcomes[place] = analyst_tools.answer(db, call, offered)
            continue
        query = tools.search_query(call)
        if isinstance(query, dict):  # its arguments do not fit; it says how
            outcomes[place] = query
        elif len(queued) >= allowed:
            outcomes[place] = {"ok": False, "error": SEARCHES_SPENT}
        else:
            queued.append((place, query))
    ran = []
    if queued:
        with ThreadPoolExecutor(max_workers=len(queued)) as pool:
            found = list(pool.map(websearch.search, [query for _, query in queued]))
        for (place, _), search in zip(queued, found):
            outcomes[place] = websearch.outcome(search)
            ran.append(search)
    return outcomes, ran


def _looked_up(db: Session, system: str, user: str, model: str | None) -> dict:
    """A step that may look things up before it answers (brief AR), in rounds:
    each round may ask for the analysis's tools (`analyst_tools`) and the web,
    their answers go back to it, and the step ends on the first round that
    answers in words. At most ROUNDS_PER_STEP rounds, the last offered no tool
    and the one before it told so (LAST_TOOL_ROUND_NOTICE), and reading the
    cache up to where the round before it ended, keeping nothing new; at most
    SEARCHES_PER_STEP searches. Every round names STEP_MAX_TOKENS and may be
    asked once more on a 500, 502 or 503, never on a cut (`advisor.call_round`).

    Returns what `advisor.call_llm` does, with the step's cost being every
    round's and every search's, unknown when any one is unknown, and
    `looked_up`, its lookups in words. A round that stops the step raises
    with the cost the step had run up until then, that round's own included
    when it was said, so the run's sentence counts it (`_stopped`)."""
    from app import analyst_tools, tools  # here: tools imports this module

    resolved = advisor.resolve_model(model)
    declared = analyst_tools.declarations(resolved, SEARCHES_PER_STEP)
    offered = [d["function"]["name"] for d in declared]
    marked = advisor.caches_on_request(resolved)
    messages: list[dict] = [{"role": "user", "content": user}]
    costs: list[float | None] = []
    asked_again: list[str] = []
    lookups = searches = 0
    sent = 0  # how many messages the round before sent
    for n in range(1, ROUNDS_PER_STEP + 1):
        last = n == ROUNDS_PER_STEP
        round_system, asked, kept_to = system, messages, None
        if n == ROUNDS_PER_STEP - 1:
            # What this round would keep, only a round with the same tools
            # could read, and none follows: it reads up to where the round
            # before it ended instead (its question, on a first round).
            kept_to = max(sent - 1, 0)
            if marked:
                asked = [*messages, {"role": "user", "content": LAST_TOOL_ROUND_NOTICE}]
            else:
                round_system = f"{system}\n\n{LAST_TOOL_ROUND_NOTICE}"
        try:
            answered = advisor.call_round(
                round_system, asked, model=model, tools=None if last else declared, kept_to=kept_to
            )
        except advisor.AdvisorError as exc:
            exc.cost = _total([*costs, getattr(exc, "cost", None)])
            raise
        costs.append(answered.usage.cost)
        if answered.asked_again:
            asked_again.append(answered.asked_again)
        if not answered.calls:
            return {
                "analysis": answered.content,
                "model": answered.model,
                "cost": _total(costs),
                "asked_again": "; ".join(asked_again) or None,
                "looked_up": _said(n - 1, lookups, searches),
            }
        outcomes, ran = _answered(db, answered.calls, SEARCHES_PER_STEP - searches, offered)
        lookups += len(answered.calls)
        searches += len(ran)
        costs.extend(s.usage.cost if s.usage is not None else None for s in ran)
        sent = len(asked)
        messages = [
            *messages,
            tools.request_message(answered.content, list(answered.calls)),
            *(tools.result_message(call, outcome) for call, outcome in zip(answered.calls, outcomes)),
        ]
    # The last round offers no tool, so it answers in words or raises.
    raise AssertionError("a step's last round asked for tools it was not offered")


def verdict_of(challenge: str) -> str | None:
    """The marker the confidant ended on: CONTESTED, FITS, or None for neither.

    The LAST `VERDICT:` line wins, because a model that discusses its own
    marker mid-text has not changed its mind by mentioning it.

    None IS A THIRD ANSWER and not a synonym for either. A reply with no marker
    is a model that did not say, which is a different fact from a model that
    said it is not arguing — the same distinction this app keeps between "no
    source answered" and "this instrument does not exist". What the two callers
    do with that difference is theirs to decide, and they decide it oppositely:
    `contested` runs the extra round, and a count of how often the mandate
    bites refuses to count the run at all.
    """
    verdict = None
    for line in challenge.splitlines():
        stripped = line.strip().lstrip("*_# ").rstrip("*_ ")
        if stripped.upper().startswith("VERDICT:"):
            said = stripped.split(":", 1)[1].strip().upper()
            verdict = said if said in (CONTESTED, FITS) else None
    return verdict


def contested(challenge: str) -> bool:
    """Whether the confidant's last word was that it is actually arguing.

    A reply with no marker at all counts as CONTESTED: the revision round is
    what this chain did before there was a marker, and skipping a step because
    a model forgot to say something is cutting depth on a formatting slip. The
    step is cut when the confidant SAYS it is not needed, and at no other time.
    """
    return verdict_of(challenge) != FITS


def challenge_of(run: models.ChainRun) -> str | None:
    """What the confidant declared across one WHOLE run, not one turn of it.

    A run can hold several challenges — the loop goes round again while the
    argument is worth it — so the run-level answer is: it was contested if the
    confidant ever said so, it fits if it said that and never the other, and it
    is None when no turn declared either.

    NOT the same question as "how deep did this run go", and the two can
    disagree in both directions, which is the reason to read the marker rather
    than count the steps. A confidant that says CONTESTED on the last round
    allowed by `MAX_REVISION_ROUNDS` buys no further revision and still
    contested; a confidant that says nothing at all buys one and declared
    nothing. Counting revisions would report the first as agreement and the
    second as argument, and both would be wrong.
    """
    verdicts = [verdict_of(s.output) for s in run.steps if s.role == "confidant"]
    if CONTESTED in verdicts:
        return CONTESTED
    if FITS in verdicts:
        return FITS
    return None


def run_chain(db: Session) -> Iterator[Step]:
    """Run the chain, saying what has finished as it finishes, and persist it
    whole at the end.

    A GENERATOR that RETURNS the `models.ChainRun` — `yield` is the progress,
    `return` is the result, and a caller that only wants the run drains it:

        walk = chain.run_chain(db)
        while True:
            try:
                next(walk)
            except StopIteration as done:
                run = done.value

    Raises advisor.AdvisorError if a step fails, and a half-run chain is not
    saved — the reader never sees a verdict that skipped its own critique. That
    is why the steps are accumulated and written once, and why a failure after
    the third yielded step still leaves nothing behind: what was said while it
    ran was true when it was said, and none of it is a record.

    A step whose answer did not FINISH fails the same way (advisor.Unfinished,
    raised by `call_llm`). Run 1, on 2026-10-02, went on for five steps from an
    analyst's text cut at "The top four" and was saved whole, because a cut
    answer did not raise. Whatever stops a step, the error says, after its
    cause, which step the run stopped at, that nothing was kept, and what the
    run had cost until then, since a run that is not saved records its spend
    nowhere. A cut is not retried: a cut on the same prompt and limit would
    repeat. The one second ask is `call_llm`'s, and each round's of a step that
    looks things up (`advisor.call_round`), for a request no provider took (a
    500, 502 or 503, which OpenRouter says it does not bill); the card says so
    before the run, and the step's line when it happens.
    """
    portfolio_ctx = advisor.build_portfolio_context(db)
    person_ctx = advisor.build_person_context(db)

    analyst_model = _model_for("analyst")
    confidant_model = _model_for("confidant")

    steps: list[dict] = []

    def run_step(
        role: str, title: str, system: str, user: str, model: str | None, looks: bool = False
    ) -> str:
        """One step: asked once (`advisor.call_llm`), or, for the analyst's
        steps (`looks`), in rounds that may look things up (`_looked_up`)."""
        started = time.monotonic()
        try:
            if looks:
                result = _looked_up(db, system + tools_prompt(advisor.resolve_model(model)), user, model)
            else:
                result = advisor.call_llm(system, user, model=model)
        except advisor.AdvisorError as error:
            # The stopped step's own price, when the provider reported one: a
            # cut answer is billed like a whole one, and a step that looked
            # things up first says what all its requests had cost.
            costs = [s["cost"] for s in steps] + [getattr(error, "cost", None)]
            raise advisor.AdvisorError(
                _stopped(error, len(steps) + 1, title, costs)
            ) from error
        steps.append(
            {
                "role": role,
                "title": title,
                "model": result["model"],
                "output": result["analysis"],
                "duration_ms": int((time.monotonic() - started) * 1000),
                "cost": result.get("cost"),
                "asked_again": result.get("asked_again"),
                "looked_up": result.get("looked_up"),
            }
        )
        return result["analysis"]

    def finished() -> Step:
        """The step just appended, as the reader is told about it."""
        last = steps[-1]
        return Step(
            step_no=len(steps),
            role=last["role"],
            title=last["title"],
            model=last["model"],
            duration_ms=last["duration_ms"],
            cost=last["cost"],
            asked_again=last["asked_again"],
            looked_up=last["looked_up"],
        )

    # 1 — the numbers, with no idea whose they are.
    # Its tools cannot see whose either (`analyst_tools`).
    findings = run_step(
        "analyst",
        "The numbers, on their own merits",
        advisor.PORTFOLIO_SYSTEM_PROMPT,
        f"Here is the portfolio:\n\n{portfolio_ctx}\n\nProvide your analysis.",
        analyst_model,
        looks=True,
    )
    yield finished()

    # 2 — the person, with no idea what the numbers are, for as many rounds as
    # the argument is worth. `answering` is what the confidant is reading: the
    # findings the first time, the analyst's own revision after that, so a
    # second round is a real second look and not the first one repeated.
    answering = findings
    challenge = ""
    revision = ""
    rounds = 0
    while True:
        again = " again" if rounds else ""
        challenge = run_step(
            "confidant",
            f"Where this would fail this person{again}",
            CONFIDANT_SYSTEM_PROMPT,
            f"{person_ctx}\n\n"
            f"# The analyst's {'answer' if rounds else 'findings'}\n\n{answering}\n\n"
            "Challenge it where it does not fit this person.",
            confidant_model,
        )
        yield finished()
        if not contested(challenge):
            break

        # 3 — the analyst answers for itself. Only here, and only because the
        # colleague said there is something to answer.
        rounds += 1
        revision = run_step(
            "revision",
            f"What the analyst revises, and what it holds{' again' if rounds > 1 else ''}",
            REVISION_SYSTEM_PROMPT,
            # The figures again, because this is the analyst answering for
            # them: a challenge about a safety net is answered with the cash
            # it can see, not with what its first answer happened to quote.
            f"# The figures you analysed\n\n{portfolio_ctx}\n\n"
            f"# Your analysis\n\n{findings}\n\n"
            + (f"# What you already answered\n\n{answering}\n\n" if rounds > 1 else "")
            + f"# The challenge\n\n{challenge}\n\n"
            "Answer point by point, labelling each REVISE or HOLD.",
            analyst_model,
            looks=True,
        )
        yield finished()
        answering = revision
        if rounds >= MAX_REVISION_ROUNDS:
            # Bounded on a REVISION and never on a challenge: the analyst
            # having the last word is the shape the synthesis reads best, and
            # stopping one turn earlier would leave the run ending on a
            # complaint nobody was allowed to answer.
            break

    # 4 — one voice, disagreements included. The revision block is omitted
    # rather than sent empty: "# Analyst's revision\n\n" with nothing under it
    # reads as an analyst that had nothing to say, which is the opposite of a
    # challenge nobody needed to answer.
    verdict = run_step(
        "synthesis",
        "What this means for you",
        SYNTHESIS_SYSTEM_PROMPT,
        f"# Structural analysis\n\n{findings}\n\n"
        f"# Challenge (who they are)\n\n{challenge}\n\n"
        + (f"# Analyst's revision\n\n{revision}\n\n" if revision else "")
        + f"# How they describe themselves\n\n{person_ctx}\n\n"
        "Write the final answer.",
        confidant_model,
    )
    yield finished()

    return crud.create_chain_run(db, verdict=verdict, steps=steps)
