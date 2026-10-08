"""A card reads as words.

The reader's cards (2026-10-08) showed the tool's argument names and raw
values ("based_on", "unknowns", "symbol null") and, once confirmed, a
"Written" block of the row as stored: its id, and "added_at" as an ISO
timestamp. Brief AJ: each tool that writes names its arguments in the
reader's words (`Tool.labels`, every argument covered), says what it wrote in
words (`Tool.receipt`), and `tools.present` works the card out each time it is
sent or read back, never stored, so the cards already in a conversation read
the same. What the model reads stays the stored arguments and result.

Every fund here is invented.
"""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from app import advisor, catalogue, crud, models, tools
from app.database import SessionLocal

CATALOGUE = pd.DataFrame(
    [
        {
            "name": "Example Global Equity UCITS ETF Acc",
            "ticker": "XGLO", "dividends": "Accumulating", "ter": 0.12, "size": 2100,
            "replication": "Physical", "domicile_country": "Ireland",
            "currency": "USD", "number_of_holdings": 1500, "hedged": False,
        },
    ],
    index=pd.Index(["IE0000AJ0001"], name="isin"),
)
FUND = "IE0000AJ0001"
WHY = {
    "reason": "An invented reason.",
    "based_on": "An invented answer in the questionnaire.",
    "unknowns": "Invented unknowns.",
}
INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T")


