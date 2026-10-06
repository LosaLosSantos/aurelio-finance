"""Institutions, investment snapshots and holdings (hybrid value rule)."""

from __future__ import annotations

import datetime

TODAY = datetime.date.today().isoformat()


def _institution(client, name="Broker A") -> int:
    return client.post("/api/institutions", json={"name": name, "type": "bank"}).json()["id"]


def _snapshot(client, institution_id: int, date: str = TODAY) -> int:
    r = client.post(
        f"/api/institutions/{institution_id}/snapshots",
        json={"date": date},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_institution_crud_roundtrip(client):
    iid = _institution(client)
    assert client.get("/api/institutions").json()[0]["name"] == "Broker A"

    upd = client.put(f"/api/institutions/{iid}", json={"name": "Bank A", "type": "bank"})
    assert upd.status_code == 200 and upd.json()["name"] == "Bank A"

    assert client.delete(f"/api/institutions/{iid}").status_code == 204
    assert client.get(f"/api/institutions/{iid}").status_code == 404


def test_snapshot_unique_date_per_institution(client):
    iid = _institution(client)
    _snapshot(client, iid)
    dup = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    )
    assert dup.status_code == 409


def test_snapshot_for_missing_institution_is_404(client):
    r = client.post("/api/institutions/999/snapshots", json={"date": TODAY})
    assert r.status_code == 404


def test_holding_value_hybrid_rule(client):
    """value wins if given; otherwise it is computed as quantity * unit_price."""
    sid = _snapshot(client, _institution(client))

    by_total = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Bond fund", "asset_class": "bond", "value": 2000, "currency": "EUR"},
    ).json()
    assert by_total["value"] == 2000

    by_qty = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "iShares World",
            "asset_class": "equity",
            "quantity": 100,
            "unit_price": 98.5,
            "currency": "EUR",
        },
    ).json()
    assert by_qty["value"] == 100 * 98.5

    # Both rows were typed with no currency, which means EUR, so the
    # situation's EUR value is the plain sum of what was typed.
    assert client.get(f"/api/snapshots/{sid}").json()["value_base"] == 2000 + 9850


def test_deleting_institution_cascades_to_snapshots_and_holdings(client):
    iid = _institution(client)
    sid = _snapshot(client, iid)
    hid = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "ETF", "asset_class": "equity", "value": 100, "currency": "EUR"},
    ).json()["id"]

    assert client.delete(f"/api/institutions/{iid}").status_code == 204
    assert client.get(f"/api/snapshots/{sid}").status_code == 404
    assert client.get(f"/api/holdings/{hid}").status_code == 404
