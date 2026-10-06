"""Accumulation plans (PAC): CRUD, institution links, advisor awareness.

A plan is declarative for now — it must NOT change the cash projection or net
worth (that would leak the contributed amount before the Buy execution exists).
"""

from __future__ import annotations

import datetime

TODAY = datetime.date.today().isoformat()


def _two_institutions(client) -> tuple[int, int]:
    a = client.post("/api/institutions", json={"name": "Broker A", "type": "bank"}).json()["id"]
    b = client.post("/api/institutions", json={"name": "Broker", "type": "broker"}).json()["id"]
    return a, b


def _plan_payload(src, tgt, **extra) -> dict:
    return {
        "name": "PAC All-World",
        "amount": 600,
        "currency": "EUR",
        "frequency": "monthly",
        "start_date": TODAY,
        "source_institution_id": src,
        "targets": [
            {
                "symbol": "VWCE.MI",
                "asset_name": "Vanguard FTSE All-World",
                "institution_id": tgt,
            }
        ],
        **extra,
    }


def test_create_list_and_dates_roundtrip(client):
    src, tgt = _two_institutions(client)
    r = client.post("/api/accumulation-plans", json=_plan_payload(src, tgt))
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["amount"] == 600 and plan["start_date"] == TODAY
    assert plan["source_institution_id"] == src
    assert plan["targets"][0]["institution_id"] == tgt
    assert client.get("/api/accumulation-plans").json()[0]["targets"][0]["symbol"] == "VWCE.MI"


def test_amount_must_be_positive(client):
    assert client.post("/api/accumulation-plans", json={"name": "Bad", "amount": 0}).status_code == 422


def test_linked_institution_must_exist(client):
    r = client.post(
        "/api/accumulation-plans",
        json={"name": "PAC", "amount": 100, "currency": "EUR", "source_institution_id": 999},
    )
    assert r.status_code == 404


def test_update_and_delete(client):
    src, tgt = _two_institutions(client)
    pid = client.post("/api/accumulation-plans", json=_plan_payload(src, tgt)).json()["id"]
    upd = client.put(
        f"/api/accumulation-plans/{pid}", json=_plan_payload(src, tgt, amount=800, frequency="quarterly")
    )
    assert upd.status_code == 200 and upd.json()["amount"] == 800 and upd.json()["frequency"] == "quarterly"
    assert client.delete(f"/api/accumulation-plans/{pid}").status_code == 204
    assert client.get(f"/api/accumulation-plans/{pid}").status_code == 404


def test_deleting_institution_sets_links_null(client):
    src, tgt = _two_institutions(client)
    pid = client.post("/api/accumulation-plans", json=_plan_payload(src, tgt)).json()["id"]
    assert client.delete(f"/api/institutions/{src}").status_code == 204
    after = client.get(f"/api/accumulation-plans/{pid}").json()
    assert after["source_institution_id"] is None  # SET NULL, plan survives
    assert after["amount"] == 600


def test_plan_does_not_touch_cash_or_net_worth(client):
    """A declared PAC must not move money: cash projection and net worth unchanged."""
    src, tgt = _two_institutions(client)
    # an anchor + a monthly salary so there IS a cash projection to perturb
    past = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
    client.post(f"/api/institutions/{src}/cash-anchors", json={"date": past, "amount": 10000, "currency": "EUR"})
    before_cash = client.get(f"/api/institutions/{src}/cash").json()["projected"]
    before_nw = client.get("/api/dashboard/summary").json()["net_worth"]

    client.post("/api/accumulation-plans", json=_plan_payload(src, tgt))

    assert client.get(f"/api/institutions/{src}/cash").json()["projected"] == before_cash
    assert client.get("/api/dashboard/summary").json()["net_worth"] == before_nw


def test_advisor_context_lists_active_plans(client):
    src, tgt = _two_institutions(client)
    client.post("/api/accumulation-plans", json=_plan_payload(src, tgt))
    from app.advisor import build_context
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        ctx = build_context(db)
    finally:
        db.close()
    assert "## PACs (recurring contributions)" in ctx
    assert "PAC All-World" in ctx and "Vanguard FTSE All-World" in ctx


# --- A plan has to name both ends -------------------------------------------
#
# `ca4858d` required an institution of a ledger entry a person posts, and ruled
# the PAC out of scope because its rows are correct. They are correct only when
# the plan has a SOURCE — that is what `pac.py` writes into
# `cash_institution_id` — and that field was optional too. With it blank and a
# target's institution blank, the same two-null defect was reachable through a
# second door, and this is that door being closed.


