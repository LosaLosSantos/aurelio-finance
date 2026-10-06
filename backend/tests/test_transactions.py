"""The investment ledger (buys) and PAC auto-execution.

Positions follow the anchor+events model: latest snapshot quantity + buys
strictly AFTER the snapshot date. Cash is debited by the actual amount spent.
The PAC catch-up prices occurrences via prices.get_price_on, monkeypatched
here so tests never hit the network."""

from __future__ import annotations

import datetime

import pytest

from app import analytics, crud, pac, prices, schemas
from app.database import SessionLocal

TODAY = datetime.date.today()
TODAY_ISO = TODAY.isoformat()
LONG_AGO = "2020-01-10"


@pytest.fixture(autouse=True)
def euro_listings(monkeypatch):
    """Every listing in this file trades in euro, and the market says so.

    The catch-up asks what a target is priced in before it sets that price
    against a plan's budget, and a listing nobody can name is not bought. The
    plans here are euro plans buying euro funds; without this every one of them
    would be skipped for the currency — and a test about an UNPRICEABLE leg
    would still pass, for that other reason."""
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")


def _institution(client, name="Broker A") -> int:
    return client.post("/api/institutions", json={"name": name, "type": "broker"}).json()["id"]


def _snapshot_with_vwce(client, iid: int, date: str, qty: float = 10, policy: str | None = None) -> int:
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": date}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Vanguard All-World",
            "asset_class": "fund_etf",
            "symbol": "VWCE.MI",
            "quantity": qty,
            "unit_price": 100,
            "currency": "EUR",
            **({"distribution_policy": policy} if policy else {}),
        },
    )
    return sid


def _buy(client, iid: int, date: str, qty: float = 4, price: float = 110, **extra):
    payload = {"currency": "EUR", "price_currency": "EUR",
        "date": date,
        "institution_id": iid,
        "asset_name": "Vanguard All-World",
        "symbol": "VWCE.MI",
        "asset_class": "fund_etf",
        "quantity": qty,
        "unit_price": price,
        **extra,
    }
    r = client.post("/api/transactions", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# --- Manual buys (CRUD) -----------------------------------------------------


def test_create_buy_defaults_amount_and_reads_back(client):
    iid = _institution(client)
    tx = _buy(client, iid, TODAY_ISO, qty=4, price=110, fees=2.5)
    assert tx["amount"] == 4 * 110 + 2.5
    assert tx["estimated"] is False and tx["plan_id"] is None
    assert client.get(f"/api/transactions/{tx['id']}").json()["symbol"] == "VWCE.MI"


def test_update_buy_clears_estimated_and_delete(client):
    iid = _institution(client)
    tx = _buy(client, iid, TODAY_ISO)
    r = client.put(
        f"/api/transactions/{tx['id']}",
        json={
            "date": TODAY_ISO,
            "institution_id": iid,
            "asset_name": "Vanguard All-World",
            "symbol": "VWCE.MI",
            "quantity": 5,
            "unit_price": 108,
            "currency": "EUR",
            "price_currency": "EUR",
            # The form's gesture for "I am not stating the cash figure, work it
            # out". An edit no longer touches a column it did not mention, so
            # leaving this key out would keep the amount the buy was stored
            # with — see `crud._update`.
            "amount": None,
        },
    )
    body = r.json()
    assert body["quantity"] == 5 and body["amount"] == 540 and body["estimated"] is False
    assert client.delete(f"/api/transactions/{tx['id']}").status_code == 204
    assert client.get(f"/api/transactions/{tx['id']}").status_code == 404


# --- Position projection (anchor + later buys) ------------------------------


def test_buy_after_snapshot_extends_position(client):
    iid = _institution(client)
    _snapshot_with_vwce(client, iid, LONG_AGO, qty=10)  # book 1000
    _buy(client, iid, TODAY_ISO, qty=4, price=110)  # spent 440

    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["quantity"] == 14
    assert row["book_value"] == 1000 + 440


def test_new_snapshot_rebases_and_buys_before_it_are_not_double_counted(client):
    iid = _institution(client)
    _snapshot_with_vwce(client, iid, LONG_AGO, qty=10)
    _buy(client, iid, "2020-02-05", qty=4, price=110)
    # Reconciliation photo AFTER the buy already includes the 4 units.
    _snapshot_with_vwce(client, iid, "2020-03-01", qty=14)

    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["quantity"] == 14  # not 18


def test_buy_of_new_symbol_creates_position(client):
    iid = _institution(client)
    _buy(client, iid, TODAY_ISO, qty=2, price=50, symbol="SWDA.MI", asset_name="iShares World")

    p = client.get("/api/dashboard/portfolio").json()
    assert len(p["rows"]) == 1
    row = p["rows"][0]
    assert row["symbol"] == "SWDA.MI" and row["quantity"] == 2 and row["book_value"] == 100


# --- Cash + net-worth consistency -------------------------------------------


def test_buy_debits_cash_and_net_worth_is_conserved(client):
    iid = _institution(client)
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": LONG_AGO, "amount": 5000, "currency": "EUR"}
    )
    _snapshot_with_vwce(client, iid, LONG_AGO, qty=10)
    before = client.get("/api/dashboard/summary").json()

    _buy(client, iid, TODAY_ISO, qty=4, price=110)  # moves 440 cash -> investments
    cash = client.get(f"/api/institutions/{iid}/cash").json()
    assert cash["buys"] == 440 and cash["projected"] == 5000 - 440

    after = client.get("/api/dashboard/summary").json()
    assert after["cash_total"] == before["cash_total"] - 440
    assert after["investments_total"] == before["investments_total"] + 440
    assert abs(after["net_worth"] - before["net_worth"]) < 1e-9


