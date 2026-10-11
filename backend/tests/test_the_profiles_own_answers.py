"""An answer the chat recorded in the profile is seen, changed and deleted.

Brief AN, item 8 (2026-10-10), closing the record's bullet "An answer the chat
records in the profile is shown nowhere". The Profile page lists the answers
to questions its form does not ask, each changed or deleted there and saved
with its one button (`profileAnswers.ts`, tested on the frontend's side), and
the chat deletes one through its card: `update_profile` with the action
delete, written through the page's own request, `crud.replace_survey_responses`
with the body its Save sends without that answer (`tools._profile_as_saved`).

So the records after the card are the records after the page's Save on the
same answers, field by field; a follow-up the form stops showing goes with the
answer it follows, as the Save drops it, and the card's diff names both. The
answers here are invented.
"""

from __future__ import annotations

import json

import pytest
from conftest import _empty_every_table

from app import advisor, crud
from app.database import SessionLocal

CALM = "How did you react to the last fall?"
FORM = [
    # A question of the form and its follow-up (app/questionnaire.py).
    {"question_key": "home_buy", "topic": "Home", "question": "Do you plan to buy a home?", "answer": "yes"},
    {"question_key": "home_when", "topic": "Home", "question": "When?", "answer": "2029"},
]
OTHERS = [
    {"question_key": "calm_in_a_fall", "topic": "Behaviour", "question": CALM, "answer": "I held"},
    {"question_key": "side_project", "topic": "Work", "question": "Any side income planned?", "answer": "none"},
]


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        yield from rounds.pop(0)

    monkeypatch.setattr(advisor, "stream_llm", fake)


def _asks(client, monkeypatch, **arguments) -> list[dict]:
    call = advisor.ToolCall(id="call_1", name="update_profile", arguments=json.dumps(arguments))
    _script(monkeypatch, [[("tool_call", call)]])
    return _events(client.post("/api/chat", json={"content": "please"}))


def _draw(client, monkeypatch, **arguments) -> dict:
    events = _asks(client, monkeypatch, **arguments)
    cards = [e["card"] for e in events if e["kind"] == "card"]
    assert cards, [e for e in events if e["kind"] == "tool"]
    return cards[0]


def _confirm(client, monkeypatch, card: dict):
    _script(monkeypatch, [[("text", "Done.")]])
    return client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})


def _setup(client) -> None:
    assert client.put("/api/survey", json=FORM + OTHERS).status_code == 200


def _answers(client) -> list[tuple]:
    return [
        (a["question_key"], a["topic"], a["question"], a["answer"])
        for a in client.get("/api/survey").json()
    ]


def _page_saves_without(client, key: str) -> None:
    """The Profile page's Save once the reader deleted the answer under `key`:
    the form's shown answers, in its order, then the others (`toSave`)."""
    questions = client.get("/api/survey/questions").json()
    stored = {a["question_key"]: a for a in client.get("/api/survey").json() if a["question_key"] != key}
    answers = {k: a["answer"] for k, a in stored.items() if a["answer"] is not None}

    def shown(q):
        cond = q.get("show_if")
        return cond is None or answers.get(cond["key"]) == cond["equals"]

    own = {q["key"] for q in questions}
    body = [
        {"question_key": q["key"], "topic": q["topic"], "question": q["text"], "answer": answers[q["key"]]}
        for q in questions
        if shown(q) and answers.get(q["key"], "") != ""
    ] + [
        {k: a[k] for k in ("question_key", "topic", "question", "answer")}
        for k, a in stored.items()
        if k not in own and (a["answer"] or "").strip()
    ]
    assert client.put("/api/survey", json=body).status_code == 200


@pytest.mark.parametrize("key, question", [("calm_in_a_fall", CALM), ("home_buy", "Do you plan to buy a home?")])
def test_a_delete_is_the_pages_save_without_the_answer(client, monkeypatch, key, question):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", question=question)
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _answers(client)

    _empty_every_table()
    _setup(client)
    _page_saves_without(client, key)
    assert by_chat == _answers(client)
    assert key not in [k for k, *_ in by_chat]


def test_the_answers_left_keep_the_day_they_were_recorded(client, monkeypatch):
    _setup(client)
    before = {a["question_key"]: a["created_at"] for a in client.get("/api/survey").json()}
    card = _draw(client, monkeypatch, action="delete", question=CALM)
    _confirm(client, monkeypatch, card)
    after = {a["question_key"]: a["created_at"] for a in client.get("/api/survey").json()}
    assert after == {k: v for k, v in before.items() if k != "calm_in_a_fall"}


def test_a_delete_shows_its_diff_and_says_nothing_brings_the_answer_back(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", question=CALM)
    assert card["confirmation"] == "diff"
    assert card["title"] == f"profile · delete the answer to {CALM}"
    assert card["diff"] == [{"field": CALM, "now": "I held", "proposed": "deleted"}]
    assert card["consequence"] == (
        "The answer goes from their questionnaire, and nothing brings it back: the "
        "chat and the analyses no longer read it."
    )


def test_a_follow_up_the_form_stops_showing_goes_too_and_the_card_says_so(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", question="Do you plan to buy a home?")
    assert card["diff"] == [
        {"field": "Do you plan to buy a home?", "now": "yes", "proposed": "deleted"},
        {"field": "When?", "now": "2029", "proposed": "deleted"},
    ]
    assert 'the answers to questions the form no longer shows without it: "When?".' in card["consequence"]
    _confirm(client, monkeypatch, card)
    assert [k for k, *_ in _answers(client)] == ["calm_in_a_fall", "side_project"]


def test_a_delete_goes_stale_when_the_questionnaire_moves(client, monkeypatch):
    _setup(client)
    card = _draw(client, monkeypatch, action="delete", question=CALM)
    changed = [dict(a, answer="I sold") if a["question_key"] == "calm_in_a_fall" else a for a in FORM + OTHERS]
    client.put("/api/survey", json=changed)
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert ("calm_in_a_fall", "Behaviour", CALM, "I sold") in _answers(client)


def test_a_rejected_delete_writes_nothing(client, monkeypatch):
    _setup(client)
    before = _answers(client)
    card = _draw(client, monkeypatch, action="delete", question=CALM)
    _script(monkeypatch, [[("text", "Kept.")]])
    assert client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "reject"}).status_code == 200
    assert _answers(client) == before


