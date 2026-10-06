"""The live cash register: anchors + projection from flows and transfers.

projected = anchor + income − expenses + transfers_in − transfers_out,
counting only events strictly AFTER the anchor date, up to as_of.
"""

from __future__ import annotations

import datetime

TODAY = datetime.date.today()
ANCHOR_DAY = (TODAY - datetime.timedelta(days=60)).isoformat()
YESTERDAY = (TODAY - datetime.timedelta(days=1)).isoformat()


def _institution(client, name="Broker A") -> int:
    return client.post("/api/institutions", json={"name": name, "type": "bank"}).json()["id"]


def _anchor(client, iid: int, amount: float, date: str = ANCHOR_DAY) -> None:
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": date, "amount": amount, "currency": "EUR"}
    )
    assert r.status_code == 201, r.text


def test_no_anchor_means_zero_projection(client):
    iid = _institution(client)
    pos = client.get(f"/api/institutions/{iid}/cash").json()
    assert pos["anchor_date"] is None and pos["projected"] == 0


def test_anchor_unique_date_per_institution(client):
    iid = _institution(client)
    _anchor(client, iid, 1000)
    dup = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": ANCHOR_DAY, "amount": 1, "currency": "EUR"},
    )
    assert dup.status_code == 409


def test_projection_includes_linked_flows_after_anchor(client):
    iid = _institution(client)
    _anchor(client, iid, 10_000)
    client.post(
        "/api/income-sources",
        json={
            "name": "Salary",
            "amount": 2000,
            "frequency": "monthly",
            "institution_id": iid,
            "start_date": ANCHOR_DAY,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/expenses",
        json={
            "name": "Rent",
            "amount": 800,
            "frequency": "monthly",
            "institution_id": iid,
            "start_date": ANCHOR_DAY,
            "currency": "EUR",
        },
    )

    pos = client.get(f"/api/institutions/{iid}/cash").json()
    # the occurrence ON the anchor date is excluded (already in the balance);
    # 60 days later at least one more monthly occurrence has happened.
    assert pos["income"] >= 2000 and pos["income"] % 2000 == 0
    assert pos["expenses"] >= 800 and pos["expenses"] % 800 == 0
    assert pos["projected"] == 10_000 + pos["income"] - pos["expenses"]


def test_unlinked_flows_do_not_touch_cash(client):
    iid = _institution(client)
    _anchor(client, iid, 5000)
    client.post(
        "/api/income-sources",
        json={"name": "Salary", "amount": 2000, "frequency": "monthly", "start_date": ANCHOR_DAY, "currency": "EUR"},
    )  # no institution_id
    pos = client.get(f"/api/institutions/{iid}/cash").json()
    assert pos["income"] == 0 and pos["projected"] == 5000


def test_transfer_moves_cash_between_institutions(client):
    a = _institution(client, "Broker A")
    b = _institution(client, "Broker B")
    _anchor(client, a, 1000)
    _anchor(client, b, 0)
    client.post(
        "/api/transfers",
        json={"date": YESTERDAY, "from_institution_id": a, "to_institution_id": b, "amount": 300,
              "currency": "EUR", "to_currency": "EUR"},
    )

    pos_a = client.get(f"/api/institutions/{a}/cash").json()
    pos_b = client.get(f"/api/institutions/{b}/cash").json()
    assert pos_a["transfers_out"] == 300 and pos_a["projected"] == 700
    assert pos_b["transfers_in"] == 300 and pos_b["projected"] == 300


def test_new_anchor_rebases_the_projection(client):
    iid = _institution(client)
    _anchor(client, iid, 10_000)
    client.post(
        "/api/income-sources",
        json={
            "name": "Salary",
            "amount": 2000,
            "frequency": "monthly",
            "institution_id": iid,
            "start_date": ANCHOR_DAY,
            "currency": "EUR",
        },
    )
    # reconcile today with the actual balance: projection restarts from it
    _anchor(client, iid, 4321, date=TODAY.isoformat())
    pos = client.get(f"/api/institutions/{iid}/cash").json()
    assert pos["anchor_amount"] == 4321 and pos["projected"] == 4321


def test_one_off_counts_once_inside_window(client):
    iid = _institution(client)
    _anchor(client, iid, 1000)
    client.post(
        "/api/expenses",
        json={
            "name": "New laptop",
            "amount": 1500,
            "frequency": "one_off",
            "institution_id": iid,
            "start_date": YESTERDAY,
            "currency": "EUR",
        },
    )
    pos = client.get(f"/api/institutions/{iid}/cash").json()
    assert pos["expenses"] == 1500 and pos["projected"] == -500


def test_semiannual_frequency_run_rate_and_projection(client):
    """A semiannual expense (e.g. car insurance) counts amount/6 per month in
    the cash-flow run-rate, and occurs every 6 months in the cash projection."""
    iid = _institution(client)
    _anchor(client, iid, 1000, date="2025-01-01")
    client.post(
        "/api/expenses",
        json={
            "name": "Car insurance",
            "amount": 300,
            "frequency": "semiannual",
            "institution_id": iid,
            "start_date": "2025-01-15",
            "currency": "EUR",
        },
    )

    # Run-rate: 300 every 6 months -> 50/month.
    cf = client.get("/api/dashboard/cashflow").json()
    assert cf["monthly_expenses"] == 50.0

    # Projection to just after one year: occurrences on Jan 15 2025, Jul 15
    # 2025 and Jan 15 2026 -> 3 x 300 after the anchor.
    pos = client.get(f"/api/institutions/{iid}/cash", params={"as_of": "2026-01-31"}).json()
    assert pos["expenses"] == 900 and pos["projected"] == 100


def test_the_series_fast_path_agrees_with_the_register_date_by_date(client, monkeypatch):
    """The register is the reference implementation and stays one.

    `_cash_totals_by_date` exists only because asking `compute_cash_position`
    for every institution at every sample date was the quadratic in the net
    worth series — 4 institutions x 130 dates, each re-SELECTing every transfer
    and every transaction. It is the same arithmetic read from tables loaded
    once, so the way to trust it is not to read it: it is to run both and
    assert they agree, on a database that has one of everything the projection
    can be moved by.

    Including a CURRENCY that is not the base. Two copies of the arithmetic
    means two places that have to convert, and with every amount in euro a copy
    that forgot to would still agree with the other to the cent — so a third
    account is kept in dollars, with its own anchor, income, expense and a
    transfer out to a euro account."""
    from app import analytics, fx
    from app.database import SessionLocal

    # A different rate on every sampled day, so a copy that converted at
    # today's rate — or at any day but the one it is projecting — disagrees.
    offsets = (61, 60, 45, 30, 20, 15, 10, 1, 0)
    daily = {
        (TODAY - datetime.timedelta(days=n)).isoformat(): {"USD": 1.10 + n / 100}
        for n in offsets
    }
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: dict(daily))
    a = _institution(client, "Broker A")
    b = _institution(client, "Broker B")
    c = _institution(client, "Wise")
    r = client.post(
        f"/api/institutions/{c}/cash-anchors",
        json={"date": (TODAY - datetime.timedelta(days=45)).isoformat(), "amount": 5_000, "currency": "USD"},
    )
    assert r.status_code == 201, r.text
    for path, body in (
        ("/api/income-sources", {"name": "Invoices", "amount": 1_250}),
        ("/api/expenses", {"name": "Hosting", "amount": 125}),
    ):
        r = client.post(
            path,
            json={**body, "frequency": "monthly", "institution_id": c,
                  "start_date": ANCHOR_DAY, "currency": "USD"},
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/api/transfers",
        json={"date": (TODAY - datetime.timedelta(days=12)).isoformat(),
              "amount": 750, "from_institution_id": c, "to_institution_id": a, "currency": "USD",
              "to_currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    # Two sums: 750 dollars leave Wise and what reached Broker A was fixed in
    # euro on the day. A copy that credits the destination with the dollars
    # restated at each date's rate disagrees with the other at every point.
    assert (r.json()["to_amount"], r.json()["fx_as_of"]) == (600.0, (TODAY - datetime.timedelta(days=15)).isoformat())
    # And a purchase the dollar account pays in dollars: a ledger amount is in
    # its own currency too, and both copies have to convert it.
    r = client.post(
        "/api/transactions",
        json={"kind": "buy", "date": (TODAY - datetime.timedelta(days=5)).isoformat(),
              "institution_id": c, "asset_name": "Apple", "symbol": "AAPL",
              "asset_class": "equity", "quantity": 2, "unit_price": 150,
              "currency": "USD", "price_currency": "USD"},
    )
    assert r.status_code == 201, r.text
    _anchor(client, a, 10_000)
    _anchor(client, b, 2_000, date=(TODAY - datetime.timedelta(days=30)).isoformat())
    # A second anchor re-bases: the dates on either side must both stay right.
    _anchor(client, a, 12_000, date=(TODAY - datetime.timedelta(days=15)).isoformat())
    client.post(
        "/api/income-sources",
        json={"name": "Salary", "amount": 2_000, "frequency": "monthly",
              "institution_id": a, "start_date": ANCHOR_DAY, "currency": "EUR"},
    )
    client.post(
        "/api/expenses",
        json={"name": "Rent", "amount": 800, "frequency": "monthly",
              "institution_id": a, "start_date": ANCHOR_DAY, "currency": "EUR"},
    )
    client.post(
        "/api/transfers",
        json={"date": (TODAY - datetime.timedelta(days=20)).isoformat(),
              "amount": 500, "from_institution_id": a, "to_institution_id": b, "currency": "EUR",
              "to_currency": "EUR"},
    )
    client.post(
        "/api/transactions",
        json={"kind": "buy", "date": (TODAY - datetime.timedelta(days=10)).isoformat(),
              "institution_id": b, "asset_name": "Vanguard", "symbol": "VWCE.MI",
              "asset_class": "fund_etf", "quantity": 1, "unit_price": 100, "currency": "EUR", "price_currency": "EUR"},
    )

    dates = [
        (TODAY - datetime.timedelta(days=n)).isoformat()
        for n in (61, 60, 45, 30, 20, 15, 10, 1, 0)
    ]
    db = SessionLocal()
    try:
        fast = analytics._cash_totals_by_date(db, dates, [a, b, c])
        for d in dates:
            reference = sum(
                analytics.compute_cash_position(
                    db, iid, datetime.date.fromisoformat(d)
                )["projected"]
                for iid in (a, b, c)
            )
            assert abs(fast[d] - reference) < 1e-9, d
    finally:
        db.close()


def test_every_accounts_anchors_come_back_in_one_read(client):
    """What the ledger and transfer forms propose a currency from: the anchor
    of the picked account in force on the row's date. One request answers for
    every account, by institution then date."""
    a = _institution(client, "Broker A")
    b = _institution(client, "Wise")
    for iid, date, currency in (
        (b, "2026-06-01", "USD"),
        (a, "2026-03-01", "EUR"),
        (b, "2026-01-01", "EUR"),
    ):
        r = client.post(
            f"/api/institutions/{iid}/cash-anchors",
            json={"date": date, "amount": 1, "currency": currency},
        )
        assert r.status_code == 201, r.text

    got = [(x["institution_id"], x["date"], x["currency"]) for x in client.get("/api/cash-anchors").json()]

    assert got == [(a, "2026-03-01", "EUR"), (b, "2026-01-01", "EUR"), (b, "2026-06-01", "USD")]
