"""The tools that write to the reader's own records, against the plumbing that
carries them.

`test_chat.py` proves the round trip — a card ends the turn, a decision runs the
tool, an outcome is stored — with a fake tool registered in the real registry.
This file is about what the real ones DO: what they refuse, what the card says
before anybody presses anything, and what makes each of them stale.

Three of the four write tools are here. The fourth, `run_analysis`, writes a
chain run rather than a row of the reader's and cannot be exercised without
faking a model, so it lives in `test_chat.py` beside the streaming it needs;
the one property that is about the REGISTRY rather than about a table — a tool
with a `propose` does not run when the model calls it — is asserted over all
four, at the bottom.

Nothing here goes near the model. Two of these tools would happily be tested
through `/api/chat`, and one test at the bottom does, because the endpoint is
where "the card cannot be redrawn" has to become a 409 rather than a 500. The
rest call `tools.answer` and `tools.settle` directly: the model's part is
choosing the arguments, and a fake stream reciting arguments a test wrote is
not evidence about any of this.
"""

from __future__ import annotations

import datetime
import json

from sqlalchemy import text

from app import advisor, crud, fx, models, tools
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()


def _ask_for(name: str, arguments: dict, call_id: str = "call_1") -> advisor.ToolCall:
    """One tool call as the model would have made it."""
    return advisor.ToolCall(id=call_id, name=name, arguments=json.dumps(arguments))


def _draft(db, tool_name: str, /, **arguments) -> dict:
    """What the tool answers a call with: `{"card": ...}` or an outcome saying
    why it could not be drafted."""
    return tools.answer(db, _ask_for(tool_name, arguments))


def _card(db, tool_name: str, /, **arguments) -> dict:
    outcome = _draft(db, tool_name, **arguments)
    assert "card" in outcome, outcome
    return outcome["card"]


def _confirm(db, card: dict) -> dict:
    """The reader pressing confirm, minus the streaming that follows it.

    `settle` reports what it finishes as it finishes, for the one tool that
    takes a minute; none of these three do, so `finish` drains a generator that
    yields nothing and hands back the outcome."""
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


def _portfolio(client, *, symbol="VWCE.MI", quantity=12.0, price=100.0, name="Broker A"):
    """One institution holding one position, photographed on 2026-01-10."""
    iid = client.post("/api/institutions", json={"name": name}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Vanguard All-World",
            "asset_class": "fund_etf",
            "symbol": symbol,
            "quantity": quantity,
            "unit_price": price,
            "currency": "EUR",
        },
    )
    return iid


# --- add_real_asset ----------------------------------------------------------


def test_a_gift_becomes_the_asset_and_the_valuation_that_says_what_it_is_worth(client):
    """The example the brief is written around. Two rows, because a possession
    with no valuation is counted as zero everywhere it is totalled — and the
    card quoted a figure."""
    with SessionLocal() as db:
        card = _card(
            db,
            "add_real_asset",
            name="gold necklace",
            value=500,
            valued_on="2026-09-04",
            category="jewelry",
            currency="eur",
        )
        assert card["outcome"] == "pending" and card["confirmation"] == "light"
        assert card["title"] == "add real asset: gold necklace, 500.00 EUR as at 2026-09-04"
        assert crud.get_real_assets(db) == [], "the model wrote"

        done = _confirm(db, card)

    assert done["ok"] is True
    assets = client.get("/api/real-assets").json()
    assert [(a["name"], a["category"], a["currency"]) for a in assets] == [
        ("gold necklace", "jewelry", "EUR")
    ]
    valuations = client.get(f"/api/real-assets/{assets[0]['id']}/valuations").json()
    assert [(v["date"], v["value"]) for v in valuations] == [("2026-09-04", 500.0)]
    assert done["result"]["real_asset_id"] == assets[0]["id"]


