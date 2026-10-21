"""One walk across the situations reads what was paid before the latest one (brief AW, part 1).

Measured at `8325ebd` (2026-10-15) on brief AV's invented scenario: a fund
photographed at 10 x 100 with no cost, three buys of 100, a new situation
carried by the code before AV (13 x 110, no cost), then one buy of 110. The
projection read 110.00 paid, for 1 unit, while the ledger held 410.00 for 4
units since the first situation: `project` reads the ledger only after each
account's latest situation, so what was bought before it was gone into that
situation's value.

`positions.recover_paid` walks every situation of an account, per row, with
the ledger between them, through `replay` and its two pools, and proposes for
each row of a latest situation what the ledger paid that the row does not say.
It writes nothing. Every name and figure here is invented.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import text

from app import crud, dated, fx, positions, prices
from app.database import SessionLocal

FIRST, SECOND, THIRD = "2026-03-02", "2026-05-04", "2026-07-01"
FUND = {"asset_name": "Fondo Beta", "asset_class": "fund_etf", "symbol": "BETA.MI"}


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


def _account(client, name: str = "Banca Beta") -> int:
    return _made(client.post("/api/institutions", json={"name": name}))["id"]


def _situation(client, bank: int, date: str, *rows: dict) -> list[int]:
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": date}))["id"]
    return [
        _made(client.post(f"/api/snapshots/{sid}/holdings", json={"currency": "EUR", **row}))["id"]
        for row in rows
    ]


def _row(quantity: float, unit_price: float, **more) -> dict:
    return {**FUND, "quantity": quantity, "unit_price": unit_price, **more}


def _entry(client, bank: int, kind: str, date: str, **figures) -> None:
    body = {"kind": kind, "date": date, "institution_id": bank, **FUND, "currency": "EUR",
            **({} if kind == "close" else {"price_currency": "EUR"}), **figures}
    _made(client.post("/api/transactions", json=body))


def _buy(client, bank: int, date: str, quantity: float, unit_price: float, **more) -> None:
    _entry(client, bank, "buy", date, quantity=quantity, unit_price=unit_price, **more)


def _walk(declined=(), day: str = "2026-10-15") -> positions.Recovery:
    with SessionLocal() as db:
        return positions.recover_paid(
            positions.load_projection_inputs(db), fx.Converter(db), day=day, declined=declined
        )


def _proposal(recovery: positions.Recovery) -> positions.PaidProposal:
    (p,) = recovery.proposals
    return p


def _market(monkeypatch, price: float | None) -> None:
    monkeypatch.setattr(prices, "get_quotes", lambda symbols: (
        {} if price is None else {s: {"symbol": s, "price": price, "as_of": THIRD} for s in symbols}))


def _start_from_the_last_one(client, bank: int, date: str) -> dict:
    snap = _made(client.post(f"/api/institutions/{bank}/snapshots/prefilled", json={"date": date}))
    (row,) = _made(client.get(f"/api/snapshots/{snap['id']}/holdings"))
    return row


@pytest.fixture
def the_day(monkeypatch):
    monkeypatch.setattr(dated, "today", lambda: "2026-10-15")


# --- Clones -----------------------------------------------------------------------------


def test_a_row_carried_before_av_is_proposed_what_the_ledger_paid(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _buy(client, bank, date, 1, 100)
    (latest,) = _situation(client, bank, SECOND, _row(13, 110))  # as the code before AV carried it

    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units, p.quantity) == (latest, 300.0, 3.0, 13.0), (
        "the 300.00 the ledger paid was in the situation's value, and nothing proposed it"
    )
    assert (p.since, p.situation_date, p.estimated) == (FIRST, SECOND, False)
    assert [(e.date, e.kind, e.quantity, e.amount) for e in p.entries] == [
        ("2026-03-16", "buy", 1.0, 100.0), ("2026-04-01", "buy", 1.0, 100.0),
        ("2026-04-15", "buy", 1.0, 100.0)]
    assert (p.row_paid, p.row_units, p.opening_paid) == (0.0, 0.0, None)
    assert _walk().unread == []


def test_a_situation_started_from_the_last_one_with_a_price_needs_nothing(client, the_day, monkeypatch):
    """Brief AV's carry already keeps it: nothing more to propose."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _buy(client, bank, date, 1, 100)
    _market(monkeypatch, 110.0)
    row = _start_from_the_last_one(client, bank, SECOND)
    assert (row["cost_basis"], row["cost_quantity"]) == (300.0, 3.0)
    assert _walk().proposals == []