def test_buy_paid_by_other_institution(client):
    broker = _institution(client, "Broker A")
    bank = _institution(client, "Bank D")
    client.post(
        f"/api/institutions/{bank}/cash-anchors", json={"date": LONG_AGO, "amount": 2000, "currency": "EUR"}
    )
    _buy(client, broker, TODAY_ISO, qty=4, price=110, cash_institution_id=bank)

    assert client.get(f"/api/institutions/{bank}/cash").json()["projected"] == 2000 - 440


# --- A buy has to come from somewhere ---------------------------------------
#
# The walk nobody had taken. Every one of this suite's other transaction posts
# names an institution — `_buy` takes the id as a required argument — so the
# path where none is named was green by never being walked.


def test_a_buy_that_names_no_institution_is_refused_and_the_total_does_not_move(client):
    """A row with NEITHER institution column set adds its own cost to the net
    worth, which is why the API will not take one.

    The cash register keeps the entries belonging to the institution it is
    computing, and a null matches no id there is — so the money never leaves
    any account. The investment side has no such filter: `positions.project`
    buckets by (institution_id, symbol) and None is a perfectly good bucket.
    Measured before the refusal existed: 1000 cash, a 100 buy naming nobody,
    net worth 1100.

    Asserted against the TOTAL and not against the row, because the row was
    never the defect — a ledger entry is allowed to be about a position held
    nowhere (the PAC writes those, below). What is not allowed is spending
    money no account loses."""
    iid = _institution(client)
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": LONG_AGO, "amount": 1000, "currency": "EUR"}
    )
    before = client.get("/api/dashboard/summary").json()
    assert (before["net_worth"], before["cash_total"]) == (1000.0, 1000.0)

    r = client.post(
        "/api/transactions",
        json={
            "date": TODAY_ISO,
            "institution_id": None,
            "asset_name": "Vanguard All-World",
            "symbol": "VWCE.MI",
            "quantity": 10,
            "unit_price": 10.0,
            "currency": "EUR",
            "price_currency": "EUR",
        },
    )
    assert r.status_code == 422, r.text
    assert "institution_id" in r.text

    after = client.get("/api/dashboard/summary").json()
    assert after["net_worth"] == before["net_worth"] == 1000.0
    assert client.get("/api/transactions").json() == []

    # And the same door, the other way: repairing such a row is what the PUT is
    # for, so it carries the same requirement.
    tx = _buy(client, iid, TODAY_ISO, qty=10, price=10.0)
    bad = client.put(
        f"/api/transactions/{tx['id']}",
        json={
            "date": TODAY_ISO,
            "institution_id": None,
            "asset_name": tx["asset_name"],
            "symbol": tx["symbol"],
            "quantity": 10,
            "unit_price": 10.0,
            "currency": "EUR",
            "price_currency": "EUR",
        },
    )
    assert bad.status_code == 422, bad.text
    assert client.get("/api/dashboard/summary").json()["net_worth"] == 1000.0


def test_an_institution_with_no_anchor_reports_a_zero_that_is_not_a_balance(client):
    """`projected: 0.0` with `anchor_date: null` means NOT ON RECORD, and the
    two fields have to be read together to know which zero this is.

    The select on the portfolio page keys off `anchor_date` for exactly this
    reason: printing the 0.0 as "0.00 available" beside an institution the app
    has never been told a balance for is the app stating a figure it does not
    have — the same distinction the portfolio already makes between a cost of
    zero and COST UNKNOWN."""
    nowhere = _institution(client, "Broker A")
    known = _institution(client, "Bank D")
    client.post(
        f"/api/institutions/{known}/cash-anchors", json={"date": LONG_AGO, "amount": 250, "currency": "EUR"}
    )

    by_id = {p["institution_id"]: p for p in client.get("/api/cash/positions").json()}
    assert by_id[nowhere]["anchor_date"] is None and by_id[nowhere]["projected"] == 0.0
    assert by_id[known]["anchor_date"] == LONG_AGO and by_id[known]["projected"] == 250.0


# --- PAC auto-execution (catch-up) ------------------------------------------