def test_the_asset_and_its_valuation_land_together_or_not_at_all(client, monkeypatch):
    """One unit of work around two writes, asserted from the failing side. An
    asset saved without the valuation is a row every total reads as zero, and
    the reader was shown a figure — so the half that worked has to go back."""

    def no(db, real_asset_id, data):
        raise RuntimeError("the disk went away")

    with SessionLocal() as db:
        card = _card(db, "add_real_asset", name="gold necklace", value=500, currency="EUR")
        monkeypatch.setattr(crud, "create_real_asset_valuation", no)
        done = _confirm(db, card)

    assert done["ok"] is False and "the disk went away" in done["error"]
    assert client.get("/api/real-assets").json() == []


def test_a_card_whose_every_row_is_new_cannot_go_stale(client):
    """The fingerprint here is the empty claim, and it is a claim rather than a
    forgotten field. A real asset has no unique column to collide with and its
    first valuation is dated against an asset that does not exist yet, so
    another window adding a second necklace is two necklaces, not this card
    going out of date."""
    with SessionLocal() as db:
        card = _card(db, "add_real_asset", name="gold necklace", value=500, currency="EUR")
        assert "held=" not in card["fingerprint"]

    client.post("/api/real-assets", json={"name": "gold necklace", "category": "jewelry", "currency": "EUR"})

    with SessionLocal() as db:
        assert _confirm(db, card)["ok"] is True
    assert len(client.get("/api/real-assets").json()) == 2


def test_the_valuation_takes_today_when_the_reader_named_no_day(client):
    """Today's date is the first line of the picture the model reads, so it can
    say it — but a missing one must not become a null date on a row whose whole
    job is to be dated."""
    with SessionLocal() as db:
        card = _card(db, "add_real_asset", name="gold necklace", value=500, currency="EUR")
        assert card["arguments"]["valued_on"] == TODAY
        _confirm(db, card)

    asset = client.get("/api/real-assets").json()[0]
    valuations = client.get(f"/api/real-assets/{asset['id']}/valuations").json()
    assert [v["date"] for v in valuations] == [TODAY]


# --- record_transaction ------------------------------------------------------


def test_a_purchase_names_its_institution_and_is_recorded_after_the_fact(client):
    """No broker is connected, so this records a trade already made. The
    institution arrives as a NAME, because the picture the model reads names
    them and never numbers them — an argument typed as a foreign key would be a
    field it could only guess at."""
    iid = _portfolio(client)

    with SessionLocal() as db:
        card = _card(
            db,
            "record_transaction",
            kind="buy",
            date="2026-08-28",
            asset_name="Coca-Cola",
            symbol="KO",
            quantity=5,
            unit_price=128.40,
            fees=2.0,
            institution="broker a",
            currency="EUR", price_currency="EUR",
        )
        assert card["title"] == (
            "record buy: 5 KO @ 128.40 EUR = 644.00 EUR · Broker A · 2026-08-28"
        )
        assert _confirm(db, card)["ok"] is True

    rows = client.get("/api/transactions").json()
    assert len(rows) == 1
    assert (rows[0]["kind"], rows[0]["symbol"], rows[0]["institution_id"]) == (
        "buy",
        "KO",
        iid,
    )
    assert rows[0]["amount"] == 644.00, "the card quoted a figure the row must carry"


def test_the_amount_on_the_card_comes_from_the_function_that_stores_it(client):
    """A buy costs price*units PLUS fees; a sell nets them off. The card asks
    the same code the row will be built from rather than keeping a copy of that
    rule, so the two cannot come apart."""
    _portfolio(client, symbol="KO", quantity=10.0)

    with SessionLocal() as db:
        sell = _card(
            db,
            "record_transaction",
            kind="sell",
            date="2026-08-28",
            asset_name="Vanguard All-World",
            symbol="KO",
            quantity=4,
            unit_price=100.0,
            fees=3.0,
            institution="Broker A",
            currency="EUR", price_currency="EUR",
        )
        assert "= 397.00" in sell["title"]
        assert _confirm(db, sell)["ok"] is True

    assert client.get("/api/transactions").json()[0]["amount"] == 397.00


