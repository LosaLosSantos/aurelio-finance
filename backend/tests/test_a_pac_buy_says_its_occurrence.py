"""A PAC's buys say which occurrence they are, and the plan says how it spends.

The reader's second test round of the chat (2026-10-08): the picture said the
plan's last execution was a Sunday and listed buys dated the Monday after,
with nothing tying the two (a weekend occurrence is bought at the next
session's close, brief AJ), and the chat offered to delete "one of the two"
as a duplicate. It also expected each fund at its weight's share of the
amount, where one budget spent in whole units gave other figures. Brief AL:
a buy that settles an occurrence carries it on its ledger line, and the
plan's line says it spends one budget in whole units, with what it carries.

Yahoo is faked at `prices._fetch_close_window`, as in
`test_a_weekend_is_not_a_missing_close.py`. Symbols, names and amounts are
invented.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from app import advisor, dated, models, prices
from app.database import SessionLocal

SUN, MON, TUE = (datetime.date(2026, 10, d) for d in (4, 5, 6))

# Two exchange listings, sessions Monday to Friday.
CLOSES = {
    "XGLO.MI": {"2026-09-28": 85.0, "2026-10-01": 85.5, "2026-10-02": 85.8, "2026-10-05": 86.45},
    "XBND.MI": {"2026-09-28": 52.0, "2026-10-01": 52.4, "2026-10-02": 52.8, "2026-10-05": 53.29},
}


@pytest.fixture()
def market(monkeypatch):
    def fetch(symbol, start, end):
        return sorted(
            (day, close)
            for day, close in CLOSES[symbol].items()
            if start.isoformat() <= day < end.isoformat()
        )

    monkeypatch.setattr(prices, "_fetch_close_window", fetch)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    monkeypatch.setattr(dated, "today", lambda: TUE.isoformat())


def _broker(client) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A", "type": "broker"}).json()["id"]
    assert client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": "2026-09-01", "amount": 5000.0, "currency": "EUR"},
    ).status_code == 201
    return iid


def _plan(client, iid: int, *, amount: float, targets: list[tuple[str, float]], execution="whole_units") -> int:
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "Example plan",
            "amount": amount,
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": SUN.isoformat(),
            "source_institution_id": iid,
            "execution": execution,
            "targets": [
                {"symbol": symbol, "asset_name": symbol, "institution_id": iid, "weight": weight}
                for symbol, weight in targets
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _picture_after_the_catch_up(client) -> str:
    assert client.post("/api/transactions/catch-up").status_code == 200
    with SessionLocal() as db:
        return advisor.build_context(db)


def _plan_line(picture: str) -> str:
    (line,) = [line for line in picture.split("\n") if line.startswith("- Example plan:")]
    return line


def test_a_buy_from_a_sunday_occurrence_says_which_occurrence_it_settles(client, market):
    """The reader's case: both funds bought on Monday for Sunday's occurrence,
    and each ledger line says so."""
    iid = _broker(client)
    _plan(client, iid, amount=400, targets=[("XGLO.MI", 70), ("XBND.MI", 30)])

    picture = _picture_after_the_catch_up(client)

    with SessionLocal() as db:
        buys = list(db.scalars(select(models.Transaction).order_by(models.Transaction.id)))
    assert {(t.date, t.plan_occurrence) for t in buys} == {("2026-10-05", "2026-10-04")}
    assert len(buys) == 2
    for t in buys:
        assert (
            f"- 2026-10-05 buy {t.quantity:g} x {t.symbol} @ {t.unit_price:.2f} EUR = "
            f"{t.amount:.2f} EUR (estimated), made by the PAC \"Example plan\" for its "
            "occurrence of 2026-10-04, bought 2026-10-05"
        ) in picture, picture


def test_the_plan_says_it_spends_one_budget_in_whole_units_and_what_it_carries(client, market):
    """70% and 30% of 400 are not what the funds got: one budget is spent a
    whole unit at a time (`pac.allocate`), and what no unit fits waits."""
    iid = _broker(client)
    plan_id = _plan(client, iid, amount=400, targets=[("XGLO.MI", 70), ("XBND.MI", 30)])

    picture = _picture_after_the_catch_up(client)

    with SessionLocal() as db:
        spent = sum(t.amount for t in db.scalars(select(models.Transaction)))
        carried = db.get(models.AccumulationPlan, plan_id).carried_remainder
    assert carried == round(400 - spent, 2) and carried > 0

    line = _plan_line(picture)
    assert (
        "Each occurrence spends 400.00 EUR and what the one before left as ONE budget, "
        "in whole units across its funds: a fund's figure follows the prices, not its "
        "weight exactly, and what no whole unit fits waits for the next occurrence "
        f"(carried now: {carried:.2f} EUR)."
    ) in line, line
    assert (
        "1 occurrence executed; the last is that of 2026-10-04, bought 2026-10-05. "
        "Its buys are the ledger entries made by this PAC: each occurrence's own "
        "execution, never a second purchase of the same thing."
    ) in line, line
    assert chr(0x2014) not in line and chr(0x2013) not in line


def test_a_plan_of_one_fund_buys_whole_units_and_carries_the_rest(client, market):
    iid = _broker(client)
    _plan(client, iid, amount=300, targets=[("XGLO.MI", 1)])

    line = _plan_line(_picture_after_the_catch_up(client))

    # 3 units at 86.45 = 259.35, so 40.65 waits.
    assert (
        "Each occurrence buys whole units only, as many as 300.00 EUR and what the one "
        "before left can pay for; what no whole unit fits waits for the next occurrence "
        "(carried now: 40.65 EUR)."
    ) in line, line


def test_a_fractional_plan_says_it_invests_exactly_its_amount(client, market):
    iid = _broker(client)
    _plan(client, iid, amount=300, targets=[("XGLO.MI", 1)], execution="fractional")

    line = _plan_line(_picture_after_the_catch_up(client))

    assert "Each occurrence invests exactly 300.00 EUR, in fractional units, split by the weights." in line
    assert "carried" not in line


def test_an_occurrence_that_bought_nothing_is_said_with_its_money_carried(client, market):
    """50 cannot buy one unit at 86.45: the occurrence ran, recorded itself as
    unfilled, and put its money in the carry."""
    iid = _broker(client)
    _plan(client, iid, amount=50, targets=[("XGLO.MI", 1)])

    line = _plan_line(_picture_after_the_catch_up(client))

    assert (
        "No occurrence has bought anything yet. 1 occurrence ran and bought nothing, "
        "their money waiting with what is carried."
    ) in line, line
    assert "(carried now: 50.00 EUR)" in line


def test_a_buy_whose_plan_was_deleted_still_says_it_was_a_plans(client, market):
    iid = _broker(client)
    plan_id = _plan(client, iid, amount=300, targets=[("XGLO.MI", 1)])
    assert client.post("/api/transactions/catch-up").status_code == 200

    assert client.delete(f"/api/accumulation-plans/{plan_id}").status_code == 204
    with SessionLocal() as db:
        picture = advisor.build_context(db)

    assert (
        "(estimated), made by a PAC no longer on record for its occurrence of "
        "2026-10-04, bought 2026-10-05"
    ) in picture, picture


def test_an_entry_typed_by_the_reader_says_nothing_of_a_plan(client, market):
    """A guard: only a buy that settles an occurrence is tied to one."""
    iid = _broker(client)
    client.post(
        "/api/transactions",
        json={"date": "2026-10-02", "institution_id": iid, "asset_name": "XGLO.MI",
              "symbol": "XGLO.MI", "quantity": 2, "unit_price": 85.8, "currency": "EUR",
              "price_currency": "EUR"},
    )

    with SessionLocal() as db:
        picture = advisor.build_context(db)

    (line,) = [line for line in picture.split("\n") if line.startswith("- 2026-10-02 buy")]
    assert line == "- 2026-10-02 buy 2 x XGLO.MI @ 85.80 EUR = 171.60 EUR"