def _plan(client, iid: int, amount=800, start="2026-01-05", **extra) -> int:
    r = client.post(
        "/api/accumulation-plans",
        json={
            "name": "PAC All-World",
            "amount": amount,
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": start,
            "source_institution_id": iid,
            "targets": [
                {
                    "symbol": "VWCE.MI",
                    "asset_name": "Vanguard All-World",
                    "institution_id": iid,
                }
            ],
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fake_price(price: float):
    def fake(symbol: str, on: datetime.date) -> dict:
        return {"symbol": symbol, "price": price, "as_of": on.isoformat()}

    return fake


def test_catchup_creates_whole_unit_buys_and_is_idempotent(client, monkeypatch):
    iid = _institution(client)
    plan_id = _plan(client, iid, amount=800, start="2026-01-05")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(168.0))

    with SessionLocal() as db:
        result = pac.execute_due(db, as_of=datetime.date(2026, 3, 10))
        created = result["created"]
        assert len(created) == 3  # Jan 5, Feb 5, Mar 5
        # The change carries. 800 buys 4 units at 168 and leaves 128; the next
        # contribution therefore has 928 and buys 5; then 888 buys 5 again.
        # Throwing that change away every month would have left 384 of 2400
        # contributed but never invested.
        assert [t.quantity for t in created] == [4, 5, 5]
        assert sum(t.amount for t in created) == 14 * 168.0
        assert all(t.estimated and t.plan_id == plan_id for t in created)

    with SessionLocal() as db:
        again = pac.execute_due(db, as_of=datetime.date(2026, 3, 10))
    assert again["created"] == [] and again["skipped"] == []

    # The position and the cash register both see the executions.
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": "2025-12-31", "amount": 5000, "currency": "EUR"}
    )
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["quantity"] == 14 and row["book_value"] == 14 * 168.0
    assert client.get(f"/api/institutions/{iid}/cash").json()["buys"] == 14 * 168.0


def test_catchup_fractional_invests_exactly_the_amount(client, monkeypatch):
    iid = _institution(client)
    _plan(client, iid, amount=800, start="2026-03-05", execution="fractional")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(168.0))

    with SessionLocal() as db:
        result = pac.execute_due(db, as_of=datetime.date(2026, 3, 10))
        (tx,) = result["created"]
        assert abs(tx.quantity - 800 / 168.0) < 1e-9 and tx.amount == 800


def test_catchup_skips_unpriceable_and_over_budget_occurrences(client, monkeypatch):
    iid = _institution(client)
    _plan(client, iid, amount=100, start="2026-03-05")  # price 168 > 100 budget

    monkeypatch.setattr(prices, "get_price_on", _fake_price(168.0))
    with SessionLocal() as db:
        result = pac.execute_due(db, as_of=datetime.date(2026, 3, 10))
    assert result["created"] == []
    assert "cannot buy a whole unit" in result["skipped"][0]["reason"]

    def boom(symbol, on):
        raise prices.PriceError("offline")

    monkeypatch.setattr(prices, "get_price_on", boom)
    # April, not March again: March RAN — it put its 100 into the carry and
    # recorded that it bought nothing — so it is settled and never reaches the
    # price fetch. This half used to re-run March, which only worked because an
    # unfilled occurrence came back for ever. That is the bug, not the fixture.
    with SessionLocal() as db:
        result = pac.execute_due(db, as_of=datetime.date(2026, 4, 10))
    # The reason names the target: with several in one plan, "offline" alone
    # would not say which one held the occurrence up.
    assert result["created"] == [] and result["skipped"][0]["reason"] == "VWCE.MI: offline"
    # And a priced failure records nothing, so April is still due.
    with SessionLocal() as db:
        settled = crud.get_plan_occurrences_settled(db, crud.get_accumulation_plans(db)[0].id)
    assert settled == {"2026-03-05"}


def test_catch_up_endpoint(client, monkeypatch):
    iid = _institution(client)
    # Exactly one occurrence, and one whose day is over: today's waits for
    # the close (test_a_rate_is_final_once_its_day_is_over).
    _plan(client, iid, start=(TODAY - datetime.timedelta(days=1)).isoformat())
    monkeypatch.setattr(prices, "get_price_on", _fake_price(160.0))

    body = client.post("/api/transactions/catch-up").json()
    assert len(body["created"]) == 1
    assert body["created"][0]["quantity"] == 5  # floor(800/160)
    assert body["created"][0]["estimated"] is True

    # idempotent through the endpoint too
    again = client.post("/api/transactions/catch-up").json()
    assert again["created"] == []


# --- Sells (average-cost accounting) ----------------------------------------


def _sell(client, iid: int, date: str, qty: float, price: float, **extra):
    return _buy(client, iid, date, qty=qty, price=price, kind="sell", **extra)


def test_sell_removes_units_at_avg_cost_and_realizes_pl(client):
    iid = _institution(client)
    _snapshot_with_vwce(client, iid, LONG_AGO, qty=10)  # 10 units, book 1000 (avg 100)
    _buy(client, iid, "2020-02-05", qty=10, price=120)  # 20 units, book 2200 (avg 110)
    _sell(client, iid, TODAY_ISO, qty=5, price=130)  # proceeds 650, cost 550

    p = client.get("/api/dashboard/portfolio").json()
    row = p["rows"][0]
    assert row["quantity"] == 15
    assert abs(row["book_value"] - 1650) < 1e-9  # 2200 - 5*110
    assert abs(row["avg_cost"] - 110) < 1e-9  # average survives the sale
    assert abs(row["realized_pl"] - 100) < 1e-9  # 650 - 550
    assert abs(p["total_realized"] - 100) < 1e-9