def _crud_plan(**overrides):
    """A plan written through the internal door, which stays loose.

    The API will not take these any more; `crud` still must, because the
    columns are nullable, nothing migrated, and a plan saved before the door
    closed has to stay executable-or-refusable on its own merits rather than
    unreadable."""
    from app import crud, schemas
    from app.database import SessionLocal

    payload = {
        "name": "PAC All-World",
        "amount": 100,
        "currency": "EUR",
        "frequency": "monthly",
        "start_date": datetime.date(2026, 1, 5),
        "source_institution_id": None,
        "targets": [
            schemas.PlanTargetCreate(
                symbol="VWCE.MI", asset_name="Vanguard All-World", institution_id=None
            )
        ],
        **overrides,
    }
    with SessionLocal() as db:
        plan = crud.create_accumulation_plan(db, schemas.AccumulationPlanCreate(**payload))
        return plan.id


def test_a_plan_that_names_neither_end_is_refused(client):
    """Both selects blank is the two-null condition, reached through the PAC.

    `pac.py` writes `cash_institution_id=plan.source_institution_id`. With no
    source that column is null, and with no target institution the other one is
    too — so the cash register, which keeps the entries belonging to the
    institution it is computing, finds that null matches no id there is and
    skips the cash side everywhere, while the position side counts in full.
    Measured on a scratch database at the commit before this one: 1000.00 of
    cash, two elapsed occurrences of 100.00 each, net worth 1000.00 -> 1200.00,
    cash untouched at 1000.00 — the plan's spending added itself to the total.

    Each half is refused on its own, because each is half of one sentence:
    money moves FROM an account INTO a holding."""
    src, tgt = _two_institutions(client)

    def refused(payload) -> list[list]:
        r = client.post("/api/accumulation-plans", json=payload)
        assert r.status_code == 422, r.text
        return [d["loc"] for d in r.json()["detail"]]

    # Asserted on the field paths, not on a substring: "institution_id" is
    # inside "source_institution_id", so the loose version of this test passes
    # when only one of the two halves is refused.
    assert refused(_plan_payload(None, None)) == [
        ["body", "source_institution_id"],
        ["body", "targets", 0, "institution_id"],
    ]
    assert refused(_plan_payload(None, tgt)) == [["body", "source_institution_id"]]
    assert refused(_plan_payload(src, None)) == [
        ["body", "targets", 0, "institution_id"]
    ]

    # Nothing was stored by any of the three, and the same requirement guards
    # the PUT — which is the door a plan saved without them is repaired
    # through, so it cannot be the one that puts them back.
    assert client.get("/api/accumulation-plans").json() == []
    pid = client.post("/api/accumulation-plans", json=_plan_payload(src, tgt)).json()["id"]
    assert (
        client.put(f"/api/accumulation-plans/{pid}", json=_plan_payload(None, tgt)).status_code
        == 422
    )
    assert client.get(f"/api/accumulation-plans/{pid}").json()["source_institution_id"] == src


def test_a_plan_saved_without_a_source_stays_readable_and_does_not_run(client, monkeypatch):
    """What the reader with an old plan sees. Today there is no such reader —
    the database has no plans at all — so this is the whole specification of a
    case that exists only in the schema's memory.

    Readable: the GET returns it unchanged, because refusing to SHOW a row is
    how a person loses the ability to fix it. Not executed: the catch-up
    reports it in `skipped` with the reason, next to the priced failures, and
    records nothing — so the occurrences stay due and run in full the moment a
    source is named. An unnamed source is a question, not a verdict on the
    schedule."""
    from app import pac, prices
    from app.database import SessionLocal

    src, _ = _two_institutions(client)
    client.post(f"/api/institutions/{src}/cash-anchors", json={"date": "2025-12-31", "amount": 1000, "currency": "EUR"})
    pid = _crud_plan()
    monkeypatch.setattr(
        prices,
        "get_price_on",
        lambda symbol, on: {"symbol": symbol, "price": 50.0, "as_of": on.isoformat()},
    )
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")  # a euro fund

    shown = client.get(f"/api/accumulation-plans/{pid}").json()
    assert shown["source_institution_id"] is None and shown["name"] == "PAC All-World"

    before = client.get("/api/dashboard/summary").json()
    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=datetime.date(2026, 2, 10))
    assert out["created"] == []
    assert len(out["skipped"]) == 1
    assert "does not say which account funds it" in out["skipped"][0]["reason"]
    after = client.get("/api/dashboard/summary").json()
    assert after["net_worth"] == before["net_worth"] == 1000.0
    assert after["cash_total"] == 1000.0

    # Nothing was recorded against those occurrences, so naming the source runs
    # them — the two that had elapsed, not one.
    client.put(f"/api/accumulation-plans/{pid}", json=_plan_payload(src, src, amount=100,
                                                                   start_date="2026-01-05"))
    with SessionLocal() as db:
        out = pac.execute_due(db, as_of=datetime.date(2026, 2, 10))
    assert len(out["created"]) == 2
    assert client.get("/api/dashboard/summary").json()["cash_total"] == 1000.0 - 200.0
