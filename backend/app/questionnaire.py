"""The Profile form's questions, and the kind of answer each one takes.

Two writers answer them: the Profile page, which draws its form from this list
(`GET /api/survey/questions`), and the chat, whose `update_profile` card is
checked against it (`fit`). The list lived in `Profile.tsx` alone until brief
AL (2026-10-08), so the backend could not know that a yes/no question takes
yes or no: in the reader's second test round the chat filed a goal, with its
amount and its year, as the answer to one of them, the reader confirmed the
card, and the form had no button to show it on. One list, read by both, so a
question added to the form is a question the chat's writes are checked against
in the same commit.

What the form stores is what `fit` returns: "yes", "no" or "unsure" for a
yes/no question, the option as the form spells it for a choice, a number in
digits. A question with words for an answer takes any words.

The texts are the form's own, byte for byte as they were in `Profile.tsx`,
because a stored answer is compared with them: "2–5 years" is an answer only
while the option reads "2–5 years".
"""

from __future__ import annotations

import re

from app import schemas


def _asked(
    key: str,
    topic: str,
    type_: str,
    text: str,
    *,
    options: tuple[str, ...] = (),
    unsure: bool = False,
    show_if: tuple[str, str] | None = None,
    explain_when: tuple[str, str] | None = None,
) -> schemas.SurveyQuestion:
    return schemas.SurveyQuestion(
        key=key,
        topic=topic,
        type=type_,
        text=text,
        options=list(options),
        unsure=unsure,
        show_if=(
            schemas.SurveyQuestionCondition(key=show_if[0], equals=show_if[1])
            if show_if is not None
            else None
        ),
        explain_when=(
            schemas.SurveyQuestionNote(equals=explain_when[0], text=explain_when[1])
            if explain_when is not None
            else None
        ),
    )


_WHEN = ("< 2 years", "2–5 years", "> 5 years")

QUESTIONS: tuple[schemas.SurveyQuestion, ...] = (
    # About you: the context.
    _asked("about_country", "About you", "text", "Which country do you live in?"),
    _asked("about_area", "About you", "text", "Which city or area?"),
    _asked("about_age", "About you", "number", "Your age?"),
    _asked(
        "about_employment",
        "About you",
        "single",
        "Employment status?",
        options=("Employee", "Self-employed", "Business owner", "Student", "Retired", "Not working"),
    ),
    _asked(
        "about_household",
        "About you",
        "single",
        "Household?",
        options=("Single", "Couple", "Family with children", "Other"),
    ),
    _asked(
        "about_dependents", "About you", "number", "How many people depend on you financially?"
    ),
    _asked(
        "about_home",
        "About you",
        "single",
        "Your housing situation?",
        options=("Rent", "Own (with mortgage)", "Own (outright)", "Live with family", "Other"),
    ),
    # Financial literacy: each explained when the answer is no.
    _asked(
        "lit_why_invest",
        "Financial literacy",
        "boolean",
        "Do you know why people invest?",
        explain_when=(
            "no",
            "Investing grows your savings over time and protects them from inflation: "
            "money left idle loses purchasing power every year. By investing in assets "
            "that yield a return, your capital can grow and outpace inflation, in "
            "exchange for some risk.",
        ),
    ),
    _asked(
        "lit_inflation",
        "Financial literacy",
        "boolean",
        "Do you know what inflation is?",
        explain_when=(
            "no",
            "Inflation is the general rise in prices over time: with the same amount you "
            "buy less tomorrow than today. At 3%/year, €100 is worth about €97 of "
            "purchasing power after one year, which is why idle cash 'loses value'.",
        ),
    ),
    _asked(
        "lit_risk_return",
        "Financial literacy",
        "boolean",
        "Do you know the risk/return trade-off?",
        explain_when=(
            "no",
            "Higher potential returns usually require accepting more risk (ups and downs, "
            "possible losses). There are no high, guaranteed, risk-free returns. Be wary "
            "of anyone promising them.",
        ),
    ),
    _asked(
        "lit_diversification",
        "Financial literacy",
        "boolean",
        "Do you know what diversification is?",
        explain_when=(
            "no",
            "Diversification means not putting all your eggs in one basket. Spreading "
            "across instruments, sectors and regions reduces the chance that a single "
            "bad investment hurts everything.",
        ),
    ),
    # Family.
    _asked("fam_want", "Family", "boolean", "Do you want to start or grow a family?", unsure=True),
    _asked(
        "fam_when",
        "Family",
        "single",
        "On what horizon?",
        options=_WHEN,
        show_if=("fam_want", "yes"),
    ),
    _asked(
        "fam_children",
        "Family",
        "number",
        "How many children do you plan for?",
        show_if=("fam_want", "yes"),
    ),
    # Housing and city.
    _asked("home_buy", "Housing & city", "boolean", "Do you plan to buy a home?", unsure=True),
    _asked(
        "home_when",
        "Housing & city",
        "single",
        "When?",
        options=_WHEN,
        show_if=("home_buy", "yes"),
    ),
    _asked(
        "home_city", "Housing & city", "text", "Any city/area you plan to move to or settle in?"
    ),
    # Career and income.
    _asked(
        "career_change",
        "Career & income",
        "boolean",
        "Do you expect a major career or income change soon?",
        unsure=True,
    ),
    _asked(
        "career_detail",
        "Career & income",
        "text",
        "Briefly, what change?",
        show_if=("career_change", "yes"),
    ),
    # Major purchases.
    _asked(
        "big_purchase",
        "Major purchases",
        "boolean",
        "Any large purchase planned (car, renovation, …)?",
        unsure=True,
    ),
    _asked(
        "big_purchase_detail",
        "Major purchases",
        "text",
        "What and roughly when?",
        show_if=("big_purchase", "yes"),
    ),
    # Retirement and horizon.
    _asked(
        "ret_age",
        "Retirement & horizon",
        "number",
        "At what age would you like to retire or be financially independent?",
    ),
    # Risk and values.
    _asked(
        "risk_tolerance",
        "Risk & values",
        "single",
        "How would you describe your risk tolerance?",
        options=("Low", "Medium", "High"),
    ),
    # The classic loss-aversion probe: both options have the SAME expected
    # value (a loss of 500), so the answer reveals the attitude to risk rather
    # than to the amount.
    _asked(
        "risk_loss_choice",
        "Risk & values",
        "single",
        "Which would you choose: a certain loss of 500 €, or a 50% chance of losing "
        "1000 € and a 50% chance of losing nothing?",
        options=("A certain loss of 500 €", "A 50/50 gamble: lose 1000 € or lose nothing"),
    ),
    _asked(
        "values_esg",
        "Risk & values",
        "boolean",
        "Do ethical / ESG considerations matter for your investments?",
        unsure=True,
    ),
    # In their own words: the richest input a model can get, and the one no
    # number can replace, how they talk about their own money and how they
    # want to be talked to.
    _asked(
        "self_narrative",
        "In your words",
        "longtext",
        "Write freely about yourself and your money: what you are working towards, what "
        "worries you, what you would never give up, how you want Aurelio to talk to you. "
        "Nothing here is validated or scored: it is context.",
    ),
    # Lifestyle.
    _asked(
        "lifestyle_notes",
        "Lifestyle",
        "text",
        "Anything else about your situation, habits, or plans Aurelio should know?",
    ),
)