def test_sell_credits_cash_and_net_worth_gains_realized(client):
    iid = _institution(client)
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": LONG_AGO, "amount": 1000, "currency": "EUR"}
    )
    _snapshot_with_vwce(client, iid, LONG_AGO, qty=10)  # book 1000, avg 100
    before = client.get("/api/dashboard/summary").json()

    _sell(client, iid, TODAY_ISO, qty=4, price=130)  # proceeds 520, cost 400
    cash = client.get(f"/api/institutions/{iid}/cash").json()
    assert cash["sells"] == 520 and cash["projected"] == 1520

    after = client.get("/api/dashboard/summary").json()
    assert after["cash_total"] == before["cash_total"] + 520
    assert after["investments_total"] == before["investments_total"] - 400
    # book net worth grows exactly by the realized gain
    assert abs(after["net_worth"] - before["net_worth"] - 120) < 1e-9


def test_sell_more_than_held_is_clamped(client):
    iid = _institution(client)
    _snapshot_with_vwce(client, iid, LONG_AGO, qty=10)
    _sell(client, iid, TODAY_ISO, qty=25, price=130)

    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["quantity"] == 0 and abs(row["book_value"]) < 1e-9


def test_sell_amount_defaults_to_net_proceeds(client):
    iid = _institution(client)
    tx = _sell(client, iid, TODAY_ISO, qty=4, price=130, fees=5)
    assert tx["amount"] == 4 * 130 - 5


# --- Dividends (auto-collection for dist positions) --------------------------


def _dist_snapshot(client, iid: int, date: str, qty: float = 10) -> int:
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": date}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Vanguard All-World Dist",
            "asset_class": "fund_etf",
            "symbol": "VWRL.MI",
            "quantity": qty,
            "unit_price": 100,
            "distribution_policy": "dist",
            "currency": "EUR",
        },
    )
    return sid


def test_dividend_catchup_credits_cash_and_is_idempotent(client, monkeypatch):
    iid = _institution(client)
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": "2026-01-01", "amount": 1000, "currency": "EUR"}
    )
    _dist_snapshot(client, iid, "2026-01-01", qty=10)
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda sym, since: [{"date": "2026-03-20", "dps": 0.75}, {"date": "2026-06-20", "dps": 0.80}],
    )
    monkeypatch.setattr(prices, "get_price_on", _fake_price(100.0))  # unused: no plans

    body = client.post("/api/transactions/catch-up").json()
    assert len(body["created"]) == 2
    d1 = body["created"][0]
    assert d1["kind"] == "dividend" and d1["quantity"] == 10 and d1["amount"] == 7.5
    assert d1["estimated"] is True

    # cash credited, position untouched
    cash = client.get(f"/api/institutions/{iid}/cash").json()
    assert cash["sells"] == 7.5 + 8.0 and cash["projected"] == 1015.5
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["quantity"] == 10 and row["book_value"] == 1000
    assert row["dividends"] == 15.5

    again = client.post("/api/transactions/catch-up").json()
    assert again["created"] == []


def test_dividend_uses_shares_held_at_ex_date(client, monkeypatch):
    iid = _institution(client)
    _dist_snapshot(client, iid, "2026-01-01", qty=10)
    _buy(client, iid, "2026-02-10", qty=5, price=100, symbol="VWRL.MI", asset_name="Vanguard All-World Dist")
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda sym, since: [{"date": "2026-03-20", "dps": 1.0}],
    )

    body = client.post("/api/transactions/catch-up").json()
    (d,) = body["created"]
    assert d["quantity"] == 15  # 10 from the snapshot + 5 bought before the ex-date
    assert d["amount"] == 15.0


def test_a_buy_on_the_ex_date_is_too_late(client, monkeypatch):
    """`replay(until=...)` is EXCLUSIVE, and this is the assertion that says
    so: you have to own the shares BEFORE the ex-date, so units bought on the
    day itself collect nothing. It is the one boundary the three copies of
    this walk disagreed about, so it is the one worth pinning."""
    iid = _institution(client)
    _dist_snapshot(client, iid, "2026-01-01", qty=10)
    _buy(client, iid, "2026-03-20", qty=5, price=100,
         symbol="VWRL.MI", asset_name="Vanguard All-World Dist")
    monkeypatch.setattr(
        prices,
        "get_dividends_since",
        lambda sym, since: [{"date": "2026-03-20", "dps": 1.0}],
    )

    (d,) = client.post("/api/transactions/catch-up").json()["created"]
    assert d["quantity"] == 10, "the 5 bought on the ex-date do not qualify"


def test_acc_positions_get_no_dividends(client, monkeypatch):
    iid = _institution(client)
    # Stated: since brief AF a holding with NO policy is asked, because its
    # own dividend history decides (test_every_dividend_in_its_own_currency).
    _snapshot_with_vwce(client, iid, "2026-01-01", qty=10, policy="acc")

    def boom(sym, since):
        raise AssertionError("acc positions must not fetch dividends")

    monkeypatch.setattr(prices, "get_dividends_since", boom)
    assert client.post("/api/transactions/catch-up").json()["created"] == []


