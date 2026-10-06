"""A new situation that starts from the previous one.

The rule this exists for: the newest snapshot is the authority for the whole
institution, so one that omits a position deletes it. Updating a single number
otherwise means re-declaring the entire account from memory.
"""

from __future__ import annotations

import datetime

import pytest

from app import fx, prices

TODAY = datetime.date.today().isoformat()
LAST_MONTH = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()


@pytest.fixture(autouse=True)
def _ecb(monkeypatch):
    """Every account below holds Coca-Cola in USD, so every test here crosses the
    FX layer. State the rate: leaving it out passed only because no rates at
    all also means no conversion — the same answer for a different reason, and
    one that would move the day a rate arrived."""
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {"2026-08-22": {"USD": 1.1681}}
    )


def _account(client) -> tuple[int, int]:
    """An institution whose latest situation holds two tracked positions and
    one opaque amount, a mix a real account often has."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LAST_MONTH}
    ).json()["id"]
    for payload in (
        {"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
         "symbol": "VWCE.MI", "isin": "IE00BK5BQT80", "quantity": 20,
         "unit_price": 100, "distribution_policy": "acc", "currency": "EUR"},
        {"asset_name": "Coca-Cola", "asset_class": "equity", "symbol": "KO",
         "quantity": 2, "unit_price": 50, "currency": "USD"},
        {"asset_name": "Bitcoin", "asset_class": "crypto", "value": 150, "currency": "EUR"},
    ):
        r = client.post(f"/api/snapshots/{sid}/holdings", json=payload)
        assert r.status_code == 201, r.text
    return iid, sid


def _quotes(mapping: dict[str, float]):
    def fake(symbols):
        return {
            s: {"symbol": s, "price": mapping[s], "as_of": TODAY}
            for s in symbols
            if s in mapping
        }

    return fake


def test_it_starts_from_the_previous_positions(client, monkeypatch):
    iid, _ = _account(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0, "KO": 90.0}))

    body = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    ).json()
    holdings = client.get(f"/api/snapshots/{body['id']}/holdings").json()

    assert len(holdings) == 3  # nothing was lost by being forgotten
    assert body["copied_from"] == LAST_MONTH
    by_name = {h["asset_name"]: h for h in holdings}
    # Identity is copied — only the user can know WHICH instruments and HOW MANY
    assert by_name["Vanguard All-World"]["quantity"] == 20
    assert by_name["Vanguard All-World"]["isin"] == "IE00BK5BQT80"
    assert by_name["Vanguard All-World"]["distribution_policy"] == "acc"
    assert by_name["Coca-Cola"]["currency"] == "USD"


def test_everything_the_market_knows_is_valued_at_the_new_date(client, monkeypatch):
    """A photograph dated today holding last month's prices is exactly what made
    P/L collapse to zero. The clone must not recreate it."""
    iid, _ = _account(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0, "KO": 90.0}))

    body = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    ).json()
    by_name = {
        h["asset_name"]: h
        for h in client.get(f"/api/snapshots/{body['id']}/holdings").json()
    }
    assert by_name["Vanguard All-World"]["unit_price"] == 110.0
    assert by_name["Vanguard All-World"]["value"] == 20 * 110.0
    assert by_name["Coca-Cola"]["value"] == 2 * 90.0
    assert sorted(body["repriced"]) == ["KO", "VWCE.MI"]


def test_it_names_the_rows_that_still_need_a_human(client, monkeypatch):
    """The whole point: out of three rows, only one is actually asking for you."""
    iid, _ = _account(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0, "KO": 90.0}))

    body = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    ).json()
    assert body["needs_attention"] == ["Bitcoin"]
    # and it is carried over untouched rather than guessed at
    by_name = {
        h["asset_name"]: h
        for h in client.get(f"/api/snapshots/{body['id']}/holdings").json()
    }
    assert by_name["Bitcoin"]["value"] == 150 and by_name["Bitcoin"]["quantity"] is None


def test_an_unreachable_market_degrades_instead_of_failing(client, monkeypatch):
    """Offline, the situation is still created — the positions just carry their
    old values, and every one of them is reported as needing a look."""
    iid, _ = _account(client)

    def boom(_symbols):
        raise prices.PriceError("offline")

    monkeypatch.setattr(prices, "get_quotes", boom)
    r = client.post(f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY})
    assert r.status_code == 201
    body = r.json()
    assert body["repriced"] == []
    assert sorted(body["needs_attention"]) == ["Bitcoin", "Coca-Cola", "Vanguard All-World"]


def test_the_same_date_twice_is_a_conflict_not_a_duplicate(client, monkeypatch):
    iid, _ = _account(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0}))
    assert (
        client.post(
            f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
        ).status_code
        == 409
    )


def test_both_creation_paths_refuse_a_taken_date_identically(client, monkeypatch):
    """The dead end the reader hit, at the layer where it is decided.

    Once a date is taken BOTH ways in are closed — "empty" and "start from the
    last one" — because the rule is about the date, not about the button. The
    reader clicked empty, was refused, and read it as "empty is broken"; the
    form can only tell them otherwise if the two paths refuse in one voice.
    That symmetry is what was never asserted."""
    iid, _ = _account(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0}))
    assert (
        client.post(
            f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
        ).status_code
        == 201
    )

    empty = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY})
    prefilled = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    )

    assert empty.status_code == 409 and prefilled.status_code == 409
    assert empty.json()["detail"] == prefilled.json()["detail"]


def test_the_refusal_names_the_institution_not_its_id(client):
    """`_account` is called Broker B; "institution 2" is a fact about our table,
    not about the reader's money, and it is what they were shown."""
    iid, _ = _account(client)
    assert (
        client.post(
            f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
        ).status_code
        == 201
    )

    detail = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["detail"]
    assert "Broker B" in detail and TODAY in detail
    assert f"institution {iid}" not in detail


