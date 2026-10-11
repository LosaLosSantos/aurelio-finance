"""A question the Profile form asks takes only its own kind of answer.

The reader's second test round of the chat (2026-10-08): asked to add a goal,
the chat drew an `update_profile` card for one of the form's yes/no/unsure
questions with the goal, its amount and its year as the answer; the reader
confirmed it, the form had no button to show it on, and no goal existed. The
form's questions lived in `Profile.tsx` alone, so nothing on the backend knew
what any of them takes (brief AL).

Now the list is `app/questionnaire.py`, served to the form, and every answer
the chat writes to one of its questions is checked against it: refused with a
sentence when it does not fit, stored as the form stores it when it does. A
goal is no answer at all, and the chat is told so. Every figure and wording of
an answer here is invented.
"""

from __future__ import annotations

import json

from app import advisor, chat, tools
from app.database import SessionLocal

# `app.questionnaire` is imported inside the two tests that read the list, so
# that on code from before it (74b9532) every other test still runs and says
# what it finds, instead of the whole file failing to import.

# One of the form's yes/no/unsure questions, as the form words it.
BIG = "Any large purchase planned (car, renovation, " + chr(0x2026) + ")?"

_ANSWERED = [
    {
        "question_key": "big_purchase",
        "topic": "Major purchases",
        "question": BIG,
        "answer": "unsure",
    },
    {"question_key": "about_age", "topic": "About you", "question": "Your age?", "answer": "30"},
]


def _ask_for(arguments: dict) -> advisor.ToolCall:
    return advisor.ToolCall(id="call_1", name="update_profile", arguments=json.dumps(arguments))


def _draft(db, **arguments) -> dict:
    return tools.answer(db, _ask_for(arguments))


def _confirm(db, card: dict) -> dict:
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


def _answers(client) -> dict[str, dict]:
    return {a["question_key"]: a for a in client.get("/api/survey").json()}


# --- The form's list, served --------------------------------------------------------


def test_the_form_draws_itself_from_the_backends_list(client):
    """One list, read by the form and by the chat's check: a question added to
    the form is a question the chat's writes are checked against."""
    from app import questionnaire

    served = client.get("/api/survey/questions").json()

    assert [q["key"] for q in served] == [q.key for q in questionnaire.QUESTIONS]
    assert len(served) == 27
    big = next(q for q in served if q["key"] == "big_purchase")
    assert big == {
        "key": "big_purchase",
        "topic": "Major purchases",
        "text": BIG,
        "type": "boolean",
        "options": [],
        "unsure": True,
        "show_if": None,
        "explain_when": None,
    }
    detail = next(q for q in served if q["key"] == "big_purchase_detail")
    assert detail["show_if"] == {"key": "big_purchase", "equals": "yes"}
    fam_when = next(q for q in served if q["key"] == "fam_when")
    assert fam_when["options"] == ["< 2 years", "2" + chr(0x2013) + "5 years", "> 5 years"]
    inflation = next(q for q in served if q["key"] == "lit_inflation")
    assert inflation["explain_when"]["equals"] == "no"


# --- What a question of the form takes ------------------------------------------------


def test_a_goal_written_into_a_yes_no_question_is_refused_with_a_sentence(client):
    """The reader's case, with invented figures: the card is never drawn, the
    answer on record is untouched, and what comes back is one sentence naming
    the question and what it takes, with no exception's name in front of it."""
    client.put("/api/survey", json=_ANSWERED)

    with SessionLocal() as db:
        outcome = _draft(db, question=BIG, answer="Yes: a goal of 12,000 for a new kitchen by 2029")

    assert "card" not in outcome
    assert outcome == {
        "ok": False,
        "error": (
            f'"{BIG}" is a question of the Profile form, and it takes "yes", "unsure" or '
            '"no": "Yes: a goal of 12,000 for a new kitchen by 2029" is not one, so no '
            "card was drawn."
        ),
    }
    assert _answers(client)["big_purchase"]["answer"] == "unsure"


def test_a_yes_in_any_case_is_drawn_and_stored_as_the_form_stores_it(client):
    """The form compares an answer with "yes" exactly (`show_if`), so "Yes" is
    written as "yes", on the card and in the row."""
    client.put("/api/survey", json=_ANSWERED)

    with SessionLocal() as db:
        outcome = _draft(db, question=BIG, answer="Yes")
        card = outcome["card"]
        assert card["title"] == f"profile · {BIG}: unsure → yes"
        assert card["diff"] == [{"field": BIG, "now": "unsure", "proposed": "yes"}]
        assert _confirm(db, card)["ok"] is True

    assert _answers(client)["big_purchase"]["answer"] == "yes"


