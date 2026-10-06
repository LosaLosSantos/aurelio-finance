"""A payment on the 29th, 30th or 31st keeps its day (brief AE, 2026-10-05).

Something that repeats is stepped from its first date, start + k months, and
never from the date before it. `add_months` clamps a day to a short month,
and stepped from the date before, the clamped day stayed: a salary on the
30th was paid on 28 February and on the 28th of every month after it.

Two places step. The cash projection (`analytics._flow_sum_in_window`) stores
nothing. The PAC (`pac.plan_occurrences`) writes every buy with the date it
was stepped to, so its half carries a second promise: a plan whose buys were
written on the old dates is not bought again on the new ones, which is why
the catch-up asks "settled?" of the month.

Every expected date is written out here, never worked out by the code under
test."""

from __future__ import annotations

import datetime

from app import analytics, crud, dated, models, pac, prices
from app.database import SessionLocal

D = datetime.date
TODAY = D(2026, 10, 5)


# --- The projection ---------------------------------------------------------


def _paid_on(start: str, frequency: str, first: str, last: str) -> list[str]:
    """The days from `first` to `last` on which the projection adds a payment
    of a flow that started on `start`, asked one day at a time."""
    since = D.fromisoformat(start)
    day, stop = D.fromisoformat(first), D.fromisoformat(last)
    out = []
    while day <= stop:
        before = day - datetime.timedelta(days=1)
        if analytics._flow_sum_in_window(1.0, frequency, since, None, before, day):
            out.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return out


def test_a_monthly_payment_on_the_29th_30th_or_31st_keeps_its_day_after_february():
    assert _paid_on("2026-01-29", "monthly", "2026-02-01", "2026-04-30") == [
        "2026-02-28", "2026-03-29", "2026-04-29",
    ]
    assert _paid_on("2026-01-30", "monthly", "2026-02-01", "2026-04-30") == [
        "2026-02-28", "2026-03-30", "2026-04-30",
    ]
    assert _paid_on("2026-01-31", "monthly", "2026-02-01", "2026-05-31") == [
        "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31",
    ]


def test_in_a_leap_year_it_is_paid_on_the_29th_of_february_then_on_its_day():
    assert _paid_on("2028-01-29", "monthly", "2028-02-01", "2028-03-31") == ["2028-02-29", "2028-03-29"]
    assert _paid_on("2028-01-30", "monthly", "2028-02-01", "2028-03-31") == ["2028-02-29", "2028-03-30"]
    assert _paid_on("2028-01-31", "monthly", "2028-02-01", "2028-03-31") == ["2028-02-29", "2028-03-31"]


def test_a_payment_started_on_a_30th_is_on_the_30th_again_after_its_first_february():
    """A salary or a monthly payment started on a 30th, say 2026-03-30,
    crosses its first February in 2027. Stepped from the date before, it was
    paid on the 28th from then on."""
    assert _paid_on("2026-03-30", "monthly", "2027-01-01", "2027-04-30") == [
        "2027-01-30", "2027-02-28", "2027-03-30", "2027-04-30",
    ]


def test_the_other_frequencies_keep_their_day_too():
    assert _paid_on("2025-11-30", "quarterly", "2026-01-01", "2026-12-31") == [
        "2026-02-28", "2026-05-30", "2026-08-30", "2026-11-30",
    ]
    assert _paid_on("2025-08-31", "semiannual", "2026-01-01", "2027-12-31") == [
        "2026-02-28", "2026-08-31", "2027-02-28", "2027-08-31",
    ]
    assert _paid_on("2024-02-29", "annual", "2025-01-01", "2028-12-31") == [
        "2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29",
    ]


def test_a_day_up_to_the_28th_falls_where_it_always_did():
    """Never clamped, so stepping from the start moves nothing for it: the
    reader's PAC, on the 4th, is one of these."""
    assert _paid_on("2026-01-28", "monthly", "2026-01-01", "2026-12-31") == [
        f"2026-{m:02d}-28" for m in range(1, 13)
    ]
    assert _paid_on("2026-10-04", "monthly", "2026-10-01", "2027-03-31") == [
        "2026-10-04", "2026-11-04", "2026-12-04", "2027-01-04", "2027-02-04", "2027-03-04",
    ]