def test_a_delete_of_an_answer_nobody_gave_is_refused(client, monkeypatch):
    _setup(client)
    events = _asks(client, monkeypatch, action="delete", question="What is your favourite colour?")
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert "There is no answer on record" in refused["detail"]


def test_an_answer_still_needs_the_answer(client, monkeypatch):
    events = _asks(client, monkeypatch, question=CALM)
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert "answer needs the answer" in refused["detail"]


def test_none_said_as_an_answer_is_an_answer(client, monkeypatch):
    """`answer` became optional for the delete; a word meaning nothing in a
    reply is still what the reader said, as before."""
    _setup(client)
    card = _draw(client, monkeypatch, question="Any pets?", answer="none")
    _confirm(client, monkeypatch, card)
    with SessionLocal() as db:
        (row,) = [r for r in crud.get_survey_responses(db) if r.question == "Any pets?"]
    assert row.answer == "none"


# --- A follow-up the form hides ------------------------------------------------------
#
# The page's Save sends only the questions the form shows, so an answer to a
# follow-up the form hides (home_when while home_buy is not "yes") is dropped
# at the next Save of anything on that page, said nowhere. Found by this brief
# and closed in it: the chat refuses such an answer, naming the question to
# answer first; and a change of the question a follow-up waits on, which hides
# an answer already on record, takes that answer away as the Save would, with
# its diff.

HOME = "Do you plan to buy a home?"


def _form_answers(client, **answers) -> None:
    body = [
        {"question_key": k, "topic": "Housing & city", "question": q, "answer": a}
        for k, q, a in (("home_buy", HOME, answers.get("home_buy")), ("home_when", "When?", answers.get("home_when")))
        if a is not None
    ] + OTHERS
    assert client.put("/api/survey", json=body).status_code == 200


@pytest.mark.parametrize("home_buy, on_record", [(None, "nothing is on record for it"), ("no", 'the answer on record is "no"')])
def test_an_answer_to_a_follow_up_the_form_hides_is_refused_naming_the_question_first(
    client, monkeypatch, home_buy, on_record
):
    _form_answers(client, home_buy=home_buy)
    events = _asks(client, monkeypatch, question="When?", question_key="home_when", answer="> 5 years")
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert refused["detail"] == (
        f'"When?" is asked by the Profile form only when "{HOME}" is "yes", and {on_record}: '
        f'answer "{HOME}" first, so no card was drawn.'
    )
    assert "home_when" not in [a["question_key"] for a in client.get("/api/survey").json()]


def test_an_answer_to_a_follow_up_the_form_shows_draws_its_card(client, monkeypatch):
    _form_answers(client, home_buy="yes")
    card = _draw(client, monkeypatch, question="When?", question_key="home_when", answer="> 5 years")
    assert card["title"] == "profile · When?: > 5 years"
    _confirm(client, monkeypatch, card)
    assert ("home_when", "Housing & city", "When?", "> 5 years") in _answers(client)


def test_an_answer_that_hides_a_follow_up_takes_it_away_as_the_save_does(client, monkeypatch):
    """home_buy from yes to no: the form stops asking "When?", so its Save
    drops that answer; the card shows it going, and writes what the Save
    writes."""
    _form_answers(client, home_buy="yes", home_when="> 5 years")
    card = _draw(client, monkeypatch, question=HOME, question_key="home_buy", answer="no")
    assert card["confirmation"] == "diff"
    assert card["diff"] == [
        {"field": HOME, "now": "yes", "proposed": "no"},
        {"field": "When?", "now": "> 5 years", "proposed": "deleted"},
    ]
    assert (
        f'The form asks "When?" only when "{HOME}" is "yes", so its answer goes too, as the '
        "Profile page's Save drops it."
    ) in card["consequence"]
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _answers(client)

    _empty_every_table()
    _form_answers(client, home_buy="yes", home_when="> 5 years")
    questions = client.get("/api/survey/questions").json()
    stored = {a["question_key"]: a for a in client.get("/api/survey").json()}
    answers = {k: a["answer"] for k, a in stored.items()} | {"home_buy": "no"}

    def shown(q):
        cond = q.get("show_if")
        return cond is None or answers.get(cond["key"]) == cond["equals"]

    own = {q["key"] for q in questions}
    body = [
        {"question_key": q["key"], "topic": q["topic"], "question": q["text"], "answer": answers[q["key"]]}
        for q in questions
        if shown(q) and answers.get(q["key"], "") != ""
    ] + [{k: a[k] for k in ("question_key", "topic", "question", "answer")} for k, a in stored.items() if k not in own]
    assert client.put("/api/survey", json=body).status_code == 200
    assert by_chat == _answers(client)
    assert "home_when" not in [k for k, *_ in by_chat]


def test_an_answer_that_hides_nothing_is_written_as_before(client, monkeypatch):
    """A guard: with no follow-up answered on record, a change of home_buy is
    the one answer it was, light or diff as before."""
    _form_answers(client, home_buy="yes")
    card = _draw(client, monkeypatch, question=HOME, question_key="home_buy", answer="no")
    assert card["diff"] == [{"field": HOME, "now": "yes", "proposed": "no"}]
