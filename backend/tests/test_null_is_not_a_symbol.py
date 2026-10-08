"""The word for nothing is not a symbol.

In the reader's test round (2026-10-08) the chat's two fund cards carried
"symbol": "null", the word and not JSON's null; accepting them stored "NULL"
as the symbol of both watchlist lines, and "Record a buy" put it in the ticker
box. Brief AJ: an optional text argument of a tool that writes reads such a
word as nothing (`tools.MaybeText`), and the migration `e62c6f6c8060` clears
the lines already written, a fund's only.

Every fund and symbol here is invented.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config

from app import advisor, catalogue, database, tools
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


@pytest.fixture
def loaded(client, monkeypatch):
    monkeypatch.setattr(catalogue, "_fetch_overview", lambda: CATALOGUE)
    assert client.post("/api/instruments/catalogue/refresh").status_code == 200
    return client


def _answer(db, name: str, arguments: dict) -> dict:
    return tools.answer(db, advisor.ToolCall(id="call_1", name=name, arguments=json.dumps(arguments)))


def _accept(db, card: dict) -> dict:
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


# --- The cards -------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["null", "NULL", " None ", "n/a", "undefined", "nil", ""])
def test_a_fund_card_whose_symbol_is_a_word_for_nothing_parks_no_symbol(loaded, word):
    with SessionLocal() as db:
        outcome = _answer(db, "suggest_instrument", {"isin": FUND, "symbol": word, **WHY})
        card = outcome["card"]
        assert card["arguments"]["symbol"] is None, "the card says no symbol"
        done = _accept(db, card)

    assert done["ok"] is True
    assert done["result"]["symbol"] is None
    assert [i["symbol"] for i in loaded.get("/api/watchlist").json()] == [None]


def test_a_real_symbol_on_a_fund_card_is_still_kept(loaded):
    """A guard: only the words for nothing are read as nothing."""
    with SessionLocal() as db:
        card = _answer(db, "suggest_instrument", {"isin": FUND, "symbol": "xglo.de", **WHY})["card"]
        _accept(db, card)

    assert [i["symbol"] for i in loaded.get("/api/watchlist").json()] == ["XGLO.DE"]


def test_a_share_card_whose_symbol_is_the_word_null_names_nothing(client):
    """Refused for what it is, a card naming no instrument, before Yahoo is
    asked about a share called NULL."""
    with SessionLocal() as db:
        outcome = _answer(db, "suggest_instrument", {"symbol": "null", **WHY})

    assert outcome["ok"] is False
    assert "Name a fund by its ISIN, or a single share by its symbol." in outcome["error"]


def test_a_buy_whose_ticker_is_the_word_null_is_refused(client):
    """The same word on the ledger's card would have recorded a buy of NULL."""
    client.post("/api/institutions", json={"name": "Broker A", "type": "broker"})
    with SessionLocal() as db:
        outcome = _answer(
            db,
            "record_transaction",
            {
                "kind": "buy", "date": "2026-10-01", "asset_name": "Example Global Equity",
                "symbol": "null", "quantity": 2, "unit_price": 100, "currency": "EUR",
                "price_currency": "EUR", "institution": "Broker A",
            },
        )

    assert "card" not in outcome
    assert outcome["ok"] is False
    assert "needs a ticker" in outcome["error"]


def test_a_note_that_says_nothing_is_kept_as_nothing(client):
    with SessionLocal() as db:
        card = _answer(
            db,
            "add_real_asset",
            {"name": "a painting", "value": 1200, "currency": "EUR", "notes": "None"},
        )["card"]
        done = _accept(db, card)

    assert done["ok"] is True
    assert client.get("/api/real-assets").json()[0]["notes"] is None


def test_the_model_is_shown_the_same_schema():
    """A validator, not a type: what the model is told a field takes is what
    it was told before, a string or null."""
    shown = tools.SuggestInstrumentArgs.model_json_schema()["properties"]["symbol"]
    assert shown["anyOf"] == [{"type": "string"}, {"type": "null"}]


# --- The lines already written --------------------------------------------------------

_LINE = (
    "INSERT INTO watchlist_items (isin, symbol, name, reason, based_on, unknowns, added_at)"
    " VALUES (?, ?, ?, 'Why.', 'Because.', 'Not known.', '2026-10-01T10:00:00')"
)


def test_the_migration_clears_the_word_on_a_funds_line_and_nothing_else(one_migration_behind):
    """What the reader's `data.db` takes at its next start, behind the app's
    own copy: a fund's line whose symbol is a word for nothing loses it, and
    every other line, and every other column, stays as it was. A share's line
    is named by its symbol and is not touched, whatever that symbol reads."""
    lines = [
        ("XA0000000011", "NULL", "Example Fund 1"),
        ("XA0000000029", " null ", "Example Fund 2"),
        ("XA0000000037", "None", "Example Fund 3"),
        ("XA0000000045", "XFUN.DE", "Example Fund 4"),
        ("XA0000000052", None, "Example Fund 5"),
        (None, "NULL", "Example Share"),
    ]
    with closing(sqlite3.connect(one_migration_behind)) as conn, conn:
        for line in lines:
            conn.execute(_LINE, line)
        before = conn.execute("SELECT * FROM watchlist_items ORDER BY id").fetchall()

    database.init_db()

    copies = list(
        one_migration_behind.parent.glob(
            "data.db.bak-*-before-migration-5a4336780500-to-e62c6f6c8060"
        )
    )
    assert len(copies) == 1, "the app copied the file before migrating it"
    with closing(sqlite3.connect(one_migration_behind)) as conn, conn:
        after = conn.execute("SELECT * FROM watchlist_items ORDER BY id").fetchall()
        symbol = [row[1] for row in conn.execute("PRAGMA table_info(watchlist_items)")].index(
            "symbol"
        )
    assert [row[symbol] for row in after] == [None, None, None, "XFUN.DE", None, "NULL"]
    assert [row[:symbol] + row[symbol + 1:] for row in after] == [
        row[:symbol] + row[symbol + 1:] for row in before
    ], "nothing but those symbols changed"

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    command.downgrade(cfg, "5a4336780500")
    with closing(sqlite3.connect(one_migration_behind)) as conn, conn:
        assert conn.execute("SELECT * FROM watchlist_items ORDER BY id").fetchall() == after, (
            "the downgrade writes nothing back"
        )
