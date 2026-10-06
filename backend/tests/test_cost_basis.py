"""What a position cost, told apart from what it is worth.

`value` used to answer four questions at once — three consumers wanted "what is
it worth" and one wanted "what did it cost", and all four got "what the
photograph said". These tests hold the two apart.
"""

from __future__ import annotations

import datetime

from app import prices

TODAY = datetime.date.today().isoformat()


def _held(client, **extra) -> tuple[int, int]:
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    payload = {"currency": "EUR", 
        "asset_name": "Vanguard All-World", "asset_class": "fund_etf",
        "symbol": "VWCE.MI", "quantity": 10, "unit_price": 150, **extra,
    }
    r = client.post(f"/api/snapshots/{sid}/holdings", json=payload)
    assert r.status_code == 201, r.text
    return iid, sid


def _row(client):
    return client.get("/api/dashboard/portfolio").json()["rows"][0]


def test_a_recorded_cost_turns_movement_into_profit(client):
    """Without it the position is worth 1500 and "cost" is 150 a unit, which is
    just where the photo was taken. With it, the 900 actually paid is the basis
    and the difference is a real gain."""
    _held(client)
    assert _row(client)["cost_known"] is False

    _held(client)  # a second institution, this time with the cost recorded
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": "2026-01-10"}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Coca-Cola", "asset_class": "equity", "symbol": "KO",
              "quantity": 10, "unit_price": 150, "cost_basis": 900, "currency": "EUR"},
    )
    row = next(r for r in client.get("/api/dashboard/portfolio").json()["rows"]
               if r["symbol"] == "KO")
    assert row["cost_known"] is True
    assert row["book_value"] == 900.0
    assert abs(row["avg_cost"] - 90.0) < 1e-9


def test_an_unknown_cost_is_never_inferred_from_the_value(client):
    """The failure this column exists to end: silence must read as "unknown",
    not as "the photograph's value happens to be the price you paid"."""
    _held(client)
    row = _row(client)
    assert row["cost_known"] is False
    assert row["book_value"] == 1500.0  # the photo still values the position


def test_a_derived_cost_says_that_it_is_derived(client):
    """A cost worked back from a broker's reported % return is a real number but
    not a verified one, and the row has to carry the difference."""
    _held(client, cost_basis=900, cost_estimated=True)
    row = _row(client)
    assert row["cost_known"] is True and row["cost_estimated"] is True


def test_a_buy_on_top_of_a_recorded_cost_stays_a_real_cost(client):
    """Cost plus cost is still cost — unlike photo plus cost, which is a blend."""
    iid, _ = _held(client, cost_basis=900)
    client.post(
        "/api/transactions",
        json={"date": TODAY, "institution_id": iid, "asset_name": "Vanguard All-World",
              "symbol": "VWCE.MI", "quantity": 5, "unit_price": 100, "currency": "EUR", "price_currency": "EUR"},
    )
    row = _row(client)
    assert row["cost_known"] is True
    assert row["book_value"] == 900.0 + 500.0
    assert abs(row["avg_cost"] - (1400 / 15)) < 1e-9


def test_the_cost_survives_a_new_situation(client, monkeypatch):
    """The whole point. Re-pricing the VALUE while dropping the COST is what
    made every new photograph forget what you paid — so cloning would have
    silently reset the basis to the market and wiped the gain."""
    iid, _ = _held(client, cost_basis=900)
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 200.0, "as_of": TODAY} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    body = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    ).json()
    cloned = client.get(f"/api/snapshots/{body['id']}/holdings").json()[0]
    assert cloned["value"] == 10 * 200.0, "the value must follow the market"
    assert cloned["cost_basis"] == 900.0, "the cost must NOT"

    row = _row(client)
    assert row["cost_known"] is True and row["book_value"] == 900.0