def test_a_situation_started_from_the_last_one_with_no_price_is_proposed_back(
    client, the_day, monkeypatch
):
    """AV's open case: nothing priced the row, so its paid part was not kept."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _buy(client, bank, date, 1, 100)
    _market(monkeypatch, None)
    row = _start_from_the_last_one(client, bank, SECOND)
    assert row["cost_basis"] is None
    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units, p.quantity) == (row["id"], 300.0, 3.0, 13.0)


def test_two_carries_one_before_av_one_after(client, the_day, monkeypatch):
    """The carry after AV keeps only what was bought since the one before; the
    walk reads both stretches."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _buy(client, bank, date, 1, 100)
    _situation(client, bank, SECOND, _row(13, 110))  # as the code before AV carried it
    _buy(client, bank, "2026-06-01", 1, 110)
    _market(monkeypatch, 115.0)
    row = _start_from_the_last_one(client, bank, THIRD)
    assert (row["cost_basis"], row["cost_quantity"]) == (110.0, 1.0)
    p = _proposal(_walk())
    assert (p.paid, p.units, p.quantity, p.since) == (410.0, 4.0, 14.0, FIRST)
    assert (p.row_paid, p.row_units) == (110.0, 1.0), "what the row says, said beside it"


# --- Situations typed by hand -------------------------------------------------------------


def test_a_situation_typed_by_hand_that_agrees(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _buy(client, bank, "2026-04-01", 2, 100)
    (latest,) = _situation(client, bank, SECOND, _row(12, 105))
    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units) == (latest, 200.0, 2.0)


def test_units_typed_from_a_statement_agree_at_the_decimals_typed(client, the_day):
    """Measured (brief AW): a ledger of 6 decimals, a statement printing 4.
    An exact comparison called it a disagreement and proposed nothing."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date, units in (("2026-03-16", 0.910747), ("2026-04-01", 0.901307), ("2026-04-15", 0.922509)):
        _buy(client, bank, date, units, round(100 / units, 4))
    (latest,) = _situation(client, bank, SECOND, _row(12.7346, 112))
    recovery = _walk()
    p = _proposal(recovery)
    assert p.holding_id == latest
    assert p.units == pytest.approx(2.734563)
    assert recovery.unread == [], "it agrees, so nothing was left unread"


def test_a_situation_typed_by_hand_that_disagrees_is_read_from_again(client, the_day):
    """The rule for a disagreement (the reader's, 2026-10-15): start again from
    that situation with nothing paid before it, and say what was left."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _buy(client, bank, "2026-04-01", 2, 100)
    _situation(client, bank, SECOND, _row(13, 105))  # the ledger gives 12
    _buy(client, bank, "2026-06-01", 3, 110)
    (latest,) = _situation(client, bank, THIRD, _row(16, 112))

    recovery = _walk()
    p = _proposal(recovery)
    assert (p.holding_id, p.paid, p.units, p.quantity, p.since) == (latest, 330.0, 3.0, 16.0, SECOND)
    (left,) = recovery.unread
    assert (left.holding_id, left.situation_date, left.stated_units, left.walked_units) == (
        latest, SECOND, 13.0, 12.0)
    assert (left.paid, left.units, left.since, left.purchases) == (200.0, 2.0, FIRST, 1)


def test_purchases_left_unread_are_said_once_per_row(client, the_day):
    """Buys of 100 at the units a close gives, as a plan's are, and a statement
    at the broker's own fills (measured, brief AW: 0.00051 to 0.000947 apart):
    the units disagree, and the three purchases are said in one line."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date, close in (("2026-03-16", 109.37), ("2026-04-01", 111.13), ("2026-04-15", 108.71)):
        _buy(client, bank, date, 100 / close, close)
    (latest,) = _situation(client, bank, SECOND, _row(12.7346, 112))
    recovery = _walk()
    assert recovery.proposals == []
    (left,) = recovery.unread
    assert (left.holding_id, left.purchases, left.stated_units) == (latest, 3, 12.7346)
    assert left.paid == pytest.approx(300.0) and left.units == pytest.approx(2.734053, abs=1e-6)


def test_a_disagreement_with_nothing_bought_says_nothing(client, the_day):
    """The demo's own case: 45 typed at 70, no buy on the ledger."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(45, 122))
    _situation(client, bank, SECOND, _row(70, 128))
    recovery = _walk()
    assert recovery.proposals == [] and recovery.unread == []


def test_a_recorded_cost_left_at_a_disagreement_is_no_purchase(client, the_day):
    """The line speaks only when purchases on record were left unread (the
    reviewer's guard): a cost typed on the situation before is not one."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100, cost_basis=900))
    _situation(client, bank, SECOND, _row(12, 105))
    assert _walk().unread == []

    _buy(client, bank, "2026-06-01", 2, 100)
    _situation(client, bank, THIRD, _row(15, 110))  # the ledger gives 14
    (left,) = _walk().unread
    assert (left.situation_date, left.stated_units, left.walked_units) == (THIRD, 15.0, 14.0)
    assert (left.paid, left.units, left.purchases, left.opening_paid, left.since) == (
        200.0, 2.0, 1, None, SECOND), "read from the second situation: the purchase alone"


def test_a_cost_recorded_where_the_reading_started_is_said_apart(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100, cost_basis=900))
    _buy(client, bank, "2026-04-01", 2, 100)
    _situation(client, bank, SECOND, _row(13, 105))  # the ledger gives 12
    (left,) = _walk().unread
    assert (left.paid, left.units, left.purchases, left.opening_paid, left.since) == (
        1100.0, 12.0, 1, 900.0, FIRST)


def test_units_typed_too_coarsely_disagree():
    """The bound: half a unit at the decimals typed is at most a thousandth of
    the units. Measured: 13 and 12.7 for 12.7346 would pass on rounding alone."""
    assert positions.units_agree(12.734563, 12.7346)
    assert positions.units_agree(12.734563, 12.73)
    assert positions.units_agree(12.700000000000001, 12.7)
    assert not positions.units_agree(12.734563, 13.0)
    assert not positions.units_agree(12.734563, 12.7)
    assert not positions.units_agree(12.734053, 12.7346), "a fill drift is no rounding"
    assert not positions.units_agree(12.734563, 13.6274), "a purchase missing"


# --- The reader's figure ------------------------------------------------------------------


def test_a_cost_the_reader_typed_is_their_figure(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _buy(client, bank, "2026-04-01", 2, 100)
    _situation(client, bank, SECOND, _row(12, 105, cost_basis=1150))
    assert _walk().proposals == [], "nothing proposed on a cost typed for every unit"


def test_the_walk_starts_again_from_a_cost_the_reader_typed(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _situation(client, bank, SECOND, _row(10, 104, cost_basis=950))
    _buy(client, bank, "2026-06-01", 2, 110)
    _situation(client, bank, THIRD, _row(12, 112))
    p = _proposal(_walk())
    assert (p.paid, p.units, p.since) == (1170.0, 12.0, SECOND)
    assert (p.opening_paid, p.opening_units) == (950.0, 10.0), "the cost recorded, said apart"


# --- Between two situations -----------------------------------------------------------------


def test_a_sell_and_a_dividend_between_situations(client, the_day):
    """A sell takes its share of the paid pool; a dividend does not touch it."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _buy(client, bank, "2026-04-01", 4, 100)
    _entry(client, bank, "sell", "2026-04-20", quantity=7, unit_price=105)
    _entry(client, bank, "dividend", "2026-04-25", quantity=7, unit_price=0.5)
    (latest,) = _situation(client, bank, SECOND, _row(7, 106))
    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units) == (latest, 200.0, 2.0)
    assert [e.kind for e in p.entries] == ["buy", "sell"]