def test_an_institution_nobody_has_heard_of_comes_back_as_something_to_correct(client):
    """A name that resolves to nothing is not the same claim as no name at all,
    and a card that showed the second as the first would record the purchase
    against no institution for a reader who named one. The refusal lists what
    does exist, because the model reads it and can correct itself."""
    _portfolio(client)

    with SessionLocal() as db:
        outcome = _draft(
            db,
            "record_transaction",
            asset_name="Coca-Cola",
            symbol="KO",
            quantity=5,
            unit_price=100.0,
            institution="Brokr A",
            currency="EUR", price_currency="EUR",
        )

    assert "card" not in outcome and outcome["ok"] is False
    assert "Brokr A" in outcome["error"] and "Broker A" in outcome["error"]
    assert client.get("/api/transactions").json() == []


def test_a_purchase_that_names_no_institution_never_reaches_a_card(client):
    """Silence used to be accepted where a WRONG name was refused, which is
    backwards: the guarded path was the harsher one going in.

    A buy naming nobody leaves both institution columns null, and such a row
    adds its own cost to the net worth — the cash register skips it while the
    position it creates is counted in full (asserted at the API in
    tests/test_transactions.py). Closing only the form would have left this
    open: `record_transaction` is a declared tool and `settle` writes the row
    on confirm, so the same money-creating entry was one confirmation away.

    Refused the way an unknown name is refused, and the message lists what does
    exist — the model reads it and can name one on the next round trip, which
    it cannot do with a card that was never wrong enough to stop."""
    _portfolio(client)

    with SessionLocal() as db:
        outcome = _draft(
            db,
            "record_transaction",
            asset_name="Coca-Cola",
            symbol="KO",
            quantity=5,
            unit_price=100.0,
            currency="EUR", price_currency="EUR",
        )

    assert "card" not in outcome and outcome["ok"] is False
    assert "Broker A" in outcome["error"]
    assert client.get("/api/transactions").json() == []

    # A dividend too: the cash it credits has to reach an account.
    with SessionLocal() as db:
        dividend = _draft(
            db,
            "record_transaction",
            kind="dividend",
            asset_name="Vanguard All-World",
            symbol="VWCE.MI",
            quantity=10,
            unit_price=1.5,
            currency="EUR", price_currency="EUR",
        )
    assert "card" not in dividend and dividend["ok"] is False
    assert client.get("/api/transactions").json() == []


def test_the_institution_refusals_read_without_a_dash(client):
    """Both refusals reach the reader in a failed tool's line, shown live since
    brief AG, and nothing the reader sees carries an em dash. Each one with no
    institution on record, and with one."""
    buy = dict(
        asset_name="Coca-Cola", symbol="KO", quantity=5, unit_price=100.0,
        currency="EUR", price_currency="EUR",
    )

    def refusals() -> tuple[str, str]:
        with SessionLocal() as db:
            unknown = _draft(db, "record_transaction", institution="Brokr A", **buy)
            nameless = _draft(db, "record_transaction", **buy)
        assert "card" not in unknown and "card" not in nameless
        return unknown["error"], nameless["error"]

    unknown, nameless = refusals()
    assert unknown.endswith("There is no institution called 'Brokr A'. On record: none.")
    assert nameless.endswith(
        "On record: none yet, and one has to exist before an entry can name it."
    )
    assert chr(0x2014) not in unknown + nameless

    _portfolio(client)
    unknown, nameless = refusals()
    assert unknown.endswith("There is no institution called 'Brokr A'. On record: Broker A.")
    assert nameless.endswith("On record: Broker A.")
    assert chr(0x2014) not in unknown + nameless