# --- Multi-target plans: spending the budget down ----------------------------


def test_fractional_splits_the_budget_by_weight_exactly():
    qty = pac.allocate(1000.0, [3.0, 1.0], [50.0, 20.0], fractional=True)
    assert qty == [750 / 50, 250 / 20]


def test_whole_units_keep_filling_with_what_the_floor_left_over():
    """The point of the feature. Split 300 across three 90-EUR funds and a
    naive floor buys ONE unit each and strands 30 EUR; the leftover has to keep
    buying until nothing else fits."""
    qty = pac.allocate(300.0, [1.0, 1.0, 1.0], [90.0, 90.0, 90.0], fractional=False)
    assert sum(qty) == 3  # 270 spent, 30 left, nothing costs 30
    qty = pac.allocate(400.0, [1.0, 1.0, 1.0], [90.0, 90.0, 90.0], fractional=False)
    assert sum(qty) == 4  # 360 spent: the 4th unit came out of the remainder


def test_the_leftover_goes_to_whatever_is_furthest_below_its_share():
    """Spending the remainder must not distort the mix: the spare unit goes to
    the target that is currently most underweight, not the first in the list."""
    # 60/40 of 200 = 120/80. Floors: 1x100 and 1x50 -> 150 spent, 50 left.
    # A wants 60% but holds 100/200 = 50%; B wants 40% and holds 25%. B is
    # further below, and B is the one that fits.
    qty = pac.allocate(200.0, [60.0, 40.0], [100.0, 50.0], fractional=False)
    assert qty == [1.0, 2.0]


def test_a_target_dearer_than_its_share_is_left_alone_not_forced():
    """The declared limit. A 250-EUR fund at 30% of 400 EUR is not bought: one
    unit would be 62% of the contribution, which is not the plan the user
    asked for. The budget still gets spent — on the target that fits — and
    execute_due reports the starved one instead of hiding it."""
    qty = pac.allocate(400.0, [70.0, 30.0], [100.0, 250.0], fractional=False)
    assert qty == [4.0, 0.0]
    assert sum(q * p for q, p in zip(qty, [100.0, 250.0])) == 400.0

    # Raise the weight and it becomes buyable, which is the documented remedy.
    assert pac.allocate(400.0, [30.0, 70.0], [100.0, 250.0], fractional=False)[1] >= 1


def test_allocation_never_overspends_the_budget():
    for budget, prices_ in [(500.0, [37.0, 91.0, 12.5]), (100.0, [99.0, 3.0]), (7.0, [8.0])]:
        qty = pac.allocate(budget, [1.0] * len(prices_), prices_, fractional=False)
        assert sum(q * p for q, p in zip(qty, prices_)) <= budget + 1e-9


def test_a_zero_weight_target_is_never_bought():
    qty = pac.allocate(1000.0, [1.0, 0.0], [50.0, 20.0], fractional=False)
    assert qty[1] == 0.0


def test_a_plan_target_that_names_no_institution_still_executes_and_stays_correct(
    client, monkeypatch
):
    """The PAC writes rows with `institution_id` NULL, and those rows are right.

    It is the precedent the manual fix was built on and the reason nothing
    migrated. A plan target may name no institution; the plan's SOURCE always
    does, so `cash_institution_id` is written and the cash leaves a real
    account. The position lands in the null bucket — unreachable by any
    situation, which is a separate complaint — but the arithmetic balances to
    the cent: what the buys took out of cash is exactly what the investments
    gained.

    Requiring an institution of the form and of the chat must not catch this in
    the blast radius, so it is asserted here rather than assumed.

    The plan is now built through `crud` rather than posted, because the form's
    door has since closed on it too: `AccumulationPlanWrite` requires the
    institution of every target, so a person can no longer create one of these
    (`test_a_plan_that_names_neither_end_is_refused` is that door). What did
    not change is the door underneath — the columns stay nullable, `crud` keeps
    accepting null, and the catch-up keeps executing a plan already saved that
    way. This is the test that says so."""
    iid = _institution(client)
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": "2025-12-31", "amount": 5000, "currency": "EUR"}
    )
    before = client.get("/api/dashboard/summary").json()
    with SessionLocal() as db:
        crud.create_accumulation_plan(
            db,
            schemas.AccumulationPlanCreate(
                name="PAC All-World",
                amount=800,
                currency="EUR",
                frequency="monthly",
                start_date=datetime.date(2026, 1, 5),
                source_institution_id=iid,
                targets=[
                    schemas.PlanTargetCreate(
                        symbol="VWCE.MI",
                        asset_name="Vanguard All-World",
                        institution_id=None,
                    )
                ],
            ),
        )
    monkeypatch.setattr(prices, "get_price_on", _fake_price(168.0))

    with SessionLocal() as db:
        created = pac.execute_due(db, as_of=datetime.date(2026, 5, 10))["created"]
        assert len(created) == 5  # Jan through May: the blank target executes
        spent = sum(t.amount for t in created)
        assert all(t.institution_id is None for t in created)
        assert all(t.cash_institution_id == iid for t in created)

    # Named on the cash side, so the register sees every one of them.
    assert client.get(f"/api/institutions/{iid}/cash").json()["buys"] == spent
    after = client.get("/api/dashboard/summary").json()
    assert after["cash_total"] == before["cash_total"] - spent
    assert after["investments_total"] == before["investments_total"] + spent
    assert abs(after["net_worth"] - before["net_worth"]) < 1e-9

    # And the position it made says what it is instead of wearing a "?" that a
    # bank actually called that would be indistinguishable from.
    (row,) = client.get("/api/dashboard/portfolio").json()["rows"]
    assert row["institution"] is None