def test_net_worth_uses_the_market_and_declares_how_much(client, monkeypatch):
    """Recording real costs must not make you poorer on paper. Net worth counts
    what things are worth; the basis is only for the P/L."""
    iid, sid = _held(client, cost_basis=900)
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Gold bar", "asset_class": "commodity", "value": 400, "currency": "EUR"},
    )
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 200.0, "as_of": TODAY} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    client.get("/api/dashboard/portfolio", params={"live": "true"})  # fill the cache

    s = client.get("/api/dashboard/summary").json()
    assert s["investments_total"] == 2000.0 + 400.0  # market, not the 900 basis
    assert s["investments_at_market"] == 2000.0
    assert s["investments_at_book"] == 400.0  # the bar nothing can price, declared


def test_todays_point_of_the_series_agrees_with_net_worth(client, monkeypatch):
    """Two numbers on the same screen that mean the same thing must be equal."""
    iid, _ = _held(client, cost_basis=900)
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 200.0, "as_of": TODAY} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    client.get("/api/dashboard/portfolio", params={"live": "true"})

    summary = client.get("/api/dashboard/summary").json()
    series = client.get("/api/dashboard/net-worth-series").json()
    assert series[-1]["date"] == TODAY
    assert abs(series[-1]["net_worth"] - summary["net_worth"]) < 1e-9


def test_the_allocation_totals_what_the_summary_totals(client, monkeypatch):
    """The same rule, one line further down the Dashboard.

    Net worth was taught to count what things are WORTH; the allocation
    underneath it was still counting what they COST, so the two financial
    totals on one screen disagreed by the whole unrealised gain — around 6% of
    the total on a portfolio it was measured against. An allocation is a risk
    view: it has to answer what you hold.
    """
    iid, sid = _held(client, cost_basis=900)  # 10 units, 900 paid
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Gold bar", "asset_class": "commodity", "value": 400, "currency": "EUR"},
    )
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": TODAY, "amount": 250, "currency": "EUR"}
    )
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 200.0, "as_of": TODAY} for s in syms},
    )
    # The listing's own currency, stated. Left un-faked these figures came out
    # right only because nobody answered and an unknown currency is treated as
    # EUR: the right number for the wrong reason, and one that would have gone
    # the other way the day Yahoo said USD.
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    client.get("/api/dashboard/portfolio", params={"live": "true"})  # fill the cache

    summary = client.get("/api/dashboard/summary").json()
    allocation = client.get("/api/dashboard/allocation").json()

    # 2000 at market, not the 900 basis — and the gold bar and the cash are in
    # both totals, so this cannot pass by both sides being wrong the same way.
    by_class = {s["asset_class"]: s["value"] for s in allocation["by_asset_class"]}
    assert by_class["fund_etf"] == 2000.0
    assert by_class["commodity"] == 400.0
    assert by_class["cash"] == 250.0
    assert abs(allocation["financial_total"] - summary["financial_total"]) < 1e-9


# --- The other direction: what it is worth, when nothing can price it -------

PHOTO_DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()