def test_a_sell_says_what_the_records_show_is_held(client):
    """The card is where "your records say 12" belongs. Selling more than the
    records know about is NOT refused — nobody here knows whether you still own
    what the last photograph said you owned, and correcting exactly that is why
    the reader is typing — so the number goes in front of them instead."""
    _portfolio(client, quantity=12.0)

    with SessionLocal() as db:
        card = _card(
            db,
            "record_transaction",
            kind="sell",
            date="2026-08-28",
            asset_name="Vanguard All-World",
            symbol="VWCE.MI",
            quantity=20,
            unit_price=110.0,
            institution="Broker A",
            currency="EUR", price_currency="EUR",
        )

    assert "(the records show 12 units held)" in card["title"]
    assert card["outcome"] == "pending"


def test_a_disposal_with_no_position_behind_it_is_refused(client):
    """The one place a write tool is stricter than the form. `positions.replay`
    sells at the running average cost, so a sell against nothing books its whole
    proceeds as realized profit — a gain the reader never made, on a position
    that does not exist. The form is driven by somebody looking at the row; the
    model is not."""
    _portfolio(client, symbol="VWCE.MI")

    with SessionLocal() as db:
        outcome = _draft(
            db,
            "record_transaction",
            kind="sell",
            asset_name="Coca-Cola",
            symbol="KO",
            quantity=5,
            unit_price=100.0,
            institution="Broker A",
            currency="EUR", price_currency="EUR",
        )

    assert outcome["ok"] is False
    assert "nothing for a sell to settle" in outcome["error"]
    assert "VWCE.MI" in outcome["error"], "it must say what IS held"


def test_a_sell_goes_stale_when_the_units_move_under_it(client):
    """The fingerprint carries the figure the title quotes, so the card and the
    sentence the reader believed go stale together. Another tab selling four is
    exactly the case a clock cannot catch: the card can be ten seconds old and
    already wrong."""
    _portfolio(client, quantity=12.0)

    with SessionLocal() as db:
        card = _card(
            db,
            "record_transaction",
            kind="sell",
            date="2026-08-28",
            asset_name="Vanguard All-World",
            symbol="VWCE.MI",
            quantity=5,
            unit_price=110.0,
            institution="Broker A",
            currency="EUR", price_currency="EUR",
        )

    client.post(
        "/api/transactions",
        json={
            "kind": "sell",
            "date": "2026-02-01",
            "asset_name": "Vanguard All-World",
            "symbol": "VWCE.MI",
            "quantity": 4,
            "unit_price": 105.0,
            "institution_id": 1,
            "currency": "EUR", "price_currency": "EUR",
        },
    )

    with SessionLocal() as db:
        done = _confirm(db, card)

    assert done["ok"] is False and done["stale"] is True
    assert len(client.get("/api/transactions").json()) == 1, "the confirm wrote"


def test_a_buy_does_not_depend_on_what_is_held(client):
    """Appending overwrites nothing, so there is no held figure in the title or
    in the fingerprint — and saying so is the claim. A card refused because
    somebody bought more of the same fund in another tab would be a refusal with
    nothing behind it."""
    _portfolio(client, quantity=12.0)

    with SessionLocal() as db:
        card = _card(
            db,
            "record_transaction",
            kind="buy",
            date="2026-08-28",
            asset_name="Vanguard All-World",
            symbol="VWCE.MI",
            quantity=3,
            unit_price=110.0,
            institution="Broker A",
            currency="EUR", price_currency="EUR",
        )
        assert "held=" not in card["fingerprint"]

    client.post(
        "/api/transactions",
        json={
            "kind": "buy",
            "date": "2026-02-01",
            "asset_name": "Vanguard All-World",
            "symbol": "VWCE.MI",
            "quantity": 7,
            "unit_price": 105.0,
            "institution_id": 1,
            "currency": "EUR", "price_currency": "EUR",
        },
    )

    with SessionLocal() as db:
        assert _confirm(db, card)["ok"] is True
    assert len(client.get("/api/transactions").json()) == 2