def test_a_two_target_plan_buys_both_in_one_occurrence(client, monkeypatch):
    """End to end: one standing order, two funds, one occurrence -> two buys,
    each at its own institution, all sharing the occurrence key so the catch-up
    stays idempotent."""
    iid = _institution(client)
    plan_id = _plan(
        client,
        iid,
        amount=500,
        start="2026-01-05",
        targets=[
            {"symbol": "VWCE.MI", "asset_name": "All-World", "institution_id": iid, "weight": 3},
            {"symbol": "EUNL.DE", "asset_name": "Core World", "institution_id": iid, "weight": 1},
        ],
    )
    prices_by_symbol = {"VWCE.MI": 100.0, "EUNL.DE": 10.0}
    monkeypatch.setattr(
        prices,
        "get_price_on",
        lambda s, on: {"symbol": s, "price": prices_by_symbol[s], "as_of": on.isoformat()},
    )

    with SessionLocal() as db:
        created = pac.execute_due(db, as_of=datetime.date(2026, 1, 10))["created"]
        by_symbol = {t.symbol: t for t in created}
        assert set(by_symbol) == {"VWCE.MI", "EUNL.DE"}
        # 75/25 of 500 at 100 and 10 a unit. Slicing first would buy 3 and 12
        # and strand 80; spending the budget as one pot buys 4 and 10 and
        # leaves nothing — 80/20 against a 75/25 target, which is as close as
        # whole units of 100 can get.
        assert by_symbol["VWCE.MI"].quantity == 4
        assert by_symbol["EUNL.DE"].quantity == 10
        assert sum(t.amount for t in created) == 500.0
        assert {t.plan_occurrence for t in created} == {"2026-01-05"}
        assert all(t.plan_id == plan_id and t.estimated for t in created)

    # Idempotent: the occurrence is done, both legs included.
    with SessionLocal() as db:
        assert pac.execute_due(db, as_of=datetime.date(2026, 1, 10))["created"] == []


def test_one_unpriceable_leg_holds_the_whole_occurrence(client, monkeypatch):
    """All or nothing. A partial fill would spend the budget on the leg that
    answered and mark the occurrence done, so the silent leg would never be
    bought and the requested mix would drift for good."""
    iid = _institution(client)
    _plan(
        client,
        iid,
        amount=500,
        start="2026-01-05",
        targets=[
            {"symbol": "VWCE.MI", "institution_id": iid},
            {"symbol": "BROKEN", "institution_id": iid},
        ],
    )

    def flaky(symbol, on):
        if symbol == "BROKEN":
            raise prices.PriceError("offline")
        return {"symbol": symbol, "price": 100.0, "as_of": on.isoformat()}

    monkeypatch.setattr(prices, "get_price_on", flaky)
    with SessionLocal() as db:
        result = pac.execute_due(db, as_of=datetime.date(2026, 1, 10))
    assert result["created"] == []
    assert "BROKEN" in result["skipped"][0]["reason"]


def test_a_failure_writing_leg_2_leaves_the_occurrence_replayable(client, monkeypatch):
    """The write half of the same all-or-nothing rule.

    Pricing every target before buying anything only covers targets that
    cannot be PRICED. It says nothing about a target that cannot be WRITTEN:
    each leg used to commit on its own, so a crash between them left leg 1 on
    disk and the occurrence key with it. The occurrence then reads as done and
    the silent fund is never bought — on this run or any later one, which is
    exactly the permanent drift the price check exists to prevent.

    One occurrence is one unit of work: both legs land, or neither does and the
    occurrence stays due."""
    iid = _institution(client)
    _plan(
        client,
        iid,
        amount=400,
        start="2026-01-05",
        targets=[
            {"symbol": "AAA", "institution_id": iid, "weight": 60},
            {"symbol": "BBB", "institution_id": iid, "weight": 40},
        ],
    )
    monkeypatch.setattr(prices, "get_price_on", _fake_price(100.0))

    # The call that writes each leg: the catch-up works the legs' columns out
    # before it takes the write lock, and only stores them under it.
    write = crud.store_transaction
    legs = {"n": 0}

    def flaky_write(db, columns, **extra):
        legs["n"] += 1
        if legs["n"] == 2:
            raise RuntimeError("the disk filled up between the two legs")
        return write(db, columns, **extra)

    monkeypatch.setattr(crud, "store_transaction", flaky_write)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            pac.execute_due(db, as_of=datetime.date(2026, 1, 10))

    # Nothing from the crashed occurrence survives it: not the first leg, not
    # the occurrence key that would retire it, not the carry it had already
    # deducted from.
    with SessionLocal() as db:
        assert crud.get_transactions(db) == []
        assert crud.get_plan_occurrences_executed(db, crud.get_accumulation_plans(db)[0].id) == set()
        assert (crud.get_accumulation_plans(db)[0].carried_remainder or 0.0) == 0.0

    # And the next run, with the disk fixed, buys the whole mix.
    monkeypatch.setattr(crud, "store_transaction", write)
    with SessionLocal() as db:
        created = pac.execute_due(db, as_of=datetime.date(2026, 1, 10))["created"]
        assert sorted(t.symbol for t in created) == ["AAA", "BBB"]
        assert {t.plan_occurrence for t in created} == {"2026-01-05"}


