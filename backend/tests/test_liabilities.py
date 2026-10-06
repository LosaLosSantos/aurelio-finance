"""Liabilities (debts): dated balances, net worth subtraction, asset links."""

from __future__ import annotations

import datetime

TODAY = datetime.date.today()
M6 = (TODAY - datetime.timedelta(days=180)).isoformat()
M1 = (TODAY - datetime.timedelta(days=30)).isoformat()


def _house(client) -> int:
    rid = client.post(
        "/api/real-assets", json={"name": "Milan flat", "category": "real_estate", "currency": "EUR"}
    ).json()["id"]
    client.post(f"/api/real-assets/{rid}/valuations", json={"date": M6, "value": 300_000})
    return rid


def _mortgage(client, house_id: int | None = None) -> int:
    r = client.post(
        "/api/liabilities",
        json={
            "name": "Home mortgage",
            "kind": "mortgage",
            "interest_rate": 3.2,
            "real_asset_id": house_id,
            "currency": "EUR",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_linking_to_missing_asset_is_404(client):
    r = client.post("/api/liabilities", json={"name": "Bad", "real_asset_id": 999, "currency": "EUR"})
    assert r.status_code == 404


def test_balance_unique_date_and_latest_balance(client):
    lid = _mortgage(client)
    assert client.get(f"/api/liabilities/{lid}").json()["latest_balance"] is None

    assert (
        client.post(f"/api/liabilities/{lid}/balances", json={"date": M6, "balance": 200_000})
    ).status_code == 201
    assert (
        client.post(f"/api/liabilities/{lid}/balances", json={"date": M1, "balance": 197_000})
    ).status_code == 201
    dup = client.post(f"/api/liabilities/{lid}/balances", json={"date": M1, "balance": 1})
    assert dup.status_code == 409

    assert client.get(f"/api/liabilities/{lid}").json()["latest_balance"] == 197_000


def test_net_worth_subtracts_latest_debt_balances(client):
    house = _house(client)
    lid = _mortgage(client, house)
    client.post(f"/api/liabilities/{lid}/balances", json={"date": M6, "balance": 200_000})
    client.post(f"/api/liabilities/{lid}/balances", json={"date": M1, "balance": 197_000})

    summary = client.get("/api/dashboard/summary").json()
    assert summary["real_total"] == 300_000
    assert summary["liabilities_total"] == 197_000
    assert summary["net_worth"] == 300_000 - 197_000

    series = client.get("/api/dashboard/net-worth-series").json()
    first, last = series[0], series[-1]
    assert first["liabilities"] == 200_000 and first["net_worth"] == 100_000
    assert last["liabilities"] == 197_000 and last["net_worth"] == 103_000


def test_deleting_asset_keeps_debt_unlinked(client):
    house = _house(client)
    lid = _mortgage(client, house)
    client.post(f"/api/liabilities/{lid}/balances", json={"date": M1, "balance": 197_000})

    assert client.delete(f"/api/real-assets/{house}").status_code == 204
    after = client.get(f"/api/liabilities/{lid}").json()
    assert after["real_asset_id"] is None
    assert after["latest_balance"] == 197_000


def test_deleting_liability_cascades_balances_and_updates_summary(client):
    lid = _mortgage(client)
    client.post(f"/api/liabilities/{lid}/balances", json={"date": M1, "balance": 5000})
    assert client.get("/api/dashboard/summary").json()["liabilities_total"] == 5000

    assert client.delete(f"/api/liabilities/{lid}").status_code == 204
    assert client.get("/api/dashboard/summary").json()["liabilities_total"] == 0