@pytest.fixture
def loaded(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


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


def _lines(fields: list[dict]) -> list[tuple]:
    return [(f["label"], f["value"], f["kind"]) for f in fields]


# --- Every argument has a label -----------------------------------------------------


@pytest.mark.parametrize(
    "name", sorted(n for n, t in tools.REGISTRY.items() if t.propose is not None)
)
def test_every_argument_of_a_tool_that_writes_has_a_label(name):
    """A field added to a tool's arguments without one fails here, before it
    reaches a card under its schema name. An empty label is a decision: that
    argument is the app's, and no card shows it."""
    tool = tools.REGISTRY[name]
    assert set(tool.arguments.model_fields) <= set(tool.labels), (
        f"{name} has arguments with no label: "
        f"{sorted(set(tool.arguments.model_fields) - set(tool.labels))}"
    )


# --- The reader's card ------------------------------------------------------------------


def test_a_fund_card_reads_as_words_before_and_after_it_is_accepted(loaded, monkeypatch):
    call = advisor.ToolCall(
        id="call_1",
        name="suggest_instrument",
        arguments=json.dumps({"isin": FUND, "symbol": "null", **WHY}),
    )
    _script(monkeypatch, [[("text", "One to watch."), ("tool_call", call)], [("text", "Added.")]])

    events = _events(loaded.post("/api/chat", json={"content": "A fund to watch?"}))
    card = next(e["card"] for e in events if e["kind"] == "card")

    assert _lines(card["fields"]) == [
        ("ISIN", FUND, "text"),
        ("Why this one", "An invented reason.", "text"),
        ("Rests on", "An invented answer in the questionnaire.", "text"),
        ("Not known", "Invented unknowns.", "text"),
    ], "no schema name, and no line for a symbol that says nothing"
    assert card["receipt"] == []

    decided = _events(loaded.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"}))
    settled = decided[1]["card"]

    assert settled["done"] == "Added to your watchlist"
    (since,) = settled["receipt"]
    assert (since["label"], since["kind"]) == ("On your watchlist since", "date")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", since["value"]), "a day, not a moment"
    assert settled["fields"] == card["fields"]

    # Read back, the same words; stored, none of them.
    conversation = loaded.get(f"/api/chat/conversations/{events[0]['conversation_id']}").json()
    read_back = next(b for m in conversation["messages"] for b in m["blocks"] if b["kind"] == "card")
    assert read_back == settled
    with SessionLocal() as db:
        stored = [
            b
            for m in db.query(models.ChatMessage)
            for b in json.loads(m.blocks)
            if b.get("kind") == "card"
        ]
    assert not {"fields", "receipt", "done"} & set(stored[0]), "never stored"
    assert stored[0]["result"]["watchlist_id"], "what the model reads keeps the row as written"


def test_a_card_kept_from_before_reads_as_words_when_read_back(client):
    """The reader's own cards were written before any of this, with the word
    "null" in their arguments and the row in their result: read back, they
    read like a new one."""
    old = {
        "kind": "card",
        "card_id": "c0ffee",
        "call_id": "toolu_1",
        "tool": "suggest_instrument",
        "title": "watch: Example Global Equity UCITS ETF Acc, IE0000AJ0001",
        "arguments": {"isin": FUND, "symbol": "null", **WHY},
        "confirmation": "light",
        "consequence": "Nothing about your money changes.",
        "verb": "Add to watchlist",
        "diff": [],
        "fingerprint": "x",
        "outcome": "confirmed",
        "result": {
            "watchlist_id": 1,
            "isin": FUND,
            "symbol": "NULL",
            "name": "Example Global Equity UCITS ETF Acc",
            "added_at": "2026-10-08T08:00:00+00:00",
        },
    }
    with SessionLocal() as db:
        conv = crud.create_chat_conversation(db)
        crud.append_chat_message(db, conv, "user", [{"kind": "text", "text": "A fund?"}])
        crud.append_chat_message(db, conv, "assistant", [old], status="done")
        conversation_id = conv.id

    conversation = client.get(f"/api/chat/conversations/{conversation_id}").json()
    card = conversation["messages"][1]["blocks"][0]

    assert "symbol" not in [f["label"] for f in card["fields"]]
    assert "Ticker" not in [f["label"] for f in card["fields"]]
    assert _lines(card["receipt"]) == [("On your watchlist since", "2026-10-08", "date")]
    assert card["done"] == "Added to your watchlist"


# --- Every receipt says what was written, in words ------------------------------------


def test_a_ledger_card_says_the_amount_and_the_day_of_its_rate():
    card = {
        "tool": "record_transaction",
        "outcome": "confirmed",
        "arguments": {
            "kind": "buy", "date": "2026-10-01", "asset_name": "Example share", "symbol": "XSHR",
            "isin": None, "asset_class": None, "quantity": 5.0, "unit_price": 20.0, "fees": 0.0,
            "currency": "EUR", "price_currency": "USD", "amount": None, "institution": "Broker A",
            "cash_institution": None, "note": "None",
        },
        "result": {
            "transaction_id": 7, "kind": "buy", "date": "2026-10-01", "asset_name": "Example share",
            "symbol": "XSHR", "quantity": 5.0, "unit_price": 20.0, "fees": 0.0, "amount": 80.0,
            "currency": "EUR", "price_currency": "USD", "fx_as_of": "2026-10-01",
            "institution": "Broker A",
        },
    }

    shown = tools.present(card)

    assert [f["label"] for f in shown["fields"]] == [
        "Entry", "Date", "Asset", "Ticker", "Units", "Price", "Fees", "Cash in", "Price in", "Held at",
    ], "nothing absent, the word None included"
    assert shown["fields"][1] == {"label": "Date", "value": "2026-10-01", "kind": "date"}
    assert shown["receipt"] == [
        {"label": "Amount", "value": "80.0", "kind": "amount", "currency": "EUR"},
        {"label": "At the ECB rate of", "value": "2026-10-01", "kind": "date"},
        {"label": "Held at", "value": "Broker A", "kind": "text"},
    ]
    assert shown["done"] == "Recorded"


def test_a_profile_card_shows_no_key_of_the_apps():
    card = {
        "tool": "update_profile",
        "outcome": "confirmed",
        "arguments": {"question": "Your age?", "answer": "31", "topic": None, "question_key": "about_age"},
        "result": {"question_key": "about_age", "topic": None, "question": "Your age?", "answer": "31", "replaced": "30"},
    }

    shown = tools.present(card)

    assert _lines(shown["fields"]) == [("Question", "Your age?", "text"), ("Answer", "31", "text")]
    assert _lines(shown["receipt"]) == [("Answer now", "31", "text"), ("It replaced", "30", "text")]


def test_an_analysis_receipt_is_how_deep_how_long_and_how_much():
    card = {
        "tool": "run_analysis",
        "outcome": "confirmed",
        "arguments": {},
        "result": {
            "run_id": 3, "finished": "2026-10-08T10:00:00+00:00", "steps": 5, "revision_rounds": 1,
            "seconds": 62, "cost_usd": 0.33, "opening": "Sell nothing.", "read_in_full": "Call read_analysis.",
        },
    }

    shown = tools.present(card)

    assert shown["receipt"] == [
        {"label": "Steps", "value": "5", "kind": "number"},
        {"label": "Took", "value": "62 s", "kind": "text"},
        {"label": "Cost", "value": "0.33", "kind": "amount", "currency": "USD"},
    ]
    assert shown["result"]["run_id"] == 3, "the link to the run, and the model, still have it"


def test_a_pending_or_rejected_card_has_no_receipt():
    for outcome in ("pending", "rejected"):
        shown = tools.present({"tool": "suggest_instrument", "outcome": outcome, "arguments": {"isin": FUND}, "result": None})
        assert shown["receipt"] == []


def test_no_card_line_is_a_moment_or_an_id():
    """Across every tool's receipt, from results as the tools write them."""
    results = {
        "suggest_instrument": {"watchlist_id": 1, "isin": FUND, "symbol": None, "name": "x", "added_at": "2026-10-08T08:00:00+00:00"},
        "add_real_asset": {"real_asset_id": 2, "name": "x", "category": None, "currency": "EUR", "valued_on": "2026-10-01", "value": 10.0},
        "run_analysis": {"run_id": 3, "finished": "2026-10-08T10:00:00+00:00", "steps": 3, "seconds": 9, "cost_usd": None},
    }
    for name, result in results.items():
        shown = tools.present({"tool": name, "outcome": "confirmed", "arguments": {}, "result": result})
        for line in shown["receipt"]:
            assert not INSTANT.match(line["value"]), line
            assert not line["label"].lower().endswith("id"), line
