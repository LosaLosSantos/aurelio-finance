"""Share proposal, confirmation, and watchlist migration contracts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config

from app import advisor, crud, database, prices, tools
from app.database import SessionLocal

REAL_FETCH_LOOKUP = prices._fetch_lookup

WHY = {
    "reason": "It would add a European industrial name to a portfolio of funds only.",
    "based_on": "You said you want a few single shares beside your ETFs.",
    "unknowns": "I do not know how much single-share risk you are willing to carry.",
}
ACME = {
    "symbol": "ACME.MI",
    "name": "Acme Industrie",
    "quote_type": "equity",
    "exchange": "MIL",
    "price": 12.3,
}


@pytest.fixture
def yahoo(monkeypatch):
    class Fake:
        lists = {"ACME.MI": [ACME]}
        silent = False
        asked: list[str] = []

    def lookup(query, count):
        Fake.asked.append(query)
        if Fake.silent:
            raise ConnectionError("Yahoo is down")
        return [dict(row) for row in Fake.lists.get(query.upper(), [])]

    def currency(symbol):
        if Fake.silent:
            raise ConnectionError("Yahoo is down")
        return "EUR"

    monkeypatch.setattr(prices, "_fetch_lookup", lookup)
    monkeypatch.setattr(prices, "_fetch_currency", currency)
    return Fake


def _suggest(db, **arguments) -> dict:
    call = advisor.ToolCall(
        id="toolu_1", name="suggest_instrument", arguments=json.dumps(arguments)
    )
    return tools.answer(db, call)


def _accept(db, card: dict) -> dict:
    return tools.finish(tools.settle(db, card["tool"], card["arguments"], card["fingerprint"]))


def test_a_share_yahoo_lists_is_put_up_and_kept_by_its_symbol(client, yahoo):
    with SessionLocal() as db:
        card = _suggest(db, symbol="acme.mi", **WHY)["card"]
        assert card["title"] == "watch: Acme Industrie, ACME.MI · share · MIL · quoted in EUR"
        assert card["verb"] == "Add to watchlist"
        assert "gives no ISIN" in card["consequence"]
        assert crud.get_watchlist_items(db) == []
        done = _accept(db, card)
        db.commit()
    assert done["ok"], done
    (line,) = client.get("/api/watchlist").json()
    assert (line["isin"], line["symbol"], line["name"]) == (None, "ACME.MI", "Acme Industrie")
    assert (line["reason"], line["based_on"], line["unknowns"]) == (
        WHY["reason"], WHY["based_on"], WHY["unknowns"],
    )


def test_confirming_a_share_asks_yahoo_again_and_refuses_what_changed(client, yahoo):
    with SessionLocal() as db:
        card = _suggest(db, symbol="ACME.MI", **WHY)["card"]
        assert yahoo.asked == ["ACME.MI"]
        yahoo.lists["ACME.MI"] = [{**ACME, "name": "Acme Holding"}]
        done = _accept(db, card)
        assert crud.get_watchlist_items(db) == []
    assert done["ok"] is False and done.get("stale") is True
    assert len(yahoo.asked) == 2


def test_a_silent_yahoo_at_confirmation_writes_nothing(client, yahoo):
    with SessionLocal() as db:
        card = _suggest(db, symbol="ACME.MI", **WHY)["card"]
        yahoo.silent = True
        done = _accept(db, card)
        assert done["ok"] is False
        assert "did not answer" in done["error"]
        assert crud.get_watchlist_items(db) == []


@pytest.mark.parametrize(
    "lists, symbol, said",
    [
        ({}, "ZZZZ.MI", "Yahoo lists nothing under 'ZZZZ.MI'"),
        (
            {"EXUS": [{"symbol": "EXUS", "name": "Example US 500 Fund", "quote_type": "etf", "exchange": "PCX"}]},
            "EXUS", "as a fund, not a share",
        ),
        (
            {"EXIN": [{"symbol": "EXIN", "name": "Example Income ETF", "quote_type": "equity", "exchange": "PCX"}]},
            "EXIN", "as a fund, not a share",
        ),
        (
            {"XS0000000009.SG": [{"symbol": "XS0000000009.SG", "name": None, "quote_type": "equity", "exchange": "STU"}]},
            "XS0000000009.SG", "is an ISIN",
        ),
        (
            {"EXC-EUR": [{"symbol": "EXC-EUR", "name": "Example Coin EUR", "quote_type": "cryptocurrency", "exchange": "CCC"}]},
            "EXC-EUR", "as cryptocurrency, not as a share",
        ),
        (
            {"NONAME.MI": [{"symbol": "NONAME.MI", "name": None, "quote_type": "equity", "exchange": "MIL"}]},
            "NONAME.MI", "with no name",
        ),
    ],
)
def test_what_yahoo_cannot_vouch_for_as_a_share_gets_no_card(client, yahoo, lists, symbol, said):
    yahoo.lists = {**lists}
    with SessionLocal() as db:
        outcome = _suggest(db, symbol=symbol, **WHY)
    assert "card" not in outcome
    assert outcome["ok"] is False and said in outcome["error"], outcome["error"]


def test_a_silent_yahoo_draws_no_card_and_is_not_called_a_no(client, yahoo):
    yahoo.silent = True
    with SessionLocal() as db:
        outcome = _suggest(db, symbol="ACME.MI", **WHY)
    assert "card" not in outcome
    assert "did not answer just now" in outcome["error"]
    assert "says nothing about whether ACME.MI exists" in outcome["error"]


def test_a_share_already_on_the_watchlist_is_not_suggested_again(client, yahoo):
    with SessionLocal() as db:
        assert _accept(db, _suggest(db, symbol="ACME.MI", **WHY)["card"])["ok"]
        db.commit()
        outcome = _suggest(db, symbol="ACME.MI", **WHY)
    assert "already on the watchlist" in outcome["error"]


def test_a_suggestion_must_name_a_fund_or_a_share(client, yahoo):
    with SessionLocal() as db:
        outcome = _suggest(db, **WHY)
    assert "card" not in outcome
    assert "Name a fund by its ISIN, or a single share by its symbol" in outcome["error"]
    assert yahoo.asked == []


def test_a_missing_name_from_yahoo_is_no_name(monkeypatch):
    import yfinance

    class Lookup:
        def __init__(self, query, timeout=None):
            pass

        def get_all(self, count=8):
            return pd.DataFrame(
                [{"shortName": float("nan"), "quoteType": "equity", "exchange": "MIL", "regularMarketPrice": 1.0}],
                index=pd.Index(["NONAME.MI"], name="symbol"),
            )

    monkeypatch.setattr(yfinance, "Lookup", Lookup)
    (row,) = REAL_FETCH_LOOKUP("NONAME.MI", 8)
    assert row["name"] is None and row["quote_type"] == "equity"


_THEN = (
    "SELECT id, isin, symbol, name, reason, based_on, unknowns, added_at "
    "FROM watchlist_items ORDER BY id"
)


@pytest.fixture
def before_the_share_migration(tmp_path, start_on):
    path = tmp_path / "data.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(cfg, "e9346d9cfd3f")
    start_on(path)
    return path


def test_the_migration_keeps_every_line_and_lets_a_share_have_no_isin(before_the_share_migration):
    path = before_the_share_migration
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO watchlist_items (isin, symbol, name, reason, based_on, unknowns, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("XA0000000011", None, "Example Equity Fund 1", "Why.", "Because.", "Not known.",
             "2026-09-30T10:00:00"),
        )
        before = conn.execute(_THEN).fetchall()

    database.init_db()

    copies = list(path.parent.glob("data.db.bak-*-before-migration-e9346d9cfd3f-to-*"))
    assert len(copies) == 1
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute(_THEN).fetchall() == before
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(watchlist_items)")}
        assert columns["isin"][3] == 0
        assert columns["name"][3] == 1
        indexes = [row[1] for row in conn.execute("PRAGMA index_list(watchlist_items)")]
        assert "ix_watchlist_items_isin" in indexes
        conn.execute(
            "INSERT INTO watchlist_items (isin, symbol, name, reason, based_on, unknowns, added_at)"
            " VALUES (NULL, 'ACME.MI', 'Acme Industrie', 'Why.', 'Because.', 'Not known.',"
            " '2026-10-06T10:00:00')"
        )

    cfg = Config()
    cfg.set_main_option("script_location", str(database.BASE_DIR / "alembic"))
    with pytest.raises(RuntimeError, match="name a share by its symbol"):
        command.downgrade(cfg, "e9346d9cfd3f")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DELETE FROM watchlist_items WHERE isin IS NULL")
    command.downgrade(cfg, "e9346d9cfd3f")
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(watchlist_items)")}
        assert columns["isin"][3] == 1
        assert conn.execute(_THEN).fetchall() == before
