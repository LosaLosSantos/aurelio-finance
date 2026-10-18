"""What the chat, the analyst and a card read of a cost paid in part (brief AV,
part 4).

Measured on the demo with an invented fund (2026-10-14): the chat's and the
analyst's line for a row 23% paid ended "COST UNKNOWN", a dash, "no purchase on
record ..." (154 characters, purchases on record, and the dash an em dash in
the chat's context), the totals called 22,246.00 "what was paid" with 1,066.00 paid, the
chat's rule said "'book' is what was paid", and a card called a blend's
average a cost. Every name and figure here is invented.
"""

from __future__ import annotations

import json

import pytest

from app import advisor, composition, crud, dated, models
from app.database import SessionLocal

SITUATION = "2026-01-01"


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


def _blend(client, buy_price: float = 100, **holding) -> int:
    """10 photographed at 100 with no cost, 3 bought since; priced at 110."""
    bank = _made(client.post("/api/institutions", json={"name": "Banca Alfa"}))["id"]
    _made(client.post(f"/api/institutions/{bank}/cash-anchors",
                      json={"date": SITUATION, "amount": 5000, "currency": "EUR"}))
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Alfa", "asset_class": "fund_etf", "symbol": "ALFA.MI",
        "quantity": 10, "unit_price": 100, "currency": "EUR", **holding}))
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": "2026-02-02", "institution_id": bank, "asset_name": "Fondo Alfa",
        "symbol": "ALFA.MI", "quantity": 3, "unit_price": buy_price, "currency": "EUR",
        "price_currency": "EUR"}))
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {"ALFA.MI": {"price": 110.0, "as_of": "2026-05-04",
                                                  "currency": "EUR"}})
    return bank


def _line(text: str) -> str:
    return next(line for line in text.splitlines() if "Fondo Alfa [fund_etf]" in line)


def _nothing_inside(monkeypatch) -> None:
    """The analyst's picture looks through every fund; this one is invented,
    so every source says so, rather than the boundary refusing the call."""
    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda symbol: None)
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)
    monkeypatch.setattr(
        composition, "_fetch_trackinsight",
        lambda ticker: (_ for _ in ()).throw(LookupError("not a fund Trackinsight lists")))


def test_the_chat_and_the_analyst_read_how_much_was_paid_and_which_part_is_a_gain(
    client, monkeypatch
):
    _nothing_inside(monkeypatch)
    _blend(client)
    with SessionLocal() as db:
        for context in (advisor.build_context(db), advisor.build_portfolio_context(db)):
            line = _line(context)
            assert line.endswith(
                "COST PARTLY PAID: 300.00 of the book (23.1%) is money paid, for 3 of the 13 "
                "units (buys, or a cost typed on a situation); the rest is the value a situation "
                "recorded. Of the P/L, +30.00 is a gain or a loss on the units paid for and "
                "+100.00 is movement since that situation, NOT profit"
            )
            assert "COST UNKNOWN" not in line


def test_a_part_paid_by_a_plan_is_said_estimated(client):
    _blend(client)
    with SessionLocal() as db:
        db.execute(models.Transaction.__table__.update().values(estimated=True))
        db.commit()
        line = _line(advisor.build_context(db))
    assert line.endswith(
        "; the part paid is ESTIMATED: some or all of it is a plan's buy priced at a market "
        "close, or a cost derived from a reported % return, not read off a contract note"
    )


def test_nothing_paid_is_still_cost_unknown_without_a_dash(client):
    bank = _made(client.post("/api/institutions", json={"name": "Banca Beta"}))["id"]
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": SITUATION}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Fondo Beta", "asset_class": "fund_etf", "symbol": "BETA.MI",
        "quantity": 10, "unit_price": 100, "currency": "EUR"}))
    with SessionLocal() as db:
        line = next(x for x in advisor.build_context(db).splitlines() if "Fondo Beta" in x)
    assert line.endswith(
        "COST UNKNOWN: no purchase on record, so the average cost above is the price the "
        "situation was recorded at, and the P/L is movement since then, NOT profit"
    )


def test_the_total_says_how_much_of_the_book_was_paid(client):
    _blend(client)
    with SessionLocal() as db:
        context = advisor.build_context(db)
    assert (
        "- TOTAL book: 1300.00, of which 300.00 is money paid and the rest situations' values "
        "with no purchase price on record"
    ) in context
    assert "TOTAL cost (what was paid)" not in context


def test_a_book_all_paid_is_still_what_was_paid(client):
    _blend(client, cost_basis=900)
    with SessionLocal() as db:
        assert "- TOTAL cost (what was paid): 1200.00" in advisor.build_context(db)


# --- A card that moves the average --------------------------------------------------------


def _card(client, monkeypatch, **arguments) -> dict:
    def fake(system_prompt, messages, model=None, tools=None, cache_at=None, kept_to=None):
        call = advisor.ToolCall(id="call_1", name="change_ledger_entry",
                                arguments=json.dumps(arguments))
        yield ("tool_call", call)

    monkeypatch.setattr(advisor, "stream_llm", fake)
    response = client.post("/api/chat", json={"content": "please"})
    assert response.status_code == 200, response.text
    events = [json.loads(frame.split("\n")[1][len("data: "):])
              for frame in response.text.strip().split("\n\n")]
    (card,) = [e["card"] for e in events if e["kind"] == "card"]
    return card


@pytest.mark.parametrize("arguments,now,proposed", [
    ({"action": "correct", "date": "2026-02-02", "kind": "buy", "instrument": "ALFA.MI",
      "new_unit_price": 110},
     "104.62 EUR, 26% of it paid", "102.31 EUR, 25% of it paid"),
    ({"action": "delete", "date": "2026-02-02", "kind": "buy", "instrument": "ALFA.MI"},
     "104.62 EUR, 26% of it paid", "100.00 EUR, no cost on record"),
])
def test_a_card_says_how_much_of_an_average_was_paid(client, monkeypatch, arguments, now, proposed):
    monkeypatch.setattr(dated, "today", lambda: "2026-05-04")
    _blend(client, buy_price=120)
    card = _card(client, monkeypatch, **arguments)
    (average,) = [d for d in card["diff"] if d["field"].startswith("Average cost of ALFA.MI")]
    assert (average["now"], average["proposed"]) == (now, proposed)
