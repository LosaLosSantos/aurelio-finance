"""A photograph cannot describe a day that has not happened.

Every number this app reports about NOW is the latest dated row *in force*.
For a while it was the latest dated row *there is*, and the two are only the
same question until somebody types a date in the future. One empty snapshot
dated eleven days out reported a 1,000.00 portfolio as holding nothing; one
999,999.00 balance on the same date took a 120,000.00 net worth to -999,998.00.
Both were accepted with a 201.

There are two halves and they are tested apart, because either one alone is
still a hole:

* the READ is bounded at today, which is what makes a row like that inert;
* the WRITE refuses one, which is what stops it being created and then
  silently ignored — the outcome a bounded read would otherwise have produced
  on its own, and the one silence this codebase refuses everywhere else.

The read tests therefore write their future rows STRAIGHT TO THE TABLES. The
API will not make one any more, and that is the point: the rows under test are
the ones already in a database from before it refused, which is exactly the
row the reader has.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from app import advisor, analytics, dated, models, positions, tools
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()
LAST_MONTH = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
NEXT_WEEK = (datetime.date.today() + datetime.timedelta(days=11)).isoformat()


# --- Fixtures ---------------------------------------------------------------


def _wealth(client) -> dict[str, int]:
    """A month-old photograph of everything: 1,000.00 invested, a 200,000.00
    house, an 80,000.00 mortgage and 500.00 of cash."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LAST_MONTH}
    ).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Vanguard All-World",
            "symbol": "VWCE.MI",
            "asset_class": "fund_etf",
            "quantity": 10,
            "value": 1000.0,
            "currency": "EUR",
        },
    )
    assert r.status_code == 201, r.text
    rid = client.post(
        "/api/real-assets", json={"name": "Milan flat", "category": "real_estate", "currency": "EUR"}
    ).json()["id"]
    client.post(
        f"/api/real-assets/{rid}/valuations",
        json={"date": LAST_MONTH, "value": 200_000.0},
    )
    lid = client.post(
        "/api/liabilities", json={"name": "Mutuo", "kind": "mortgage", "currency": "EUR"}
    ).json()["id"]
    client.post(
        f"/api/liabilities/{lid}/balances",
        json={"date": LAST_MONTH, "balance": 80_000.0},
    )
    client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": LAST_MONTH, "amount": 500.0, "currency": "EUR"},
    )
    return {"institution": iid, "snapshot": sid, "real_asset": rid, "liability": lid}


def _write_rows_dated_next_week(ids: dict[str, int]) -> None:
    """The four rows the API used to accept, put where it used to put them."""
    with SessionLocal() as db:
        db.add(models.Snapshot(institution_id=ids["institution"], date=NEXT_WEEK))
        db.add(
            models.RealAssetValuation(
                real_asset_id=ids["real_asset"], date=NEXT_WEEK, value=1.0
            )
        )
        db.add(
            models.LiabilityBalance(
                liability_id=ids["liability"], date=NEXT_WEEK, balance=999_999.0
            )
        )
        db.add(
            models.CashAnchor(
                institution_id=ids["institution"], date=NEXT_WEEK, amount=99_999.0, currency="EUR"
            )
        )
        db.commit()


# --- 1. The read is bounded at today ----------------------------------------


def test_a_photograph_of_next_week_does_not_change_what_is_held_today(client):
    """The one that matters. Nothing was sold and no day has passed, so every
    total says exactly what it said before the rows existed."""
    ids = _wealth(client)
    before = client.get("/api/dashboard/summary").json()
    assert (
        before["investments_total"],
        before["real_total"],
        before["liabilities_total"],
    ) == (1000.0, 200_000.0, 80_000.0)

    _write_rows_dated_next_week(ids)

    after = client.get("/api/dashboard/summary").json()
    for series in (
        "investments_total",
        "real_total",
        "liabilities_total",
        "cash_total",
        "net_worth",
    ):
        assert after[series] == before[series], (
            f"{series} moved because of a row dated {NEXT_WEEK}"
        )
    # And the position is still THERE, not merely still totalled: an empty
    # photograph read as current does not zero a total, it deletes the rows.
    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    assert [r["symbol"] for r in rows] == ["VWCE.MI"]


def test_the_data_is_not_claimed_to_be_fresher_than_it_is(client):
    """`as_of` says how recent the newest figure behind the summary is. Read
    unbounded it answered with the future date, which is a claim to know
    something about a day nobody has lived through."""
    ids = _wealth(client)
    _write_rows_dated_next_week(ids)
    assert client.get("/api/dashboard/summary").json()["as_of"] == LAST_MONTH