def test_a_disposal_that_named_no_institution_adopts_the_one_holding_it(client):
    """Exactly one position matched, so where it is held is not a guess. Leaving
    the row's institution null instead would take the cash out of nowhere."""
    iid = _portfolio(client, quantity=9.0)

    with SessionLocal() as db:
        card = _card(
            db,
            "record_transaction",
            kind="close",
            date="2026-08-28",
            asset_name="Vanguard All-World",
            amount=900.0,
            currency="EUR",
        )
        assert "· Broker A" in card["title"]
        assert _confirm(db, card)["ok"] is True

    assert client.get("/api/transactions").json()[0]["institution_id"] == iid


# --- update_profile ----------------------------------------------------------


_FORM = [
    {"question_key": "about_age", "topic": "About you", "question": "Your age?", "answer": "30"},
    {
        "question_key": "risk_tolerance",
        "topic": "Risk & values",
        "question": "How would you describe your risk tolerance?",
        "answer": "Medium",
    },
]


def test_a_question_the_form_never_asked_is_an_append_and_a_light_card(client):
    """The loop the chain has been waiting for: it declares what it does not
    know, the chat asks in conversation, and the answer becomes a row the form
    never had. Nothing is overwritten, so nothing needs a diff."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        card = _card(
            db,
            "update_profile",
            question="What did you do when the market fell in 2020?",
            answer="I sold everything in March and bought back in June.",
            topic="Risk & values",
        )
        assert card["confirmation"] == "light" and card["diff"] == []
        assert card["fingerprint"].endswith("=<unanswered>")
        assert _confirm(db, card)["ok"] is True

    answers = {a["question_key"]: a for a in client.get("/api/survey").json()}
    assert set(answers) == {
        "about_age",
        "risk_tolerance",
        "what_did_you_do_when_the_market_fell_in_2020",
    }
    written = answers["what_did_you_do_when_the_market_fell_in_2020"]
    assert written["topic"] == "Risk & values"
    assert written["question"] == "What did you do when the market fell in 2020?"
    assert answers["about_age"]["answer"] == "30", "the other answers moved"


def test_changing_an_answer_shows_the_diff_and_says_what_it_costs(client):
    """The rule is about REVERSIBILITY, not about which table is touched. A
    survey answer carries no date and no history: after this it says something
    else, and the old one is nowhere. That earns the diff, and the sentence
    above the diff comes from the tool — the snapshot's "every figure anchored
    after it moves" is not true of this and must not be shown over it."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        card = _card(db, "update_profile", question="Your age?", answer="31")

    assert card["confirmation"] == "diff"
    assert card["diff"] == [{"field": "Your age?", "now": "30", "proposed": "31"}]
    assert "does not survive anywhere" in card["consequence"]
    assert card["title"] == "profile · Your age?: 30 → 31"


def test_the_same_question_spelt_differently_finds_the_row_it_already_has(client):
    """A key is minted from the question, and the same function is what matches
    an existing one — so punctuation and case cannot mint a second copy of a
    question that is already there. A duplicate would not be an error anywhere;
    it would just quietly give the confidant two answers to one question."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        card = _card(db, "update_profile", question="your age", answer="31")
        assert card["confirmation"] == "diff", "it did not recognise the question"
        assert _confirm(db, card)["ok"] is True

    answers = {a["question_key"]: a["answer"] for a in client.get("/api/survey").json()}
    assert answers == {"about_age": "31", "risk_tolerance": "Medium"}


def test_an_answer_that_is_changed_keeps_the_forms_wording_and_its_topic(client):
    """The form owns the question text. Letting a paraphrase from a
    conversation rewrite the label would change the question under an answer
    that was given to the old one."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        card = _card(
            db,
            "update_profile",
            question_key="risk_tolerance",
            question="how risky do you like it",
            answer="High",
            topic="Somewhere else",
        )
        assert _confirm(db, card)["ok"] is True

    row = next(
        a for a in client.get("/api/survey").json() if a["question_key"] == "risk_tolerance"
    )
    assert row["answer"] == "High"
    assert row["question"] == "How would you describe your risk tolerance?"
    assert row["topic"] == "Risk & values"


