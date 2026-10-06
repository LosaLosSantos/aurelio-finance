"""Listing endpoints must cost the same number of queries whatever the row count.

`InstitutionRead.latest_snapshot` and `LiabilityRead.latest_balance` are model
properties over a collection: convenient, and N+1 by construction the moment
the collection is loaded lazily. The properties are KEPT — they are fields of
the public API the frontend reads — and the N+1 is gone because `crud` eager-
loads what they walk.

Nothing about that arrangement is self-enforcing. Deleting a `selectinload`
leaves every test green, every number right, and the query count growing with
the portfolio: the kind of regression nobody sees until the list is long and
the page is slow. So the guard counts.
"""

from __future__ import annotations

import contextlib

from sqlalchemy import event

from app.database import engine


@contextlib.contextmanager
def _counting_queries():
    """Count the statements the app actually sends while the block runs."""
    seen: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _institution_with_two_photographs(client, name: str) -> int:
    iid = client.post("/api/institutions", json={"name": name}).json()["id"]
    for date in ("2026-01-01", "2026-02-01"):
        client.post(f"/api/institutions/{iid}/snapshots", json={"date": date})
    return iid


def _liability_with_two_balances(client, name: str) -> int:
    lid = client.post(
        "/api/liabilities", json={"name": name, "kind": "mortgage", "currency": "EUR"}
    ).json()["id"]
    for date, amount in (("2026-01-01", 200_000), ("2026-02-01", 197_000)):
        client.post(
            f"/api/liabilities/{lid}/balances", json={"date": date, "balance": amount}
        )
    return lid


def test_listing_institutions_does_not_query_once_per_institution(client):
    _institution_with_two_photographs(client, "Broker A")
    with _counting_queries() as one:
        assert client.get("/api/institutions").status_code == 200

    for n in range(2, 7):
        _institution_with_two_photographs(client, f"Bank {n}")
    with _counting_queries() as six:
        assert len(client.get("/api/institutions").json()) == 6

    assert len(six) == len(one), (
        "six institutions cost more queries than one: the snapshots are being "
        f"loaded lazily again ({len(one)} -> {len(six)} statements)"
    )


def test_listing_liabilities_does_not_query_once_per_liability(client):
    _liability_with_two_balances(client, "Mutuo")
    with _counting_queries() as one:
        assert client.get("/api/liabilities").status_code == 200

    for n in range(2, 7):
        _liability_with_two_balances(client, f"Prestito {n}")
    with _counting_queries() as six:
        assert len(client.get("/api/liabilities").json()) == 6

    assert len(six) == len(one), (
        "six liabilities cost more queries than one: the balances are being "
        f"loaded lazily again ({len(one)} -> {len(six)} statements)"
    )
def test_listing_situations_does_not_query_once_per_situation(client):
    """The value of a situation is a sum over its holdings, and the list has to
    cost the same whether an account has one photograph or six."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]

    def _situation(date: str) -> None:
        sid = client.post(
            f"/api/institutions/{iid}/snapshots", json={"date": date}
        ).json()["id"]
        client.post(
            f"/api/snapshots/{sid}/holdings",
            json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
                  "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
        )

    _situation("2026-01-01")
    with _counting_queries() as one:
        assert len(client.get(f"/api/institutions/{iid}/snapshots").json()) == 1

    for month in range(2, 7):
        _situation(f"2026-0{month}-01")
    with _counting_queries() as six:
        assert len(client.get(f"/api/institutions/{iid}/snapshots").json()) == 6

    assert len(six) == len(one), (
        "six situations cost more queries than one: the holdings are being "
        f"loaded lazily again ({len(one)} -> {len(six)} statements)"
    )