def test_the_allocation_agrees_with_the_summary_about_the_house(client):
    """The dashboard's two views of real wealth read the same series, and both
    are bounded — fixing one alone would have put two different numbers for the
    same house on the same screen."""
    ids = _wealth(client)
    _write_rows_dated_next_week(ids)
    summary = client.get("/api/dashboard/summary").json()
    allocation = client.get("/api/dashboard/allocation").json()
    assert allocation["real_total"] == summary["real_total"] == 200_000.0


def test_a_new_situation_is_prefilled_from_the_photograph_in_force(client):
    """The prefill starts from the latest photograph, and "latest" has to mean
    the same thing here as everywhere else — otherwise a new situation is
    copied from a row describing next week."""
    ids = _wealth(client)
    _write_rows_dated_next_week(ids)
    r = client.post(
        f"/api/institutions/{ids['institution']}/snapshots/prefilled",
        json={"date": TODAY},
    )
    assert r.status_code == 201, r.text
    assert r.json()["copied_from"] == LAST_MONTH


def test_the_omissions_notice_does_not_report_a_drop_that_has_not_happened(client):
    """The notice that promises never to be silent, reading unbounded.

    `_unresolved_omissions` compares an institution's last two photographs and
    names what the newer one stopped mentioning. It issued its own
    `select(models.Snapshot)` instead of going through `dated`, so "the last
    two" meant the last two THERE ARE — and a row dated next week is one of
    them. The position is still held, still counted in full, and the notice
    announced that it had left, on a day nobody has lived through.

    It is the same bug as the four above and it fails in the opposite
    direction, which is why it is worth its own test: those read a future row
    and made value disappear, this one reads it and invents a disappearance.
    Both are the app claiming to know something about a day that has not
    happened, and this one does it in the sentence whose entire job is to be
    believed when value really does leave."""
    ids = _wealth(client)
    _write_rows_dated_next_week(ids)

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 1000.0, "still held, in full"
    assert summary["unresolved_omissions"] == [], (
        f"a drop was announced for {NEXT_WEEK}, against value still counted"
    )
    # The same function answers the portfolio, and the notice is rendered on
    # both pages: a bound on one of the two would leave the warning showing
    # where the rows it names are listed as held.
    portfolio = client.get("/api/dashboard/portfolio").json()
    assert portfolio["unresolved_omissions"] == []


# --- 2. The fourth series was already right and stays right -----------------


def test_the_cash_register_still_refuses_the_future_anchor(client):
    """Cash is the one series that got this right, by anchoring at `as_of` from
    the beginning. It must not be dragged into the fix — this asserts the
    behaviour that told us what right looked like."""
    ids = _wealth(client)
    _write_rows_dated_next_week(ids)
    cash = client.get(f"/api/institutions/{ids['institution']}/cash").json()
    assert cash["anchor_date"] == LAST_MONTH
    assert cash["projected"] == 500.0


# --- 3. History is the half that always worked ------------------------------


def test_the_net_worth_history_answers_a_past_day_the_same_way(client):
    """The past points pass a real `as_of` and were never wrong; a fix to the
    "now" question must leave them exactly as they are.

    Its LAST point is a different matter, and this asserts it too: the series
    ends at today, and today's point is the "now" question, asked by the same
    projection the dashboard asks. It moved with the rest — 121,000.00 to
    120,000.00 on the measurement this file was written from — while every
    earlier point stood still. Real assets and liabilities were right even
    there, because that half of the series was always a `carry_forward` bounded
    at the day being drawn."""
    ids = _wealth(client)
    before = client.get("/api/dashboard/net-worth-series").json()
    _write_rows_dated_next_week(ids)
    assert client.get("/api/dashboard/net-worth-series").json() == before


# --- 4. The write refuses, instead of accepting and ignoring ----------------


@pytest.mark.parametrize(
    "path, payload",
    [
        ("/api/institutions/{institution}/snapshots", {"date": NEXT_WEEK}),
        ("/api/institutions/{institution}/snapshots/prefilled", {"date": NEXT_WEEK}),
        ("/api/real-assets/{real_asset}/valuations", {"date": NEXT_WEEK, "value": 1.0}),
        (
            "/api/liabilities/{liability}/balances",
            {"date": NEXT_WEEK, "balance": 999_999.0},
        ),
        (
            "/api/institutions/{institution}/cash-anchors",
            {"date": NEXT_WEEK, "amount": 99_999.0},
        ),
    ],
)
def test_a_dated_row_cannot_be_recorded_for_a_day_that_has_not_happened(
    client, path, payload
):
    """All four series, and the prefill that makes a snapshot too. A bounded
    read alone would have left these 201s doing nothing at all, which is the
    silence this app refuses everywhere else."""
    ids = _wealth(client)
    r = client.post(path.format(**ids), json=payload)
    assert r.status_code == 422, r.text
    assert "has not happened yet" in r.text