def test_a_profile_card_goes_stale_when_the_answer_moves_under_it(client):
    """The fingerprint is what that question says now, which is what the diff
    was drawn from — so a card can never be confirmed against a sentence other
    than the one the reader was shown."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        card = _card(db, "update_profile", question="Your age?", answer="31")

    client.put("/api/survey", json=[{**_FORM[0], "answer": "32"}, _FORM[1]])

    with SessionLocal() as db:
        done = _confirm(db, card)

    assert done["ok"] is False and done["stale"] is True
    answers = {a["question_key"]: a["answer"] for a in client.get("/api/survey").json()}
    assert answers["about_age"] == "32", "the confirm wrote over it"


def test_the_result_says_what_was_replaced(client):
    """The model is handed this back as the answer to its call, and "your age is
    now 31" reads differently from "changed from 30 to 31". The card shows the
    same fact under its diff."""
    client.put("/api/survey", json=_FORM)

    with SessionLocal() as db:
        card = _card(db, "update_profile", question="Your age?", answer="31")
        done = _confirm(db, card)

    assert done["result"]["replaced"] == "30"
    assert done["result"]["question_key"] == "about_age"


# --- through the endpoint ----------------------------------------------------


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [
        json.loads(frame.split("\n")[1][len("data: "):])
        for frame in response.text.strip().split("\n\n")
    ]


def _stream(monkeypatch, rounds):
    """One scripted round trip per element, and a round past the script is an
    AssertionError — a fake that answers every call the same way turns one tool
    call into a loop that never ends."""
    seen: list[dict] = []

    def fake(system_prompt, messages, model=None, tools=None, cache_at=None):
        seen.append({"messages": list(messages)})
        assert len(seen) <= len(rounds), f"round trip {len(seen)} is past the script"
        yield from rounds[len(seen) - 1]

    monkeypatch.setattr(advisor, "stream_llm", fake)
    return seen


def test_the_chat_proposes_a_real_write_and_confirming_it_records_the_row(
    client, monkeypatch
):
    """End to end, once, on a real tool: the turn ends on the card, nothing is
    written, and the decision endpoint writes and streams what the model makes
    of it."""
    _stream(
        monkeypatch,
        [
            [
                ("text", "I can record that:"),
                (
                    "tool_call",
                    _ask_for(
                        "add_real_asset",
                        {"name": "gold necklace", "value": 500, "category": "jewelry", "currency": "EUR"},
                    ),
                ),
            ]
        ],
    )
    events = _events(
        client.post(
            "/api/chat",
            json={"content": "my grandmother gave me a 500 euro gold necklace"},
        )
    )
    assert [e["kind"] for e in events] == ["start", "delta", "card", "done"]
    card = next(e["card"] for e in events if e["kind"] == "card")
    assert client.get("/api/real-assets").json() == []

    _stream(monkeypatch, [[("text", "Recorded.")]])
    decided = _events(
        client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})
    )
    assert [e["kind"] for e in decided] == ["start", "decided", "delta", "done"]
    assert decided[1]["card"]["outcome"] == "confirmed"
    assert [a["name"] for a in client.get("/api/real-assets").json()] == ["gold necklace"]

    stored = client.get(
        f"/api/chat/conversations/{events[0]['conversation_id']}"
    ).json()["messages"][1]["blocks"][1]
    assert stored["outcome"] == "confirmed"
    assert stored["result"]["value"] == 500.0


def test_a_card_that_can_no_longer_be_drawn_is_a_409_and_not_a_500(client, monkeypatch):
    """The institution the card named was renamed while the reader was reading.
    Redrawing it now raises, and that is the strongest form of the ground having
    moved — so it has to arrive as the same refusal a moved fingerprint does,
    before the first byte, rather than as an exception escaping into the unit of
    work that was about to write the row."""
    _portfolio(client, quantity=12.0)
    _stream(
        monkeypatch,
        [
            [
                (
                    "tool_call",
                    _ask_for(
                        "record_transaction",
                        {
                            "kind": "buy",
                            "date": "2026-08-28",
                            "asset_name": "Coca-Cola",
                            "symbol": "KO",
                            "quantity": 5,
                            "unit_price": 128.40,
                            "institution": "Broker A",
                            "currency": "EUR", "price_currency": "EUR",
                        },
                    ),
                )
            ]
        ],
    )
    events = _events(client.post("/api/chat", json={"content": "ho comprato 5 Coca-Cola"}))
    card = next(e["card"] for e in events if e["kind"] == "card")

    client.put("/api/institutions/1", json={"name": "Bank A"})

    refused = client.post(f"/api/chat/cards/{card['card_id']}", json={"decision": "confirm"})
    assert refused.status_code == 409
    assert "Broker A" in refused.json()["detail"]
    assert client.get("/api/transactions").json() == []

    # What became of it, since brief AN: stale, and not decided again.
    with SessionLocal() as db:
        block = crud.find_chat_card(db, card["card_id"])[1]
    assert block["outcome"] == "stale"


def test_the_write_tools_do_not_run_when_the_model_calls_them(client):
    """The property that makes a tool a WRITE tool, asserted over the registry
    rather than tool by tool: everything with a `propose` draws a card, and a
    tool added tomorrow is covered tomorrow by nobody."""
    writers = {n for n, t in tools.REGISTRY.items() if t.propose is not None}
    assert writers == {
        "add_real_asset",
        "record_transaction",
        "update_profile",
        "run_analysis",
        # The fifth draws a card while writing nothing of the READER's — a
        # watchlist line owns nothing and totals nowhere. It is in this set
        # anyway, because the property is about the registry: a tool with a
        # `propose` does not run when the model calls it, whatever it would
        # have written. Exercised in tests/test_watchlist.py.
        "suggest_instrument",
        # Brief AN: the income and the expenses, as the Cash flow page writes
        # them (tests/test_the_chat_writes_income_and_expenses.py).
        "write_flow",
        # And the cash, as its two forms write it (test_the_chat_writes_the_cash.py).
        "record_transfer",
        "set_cash_balance",
        # And the goals (test_the_chat_writes_a_goal.py).
        "write_goal",
        # And the base, which asks the ECB's feed while it writes, so it walks
        # as the analysis does (test_the_chat_changes_the_base.py).
        "change_base_currency",
    }

    # A buy names its institution, because one that does not is now refused
    # before a card is drawn — the cash has to leave a real account. This test
    # is about the registry and not about that rule, so it satisfies it rather
    # than working around it.
    client.post("/api/institutions", json={"name": "Broker A"})

    with SessionLocal() as db:
        before = {
            "real_assets": len(crud.get_real_assets(db)),
            "transactions": len(crud.get_transactions(db)),
            "survey": len(crud.get_survey_responses(db)),
            "runs": db.query(models.ChainRun).count(),
        }
        cards = [
            _card(db, "add_real_asset", name="a thing", value=1, currency="EUR"),
            _card(
                db,
                "record_transaction",
                asset_name="Coca-Cola",
                symbol="KO",
                quantity=1,
                unit_price=1,
                institution="Broker A",
                currency="EUR", price_currency="EUR",
            ),
            _card(db, "update_profile", question="Anything?", answer="yes"),
            # The fourth writes a ChainRun rather than a row of the reader's,
            # and it is here for the same reason as the other three: the
            # property is about the registry, not about which table is touched.
            # The `offline` fixture is what proves it did not run — a chain that
            # started would have reached call_llm and raised.
            _card(db, "run_analysis"),
        ]
        after = {
            "real_assets": len(crud.get_real_assets(db)),
            "transactions": len(crud.get_transactions(db)),
            "survey": len(crud.get_survey_responses(db)),
            "runs": db.query(models.ChainRun).count(),
        }

    assert [c["outcome"] for c in cards] == ["pending"] * 4
    assert before == after
    assert db.get(models.RealAsset, 1) is None


def test_a_purchase_across_two_currencies_shows_the_debit_and_the_day_of_its_rate(
    client, monkeypatch
):
    """The card quotes the figure the row will carry, and for a price in one
    currency paid from an account in another that figure was worked out here —
    so the card says at which day's rate, and the reader can hold it against
    their statement before confirming. With no rate for the day, no card: the
    model is told to ask for the statement's figure."""
    day = "2026-08-28"
    rates = {day: {"USD": 1.25}}
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: dict(rates))
    _portfolio(client)
    purchase = dict(
        kind="buy", date=day, asset_name="Apple", symbol="AAPL", quantity=1,
        unit_price=100.0, institution="Broker A", currency="EUR", price_currency="USD",
    )

    with SessionLocal() as db:
        card = _card(db, "record_transaction", **purchase)
        assert card["title"] == (
            f"record buy: 1 AAPL @ 100.00 USD = 80.00 EUR (at the ECB rate of {day}) "
            f"· Broker A · {day}"
        )
        assert _confirm(db, card)["ok"] is True

    row = client.get("/api/transactions").json()[0]
    assert (row["amount"], row["currency"], row["price_currency"], row["fx_as_of"]) == (
        80.0, "EUR", "USD", day
    )

    rates.clear()
    with SessionLocal() as db:
        db.execute(text("DELETE FROM fx_rates"))
        db.commit()
        refused = _draft(db, "record_transaction", **purchase)
    assert "card" not in refused and "statement" in refused["error"]