def test_a_number_question_takes_digits_and_nothing_else(client):
    client.put("/api/survey", json=_ANSWERED)

    with SessionLocal() as db:
        refused = _draft(db, question="Your age?", answer="31 anni")
        drawn = _draft(db, question="Your age?", answer="31")

    assert refused["ok"] is False
    assert refused["error"].startswith('"Your age?" is a question of the Profile form')
    assert "a number, in digits" in refused["error"]
    assert drawn["card"]["diff"] == [{"field": "Your age?", "now": "30", "proposed": "31"}]


def test_a_choice_is_stored_as_the_form_spells_it_and_anything_else_is_refused(client):
    with SessionLocal() as db:
        card = _draft(db, question_key="risk_tolerance", question="Risk?", answer="medium")["card"]
        assert _confirm(db, card)["ok"] is True
        refused = _draft(db, question_key="risk_tolerance", question="Risk?", answer="Quite high")

    assert _answers(client)["risk_tolerance"]["answer"] == "Medium"
    assert refused["ok"] is False
    assert '"Low", "Medium" or "High"' in refused["error"]


def test_a_form_question_nobody_answered_is_found_by_its_wording(client):
    """With no row to find it by, a first answer to "Your age?" used to be filed
    under a key minted from those words, which the form never shows and no
    check reads. It is the form's question, under the form's key and topic."""
    with SessionLocal() as db:
        card = _draft(db, question="Your age?", answer="40")["card"]
        assert _confirm(db, card)["ok"] is True

    answers = _answers(client)
    assert set(answers) == {"about_age"}
    assert answers["about_age"]["answer"] == "40"
    assert answers["about_age"]["question"] == "Your age?"
    assert answers["about_age"]["topic"] == "About you"


def test_a_form_question_named_by_its_key_is_checked_whatever_the_wording(client):
    with SessionLocal() as db:
        refused = _draft(db, question_key="big_purchase", question="Big plans?", answer="maybe")

    assert refused["ok"] is False
    assert refused["error"].startswith(f'"{BIG}" is a question of the Profile form')
    assert _answers(client) == {}


def test_a_question_the_form_never_asked_still_takes_any_words(client):
    """The other half of the tool, untouched: what the form never thought to
    ask is recorded in the reader's own words."""
    with SessionLocal() as db:
        card = _draft(
            db,
            question="What would you never give up?",
            answer="A month a year without work, whatever it costs.",
            topic="In your words",
        )["card"]
        assert _confirm(db, card)["ok"] is True

    row = _answers(client)["what_would_you_never_give_up"]
    assert row["answer"] == "A month a year without work, whatever it costs."
    assert row["topic"] == "In your words"


# --- What the chat is told ------------------------------------------------------------


def test_the_model_is_told_every_form_question_and_what_it_takes():
    """A question nobody has answered is nowhere in the picture, so the tool's
    own declaration names each one: its key, its wording, what it takes."""
    from app import questionnaire

    (declared,) = [
        d for d in tools.declarations() if d["function"]["name"] == "update_profile"
    ]
    told = declared["function"]["parameters"]["properties"]["question_key"]["description"]
    for q in questionnaire.QUESTIONS:
        assert f'{q.key} "{q.text}" ({questionnaire.takes(q)})' in told, q.key
    assert "Never a goal" in declared["function"]["description"]


def test_the_chat_writes_a_goal_with_its_own_tool_and_never_as_an_answer():
    """Brief AL told the chat that no tool writes a goal; since brief AN one
    does, and the questionnaire still takes none."""
    for model in ("anthropic/claude-opus-5.5", "qwen/qwen3.8-max-0902"):
        prompt = chat.system_prompt(model)
        assert "no tool here creates, changes or deletes a goal yet" not in prompt
        assert "A goal is not one of those answers: never write one into the questionnaire" in prompt
        assert "`write_goal`: one of their goals, added, changed or deleted" in prompt


def test_the_picture_heads_the_questionnaire_as_a_profile_and_its_goals_apart(client):
    """The heading said "profile & goals (from the questionnaire)", which is
    where the goal went. The questionnaire holds no goals; the list of goals
    is its own section, which says so when it is empty."""
    client.put("/api/survey", json=_ANSWERED)

    with SessionLocal() as db:
        picture = advisor.build_context(db)
    assert "## Personal profile (from the questionnaire)" in picture
    assert "& goals" not in picture
    assert picture.endswith("## Goals\n- (none recorded)")

    client.post(
        "/api/goals",
        json={"name": "Emergency fund", "type": "emergency_fund", "currency": "EUR"},
    )
    with SessionLocal() as db:
        picture = advisor.build_context(db)
    assert "## Goals\n- Emergency fund [emergency_fund]" in picture
    assert "(none recorded)" not in picture