def test_the_chat_cannot_propose_a_valuation_for_a_day_that_has_not_happened(client):
    """The other way in. `add_real_asset` writes into one of the four series,
    so it carries the same refusal — and carries it on its ARGUMENTS, so the
    card is refused as it is drawn rather than after the reader has confirmed
    it."""
    with pytest.raises(ValidationError) as exc:
        tools.AddRealAssetArgs(
            name="Milan flat", value=200_000.0, currency="EUR", valued_on=NEXT_WEEK
        )
    assert "has not happened yet" in str(exc.value)
    assert tools.AddRealAssetArgs(
        name="Milan flat", value=200_000.0, currency="EUR", valued_on=TODAY
    ).valued_on == datetime.date.today()


def test_today_is_allowed_because_a_photograph_taken_today_describes_today(client):
    """The boundary. `latest_on_or_before` is inclusive and must stay so; a
    refusal one day too eager would leave the app unable to record the
    present."""
    ids = _wealth(client)
    r = client.post(
        f"/api/real-assets/{ids['real_asset']}/valuations",
        json={"date": TODAY, "value": 210_000.0},
    )
    assert r.status_code == 201, r.text
    assert client.get("/api/dashboard/summary").json()["real_total"] == 210_000.0


def test_a_row_already_dated_in_the_future_can_still_be_read_and_corrected(client):
    """What happens to the row the reader already has. The refusal is on the way
    IN only: one that also blocked the way out would take away the very screen
    the row is corrected from — the list answered 500 while it did. So the row
    stays listed, and the way out is to move its date or delete it."""
    ids = _wealth(client)
    _write_rows_dated_next_week(ids)

    listed = client.get(f"/api/institutions/{ids['institution']}/snapshots").json()
    stale = next(s for s in listed if s["date"] == NEXT_WEEK)

    # Saving it back unchanged is refused, and says why.
    unchanged = client.put(f"/api/snapshots/{stale['id']}", json={"date": NEXT_WEEK})
    assert unchanged.status_code == 422
    assert "has not happened yet" in unchanged.text

    # Moving the date to a day that exists is one way out; deleting is the other.
    fixed = client.put(f"/api/snapshots/{stale['id']}", json={"date": TODAY})
    assert fixed.status_code == 200, fixed.text
    assert client.delete(f"/api/snapshots/{stale['id']}").status_code == 204


# --- 3. An event is kept for its day, and applied on it ---------------------

# 42df622 left transactions free to carry a future date, on purpose: a buy
# scheduled for next week is a fact the reader may state. What was never meant
# is for it to be APPLIED before its day. The projection read the ledger with
# no upper bound whenever it was asked about today, while the cash register
# stopped at today — so the units of a buy dated ahead arrived at once and its
# cost did not, and the net worth gained the whole purchase from nothing.
# Measured on 2026-09-15: 10 units held, a buy of 10 more dated ten days out,
# investments 1000.00 -> 2000.00 with the cash unmoved.

