"""Two ways of telling the truth about what the app knows.

P0f — the advisor is the one consumer that REASONS about the figures, and was
the one never told which of them the app distrusts.
P0d — "stale" flattens two different ageings into one word.
"""

from __future__ import annotations

import datetime

from app import advisor, analytics

TODAY = datetime.date.today()
LONG_AGO = (TODAY - datetime.timedelta(days=200)).isoformat()


def _position(client, **extra) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LONG_AGO}
    ).json()["id"]
    payload = {"currency": "EUR", 
        "asset_name": "Vanguard All-World", "asset_class": "fund_etf",
        "symbol": "VWCE.MI", "quantity": 10, "unit_price": 150, **extra,
    }
    assert client.post(f"/api/snapshots/{sid}/holdings", json=payload).status_code == 201
    return iid


# --- P0f: the advisor must see the caveats the screen shows -----------------


def test_the_advisor_is_told_when_a_cost_is_not_a_cost(client):
    """It used to print 'avg cost 150.00' as a bare fact on a row the table
    itself labels 'cost unknown'."""
    _position(client)
    text = advisor.build_context(_db(client))
    assert "avg cost" in text
    assert "COST UNKNOWN" in text, "the model was left to read a snapshot price as a cost"


def test_a_recorded_cost_carries_no_warning(client):
    _position(client, cost_basis=900)
    text = advisor.build_context(_db(client))
    assert "COST UNKNOWN" not in text
    assert "ESTIMATED" not in text


def test_a_derived_cost_is_flagged_as_derived(client):
    _position(client, cost_basis=900, cost_estimated=True)
    assert "cost ESTIMATED" in advisor.build_context(_db(client))


def _db(client):
    from app.database import SessionLocal

    return SessionLocal()


# --- P0d: two ageings, not one ---------------------------------------------


def test_a_position_carries_the_date_it_was_last_confirmed(client):
    _position(client)
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["observed_on"] == LONG_AGO
    assert row["quantity_age_days"] == 200


def test_a_fresh_position_is_not_flagged(client):
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY.isoformat()}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Coca-Cola", "asset_class": "equity", "symbol": "KO",
              "quantity": 2, "unit_price": 90, "currency": "EUR"},
    )
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["quantity_age_days"] == 0


def test_a_ledger_born_position_is_dated_by_its_last_entry(client):
    """It sits in no photograph, so what confirms it is the transaction."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    when = (TODAY - datetime.timedelta(days=5)).isoformat()
    client.post(
        "/api/transactions",
        json={"date": when, "institution_id": iid, "asset_name": "iShares World",
              "symbol": "SWDA.MI", "quantity": 4, "unit_price": 90, "currency": "EUR", "price_currency": "EUR"},
    )
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["observed_on"] == when and row["quantity_age_days"] == 5


def test_days_since_handles_nothing_to_count_from():
    assert analytics._days_since(None) is None
    assert analytics._days_since("not-a-date") is None
    assert analytics._days_since(TODAY.isoformat(), TODAY) == 0