def test_a_starved_target_is_reported_not_silently_skipped(client, monkeypatch):
    """The declared limit made visible: the plan still runs, but it says which
    fund it bought nothing of and why."""
    iid = _institution(client)
    _plan(
        client,
        iid,
        amount=400,
        start="2026-01-05",
        targets=[
            {"symbol": "CHEAP", "institution_id": iid, "weight": 70},
            {"symbol": "DEAR", "institution_id": iid, "weight": 30},
        ],
    )
    prices_by_symbol = {"CHEAP": 100.0, "DEAR": 250.0}
    monkeypatch.setattr(
        prices,
        "get_price_on",
        lambda s, on: {"symbol": s, "price": prices_by_symbol[s], "as_of": on.isoformat()},
    )
    with SessionLocal() as db:
        result = pac.execute_due(db, as_of=datetime.date(2026, 1, 10))
        # Read inside the session: `created` holds live ORM rows, and the
        # occurrence's commit expires them, so a symbol read after the session
        # closed is a detached-instance error rather than an assertion.
        assert [t.symbol for t in result["created"]] == ["CHEAP"]
    assert "DEAR" in result["skipped"][0]["reason"]


def test_the_change_is_carried_to_the_next_contribution(client, monkeypatch):
    """A standing order does not throw its change away. Without this, 800 EUR a
    month against a 168 EUR fund buys 4 units forever and quietly leaves 128
    behind every single time."""
    iid = _institution(client)
    _plan(client, iid, amount=800, start="2026-01-05")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(168.0))

    with SessionLocal() as db:
        created = pac.execute_due(db, as_of=datetime.date(2026, 3, 10))["created"]
        assert [t.quantity for t in created] == [4, 5, 5]
        plan = crud.get_accumulation_plans(db)[0]
        # 2400 contributed, 2352 invested, 48 waiting for next month
        assert plan.carried_remainder == round(2400 - 14 * 168.0, 2)


def test_carrying_the_change_does_not_win_a_race_the_target_keeps_losing(client, monkeypatch):
    """The limit of the fix, measured rather than assumed.

    Carrying the change fixes money LEFT OVER. It does not fix a target that
    keeps losing: with 400 a month, 70/30, at 100 and 250, the greedy fill
    always finds four 100-EUR units to buy, spends the contribution exactly,
    and leaves nothing to carry — so the 250 fund is never reached, month after
    month. Buying it would need the allocator to HOLD BACK its share instead of
    spending it on whatever fits, which trades one cost (an unbought target)
    for another (cash sitting idle). That choice is not made here."""
    iid = _institution(client)
    _plan(
        client, iid, amount=400, start="2026-01-05",
        targets=[
            {"symbol": "CHEAP", "institution_id": iid, "weight": 70},
            {"symbol": "DEAR", "institution_id": iid, "weight": 30},
        ],
    )
    px = {"CHEAP": 100.0, "DEAR": 250.0}
    monkeypatch.setattr(
        prices, "get_price_on",
        lambda s, on: {"symbol": s, "price": px[s], "as_of": on.isoformat()},
    )
    with SessionLocal() as db:
        created = pac.execute_due(db, as_of=datetime.date(2026, 6, 10))["created"]
        bought = {}
        for t in created:
            bought[t.symbol] = bought.get(t.symbol, 0) + t.quantity
    assert bought.get("DEAR", 0) == 0, "if this now passes, the allocator policy changed"
    assert bought.get("CHEAP", 0) == 4 * 6, "the contribution is spent exactly, every month"


def _contributions_due(amount: float, start: str, as_of: datetime.date) -> float:
    """What a monthly plan has been given by `as_of` — one contribution per
    elapsed occurrence, which is the ceiling on what it can honestly spend."""
    occ = datetime.date.fromisoformat(start)
    n = 0
    while occ <= as_of:
        n += 1
        occ = analytics.add_months(occ, 1)
    return n * amount


