"""A suggestion card can carry an amount, chosen within what the records allow.

Brief AQ (2026-10-12). In the brief's P0 no card carried an amount: "how much"
was said in prose, from the model's own arithmetic. A suggestion card may now
carry a sum now, a monthly sum or both, in the base currency, with what the
chat assumed. Drawing it reads the figures `size_purchase` reads (`sizing`),
refuses an amount above them (the cash above the reserve; what is left each
month once the PACs and the goals' contributions are taken out, the reader's
choice), says them on the card with the line that this is not regulated
advice, and goes stale when they move. The watchlist keeps the amount and what
it stood on (migration 491fe57d31db). A security the catalogue or Yahoo does
not verify stays refused, amount or not.

Every name, ISIN, symbol and amount here is invented.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config

from app import advisor, catalogue, database, dated, prices, tools
from app.database import SessionLocal

TODAY = "2026-03-10"
FUND, MISSING = "IE0000AQ0101", "IE0000AQ0109"

REGISTRY = pd.DataFrame(
    [
        {"name": "Example Global Bond UCITS ETF Acc", "ticker": "EXGB", "dividends": "Accumulating",
         "ter": 0.1, "size": 2500, "replication": "Sampling", "domicile_country": "Ireland",
         "currency": "EUR", "number_of_holdings": 900, "hedged": True},
    ],
    index=pd.Index([FUND], name="isin"),
)

WHY = {
    "reason": "A broad bond fund beside cash that has nothing else to do.",
    "based_on": "You said you want something steadier than shares for part of your savings.",
    "unknowns": "I do not know your tax situation or how long this money can stay invested.",
}
SIZED = {
    "amount_now": 1500,
    "amount_monthly": 400,
    "amount_currency": "EUR",
    "amount_assumptions": "The app's six months of reserve, the bike's 100 a month kept, half the room now.",
}
# What the card says the amounts stand on, the records below read on TODAY.
TAIL = (
    "your records of 2026-03-10. 9000.00 EUR on your accounts, "
    "3000.00 EUR of it above a reserve of 6 months of essential expenses (the app's "
    "default, as your profile does not say): 1500.00 EUR now would leave 1500.00 EUR "
    "above it, and is 16.67% of your financial wealth. 1900.00 EUR is left each month "
    "once the PACs and the goals' recorded contributions are taken out: 400.00 EUR a "
    'month is 21.05% of it. The goal "New bike" needs 200.14 EUR a month to 2027-03-10 '
    "with no growth, and 100.00 EUR a month is recorded for it, 100.14 EUR short. Were "
    "every goal given its need, 1799.86 EUR would be left each month."
)
FIGURES = "The amounts stand on " + TAIL
NOT_ADVICE = "This is educational information, not personalised regulated advice."


@pytest.fixture
def records(client, monkeypatch):
    """The registry loaded; an account with 10,000 on 1 March, a salary of
    3,000 on the 27th and rent of 1,000 paid on the 5th; a goal with 100 a
    month recorded towards it."""
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: REGISTRY)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    bank = client.post("/api/institutions", json={"name": "Example Bank", "type": "bank"}).json()["id"]
    assert client.post(f"/api/institutions/{bank}/cash-anchors",
                       json={"date": "2026-03-01", "amount": 10000, "currency": "EUR"}).status_code == 201
    for path, body in (
        ("/api/income-sources", {"name": "Salary", "amount": 3000, "kind": "active", "category": "salary",
                                 "start_date": "2025-01-27"}),
        ("/api/expenses", {"name": "Rent", "amount": 1000, "nature": "essential", "category": "housing",
                           "start_date": "2025-01-05"}),
    ):
        made = client.post(path, json={**body, "currency": "EUR", "frequency": "monthly",
                                       "institution_id": bank})
        assert made.status_code == 201, made.text
    made = client.post("/api/goals", json={
        "name": "New bike", "type": "target_amount", "currency": "EUR", "target_amount": 3000,
        "target_date": "2027-03-10", "current_amount": 600, "monthly_contribution": 100})
    assert made.status_code == 201, made.text
    return {"client": client, "bank": bank}


def _suggest(db, **arguments) -> dict:
    return tools.answer(db, advisor.ToolCall(id="toolu_1", name="suggest_instrument",
                                             arguments=json.dumps(arguments)))


def _accept(db, card: dict) -> dict:
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


def _fields(card: dict) -> list[dict]:
    return tools.present(card)["fields"]


# --- The card ------------------------------------------------------------------------------


def test_a_card_carries_the_amount_its_assumptions_and_what_it_stood_on(records):
    with SessionLocal() as db:
        card = _suggest(db, isin=FUND, **WHY, **SIZED)["card"]
    fields = {f["label"]: f for f in _fields(card)}
    assert fields["Now"] == {"label": "Now", "value": "1500.0", "kind": "amount", "currency": "EUR"}
    assert fields["Each month"] == {"label": "Each month", "value": "400.0", "kind": "amount",
                                    "currency": "EUR"}
    assert fields["Assumes"]["value"] == SIZED["amount_assumptions"]
    assert not any(f["value"] == "EUR" for f in fields.values()), "the currency is said with the amounts"
    assert card["consequence"] == tools._WATCH_CONSEQUENCE + " " + FIGURES + " " + NOT_ADVICE
    assert card["verb"] == "Add to watchlist"


def test_accepted_the_watchlist_keeps_the_amount_and_what_it_stood_on(records):
    client = records["client"]
    with SessionLocal() as db:
        card = _suggest(db, isin=FUND, **WHY, **SIZED)["card"]
        done = _accept(db, card)
        db.commit()
    assert done["ok"], done
    (line,) = client.get("/api/watchlist").json()
    assert (line["amount_now"], line["amount_monthly"], line["amount_currency"]) == (1500.0, 400.0, "EUR")
    assert line["amount_assumptions"] == SIZED["amount_assumptions"]
    # Kept to follow "Stood on" on the watchlist line.
    assert line["amount_figures"] == TAIL
    receipt = tools.present({**card, "outcome": "confirmed", "result": done["result"]})["receipt"]
    assert {"label": "Now", "value": "1500.0", "kind": "amount", "currency": "EUR"} in receipt
    assert {"label": "Each month", "value": "400.0", "kind": "amount", "currency": "EUR"} in receipt


def test_a_card_with_no_amount_says_what_it_said_and_that_it_is_not_advice(records):
    client = records["client"]
    with SessionLocal() as db:
        card = _suggest(db, isin=FUND, **WHY)["card"]
        assert card["consequence"] == tools._WATCH_CONSEQUENCE + " " + NOT_ADVICE
        assert not any(f["label"] in ("Now", "Each month", "Assumes") for f in _fields(card))
        assert _accept(db, card)["ok"]
        db.commit()
    (line,) = client.get("/api/watchlist").json()
    assert [line[k] for k in ("amount_now", "amount_monthly", "amount_currency",
                              "amount_assumptions", "amount_figures")] == [None] * 5


# --- What the records allow ------------------------------------------------------------------


def _refusal(**arguments) -> str:
    with SessionLocal() as db:
        outcome = _suggest(db, isin=FUND, **WHY, **arguments)
    assert outcome.get("ok") is False, outcome
    return outcome["error"]


def test_a_sum_now_above_the_cash_above_the_reserve_is_refused_with_the_figure(records):
    said = _refusal(amount_now=3500, amount_currency="EUR", amount_assumptions="All of it.")
    assert (
        "3500.00 EUR is more than the cash above the reserve, 3000.00 EUR (9000.00 EUR on the "
        "accounts, a reserve of 6000.00 EUR: 6 months of essential expenses, the app's default, "
        "as your profile does not say). Choose within it"
    ) in said


def test_a_monthly_sum_above_what_is_left_after_the_commitments_is_refused(records):
    said = _refusal(amount_monthly=2000, amount_currency="EUR", amount_assumptions="All of it.")
    assert (
        "2000.00 EUR a month is more than what is left each month once the PACs and the goals' "
        "contributions are taken out, 1900.00 EUR. Choose within it."
    ) in said


def test_the_profile_s_months_move_the_room(records):
    client = records["client"]
    assert client.put("/api/survey", json=[{"question_key": "reserve_months", "answer": "3"}]).status_code == 200
    with SessionLocal() as db:
        card = _suggest(db, isin=FUND, **WHY, **{**SIZED, "amount_now": 4000})["card"]
    assert "6000.00 EUR of it above a reserve of 3 months of essential expenses (your answer in the Profile)" in card["consequence"]


def test_an_amount_says_what_it_assumed_and_nothing_assumes_without_one(records):
    assert "An amount travels with what it assumed" in _refusal(amount_now=100, amount_currency="EUR")
    assert "amount_assumptions goes with an amount" in _refusal(amount_assumptions="Half of it.")


def test_the_amounts_are_in_the_base_currency_and_say_so(records):
    assert ("The amounts are in the base currency, EUR: name it in amount_currency, not USD."
            in _refusal(amount_now=100, amount_currency="USD", amount_assumptions="Some."))
    assert ("The amounts are in the base currency, EUR: name it in amount_currency."
            in _refusal(amount_now=100, amount_assumptions="Some."))


def test_records_that_cannot_size_an_amount_refuse_it(client, monkeypatch):
    monkeypatch.setattr(dated, "today", lambda: TODAY)
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: REGISTRY)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    assert "No reserve can be sized" in _refusal(amount_now=100, amount_currency="EUR",
                                                 amount_assumptions="Some.")
    assert "What is left each month cannot be said" in _refusal(
        amount_monthly=100, amount_currency="EUR", amount_assumptions="Some.")


def test_a_security_nothing_verifies_is_refused_amount_or_not(records, monkeypatch):
    with SessionLocal() as db:
        fund = _suggest(db, isin=MISSING, **WHY, **SIZED)
        monkeypatch.setattr(prices, "_fetch_lookup", lambda query, count: [])
        share = _suggest(db, symbol="NONE.MI", **WHY, **SIZED)
    assert fund["ok"] is False and "is not in the local registry" in fund["error"]
    assert share["ok"] is False and "Yahoo lists nothing under 'NONE.MI'" in share["error"]


def test_the_card_goes_stale_when_what_it_stood_on_moves(records):
    client = records["client"]
    with SessionLocal() as db:
        card = _suggest(db, isin=FUND, **WHY, **SIZED)["card"]
    # A balance recorded since: the cash, and so the room, is no longer what the
    # card said, though 1,500 would still fit in it.
    assert client.post(f"/api/institutions/{records['bank']}/cash-anchors",
                       json={"date": "2026-03-08", "amount": 8500, "currency": "EUR"}).status_code == 201
    with SessionLocal() as db:
        done = _accept(db, card)
    assert done["ok"] is False and done.get("stale") is True


# --- A share's card -------------------------------------------------------------------------


def test_a_share_s_card_says_the_currency_its_listing_is_quoted_in(records, monkeypatch):
    listed = [{"symbol": "EXCO.MI", "name": "Example Company", "quote_type": "equity",
               "exchange": "MIL", "price": 12.5}]
    monkeypatch.setattr(prices, "_fetch_lookup", lambda query, count: listed)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    with SessionLocal() as db:
        card = _suggest(db, symbol="EXCO.MI", **WHY, **SIZED)["card"]
        assert card["title"] == "watch: Example Company, EXCO.MI · share · MIL · quoted in EUR"
        assert card["consequence"].endswith(FIGURES + " " + NOT_ADVICE)
        # Yahoo silent about it: said so, never inferred from the exchange.
        monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: (_ for _ in ()).throw(OSError("silent")))
        silent = _suggest(db, symbol="EXCO.MI", **WHY)["card"]
    assert silent["title"] == "watch: Example Company, EXCO.MI · share · MIL · currency not given by Yahoo"
    # And a silence about the currency is not a change of the listing.
    assert silent["fingerprint"] == card["fingerprint"].split("|EUR|")[0]


# --- The migration ---------------------------------------------------------------------------


_COLUMNS = ("amount_now", "amount_monthly", "amount_currency", "amount_assumptions", "amount_figures")


@pytest.fixture
def before_the_amounts(tmp_path, start_on):
    """A file the real chain built up to `e62c6f6c8060`, the revision before
    the amounts', which the next `database.init_db()` starts on."""
    path = tmp_path / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, "e62c6f6c8060")
    start_on(path)
    return path


def test_the_migration_adds_the_amounts_and_keeps_every_line_as_it_was(before_the_amounts):
    path = before_the_amounts
    then = "SELECT id, isin, symbol, name, reason, based_on, unknowns, added_at FROM watchlist_items"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO watchlist_items (isin, symbol, name, reason, based_on, unknowns, added_at)"
            " VALUES ('XA0000000011', NULL, 'Example Fund 1', 'Why.', 'Because.', 'Not known.',"
            " '2026-10-01T10:00:00')"
        )
        before = conn.execute(then).fetchall()

    database.init_db()

    # "-to-*": the copy names the head the app migrates to, which a later
    # migration moves (brief AV's did).
    copies = list(path.parent.glob("data.db.bak-*-before-migration-e62c6f6c8060-to-*"))
    assert len(copies) == 1, "the app copied the file before migrating it"
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute(then).fetchall() == before
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(watchlist_items)")}
        assert all(columns[c][3] == 0 for c in _COLUMNS), "each is nullable"
        assert conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM watchlist_items").fetchall() == [(None,) * 5]

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    command.downgrade(cfg, "e62c6f6c8060")
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(watchlist_items)")]
        assert not set(_COLUMNS) & set(columns)
        assert conn.execute(then).fetchall() == before


