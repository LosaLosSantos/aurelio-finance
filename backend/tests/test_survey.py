"""The questionnaire has two write paths now, and they are not interchangeable.

`replace_survey_responses` is the form's: it deletes every answer and reinserts
what it was handed, which is correct for a caller that renders all 27 questions
and posts them all back. `upsert_survey_response` is the one the chat needs,
because a conversation knows about ONE answer and going through the other door
would erase the profile in order to fill in a line of it.

The tests below pin both, including the part that makes the first one
dangerous — an answer the payload does not name is deleted — because that is
the invariant the Profile form now has to keep on purpose rather than by
accident.
"""

from __future__ import annotations

from app import crud
from app.database import SessionLocal

_FORM = [
    {"question_key": "about_age", "topic": "About you", "question": "Your age?", "answer": "30"},
    {
        "question_key": "risk_tolerance",
        "topic": "Risk & values",
        "question": "How would you describe your risk tolerance?",
        "answer": "Medium",
    },
    {
        "question_key": "ret_age",
        "topic": "Retirement & horizon",
        "question": "At what age would you like to retire?",
        "answer": "60",
    },
]


def _answers(client) -> dict[str, str | None]:
    return {a["question_key"]: a["answer"] for a in client.get("/api/survey").json()}


def test_one_answer_is_written_by_key_and_the_other_twenty_six_stay(client):
    """The blocker this function exists to remove. Before it, the only way in
    was the full replace, so a chat writing one answer wrote a questionnaire of
    one answer."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        crud.upsert_survey_response(db, "about_age", "31")

    assert _answers(client) == {
        "about_age": "31",
        "risk_tolerance": "Medium",
        "ret_age": "60",
    }


def test_a_key_nobody_has_answered_yet_is_created_with_its_question_and_topic(client):
    """The half that closes the loop: the chain says what it does not know, the
    chat asks in conversation, and the answer has to become a row that did not
    exist. A question with no wording and no topic would come back to the
    confidant as a bare key under "Other"."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        crud.upsert_survey_response(
            db,
            "sold_in_2020",
            "I sold everything in March 2020 and bought back in June.",
            topic="Risk & values",
            question="What did you do when the market fell in 2020?",
        )

    row = next(a for a in client.get("/api/survey").json() if a["question_key"] == "sold_in_2020")
    assert row["topic"] == "Risk & values"
    assert row["question"] == "What did you do when the market fell in 2020?"
    assert row["answer"].startswith("I sold everything")
    assert len(client.get("/api/survey").json()) == 4


def test_correcting_an_answer_cannot_blank_the_question_it_answers(client):
    """`topic` and `question` are written only when they are given. A caller
    that knows the new answer and nothing else must not be able to take the
    label off the row on its way past — the form owns that wording, and an
    answer filed under a blank question is unreadable to everything downstream."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        crud.upsert_survey_response(db, "risk_tolerance", "High")

    row = next(
        a for a in client.get("/api/survey").json() if a["question_key"] == "risk_tolerance"
    )
    assert row["answer"] == "High"
    assert row["question"] == "How would you describe your risk tolerance?"
    assert row["topic"] == "Risk & values"


def test_a_blank_answer_is_written_rather_than_ignored(client):
    """Clearing one is a thing to be able to do, and `_render_survey` already
    reads a blank as unanswered rather than as a stated nothing. A None that
    silently did not write would leave the old answer standing under a caller
    that thought it had removed it."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        crud.upsert_survey_response(db, "about_age", None)

    assert _answers(client)["about_age"] is None


def test_the_form_still_replaces_the_whole_set_including_what_it_did_not_send(client):
    """The other door, pinned as the hazard it is.

    PUT /api/survey deletes what its payload does not name. That is right for a
    form posting back everything it read, and it is why the Profile page has to
    carry forward the rows it does not render itself: a question the chat wrote
    is not in its QUESTIONS list, and a save that dropped it would delete an
    answer nobody meant to touch."""
    client.put("/api/survey", json=_FORM)
    with SessionLocal() as db:
        crud.upsert_survey_response(db, "sold_in_2020", "I sold everything.")
    assert "sold_in_2020" in _answers(client)

    client.put("/api/survey", json=_FORM)  # the form, unaware of the new row
    assert "sold_in_2020" not in _answers(client)