def test_the_cash_register_adds_a_salary_on_its_own_day(client):
    """The same rule where the reader sees it: an account's projected cash.
    Stepped from the date before, the March salary was already in it on the
    28th."""
    iid = client.post("/api/institutions", json={"name": "Current account", "type": "bank"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": "2025-12-31", "amount": 0, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/income-sources",
        json={
            "name": "Salary",
            "amount": 2000,
            "currency": "EUR",
            "frequency": "monthly",
            "institution_id": iid,
            "start_date": "2025-03-30",
        },
    )
    assert r.status_code == 201, r.text
    with SessionLocal() as db:

        def cash(on: str) -> float:
            return analytics.compute_cash_position(db, iid, as_of=D.fromisoformat(on))["projected"]

        assert cash("2026-01-29") == 0
        assert cash("2026-01-30") == 2000
        assert cash("2026-02-27") == 2000
        assert cash("2026-02-28") == 4000
        assert cash("2026-03-29") == 4000
        assert cash("2026-03-30") == 6000


# --- The PAC: its dates -----------------------------------------------------


def _dates(start: str, up_to: str, frequency: str = "monthly", end: str | None = None) -> list[str]:
    plan = models.AccumulationPlan(start_date=start, frequency=frequency, end_date=end)
    return [d.isoformat() for d in pac.plan_occurrences(plan, D.fromisoformat(up_to))]


def test_a_plans_dates_keep_their_day_after_february():
    assert _dates("2026-01-29", "2026-04-30") == ["2026-01-29", "2026-02-28", "2026-03-29", "2026-04-29"]
    assert _dates("2026-01-30", "2026-04-30") == ["2026-01-30", "2026-02-28", "2026-03-30", "2026-04-30"]
    assert _dates("2026-01-31", "2026-05-31") == [
        "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31",
    ]
    assert _dates("2028-01-31", "2028-03-31") == ["2028-01-31", "2028-02-29", "2028-03-31"]
    assert _dates("2024-02-29", "2028-02-29", "annual") == [
        "2024-02-29", "2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29",
    ]
    # Still bounded by the plan's end.
    assert _dates("2026-01-31", "2026-12-31", end="2026-03-31") == ["2026-01-31", "2026-02-28", "2026-03-31"]


# --- The PAC: what is already written ---------------------------------------


def _old_stepping(plan: models.AccumulationPlan, up_to: D) -> list[D]:
    """How `pac.plan_occurrences` stepped until brief AE: from the date
    before. Used to write a plan's rows exactly as that code wrote them."""
    step = analytics.STEP_MONTHS.get(plan.frequency or "monthly", 1)
    out, occ = [], D.fromisoformat(plan.start_date)
    while occ <= up_to:
        out.append(occ)
        occ = analytics.add_months(occ, step)
    return out


def _account_and_plan(client, monkeypatch, start: str, amount: float = 100.0, close: float = 50.0) -> int:
    """An account with 10,000 of cash on 2026-01-01, and a monthly plan from
    it into one fund whose every close is `close`."""
    iid = client.post("/api/institutions", json={"name": "Broker", "type": "broker"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": "2026-01-01", "amount": 10000, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "Monthly plan",
            "amount": amount,
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": start,
            "source_institution_id": iid,
            "targets": [{"symbol": "VWCE.MI", "asset_name": "All-World", "institution_id": iid}],
        },
    )
    assert r.status_code == 201, r.text
    monkeypatch.setattr(
        prices, "get_price_on", lambda s, on: {"symbol": s, "price": close, "as_of": on.isoformat()}
    )
    monkeypatch.setattr(prices, "get_currencies", lambda symbols: {s: "EUR" for s in symbols})
    return iid


def _catch_up(monkeypatch, on: D) -> list[str]:
    """One catch-up as of `on`, with `on` as the app's today: the occurrence
    of each buy it wrote."""
    monkeypatch.setattr(dated, "today", lambda: on.isoformat())
    with SessionLocal() as db:
        return [t.plan_occurrence for t in pac.execute_due(db, as_of=on)["created"]]


def _records(iid: int) -> dict:
    """Everything a catch-up can change, as of TODAY."""
    with SessionLocal() as db:
        buys = [t for t in crud.get_transactions(db) if t.plan_id]
        plan = crud.get_accumulation_plans(db)[0]
        return {
            "buys": sorted(t.plan_occurrence for t in buys),
            "units": sum(t.quantity for t in buys),
            "cash": round(analytics.compute_cash_position(db, iid, as_of=TODAY)["projected"], 2),
            "unfilled": sorted(u.occurrence for u in plan.unfilled_occurrences),
            "carry": plan.carried_remainder,
        }


def _edit_start(client, start: str) -> None:
    plan = client.get("/api/accumulation-plans").json()[0]
    body = {
        k: plan[k]
        for k in ("name", "amount", "currency", "frequency", "execution", "source_institution_id", "end_date")
    }
    body["start_date"] = start
    body["targets"] = [
        {k: t[k] for k in ("symbol", "asset_name", "institution_id", "weight")} for t in plan["targets"]
    ]
    r = client.put(f"/api/accumulation-plans/{plan['id']}", json=body)
    assert r.status_code == 200, r.text


def test_a_plan_on_the_31st_buys_on_the_31st_or_the_last_day_of_a_shorter_month(client, monkeypatch):
    _account_and_plan(client, monkeypatch, "2026-01-31")
    assert _catch_up(monkeypatch, D(2026, 6, 5)) == [
        "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31",
    ]


def test_buys_written_on_the_old_dates_are_not_bought_again(client, monkeypatch):
    """The plan of the measurement: 9 buys written the old way, on the 28th
    from February on. Stepped from the start, the same months fall on the
    30th and the 31st; asked by date, 7 of them were bought again and the
    account was debited 700 twice."""
    iid = _account_and_plan(client, monkeypatch, "2026-01-31")
    with monkeypatch.context() as old:
        old.setattr(pac, "plan_occurrences", _old_stepping)
        assert _catch_up(old, TODAY) == [
            "2026-01-31", "2026-02-28", "2026-03-28", "2026-04-28", "2026-05-28",
            "2026-06-28", "2026-07-28", "2026-08-28", "2026-09-28",
        ]
    before = _records(iid)
    assert (before["units"], before["cash"]) == (18, 9100)

    assert _catch_up(monkeypatch, TODAY) == []
    assert _records(iid) == before
    # The months after it fall on the plan's own day, once each.
    assert _catch_up(monkeypatch, D(2026, 11, 5)) == ["2026-10-31"]
    assert _catch_up(monkeypatch, D(2026, 12, 5)) == ["2026-11-30"]
    assert _catch_up(monkeypatch, D(2026, 12, 5)) == []


def test_months_that_bought_nothing_on_the_old_dates_are_not_run_again(client, monkeypatch):
    """100 a month against a 150 unit: one month in three buys nothing and is
    recorded as such, its 100 carried. Asked by date after the change, the
    three were run again and four months bought a second time: 4 more units,
    600 more out of the account, a carry of 100 that was never given."""
    iid = _account_and_plan(client, monkeypatch, "2026-01-30", amount=100.0, close=150.0)
    with monkeypatch.context() as old:
        old.setattr(pac, "plan_occurrences", _old_stepping)
        _catch_up(old, TODAY)
    before = _records(iid)
    assert before["unfilled"] == ["2026-01-30", "2026-04-28", "2026-07-28"]
    assert (before["units"], before["cash"], before["carry"]) == (6, 9100, 0)

    assert _catch_up(monkeypatch, TODAY) == []
    assert _records(iid) == before


def test_an_edited_start_day_does_not_buy_the_elapsed_months_again(client, monkeypatch):
    """Found by brief AE: asked by date, a running plan moved from the 15th
    to the 20th bought all 9 elapsed months again on the 20th. A plan buys
    once a month, and the month is already settled."""
    iid = _account_and_plan(client, monkeypatch, "2026-01-15")
    assert len(_catch_up(monkeypatch, TODAY)) == 9
    before = _records(iid)

    _edit_start(client, "2026-01-20")
    assert _catch_up(monkeypatch, TODAY) == []
    assert _records(iid) == before
    assert _catch_up(monkeypatch, D(2026, 11, 5)) == ["2026-10-20"]


def test_a_start_moved_earlier_still_writes_the_months_it_adds(client, monkeypatch):
    """The month rule settles what was settled, and nothing else: an earlier
    start is a request for the months before, and they are written."""
    _account_and_plan(client, monkeypatch, "2026-06-15")
    assert _catch_up(monkeypatch, TODAY) == ["2026-06-15", "2026-07-15", "2026-08-15", "2026-09-15"]

    _edit_start(client, "2026-03-15")
    assert _catch_up(monkeypatch, TODAY) == ["2026-03-15", "2026-04-15", "2026-05-15"]


def test_the_check_under_the_write_lock_asks_the_month(client, monkeypatch):
    """`_settle` asks again, holding the lock, whether the occurrence is
    settled, and must ask it as the catch-up did. A month settled on the 28th
    settles the 31st, so nothing is written for it; a month with nothing in
    it is written, so the check is not simply refusing everything."""
    _account_and_plan(client, monkeypatch, "2026-01-31")
    with SessionLocal() as db:
        plan = crud.get_accumulation_plans(db)[0]
        crud.record_unfilled_occurrence(db, plan.id, "2026-03-28", "written the old way")

        def settle(occurrence: str):
            return pac._settle(
                db, plan, occurrence,
                worked_from=plan.carried_remainder, carry=None, columns=[], unfilled="bought nothing",
            )

        assert settle("2026-03-31") is None
        assert settle("2026-04-30") == []
        assert crud.get_plan_occurrences_settled(db, plan.id) == {"2026-03-28", "2026-04-30"}