def test_a_close_between_situations_starts_the_purchases_again(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _buy(client, bank, "2026-03-16", 2, 100)
    _entry(client, bank, "close", "2026-04-01", amount=1300)
    _buy(client, bank, "2026-04-15", 3, 90)
    (latest,) = _situation(client, bank, SECOND, _row(3, 95))
    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units, p.quantity) == (latest, 270.0, 3.0, 3.0)
    assert p.since == "2026-04-01", "what was bought before the close stands behind no unit"
    assert [e.date for e in p.entries] == ["2026-04-15"]


def test_a_row_bought_between_two_situations_and_typed_in_the_second(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, {**FUND, "asset_name": "Altro", "symbol": "ALTRO.MI",
                                     "quantity": 1, "unit_price": 50})
    _buy(client, bank, "2026-04-01", 5, 100)
    (latest,) = _situation(client, bank, SECOND, _row(5, 104))
    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units, p.quantity, p.since) == (latest, 500.0, 5.0, 5.0, FIRST)


# --- Nothing to propose ---------------------------------------------------------------------


def test_a_row_with_a_single_situation_proposes_nothing(client, the_day):
    """What the ledger holds on or before an account's first situation is in
    that photograph."""
    bank = _account(client)
    _buy(client, bank, "2026-02-02", 3, 100)
    _situation(client, bank, FIRST, _row(13, 110))
    _buy(client, bank, "2026-04-01", 1, 110)
    recovery = _walk()
    assert recovery.proposals == [] and recovery.unread == []


def test_units_photographed_with_no_value_and_no_cost_are_not_proposed(client, the_day):
    """STILL OPEN F3: such units sit in the paid pool at zero. Nothing bought
    them, so nothing is proposed for them. The API refuses such a row since
    brief BE; one written before is read so."""
    bank = _account(client)
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": FIRST}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings",
                      json={**FUND, "quantity": 10, "unit_price": 100, "currency": "EUR"}))
    with SessionLocal() as db:
        db.execute(text("UPDATE holdings SET unit_price = NULL, value = NULL"))
        db.commit()
    _buy(client, bank, "2026-04-01", 5, 100)
    _situation(client, bank, SECOND, _row(15, 105))
    assert _walk().proposals == []