# --- The currency a card stores ------------------------------------------------


def _london_buy(client, monkeypatch, price_currency):
    """100 units at 50 in `price_currency`, paid from a EUR account, on a day
    whose ECB rate is 0.80 GBP to the euro: the measured case of 2026-09-22."""
    day = "2026-08-28"
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {day: {"GBP": 0.80, "USD": 1.25}}
    )
    _portfolio(client)
    with SessionLocal() as db:
        card = _card(
            db, "record_transaction", kind="buy", date=day, asset_name="Vodafone",
            symbol="VOD.L", quantity=100, unit_price=50.0, institution="Broker A",
            currency="EUR", price_currency=price_currency,
        )
        assert _confirm(db, card)["ok"] is True
    return client.get("/api/transactions").json()[0]


def test_london_pence_stay_pence_through_the_chat(client, monkeypatch):
    """GBp is pence and GBP is pounds, a hundred times more. The chat used to
    upper-case every code it stored, so the same buy was 62.50 EUR through the
    ledger's form and 6,250.00 EUR through the chat."""
    row = _london_buy(client, monkeypatch, "GBp")
    assert (row["price_currency"], row["amount"], row["currency"]) == ("GBp", 62.5, "EUR")


def test_a_lower_case_code_is_still_stored_upper_case(client, monkeypatch):
    """Case is kept only where it means something: "usd" is USD, as before."""
    row = _london_buy(client, monkeypatch, "usd")
    assert (row["price_currency"], row["amount"]) == ("USD", 4000.0)


def test_gbx_is_still_pence_in_any_case(client, monkeypatch):
    row = _london_buy(client, monkeypatch, "gbx")
    assert (row["price_currency"], row["amount"]) == ("GBX", 62.5)


def test_the_chat_keeps_the_case_of_whatever_fx_says_is_case_significant(monkeypatch):
    """Read from fx's own table, not a second list: a new case-significant unit
    added there is kept by the chat without touching tools.py."""
    monkeypatch.setitem(fx._MINOR_EXACT, "ZAc", ("ZAR", 100.0))
    assert tools._stored_currency("ZAc") == "ZAc"
    assert tools._stored_currency("GBp") == "GBp"
    assert tools._stored_currency("gbp") == "GBP"
    assert tools._stored_currency("usd") == "USD"