BY_KEY: dict[str, schemas.SurveyQuestion] = {q.key: q for q in QUESTIONS}


class AnswerRefused(ValueError):
    """An answer the form's question does not take, said in one sentence that
    names the question and what it takes. A rule speaking, not a failure: the
    chat shows the sentence as it is, with no exception's name in front of it."""


def choices(question: schemas.SurveyQuestion) -> list[str]:
    """What the form offers to press or pick, in its order: yes and no for a
    yes/no question (unsure between them where the form offers it), the
    options for a choice, nothing for a question answered in words or digits."""
    if question.type == "boolean":
        return ["yes", "unsure", "no"] if question.unsure else ["yes", "no"]
    if question.type == "single":
        return list(question.options)
    return []


def visible(question: schemas.SurveyQuestion, answers: dict[str, str]) -> bool:
    """Whether the Profile form shows `question` with these answers: always,
    or, for a follow-up, while the answer it follows is the one it waits for.
    `isVisible` in the frontend's `questionnaire.ts`, which the form draws and
    saves by: a follow-up it does not show is left out of its Save."""
    return question.show_if is None or answers.get(question.show_if.key) == question.show_if.equals


def takes(question: schemas.SurveyQuestion) -> str:
    """The kind of answer `question` takes, in words: what a refusal says, and
    what the chat is told under each question it can answer."""
    offered = choices(question)
    if offered:
        quoted = [f'"{choice}"' for choice in offered]
        return ", ".join(quoted[:-1]) + " or " + quoted[-1]
    if question.type == "number":
        return "a number, in digits"
    return "any words"


# What the form's number box stores: digits, with a decimal point if any.
_NUMBER = re.compile(r"\d+(\.\d+)?")


def fit(question: schemas.SurveyQuestion, answer: str) -> str:
    """`answer` as the form stores it for `question`, or AnswerRefused.

    A choice is matched whatever its case and stored as the form spells it, so
    "Yes" is "yes" and "medium" is "Medium". A number is digits and nothing
    else: "35 years" is refused, so that what the form shows in its number box
    is what was stored."""
    given = answer.strip()
    offered = choices(question)
    if offered:
        for choice in offered:
            if given.casefold() == choice.casefold():
                return choice
    elif question.type == "number":
        if _NUMBER.fullmatch(given):
            return given
    else:
        return given
    raise AnswerRefused(
        f'"{question.text}" is a question of the Profile form, and it takes '
        f'{takes(question)}: "{given}" is not one, so no card was drawn.'
    )