AHEAD = [
    pytest.param(
        {"kind": "buy", "symbol": "VWCE.MI", "asset_name": "Vanguard All-World",
         "asset_class": "fund_etf", "quantity": 10, "unit_price": 100, "currency": "EUR", "price_currency": "EUR"},
        id="a buy of the position held",
    ),
    pytest.param(
        {"kind": "sell", "symbol": "VWCE.MI", "asset_name": "Vanguard All-World",
         "quantity": 4, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
        id="a sale of part of it",
    ),
    pytest.param(
        {"kind": "close", "symbol": "VWCE.MI", "asset_name": "Vanguard All-World",
         "amount": 1100, "currency": "EUR"},
        id="a close of all of it",
    ),
    pytest.param(
        {"kind": "buy", "symbol": "EUNL.DE", "asset_name": "iShares Core World",
         "asset_class": "fund_etf", "quantity": 10, "unit_price": 9, "currency": "EUR", "price_currency": "EUR"},
        id="a buy of something never photographed",
    ),
]


def _today(client) -> dict:
    """Everything that says what is held NOW, in one comparable shape."""
    summary = client.get("/api/dashboard/summary").json()
    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    series = client.get("/api/dashboard/net-worth-series").json()
    return {
        "investments": summary["investments_total"],
        "cash": summary["cash_total"],
        "net worth": summary["net_worth"],
        "rows": sorted(
            (r["asset_name"], r["quantity"], r["book_value"], r["realized_pl"], r["closed_on"])
            for r in rows
        ),
        "series today": series[-1]["net_worth"],
    }


@pytest.mark.parametrize("entry", AHEAD)
def test_an_entry_dated_ahead_is_kept_and_changes_nothing_held_today(client, entry):
    ids = _wealth(client)
    before = _today(client)

    r = client.post(
        "/api/transactions",
        json={"currency": "EUR", "price_currency": "EUR", **entry, "date": NEXT_WEEK, "institution_id": ids["institution"]},
    )

    assert r.status_code == 201, r.text  # storing it is still allowed
    assert [t["date"] for t in client.get("/api/transactions").json()] == [NEXT_WEEK]
    assert _today(client) == before


def test_the_same_buy_counts_on_its_day_units_and_cost_together(client, monkeypatch):
    """The other edge, so the bound cannot be over-corrected into "future rows
    never count". On the day itself both halves of the purchase land at once:
    the units in the position and the cost out of the cash."""
    ids = _wealth(client)
    client.post(
        "/api/transactions",
        json={"currency": "EUR", "price_currency": "EUR", **AHEAD[0].values[0], "date": NEXT_WEEK, "institution_id": ids["institution"]},
    )
    arrived = datetime.date.fromisoformat(NEXT_WEEK)
    monkeypatch.setattr(dated, "today", lambda: NEXT_WEEK)

    with SessionLocal() as db:
        held = [p for p in positions.project(db) if p.symbol == "VWCE.MI"]
        cash = analytics.compute_cash_position(db, ids["institution"], as_of=arrived)

    assert [p.quantity for p in held] == [20.0]
    assert cash["buys"] == 1000.0 and cash["projected"] == 500.0 - 1000.0


def test_a_situation_taken_today_does_not_photograph_a_buy_still_to_come(
    client, monkeypatch
):
    """Where applying it early stopped being a display error and became a
    stored one. The prefilled situation copies the projection, so it wrote the
    20 units into a photograph dated today — and when the buy's day came, the
    buy was after that photograph and was applied on top of it again. 30 units,
    with 20 bought, for good."""
    ids = _wealth(client)
    client.post(
        "/api/transactions",
        json={"currency": "EUR", "price_currency": "EUR", **AHEAD[0].values[0], "date": NEXT_WEEK, "institution_id": ids["institution"]},
    )

    r = client.post(
        f"/api/institutions/{ids['institution']}/snapshots/prefilled",
        json={"date": TODAY},
    )
    assert r.status_code == 201, r.text
    photographed = client.get(f"/api/snapshots/{r.json()['id']}/holdings").json()
    assert [(h["symbol"], h["quantity"]) for h in photographed] == [("VWCE.MI", 10.0)]

    monkeypatch.setattr(dated, "today", lambda: NEXT_WEEK)
    with SessionLocal() as db:
        held = [p for p in positions.project(db) if p.symbol == "VWCE.MI"]
    assert [p.quantity for p in held] == [20.0]


def test_the_analyst_is_not_told_that_a_buy_still_to_come_was_invested(client):
    """The one reader of now that did not go through the projection. The ledger
    digest the portfolio analysis reads summed every buy on record, so a buy
    dated ahead reached the model as money already invested — and the analyst
    reasons about allocation from exactly that sentence. The entry stays in
    front of it, with its date, and outside the count."""
    ids = _wealth(client)
    for date, quantity in ((TODAY, 5), (NEXT_WEEK, 10)):
        r = client.post(
            "/api/transactions",
            json={"currency": "EUR", "price_currency": "EUR", **AHEAD[0].values[0], "quantity": quantity, "date": date,
                  "institution_id": ids["institution"]},
        )
        assert r.status_code == 201, r.text

    with SessionLocal() as db:
        # The digest section only: since brief Z the money beside the
        # investments follows it, and its totals are not the digest's.
        digest = advisor.build_portfolio_context(db).split("## Ledger digest", 1)[1]
        digest = digest.split("\n## ", 1)[0]

    # Today counts: `(anchor, today]` is closed on the right, here as in the
    # projection above it.
    assert "- 1 buys (500.00 invested)" in digest
    assert "1500.00" not in digest
    assert f"{NEXT_WEEK} buy 10 x VWCE.MI = 1000.00" in digest
    assert "NOT counted" in digest
