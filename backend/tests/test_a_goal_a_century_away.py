"""A goal a century away is priced like any other.

Issue #4 (2026-10-17, reported by Bortlesboat). The return a goal requires is
found by bisection, whose first guess, 100% a month, is raised to the power of
the horizon's months: from 1024 months, a little over 85 years, that power is
past the largest float, and it raised OverflowError. The Goals form saved such
a goal all the same, and from then on every reader that prices the goals failed
with it: the form's live note (a 500 the note hides), the picture the chat
reads on every turn (each question stored, then answered with a 500), the MCP
server's picture, which is the same text, and the room `size_purchase` stands
on. A year typed wrong was enough.

The fix the issue proposed, an overflow read as reaching the target, found a
rate for a goal with nothing invested and nothing added; the last test holds
that goal to "unreachable" at the same horizon.

Every goal here is invented.
"""

from __future__ import annotations

import datetime
import re

from app import advisor, planning, sizing
from app.database import SessionLocal

FAR_GOAL = {
    "name": "Far goal", "type": "target_amount", "currency": "EUR",
    "target_amount": 10_000_000, "current_amount": 1000, "monthly_contribution": 100,
}


def _a_century_away() -> str:
    """1 January a hundred years ahead: past 85 years whatever day the suite runs."""
    return datetime.date(datetime.date.today().year + 100, 1, 1).isoformat()


def test_the_forms_live_note_says_the_return_a_century_away(client):
    got = client.post("/api/planning/required-return", json={
        "current_amount": 1000, "monthly_contribution": 100,
        "target_amount": 10_000_000, "target_date": _a_century_away(),
    })
    assert got.status_code == 200, got.text
    rate = got.json()["required_annual_return"]
    assert rate is not None and 0 < rate < 0.1


def test_a_goal_a_century_away_leaves_the_picture_and_the_room_readable(client):
    made = client.post("/api/goals", json={**FAR_GOAL, "target_date": _a_century_away()})
    assert made.status_code == 201, made.text
    with SessionLocal() as db:
        picture = advisor.build_context(db)  # the MCP server's picture, byte for byte
        (need,) = sizing.room(db).goals
    assert re.search(
        r"- Far goal \[target_amount\]: target 10000000 EUR by \d{4}-\d\d-\d\d "
        r"\(current 1000, \+100/mo, ~[\d.]+y\) -> requires \d+\.\d%/yr",
        picture,
    )
    assert need.name == "Far goal" and 0 < need.required_return < 0.1
    assert need.assessment == planning.assess(need.required_return)


def test_the_chat_answers_with_a_goal_a_century_away(client, monkeypatch):
    client.post("/api/goals", json={**FAR_GOAL, "target_date": _a_century_away()})
    seen = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        seen.append(messages[0]["content"])
        yield ("text", "Noted.")

    monkeypatch.setattr(advisor, "stream_llm", fake)
    got = client.post("/api/chat", json={"content": "How far is my goal?"})
    assert got.status_code == 200, got.text
    assert "event: done" in got.text
    assert "- Far goal [target_amount]: target 10000000 EUR" in seen[0]


def test_with_nothing_in_it_a_goal_a_century_away_is_unreachable(client):
    got = client.post("/api/planning/required-return", json={
        "target_amount": 10_000_000, "target_date": _a_century_away(),
    })
    assert got.status_code == 200, got.text
    assert got.json()["required_annual_return"] is None
    assert got.json()["assessment"] == planning.assess(None)