def test_a_ticker_on_two_rows_of_one_situation_is_not_proposed(client, the_day):
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _buy(client, bank, "2026-04-01", 2, 100)
    _situation(client, bank, SECOND, _row(6, 105), _row(6, 105))
    recovery = _walk()
    assert recovery.proposals == [] and recovery.unread == []


# --- A cost carried, and a buy corrected behind it -----------------------------------------


def _plan(client, monkeypatch, bank: int) -> None:
    monkeypatch.setattr(prices, "get_price_on", lambda symbol, on, today=None: {
        "symbol": symbol, "price": 100.0, "as_of": on.isoformat()})
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    from app import pac
    _made(client.post("/api/accumulation-plans", json={
        "name": "Piano Beta", "amount": 100, "currency": "EUR", "frequency": "monthly",
        "execution": "fractional", "start_date": "2026-03-16", "source_institution_id": bank,
        "targets": [{"symbol": FUND["symbol"], "asset_name": FUND["asset_name"],
                     "institution_id": bank, "weight": 1}]}))
    with SessionLocal() as db:
        assert len(pac.execute_due(db, as_of=datetime.date(2026, 5, 16))["created"]) == 3


def test_a_carried_cost_follows_a_buy_corrected_behind_it(client, the_day, monkeypatch):
    """Found by brief AW's P0: the carry wrote 300.00 for 3, estimated; the
    first buy corrected to its contract note afterwards, the row kept 300.00."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    _plan(client, monkeypatch, bank)
    _market(monkeypatch, 110.0)
    row = _start_from_the_last_one(client, bank, "2026-05-20")
    assert (row["cost_basis"], row["cost_quantity"], row["cost_estimated"]) == (300.0, 3.0, True)
    assert _walk().proposals == []

    first = min((t for t in _made(client.get("/api/transactions")) if t["kind"] == "buy"),
                key=lambda t: t["date"])
    # As the ledger form sends a correction: the amount null, worked out again.
    _made(client.put(f"/api/transactions/{first['id']}", json={
        "kind": "buy", "date": first["date"], "institution_id": bank, **FUND,
        "quantity": 1, "unit_price": 95, "amount": None, "currency": "EUR",
        "price_currency": "EUR"}))
    p = _proposal(_walk())
    assert (p.holding_id, p.paid, p.units, p.estimated) == (row["id"], 295.0, 3.0, True)
    assert (p.row_paid, p.row_units, p.row_estimated) == (300.0, 3.0, True)


def test_a_carried_cost_in_another_currency_than_its_buys_compares_units_only(
    client, the_day, monkeypatch
):
    """The amounts convert at today's rate; a carried cost was converted on its
    own day. A rate's move alone must not read as a correction."""
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {
        "2026-10-15": {"USD": 1.0}, "2026-03-02": {"USD": 1.25}})
    usd = {**FUND, "symbol": "BETA.US", "currency": "USD"}
    with SessionLocal() as db:
        crud.upsert_price_caches(db, {"BETA.US": {"price": 140.0, "as_of": "2026-10-14",
                                                  "currency": "USD"}})
    bank = _account(client)
    _situation(client, bank, FIRST, {**usd, "quantity": 10, "unit_price": 125})
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _made(client.post("/api/transactions", json={
            "kind": "buy", "date": date, "institution_id": bank, **usd, "quantity": 1,
            "unit_price": 100, "price_currency": "EUR", "currency": "EUR"}))
    # As a carry on a day the dollar stood at 1.25 would have written 300.00.
    _situation(client, bank, SECOND, {**usd, "quantity": 13, "unit_price": 140,
                                      "cost_basis": 375, "cost_quantity": 3})
    assert _walk().proposals == [], "375 dollars read as 375.00 today, the buys 300.00: no correction"


# --- A decline -------------------------------------------------------------------------------


def test_a_declined_row_is_where_the_walk_starts_again(client, the_day, monkeypatch):
    """Measured (brief AW): remembered as 'not this row' only, the next
    situation started from the last brought the same proposal back."""
    bank = _account(client)
    _situation(client, bank, FIRST, _row(10, 100))
    for date in ("2026-03-16", "2026-04-01", "2026-04-15"):
        _buy(client, bank, date, 1, 100)
    (declined,) = _situation(client, bank, SECOND, _row(13, 110))
    assert _proposal(_walk()).holding_id == declined
    assert _walk(declined={declined}).proposals == []

    _market(monkeypatch, 115.0)
    later = _start_from_the_last_one(client, bank, THIRD)
    assert later["cost_basis"] is None, "nothing bought since the declined situation"
    assert _walk(declined={declined}).proposals == []
    assert _proposal(_walk()).holding_id == later["id"], "without the barrier it comes back"