def _opaque_with_a_recorded_cost(client) -> int:
    """A photograph that says 500 and a receipt that says 400, on a position
    the market cannot price: a ticker nothing quotes (offline, so nothing is
    quoted at all), 10 units, and a cost the user actually recorded."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": PHOTO_DAY}
    ).json()["id"]
    r = client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fondo chiuso", "asset_class": "fund_etf",
              "symbol": "OPAQUE.MI", "quantity": 10, "unit_price": 50,
              "cost_basis": 400, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    return iid


def test_what_it_is_worth_does_not_fall_back_to_what_it_cost(client):
    """The chart and the Dashboard must answer the same question the history
    answers, and the question is what the position is WORTH.

    A photograph is an observation of value: on the day it was taken, 500 is
    what this position was worth, and 400 is a different fact about it — the
    price that was paid, which the P/L is measured against. `current_value`
    falls back to the book when the market cannot price a row, and the book is
    the COST, so today's number quietly answered the cost question while every
    historical point answered the value one. The two mechanisms disagreed
    before and they disagree now: making the history run on `project()` did
    not introduce this, it made it visible, because the same series now shows
    both answers — 500 all the way along and 400 on the last day."""
    _opaque_with_a_recorded_cost(client)

    series = client.get("/api/dashboard/net-worth-series").json()
    by_date = {pt["date"]: round(pt["financial"], 6) for pt in series}
    assert by_date[PHOTO_DAY] == 500.0, "the history says what the photo said"
    assert by_date[TODAY] == 500.0, "and today must not answer a different question"

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 500.0
    assert summary["investments_at_book"] == 500.0, (
        "declared as un-priced, at its observed value — not at its cost"
    )


def test_an_unpriced_row_publishes_what_it_is_worth_and_claims_no_profit(client, monkeypatch):
    """The decision this fix forced, pinned.

    A row nothing can price now has two numbers that differ: the photograph
    said 500, the receipt said 400. `delta` — the column the UI labels "P/L vs
    recorded" — stays NULL there, because on every other row that column means
    "a live market against what you paid", and a month-old broker statement
    entering it as +100 of green would be one kind of fact wearing another's
    clothes. What the row does instead is publish both numbers, so the
    difference is visible to anyone who wants it and asserted by nobody.

    That has a consequence worth stating out loud rather than discovering: the
    portfolio's two totals no longer differ by the sum of the delta column. The
    gap is exactly the unpriced rows' observed − cost, and this test measures
    it, because a total whose parts cannot be traced is the failure this whole
    change exists to end."""
    _opaque_with_a_recorded_cost(client)  # photo 500, cost 400, nothing quotes it
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": PHOTO_DAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100,
              "cost_basis": 800, "currency": "EUR"},
    )
    # Only one of the two symbols has a quote: the other is the row under test.
    monkeypatch.setattr(
        prices, "get_quotes",
        lambda syms: {"VWCE.MI": {"symbol": "VWCE.MI", "price": 120.0, "as_of": TODAY}},
    )
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    p = client.get("/api/dashboard/portfolio", params={"live": "true"}).json()

    opaque = next(r for r in p["rows"] if r["symbol"] == "OPAQUE.MI")
    assert opaque["book_value"] == 400.0, "what the receipt said"
    assert opaque["observed_value"] == 500.0, "what the statement said"
    assert opaque["market_value"] is None, "and the market said nothing"
    assert opaque["delta"] is None and opaque["delta_pct"] is None, (
        "no quote, no P/L: the movement is there to be read off the two "
        "figures, not asserted in the column that means market-versus-cost"
    )

    priced = next(r for r in p["rows"] if r["symbol"] == "VWCE.MI")
    assert priced["market_value"] == 1200.0
    assert priced["delta"] == 400.0, "1200 at market against the 800 paid"

    assert p["total_book"] == 1200.0, "400 + 800, both of them costs"
    assert p["total_market"] == 1700.0, "1200 at market + 500 last observed"
    column = sum(r["delta"] for r in p["rows"] if r["delta"] is not None)
    assert p["total_market"] - p["total_book"] - column == 100.0, (
        "the two totals differ from the delta column by exactly the unpriced "
        "row's observed − cost, and the row carries both so it can be shown"
    )


def test_the_observed_value_walks_the_ledger_like_the_book_does(client):
    """Two openings, one set of entries — and the entries really are applied.

    The value reading is not the photograph frozen: a purchase after the photo
    adds what it cost to BOTH walks, or the row would report last month's worth
    forever while its book grew. Photo 1000 for 10 units with 800 recorded as
    the cost, then 5 more units for 600: the receipt total is 1400 and the
    observed total is 1600, and the difference is the 200 of gain the
    photograph had already recorded."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": PHOTO_DAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fondo chiuso", "asset_class": "fund_etf",
              "symbol": "OPAQUE.MI", "quantity": 10, "unit_price": 100,
              "cost_basis": 800, "currency": "EUR"},
    )
    assert client.post(
        "/api/transactions",
        json={"kind": "buy", "date": TODAY, "institution_id": iid,
              "asset_name": "Fondo chiuso", "symbol": "OPAQUE.MI",
              "asset_class": "fund_etf", "quantity": 5, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201

    row = next(r for r in client.get("/api/dashboard/portfolio").json()["rows"]
               if r["symbol"] == "OPAQUE.MI")
    assert row["quantity"] == 15
    assert row["book_value"] == 1400.0, "800 paid before, 600 paid now"
    assert row["observed_value"] == 1600.0, "1000 observed before, 600 paid now"
    assert client.get("/api/dashboard/summary").json()["investments_total"] == 1600.0


def test_a_photograph_that_recorded_no_value_is_not_an_observation_of_zero(client):
    """The quantity form takes a price, and does not insist on one.

    A holding entered as "10 units, cost 400" with no unit price photographs a
    quantity and no value. Opening the value walk at that zero reported the
    position as worth nothing — net worth, allocation and every point of the
    chart included — while the row went on saying it cost 400. No photographed
    value is not a value of zero: it is no observation, and then what was paid
    is the only one there is, exactly as for a position born in the ledger."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": PHOTO_DAY}
    ).json()["id"]
    assert client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Azioni", "asset_class": "equity", "symbol": "OPQ.MI",
              "quantity": 10, "cost_basis": 400, "currency": "EUR"},
    ).status_code == 201

    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["book_value"] == 400.0 and row["observed_value"] == 400.0
    assert client.get("/api/dashboard/summary").json()["investments_total"] == 400.0


def test_a_cost_typed_on_a_lump_is_a_cost_while_you_hold_it(client):
    """If you typed a cost, that is the cost — units or no units.

    A "Totale €" row (no quantity, no ticker) accepts a purchase price: the
    form offers the field and the API stores it. The projection then read it
    in exactly one place — the branch that disposes of the position — so the
    same holding said "cost unknown" for as long as you held it and measured
    its realized gain against the recorded 400 the moment you closed it. One
    figure, in the database the whole time, with two opposite answers
    depending on whether you had sold.

    Answering it while held costs nothing now and would have cost the totals
    before: with `current_value` falling back to the book, making book_value
    the 400 would have taken 100 out of the net worth. It falls back to
    `observed_value`, so the receipt can be the cost and the statement can
    still be the worth."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": PHOTO_DAY}
    ).json()["id"]
    assert client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fondo chiuso", "asset_class": "fund_etf",
              "value": 500, "cost_basis": 400, "currency": "EUR"},
    ).status_code == 201

    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert row["cost_known"] is True, "you wrote the cost down"
    assert row["book_value"] == 400.0, "and that is what it cost"
    assert row["observed_value"] == 500.0, "while the photograph still says 500"

    # And the totals do not move: worth is not cost.
    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 500.0
    assert summary["net_worth"] == 500.0


def test_the_lump_answers_the_same_before_and_after_it_is_closed(client):
    """The two answers were the contradiction; one of them was already right.
    Closing it at 900 realizes 500 against the recorded 400 — and that number
    must not depend on the disposal having happened."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": PHOTO_DAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fondo chiuso", "asset_class": "fund_etf",
              "value": 500, "cost_basis": 400, "currency": "EUR"},
    )
    held = client.get("/api/dashboard/portfolio").json()["rows"][0]

    client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Fondo chiuso", "amount": 900, "currency": "EUR"},
    )
    closed = client.get("/api/dashboard/portfolio").json()["rows"][0]

    assert held["cost_known"] == closed["cost_known"] is True
    assert closed["realized_pl"] == 500.0, "900 against the 400 recorded"
    assert closed["book_value"] == 0.0, "gone: the exit is on record"
