"""The chat writes a goal as the Goals form on the Profile page writes it.

Brief AN, item 5 (2026-10-10). In the reader's second test round the chat was
asked to add a goal, filed it as an answer in the questionnaire, and brief AL
stopped that with a rule: no tool writes a goal, say so. `write_goal` adds,
changes and deletes one through the schema the form posts (`GoalCreate`) and
the crud function its request calls, and the rule becomes: a goal is never an
answer in the questionnaire.

For each action the records after the card is confirmed equal, field by
field, the records after the form's request on the same starting records
(`Goals.tsx`: the target's four figures only for a target_amount goal, the
base as the proposed currency, no note). Every goal here is invented.
"""

from __future__ import annotations

import json

import pytest
from conftest import _empty_every_table

from app import advisor, chat, tools


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
    call = advisor.ToolCall(id="call_1", name="write_goal", arguments=json.dumps(arguments))
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


def _setup(client) -> dict:
    """An emergency fund and a target, the goals every scenario starts from."""
    fund = client.post(
        "/api/goals",
        json={"name": "Rainy days", "type": "emergency_fund", "currency": "EUR",
              "target_amount": None, "target_date": None, "current_amount": None,
              "monthly_contribution": None},
    )
    kitchen = client.post(
        "/api/goals",
        json={"name": "New kitchen", "type": "target_amount", "currency": "EUR",
              "target_amount": 12000.0, "target_date": "2028-06-30",
              "current_amount": 2000.0, "monthly_contribution": 250.0},
    )
    assert fund.status_code == kitchen.status_code == 201
    return {"fund": fund.json()["id"], "kitchen": kitchen.json()["id"]}


def _goals(client) -> list[dict]:
    return [
        {k: v for k, v in g.items() if k not in ("id", "created_at")}
        for g in client.get("/api/goals").json()
    ]


def _by_chat_and_by_form(client, monkeypatch, arguments: dict, form) -> list[dict]:
    _setup(client)
    card = _draw(client, monkeypatch, **arguments)
    assert _confirm(client, monkeypatch, card).status_code == 200
    by_chat = _goals(client)
    _empty_every_table()
    form(client, _setup(client))
    assert by_chat == _goals(client)
    return by_chat


def test_a_goal_added_is_the_forms_add(client, monkeypatch):
    def form(client, ids):
        made = client.post(
            "/api/goals",
            json={"name": "House deposit", "type": "target_amount", "currency": "EUR",
                  "target_amount": 30000.0, "target_date": "2031-03-31",
                  "current_amount": None, "monthly_contribution": 400.0},
        )
        assert made.status_code == 201, made.text

    goals = _by_chat_and_by_form(
        client, monkeypatch,
        {"action": "add", "name": "House deposit", "type": "target_amount",
         "target_amount": 30000, "target_date": "2031-03-31", "monthly_contribution": 400},
        form,
    )
    assert [g["name"] for g in goals] == ["Rainy days", "New kitchen", "House deposit"]


def test_a_goal_changed_is_the_forms_edit(client, monkeypatch):
    def form(client, ids):
        edited = client.put(
            f"/api/goals/{ids['kitchen']}",
            json={"name": "New kitchen", "type": "target_amount", "currency": "EUR",
                  "target_amount": 15000.0, "target_date": "2028-06-30",
                  "current_amount": 2000.0, "monthly_contribution": 250.0},
        )
        assert edited.status_code == 200, edited.text

    goals = _by_chat_and_by_form(
        client, monkeypatch,
        {"action": "change", "name": "New kitchen", "target_amount": 15000},
        form,
    )
    assert goals[1]["target_amount"] == 15000.0


def test_a_goal_whose_type_changes_drops_its_target_as_the_form_does(client, monkeypatch):
    def form(client, ids):
        client.put(
            f"/api/goals/{ids['kitchen']}",
            json={"name": "New kitchen", "type": "long_term_growth", "currency": "EUR",
                  "target_amount": None, "target_date": None, "current_amount": None,
                  "monthly_contribution": None},
        )

    goals = _by_chat_and_by_form(
        client, monkeypatch,
        {"action": "change", "name": "New kitchen", "type": "long_term_growth"},
        form,
    )
    assert goals[1]["target_amount"] is None


def test_a_goal_deleted_is_the_forms_delete(client, monkeypatch):
    def form(client, ids):
        assert client.delete(f"/api/goals/{ids['fund']}").status_code == 204

    goals = _by_chat_and_by_form(
        client, monkeypatch, {"action": "delete", "name": "Rainy days"}, form
    )
    assert [g["name"] for g in goals] == ["New kitchen"]


def test_an_add_is_light_and_a_change_or_a_delete_shows_its_diff(client, monkeypatch):
    _setup(client)
    added = _draw(
        client, monkeypatch, action="add", name="Sabbatical", type="target_amount",
        target_amount=8000, target_date="2029-09-01",
    )
    assert added["confirmation"] == "light"
    assert added["title"] == "add goal: Sabbatical, 8000.00 EUR by 2029-09-01"

    changed = _draw(client, monkeypatch, action="change", name="New kitchen", monthly_contribution=300)
    assert changed["confirmation"] == "diff"
    assert changed["diff"] == [{"field": "Each month", "now": "250.00", "proposed": "300.00"}]

    deleted = _draw(client, monkeypatch, action="delete", name="New kitchen")
    assert deleted["confirmation"] == "diff"
    assert deleted["consequence"] == "The goal goes from their list, and nothing brings it back."


@pytest.mark.parametrize(
    "arguments, said",
    [
        ({"action": "add", "name": "Calm", "type": "emergency_fund", "target_amount": 5000},
         "A goal of type emergency_fund stores no target_amount"),
        ({"action": "change", "name": "Boat", "target_amount": 1},
         "There is no goal called 'Boat'. On record: Rainy days, New kitchen."),
        ({"action": "add", "name": "Something"}, "add needs the goal's type"),
    ],
    ids=["target on a typed goal", "unknown goal", "no type"],
)
def test_a_goal_card_that_cannot_be_what_was_asked_is_refused_in_words(client, monkeypatch, arguments, said):
    _setup(client)
    events = _asks(client, monkeypatch, **arguments)
    assert [e for e in events if e["kind"] == "card"] == []
    (refused,) = [e for e in events if e["kind"] == "tool"]
    assert said in refused["detail"]


def test_a_goal_card_goes_stale_when_the_goal_moves(client, monkeypatch):
    ids = _setup(client)
    card = _draw(client, monkeypatch, action="change", name="New kitchen", target_amount=15000)
    client.put(
        f"/api/goals/{ids['kitchen']}",
        json={"name": "New kitchen", "type": "target_amount", "currency": "EUR",
              "target_amount": 13000.0, "target_date": "2028-06-30",
              "current_amount": 2000.0, "monthly_contribution": 250.0},
    )
    assert _confirm(client, monkeypatch, card).status_code == 409
    assert client.get(f"/api/goals/{ids['kitchen']}").json()["target_amount"] == 13000.0


def test_a_goal_is_never_an_answer_in_the_questionnaire(client):
    """The description of `update_profile` still says so, and points at the
    tool that writes one."""
    description = tools.REGISTRY["update_profile"].description
    assert "Never a goal: goals are a list of their own, written with `write_goal`." in description
    assert "write_goal" in [d["function"]["name"] for d in tools.declarations()]
    assert "`write_goal`" in chat.SYSTEM_PROMPT