def test_running_the_catch_up_twice_at_one_date_buys_nothing_the_second_time(
    client, monkeypatch
):
    """Idempotence is the whole contract of the catch-up: it runs at every app
    start, so "again, same day" has to be a no-op.

    It was not, for a plan whose contribution cannot buy a whole unit. Being
    done was derived from having bought — the occurrence key lives on the
    Transaction — so an occurrence that ran, folded its 100 into the carry and
    bought nothing was indistinguishable from one that had never run. It came
    back on the next run with a FRESH contribution, on top of a carry a later
    occurrence had already spent."""
    iid = _institution(client)
    _plan(client, iid, amount=100, start="2026-01-15")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(150.0))
    as_of = datetime.date(2026, 2, 20)  # January and February are both due

    def state():
        with SessionLocal() as db:
            txs = crud.get_transactions(db)
            return (
                sum(t.quantity for t in txs),
                round(sum(t.amount for t in txs), 2),
                crud.get_accumulation_plans(db)[0].carried_remainder,
            )

    with SessionLocal() as db:
        pac.execute_due(db, as_of=as_of)
    first = state()
    # 200 contributed, one 150 unit bought, 50 waiting.
    assert first == (1.0, 150.0, 50.0)

    for _ in range(3):
        with SessionLocal() as db:
            assert pac.execute_due(db, as_of=as_of)["created"] == []
        assert state() == first, "a restart re-executed an occurrence that had already run"


def test_a_plan_never_spends_more_than_it_has_been_given(client, monkeypatch):
    """The invariant the bug broke, and the one worth stating out loud: across
    any number of runs, at any date, a plan cannot have invested more than the
    contributions it has received by then. It bought a second 150 unit out of
    two 100 contributions."""
    iid = _institution(client)
    _plan(client, iid, amount=100, start="2026-01-15")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(150.0))

    for month in range(1, 7):
        as_of = datetime.date(2026, month, 20)
        for _ in range(2):  # twice at each date: the app gets restarted
            with SessionLocal() as db:
                pac.execute_due(db, as_of=as_of)
        with SessionLocal() as db:
            spent = round(sum(t.amount for t in crud.get_transactions(db)), 2)
            carry = crud.get_accumulation_plans(db)[0].carried_remainder
        due = _contributions_due(100, "2026-01-15", as_of)
        assert spent <= due, f"{as_of}: spent {spent} of {due} contributed"
        # And nothing evaporates: what was not invested is still carried.
        assert round(spent + carry, 2) == due, f"{as_of}: {spent} + {carry} != {due}"


def test_deleting_an_auto_created_buy_puts_its_occurrence_back_in_the_queue(
    client, monkeypatch
):
    """The asymmetry is deliberate, and it is the reason only UNFILLED
    occurrences get a record of their own.

    An occurrence that bought is still recognised by its transactions, so
    removing the buy is how a saver says "not this one, do it again". An
    occurrence that bought nothing has no transaction to remove — its record is
    the only thing that remembers it ran, and it is not a buy to be undone."""
    iid = _institution(client)
    _plan(client, iid, amount=100, start="2026-01-15")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(150.0))
    as_of = datetime.date(2026, 2, 20)

    with SessionLocal() as db:
        pac.execute_due(db, as_of=as_of)
        plan_id = crud.get_accumulation_plans(db)[0].id
        # January ran and could not afford a unit; February bought with the
        # 100 January carried forward.
        assert crud.get_plan_occurrences_settled(db, plan_id) == {"2026-01-15", "2026-02-15"}
        tx_id = [t.id for t in crud.get_transactions(db) if t.plan_id][0]

    with SessionLocal() as db:
        crud.delete_transaction(db, tx_id)
        assert crud.get_plan_occurrences_settled(db, plan_id) == {"2026-01-15"}

    with SessionLocal() as db:
        again = pac.execute_due(db, as_of=as_of)["created"]
        assert [t.plan_occurrence for t in again] == ["2026-02-15"]


def test_an_unfilled_occurrence_keeps_the_reason_it_bought_nothing(client, monkeypatch):
    """Settling it on the first run is what stops the double spend, and it also
    takes the explanation out of every later run's `skipped`. Nothing else
    remembers, so the record carries the sentence the run reported — otherwise
    the fix would leave the app knowing less than the bug did."""
    iid = _institution(client)
    _plan(client, iid, amount=100, start="2026-01-15")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(150.0))

    with SessionLocal() as db:
        first = pac.execute_due(db, as_of=datetime.date(2026, 1, 20))
        assert "cannot buy a whole unit" in first["skipped"][0]["reason"]

    with SessionLocal() as db:
        # Gone from the run's report, because the occurrence is no longer due...
        assert pac.execute_due(db, as_of=datetime.date(2026, 1, 20))["skipped"] == []
        # ...and kept where it can still be answered from.
        plan = crud.get_accumulation_plans(db)[0]
        [row] = plan.unfilled_occurrences
        assert row.occurrence == "2026-01-15"
        assert "cannot buy a whole unit of any target (cheapest is 150.00 EUR)" in row.reason
        # The contribution it absorbed is on disk with it, not lost with the run.
        assert plan.carried_remainder == 100.0


def test_a_fractional_plan_never_carries_anything(client, monkeypatch):
    """It spends the contribution exactly, so there is no change to carry and a
    balance would be a fiction."""
    iid = _institution(client)
    _plan(client, iid, amount=800, start="2026-01-05", execution="fractional")
    monkeypatch.setattr(prices, "get_price_on", _fake_price(168.0))
    with SessionLocal() as db:
        pac.execute_due(db, as_of=datetime.date(2026, 2, 10))
        assert crud.get_accumulation_plans(db)[0].carried_remainder == 0.0
