"""Units need a price, a value or a cost, at the API as on the form.

Brief AV's P0, 2026-10-14: units photographed with no value and no cost count
at zero. The situation form never sends such a row (units go with a price, a
total with its value), but the API took it: measured at `c61e5bc` (brief BE),
10 units with no price, value or cost answered 201, and after a buy of 5 at
100 the projection read a book of 500.00 for 15 units, an average of 33.33,
the cost known. Now the holdings' write rule refuses them in words, on the
row as the request leaves it. Units with a cost and no price stay: what was
paid is then their one observation. Every name is invented.
"""

from __future__ import annotations

import pytest

REFUSED = (
    "Units need a price, a value or a cost: type the price per unit, what the whole position "
    "is worth, or what it cost."
)


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


@pytest.fixture()
def situation(client) -> int:
    bank = _made(client.post("/api/institutions", json={"name": "Banca Gamma"}))["id"]
    return _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": "2026-01-02"}))["id"]


def _row(**fields) -> dict:
    return {"asset_name": "Fondo Gamma", "asset_class": "fund_etf", "symbol": "ZZGAM.MI",
            "currency": "EUR", **fields}


def test_units_with_neither_a_price_nor_a_value_are_refused_in_words(client, situation):
    r = client.post(f"/api/snapshots/{situation}/holdings", json=_row(quantity=10))

    assert r.status_code == 422
    assert r.json()["detail"] == REFUSED
    assert client.get(f"/api/snapshots/{situation}/holdings").json() == []


def test_an_edit_that_leaves_units_with_neither_is_refused(client, situation):
    row = _made(client.post(f"/api/snapshots/{situation}/holdings", json=_row(quantity=10, unit_price=100)))

    r = client.put(f"/api/holdings/{row['id']}", json=_row(quantity=10, unit_price=None, value=None))

    assert r.status_code == 422
    assert r.json()["detail"] == REFUSED
    stored = client.get(f"/api/holdings/{row['id']}").json()
    assert (stored["quantity"], stored["unit_price"], stored["value"]) == (10.0, 100.0, 1000.0)


@pytest.mark.parametrize(
    "fields",
    [
        {"quantity": 10, "unit_price": 100},
        {"quantity": 10, "value": 1000},
        {"quantity": 10, "cost_basis": 400},
        {"value": 1000},
    ],
    ids=["units and a price", "units and a value", "units and a cost", "a total"],
)
def test_every_other_shape_is_kept(client, situation, fields):
    assert client.post(f"/api/snapshots/{situation}/holdings", json=_row(**fields)).status_code == 201