def test_moving_a_situation_onto_a_taken_date_names_it_too(client):
    """The same refusal reached by editing rather than by creating: it used to
    name neither the institution nor the date."""
    iid, source = _account(client)
    other = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]

    clash = client.put(f"/api/snapshots/{other}", json={"date": LAST_MONTH})
    assert clash.status_code == 409, clash.text
    assert "Broker B" in clash.json()["detail"]
    assert LAST_MONTH in clash.json()["detail"]
    assert client.get(f"/api/snapshots/{source}").json()["date"] == LAST_MONTH


def test_nothing_to_start_from_is_a_404(client):
    iid = client.post("/api/institutions", json={"name": "Empty"}).json()["id"]
    r = client.post(f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY})
    assert r.status_code == 404 and "nothing to start from" in r.json()["detail"]


def test_the_new_situation_becomes_the_current_one(client, monkeypatch):
    """It has to actually take over, or the whole exercise is decorative."""
    iid, _ = _account(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0, "KO": 90.0}))
    client.post(f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY})

    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    vwce = next(r for r in rows if r["symbol"] == "VWCE.MI")
    assert vwce["book_value"] == 20 * 110.0  # the new photo, not last month's


def test_it_carries_buys_made_since_the_source_photo(client, monkeypatch):
    """The bug this test exists for: copying the SOURCE rows re-asserts the old
    quantities, and because the ledger is anchored to the latest snapshot those
    buys then count as 'already in the photo' and vanish for good."""
    iid, _ = _account(client)
    r = client.post(
        "/api/transactions",
        json={"date": TODAY, "institution_id": iid, "asset_name": "Vanguard All-World",
              "symbol": "VWCE.MI", "asset_class": "fund_etf", "quantity": 5,
              "unit_price": 108, "currency": "EUR", "price_currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    assert next(
        row for row in client.get("/api/dashboard/portfolio").json()["rows"]
        if row["symbol"] == "VWCE.MI"
    )["quantity"] == 25  # 20 in the photo + 5 bought

    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0, "KO": 90.0}))
    body = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    ).json()

    cloned = {
        h["symbol"]: h for h in client.get(f"/api/snapshots/{body['id']}/holdings").json()
    }
    assert cloned["VWCE.MI"]["quantity"] == 25, "the buy was swallowed by the clone"
    assert cloned["VWCE.MI"]["value"] == 25 * 110.0
    # and it survives the round trip: the projection agrees with the new photo
    assert next(
        row for row in client.get("/api/dashboard/portfolio").json()["rows"]
        if row["symbol"] == "VWCE.MI"
    )["quantity"] == 25


