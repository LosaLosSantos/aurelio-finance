"""A note the app writes by itself says where the row came from, and nothing an
edit can make false.

The standing rule for machine stamps: a stamp states only what no later edit
can make false, and anything about the row's current figures lives in a column
the same edit changes. The test for any stamp: would every word still be true
after the reader corrects every editable field of the row?

The dividend's stamp failed it. It read "Dividend 0.5 per share (gross,
auto-recorded)", and the correction it exists for, the broker's net credit
typed over the market's gross figure, keeps the note (an edit writes only what
it sent) while it clears `estimated`. Measured by the reviewer on a scratch
database before item 08 drew a single note: a net figure went on saying
"gross". So the stamp now names only its origin, with its unit, and whether
the figure is still the market's is `estimated`'s alone.

The unit is the listing's. A figure per share without one is not a figure: in
London "a dividend of 5 per share" is five pence or five pounds, the hundredfold
error the chat stopped making in bf170d1.
"""

from __future__ import annotations

import pytest

from app import crud, prices
from app.database import SessionLocal

EX_DATE = "2026-03-20"

# What the ledger form sends when a row is edited, as the Edge run of item 08
# captured it: every key but the note, which the form has no box for.
LEDGER_FORM_KEYS = (
    "amount", "asset_name", "currency", "date", "fees", "institution_id",
    "kind", "price_currency", "quantity", "symbol", "unit_price",
)


def _auto_recorded_dividend(client, monkeypatch, *, symbol, held_in, listed_in, dps):
    """One distributing position in an account with no cash anchor, so the
    dividend is recorded in the unit it was paid in, and the catch-up that
    records it."""
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-01"}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "A distributing fund",
            "asset_class": "fund_etf",
            "symbol": symbol,
            "quantity": 100,
            "unit_price": 100,
            "distribution_policy": "dist",
            "currency": held_in,
        },
    )
    if listed_in is not None:
        # What pricing the listing once taught the price cache.
        with SessionLocal() as db:
            crud.upsert_price_caches(
                db, {symbol: {"price": 100.0, "as_of": "2026-03-01", "currency": listed_in}}
            )
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda sym, since: prices.DividendWindow(answered=True, dividends=[{"date": EX_DATE, "dps": dps}]),
    )
    assert client.post("/api/transactions/catch-up").status_code == 200
    rows = [t for t in client.get("/api/transactions").json() if t["kind"] == "dividend"]
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize(
    "symbol, held_in, listed_in, dps, stamp",
    [
        # Milan, in euro, never priced: the holding's own currency stands in
        # for the listing's, the rule a position is valued by.
        ("VWRL.MI", "EUR", None, 0.5,
         "Auto-recorded from market data: a dividend of 0.5 EUR per share"),
        # London, quoted in pence, in a position typed in pounds: the figure is
        # in the listing's unit, and the stamp says which.
        ("VOD.L", "GBP", "GBp", 5.2,
         "Auto-recorded from market data: a dividend of 5.2 GBp per share"),
    ],
)
def test_an_auto_recorded_dividend_says_where_it_came_from_and_in_what_unit(
    client, monkeypatch, symbol, held_in, listed_in, dps, stamp
):
    row = _auto_recorded_dividend(
        client, monkeypatch, symbol=symbol, held_in=held_in, listed_in=listed_in, dps=dps
    )
    assert row["note"] == stamp
    assert row["estimated"] is True


def test_a_correction_clears_the_estimate_and_leaves_the_stamp_true(client, monkeypatch):
    """The workflow the stamp exists for: the statement's net credit replaces
    the gross figure through the ledger form. The state moves, in `estimated`;
    the origin stays, and is still true."""
    row = _auto_recorded_dividend(
        client, monkeypatch, symbol="VWRL.MI", held_in="EUR", listed_in=None, dps=0.5
    )
    assert row["amount"] == 50.0

    answer = client.put(
        f"/api/transactions/{row['id']}",
        json={k: row[k] for k in LEDGER_FORM_KEYS} | {"amount": 43.75},
    )
    assert answer.status_code == 200, answer.text
    after = answer.json()
    assert after["amount"] == 43.75
    assert after["estimated"] is False
    assert after["note"] == "Auto-recorded from market data: a dividend of 0.5 EUR per share"
