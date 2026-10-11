"""The chat is told once how every card writes, and what no card does yet.

Brief AN, item 11 (2026-10-10). The rules every write tool shares (a card is a
proposal, drawn on request, one for each change and up to three in an answer,
written as the page's own form writes it; names as the picture gives them;
the language of the data; a currency's code; today for a day not named) are
said once, in the system prompt, and no declaration repeats them: the reader's
ask, after the plan estimated the declarations at 43,000 characters. And the
prompt lists what no card does yet and where the reader does it, so a missing
tool is said as one and never presented as the chat's own choice (the
record's bullet of 2026-10-02).

And the prompt says the picture already holds what a confirmed card wrote. It
said the picture was rebuilt "the moment they asked", and a turn that answers a
card rebuilds it after the write: in P1 (2026-10-10, Opus 5.5, paid, on a test
database) four replies of seven warned of a duplicate that did not exist.
"""

from __future__ import annotations

import json

import pytest

from app import advisor, chat, tools

OPUS = "anthropic/claude-opus-5.5"
PROMPTS = [chat.system_prompt(OPUS), chat.SYSTEM_PROMPT]


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _script(monkeypatch, rounds):
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        seen.append({"system": system_prompt, "messages": list(messages)})
        assert len(seen) <= len(rounds), f"round {len(seen)} is past the script"
        yield from rounds[len(seen) - 1]

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


@pytest.mark.parametrize("prompt", PROMPTS, ids=["offered the web", "not"])
def test_the_rules_every_card_shares_are_said_once_in_the_prompt(prompt):
    for rule in (
        "You do not write; you PROPOSE.",
        "Propose a write only when they ask for one",
        "Draw up to three cards in one answer, of any kind",
        "A card writes what the page's own form writes, so they then see it and change it there",
        "it says in their words what confirming does: say the same, and nothing it does not",
        "Name things exactly as the picture above names them",
        "Write in the language of the DATA, not of the question",
        "London pence are GBp, written exactly so",
        "A day they did not name is today, the first line of the picture.",
    ):
        assert prompt.count(rule) == 1, rule


def test_no_declaration_repeats_them():
    declared = json.dumps(tools.declarations() + tools.web_search(OPUS), ensure_ascii=False)
    for repeated in (
        "It does not write: it draws a card",
        "language of the DATA",
        "language the DATA",
        "BY NAME and exactly as it appears",
        "Today's date is the first line",
        "as the form does",
        "hundred times more",
    ):
        assert repeated not in declared, repeated


@pytest.mark.parametrize("prompt", PROMPTS, ids=["offered the web", "not"])
def test_the_prompt_says_what_no_card_does_yet_and_where(prompt):
    said = prompt[prompt.index("What no card does yet") :]
    for missing, where in (
        ("an account, added, renamed or deleted", "Records, Wealth"),
        ("a situation and its holdings", "the account's page"),
        ("a real asset's later valuations", "Records, Real assets"),
        ("a debt and its balances", "Records, Debts"),
        ("a PAC, its amount, its schedule and its funds", "Records, Cash flow"),
        ("correcting or deleting a ledger entry", "Portfolio, the ledger"),
        ("correcting or deleting a transfer, or deleting a balance", "the account's page"),
        # A card's null keeps a field as it is (write_flow, write_goal).
        ("emptying a field of a line or a goal", "Records, Cash flow; Profile"),
        ("the tax rates", "Profile"),
        ("dropping an idea from the watchlist", "Portfolio"),
    ):
        assert missing in said and where in said, missing
    assert "never as a choice of yours" in said


def test_every_card_the_prompt_lists_is_a_tool_that_draws_one():
    prompt = chat.SYSTEM_PROMPT
    writers = {name for name, tool in tools.REGISTRY.items() if tool.propose is not None}
    for name in writers:
        assert f"`{name}`" in prompt, name


@pytest.mark.parametrize("prompt", PROMPTS, ids=["offered the web", "not"])
def test_the_prompt_says_the_picture_already_holds_what_a_confirmed_card_wrote(prompt):
    assert "the moment they asked" not in prompt
    assert prompt.count("newer than everything after it") == 1
    assert "anything there that matches a confirmed card is that card's own write, never a second copy" in prompt


def test_the_turn_after_a_confirmed_card_reads_its_write_in_the_picture_above_the_question(
    client, monkeypatch
):
    """What the prompt says, held to the code: the picture the question was
    asked with has no such line, and the picture of the turn that answers the
    card has it, at the top, before the question that asked for it."""
    bank = client.post("/api/institutions", json={"name": "Example Bank"}).json()["id"]
    anchored = client.post(
        f"/api/institutions/{bank}/cash-anchors",
        json={"date": "2026-09-30", "amount": 2000.0, "currency": "EUR"},
    )
    assert anchored.status_code == 201, anchored.text
    arguments = {
        "action": "add", "side": "expense", "name": "Climbing gym", "account": "Example Bank",
        "amount": 45, "first_payment": "2026-11-03", "nature": "discretionary",
        "category": "leisure",
    }
    call = advisor.ToolCall(id="call_1", name="write_flow", arguments=json.dumps(arguments))
    asked = _script(monkeypatch, [[("text", "Here it is:"), ("tool_call", call)]])
    events = _events(client.post("/api/chat", json={"content": "Add the climbing gym, 45 a month."}))
    card = next(e["card"] for e in events if e["kind"] == "card")
    assert "Climbing gym" not in asked[0]["messages"][0]["content"]

    answered = _script(monkeypatch, [[("text", "Done.")]])
    _events(client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}))

    messages = answered[0]["messages"]
    assert "Climbing gym" in messages[0]["content"]
    question = next(
        i for i, m in enumerate(messages) if "Add the climbing gym" in json.dumps(m["content"])
    )
    assert question > 0
    assert "newer than everything after it" in answered[0]["system"]