def test_a_position_sold_out_of_is_not_carried(client, monkeypatch):
    """The other direction: a position walked to zero by the ledger has no place
    in a photograph of what you hold."""
    iid, _ = _account(client)
    client.post(
        "/api/transactions",
        json={"kind": "sell", "date": TODAY, "institution_id": iid,
              "asset_name": "Coca-Cola", "symbol": "KO", "asset_class": "equity",
              "quantity": 2, "unit_price": 95, "currency": "EUR", "price_currency": "EUR"},
    )
    monkeypatch.setattr(prices, "get_quotes", _quotes({"VWCE.MI": 110.0, "KO": 90.0}))
    body = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    ).json()

    names = [
        h["asset_name"]
        for h in client.get(f"/api/snapshots/{body['id']}/holdings").json()
    ]
    assert "Coca-Cola" not in names and "Vanguard All-World" in names


# --- A new photograph is a restatement, not a transaction -------------------


def _bought_after_the_photo(client) -> int:
    """One position, photographed and then added to: 10 units at 100 with 800
    recorded as their cost, plus 5 more bought for 600. The projection is 15
    units that cost 1400 and were last observed to be worth 1600."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LAST_MONTH}
    ).json()["id"]
    assert client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fondo chiuso", "asset_class": "fund_etf",
              "symbol": "OPAQUE.MI", "quantity": 10, "unit_price": 100,
              "cost_basis": 800, "currency": "EUR"},
    ).status_code == 201
    assert client.post(
        "/api/transactions",
        json={"kind": "buy", "date": TODAY, "institution_id": iid,
              "asset_name": "Fondo chiuso", "symbol": "OPAQUE.MI",
              "asset_class": "fund_etf", "quantity": 5, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201
    return iid


def _prefill(client, iid: int) -> dict:
    r = client.post(
        f"/api/institutions/{iid}/snapshots/prefilled", json={"date": TODAY}
    )
    assert r.status_code == 201, r.text
    return {h["symbol"]: h for h in
            client.get(f"/api/snapshots/{r.json()['id']}/holdings").json()}


def test_taking_a_new_situation_does_not_move_the_net_worth(client, monkeypatch):
    """THE test for this endpoint, and the one that was missing.

    A prefilled snapshot restates what is already known — it is not an event.
    Nothing was bought, sold or revalued by pressing the button, so the wealth
    on the other side of it must be the wealth on this side. It was not: the
    new photograph took its QUANTITY from the projection (15 units) and its
    VALUE from the old photograph (1000, which was 10 units' worth), so the
    act of recording a situation destroyed 600 of net worth."""
    iid = _bought_after_the_photo(client)
    monkeypatch.setattr(prices, "get_quotes", lambda syms: {})  # nothing quotes it

    before = client.get("/api/dashboard/summary").json()["net_worth"]
    assert before == 1600.0, "10 units observed at 1000, plus 600 paid for 5 more"

    _prefill(client, iid)

    assert client.get("/api/dashboard/summary").json()["net_worth"] == before


def test_the_new_photograph_says_the_same_thing_twice(client, monkeypatch):
    """Its own numbers have to agree with each other: quantity x unit price is
    the value, or one of the three is wrong. The old clone wrote 15 units at a
    unit price of 100 and a total of 1000, and 15 x 100 is 1500."""
    iid = _bought_after_the_photo(client)
    monkeypatch.setattr(prices, "get_quotes", lambda syms: {})

    row = _prefill(client, iid)["OPAQUE.MI"]
    assert row["quantity"] == 15
    assert row["value"] == 1600.0, "what the position is worth, carried whole"
    assert row["unit_price"] is not None, (
        "a quantity with no unit price re-opens in the form's total mode, "
        "which sends quantity: null — the row would lose its units on the "
        "first edit"
    )
    assert abs(row["quantity"] * row["unit_price"] - row["value"]) < 1e-9


def test_a_new_situation_does_not_forget_what_the_buys_cost(client, monkeypatch):
    """The cost of everything bought after the photo was dropped: the clone
    carried the SOURCE row's cost_basis (800, for 10 units) beside the new
    quantity (15), so 600 of money actually paid stopped being cost — and
    reappeared as profit, in a column marked cost_known."""
    iid = _bought_after_the_photo(client)
    monkeypatch.setattr(prices, "get_quotes", _quotes({"OPAQUE.MI": 130.0}))

    row = _prefill(client, iid)["OPAQUE.MI"]
    assert row["cost_basis"] == 1400.0, "800 recorded + 600 paid since"

    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})
    after = next(
        r for r in client.get(
            "/api/dashboard/portfolio", params={"live": "true"}
        ).json()["rows"]
        if r["symbol"] == "OPAQUE.MI"
    )
    assert after["book_value"] == 1400.0
    assert abs(after["avg_cost"] - 1400 / 15) < 1e-9
    assert after["cost_known"] is True
    assert after["delta"] == 15 * 130.0 - 1400.0, (
        "the gain against what was paid — carrying the old 800 reported the "
        "600 the user spent as 600 of profit, in a column marked cost_known"
    )


def test_an_unknown_cost_is_not_invented_by_taking_a_new_situation(client, monkeypatch):
    """The other half of the same rule. When the source photo recorded no cost,
    the projection's book is the photograph's value plus the buys — a blend,
    and this app does not call a blend a cost. The new photograph must carry
    no cost at all rather than write that number down as one."""
    iid = client.post("/api/institutions", json={"name": "Broker C"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LAST_MONTH}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Fondo chiuso", "asset_class": "fund_etf",
              "symbol": "OPAQUE.MI", "quantity": 10, "unit_price": 100,
              "currency": "EUR"},
    )
    client.post(
        "/api/transactions",
        json={"kind": "buy", "date": TODAY, "institution_id": iid,
              "asset_name": "Fondo chiuso", "symbol": "OPAQUE.MI",
              "asset_class": "fund_etf", "quantity": 5, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
    )
    monkeypatch.setattr(prices, "get_quotes", lambda syms: {})

    assert _prefill(client, iid)["OPAQUE.MI"]["cost_basis"] is None
    after = next(r for r in client.get("/api/dashboard/portfolio").json()["rows"]
                 if r["symbol"] == "OPAQUE.MI")
    assert after["cost_known"] is False


def test_a_foreign_currency_row_is_restated_in_its_own_currency(client, monkeypatch):
    """The projection computes in EUR; a photograph is written in the currency
    the row is denominated in. Storing the EUR figure under a USD row does not
    only mislabel it — the next projection converts it AGAIN, so the position
    shrinks by the exchange rate every time a situation is recorded, and the
    net worth with it."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": LAST_MONTH}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Coca-Cola", "asset_class": "equity", "symbol": "KO",
              "quantity": 10, "unit_price": 100, "currency": "USD"},
    )
    client.post(
        "/api/transactions",
        json={"kind": "buy", "date": TODAY, "institution_id": iid,
              "asset_name": "Coca-Cola", "symbol": "KO", "asset_class": "equity",
              "quantity": 5, "unit_price": 120, "currency": "EUR", "price_currency": "EUR"},
    )
    monkeypatch.setattr(prices, "get_quotes", lambda syms: {})

    before = client.get("/api/dashboard/summary").json()["net_worth"]
    row = _prefill(client, iid)["KO"]

    assert row["currency"] == "USD", "the photograph keeps its own denomination"
    assert abs(row["quantity"] * row["unit_price"] - row["value"]) < 1e-9
    assert row["value"] > 1000, "1000 USD photographed plus 600 EUR of units"
    assert abs(client.get("/api/dashboard/summary").json()["net_worth"] - before) < 1e-9
