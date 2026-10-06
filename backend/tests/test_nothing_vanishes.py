"""Nothing may take value out of the net worth without a line saying where it went.

Two halves of the same rule. P0d names what a newer photograph stopped
mentioning; P0c gives the rows that have no units an explicit way out, so
vanishing stops being the only exit.
"""

from __future__ import annotations

import datetime

from app import fx, prices

TODAY = datetime.date.today().isoformat()
BEFORE = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()


def _two_photos(client) -> int:
    """A first situation with two positions, a second that mentions only one."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    first = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": BEFORE}
    ).json()["id"]
    for payload in (
        {"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
         "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
        {"asset_name": "Gold bar", "asset_class": "commodity", "value": 400, "currency": "EUR"},
    ):
        client.post(f"/api/snapshots/{first}/holdings", json=payload)
    second = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{second}/holdings",
        json={"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
              "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"},
    )
    return iid


# --- P0d: what an omission removed ------------------------------------------


def test_a_position_that_vanished_is_named_with_its_value(client):
    """It used to leave the totals in total silence."""
    _two_photos(client)
    s = client.get("/api/dashboard/summary").json()
    assert [o["asset_name"] for o in s["unresolved_omissions"]] == ["Gold bar"]
    o = s["unresolved_omissions"][0]
    # The number itself, from the one place it lives. There used to be a
    # second copy of it on the summary; see the commit that removed it.
    assert o["last_value"] == 400.0
    assert o["last_seen"] == BEFORE and o["dropped_on"] == TODAY


def test_a_disposal_on_record_explains_the_absence(client):
    """Selling is an assertion; forgetting is the absence of one. Only the
    second is worth reporting."""
    iid = _two_photos(client)
    r = client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 430, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    assert client.get("/api/dashboard/summary").json()["unresolved_omissions"] == []


def test_one_photograph_reports_nothing(client):
    """With nothing to compare against, silence is correct."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Gold bar", "asset_class": "commodity", "value": 400, "currency": "EUR"},
    )
    assert client.get("/api/dashboard/summary").json()["unresolved_omissions"] == []



# --- What a photograph is compared AGAINST ----------------------------------
#
# Three of the four ways value could leave in silence were one question, and
# this is it. The check compared a photograph to the PREVIOUS PHOTOGRAPH, when
# what it meant to ask was whether the photograph agrees with what the app
# believed. Everything below fails at `c2b53cb`.

FIRST = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
SECOND = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
THIRD = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()

VWCE = {"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
        "symbol": "VWCE.MI", "quantity": 10, "unit_price": 100, "currency": "EUR"}
GOLD = {"asset_name": "Gold bar", "asset_class": "commodity", "value": 400, "currency": "EUR"}


def _situation(client, iid: int, date: str, holdings=()) -> int:
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": date}
    ).json()["id"]
    for h in holdings:
        assert client.post(f"/api/snapshots/{sid}/holdings", json=h).status_code == 201
    return sid


def _omissions(client) -> list[dict]:
    return client.get("/api/dashboard/summary").json()["unresolved_omissions"]


def test_a_second_situation_does_not_bury_the_warning(client):
    """The notice used to live exactly ONE photograph.

    It read `snaps[-2], snaps[-1]`, so the next situation the reader declared
    pushed the explanation out of a window that only held two — and anyone
    opening the app a month later had no way to learn what had happened. The
    money is still gone either way; only the sentence about it disappeared."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [GOLD])
    _situation(client, iid, SECOND, [])
    _situation(client, iid, THIRD, [])

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 0.0, "the value really is gone"
    named = summary["unresolved_omissions"]
    assert [o["asset_name"] for o in named] == ["Gold bar"]
    assert named[0]["last_value"] == 400.0
    # The situation that DROPPED it, not merely the newest one there is.
    assert named[0]["dropped_on"] == SECOND
    assert named[0]["last_seen"] == FIRST


def test_a_position_born_in_the_ledger_is_named_when_a_situation_omits_it(client):
    """The case the product generates most, and the one it was blindest to.

    A buy recorded after the last photograph creates a position that has never
    been in ANY photograph — so a check reading only previous photographs could
    not see it, and a situation that failed to mention it deleted it without a
    line. The cash had left; the units never arrived; nothing was said."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [VWCE])
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": FIRST, "amount": 5000, "currency": "EUR"}
    )
    assert client.post(
        "/api/transactions",
        json={"kind": "buy", "date": SECOND, "institution_id": iid,
              "asset_name": "iShares Core MSCI World", "symbol": "EUNL.DE",
              "asset_class": "fund_etf", "quantity": 10, "unit_price": 10, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201
    assert client.get("/api/dashboard/summary").json()["investments_total"] == 1100.0

    # A situation that re-states the photographed row and says nothing about
    # the bought one. Only the ledger ever knew about it.
    _situation(client, iid, THIRD, [VWCE])

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 1000.0, "100.00 left the totals"
    named = summary["unresolved_omissions"]
    assert [o["symbol"] for o in named] == ["EUNL.DE"]
    assert named[0]["last_value"] == 100.0
    # Last confirmed by its ledger entry, never by a photograph — a date the
    # previous implementation had no way to produce at all.
    assert named[0]["last_seen"] == SECOND
    assert named[0]["dropped_on"] == THIRD


def test_the_first_situation_of_an_account_is_compared_against_something(client):
    """`len(snaps) < 2` read as "nothing to compare against yet".

    True until a buy alone could create a position. After that, an account can
    hold value while having no photograph at all — so its FIRST situation can
    delete everything the ledger built, and the check skipped it by definition.
    Against the projection there is no photograph with nothing to compare
    against: the first one has the whole ledger behind it."""
    iid = client.post("/api/institutions", json={"name": "Broker C"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": FIRST, "amount": 1400, "currency": "EUR"}
    )
    for name, symbol, qty, price in (
        ("iShares Core MSCI World", "SWDA.MI", 10, 51),
        ("Vanguard All-World", "VWCE.MI", 2, 50),
    ):
        assert client.post(
            "/api/transactions",
            json={"kind": "buy", "date": SECOND, "institution_id": iid,
                  "asset_name": name, "symbol": symbol, "asset_class": "fund_etf",
                  "quantity": qty, "unit_price": price, "currency": "EUR", "price_currency": "EUR"},
        ).status_code == 201
    assert client.get(f"/api/institutions/{iid}/snapshots").json() == []
    assert client.get("/api/dashboard/summary").json()["investments_total"] == 610.0

    _situation(client, iid, THIRD, [])  # the account's first, and empty

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 0.0
    assert [(o["symbol"], o["last_value"]) for o in summary["unresolved_omissions"]] == [
        ("SWDA.MI", 510.0),
        ("VWCE.MI", 100.0),
    ], "610.00 of ledger-born positions, named"


def test_putting_a_position_back_clears_only_that_warning(client):
    """"Dropped by mistake → put it back" is what the notice tells the reader
    to do, and doing it has to be enough — for that row, and only that row.

    The value is in the totals again, so nothing left them and there is nothing
    to warn about. Going on reporting a drop the reader has already undone is
    how a warning teaches itself to be ignored, which costs more than the
    silence this whole function exists to prevent.

    Both rows are dropped by the same situation on purpose. With only one, the
    account would be skipped wholesale by the pre-filter and the test would
    pass without ever reaching the rule it is here to hold: it is the row still
    missing that forces the walk to run over the row that came back."""
    bitcoin = {"asset_name": "Bitcoin", "asset_class": "crypto", "value": 200, "currency": "EUR"}
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [VWCE, GOLD, bitcoin])
    _situation(client, iid, SECOND, [VWCE])
    assert sorted(o["asset_name"] for o in _omissions(client)) == ["Bitcoin", "Gold bar"]

    _situation(client, iid, THIRD, [VWCE, GOLD])  # the gold bar put back

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 1400.0, "the gold bar is back in the totals"
    assert [o["asset_name"] for o in summary["unresolved_omissions"]] == ["Bitcoin"], (
        "the row that came back is settled; the one still missing is not"
    )



def test_the_value_named_is_the_value_that_left(client, monkeypatch):
    """A quantity-based row is worth what its LISTING trades in, not what its
    currency field was typed as.

    That rule exists because a fund labelled USD (its share class) but quoted
    in EUR in Milan otherwise reports a 17% gain that never happened. The
    notice read the typed field, so it announced the departure of a smaller
    number than the one the position had been contributing — the same holding,
    two values, on two screens. Reading the value off the projection settles it
    in the only way that cannot drift: there is one definition and this is not
    a second copy of it."""
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {"2026-08-20": {"USD": 1.25}}
    )
    monkeypatch.setattr(
        prices,
        "get_quotes",
        lambda syms: {s: {"symbol": s, "price": 100.0, "as_of": TODAY} for s in syms},
    )
    monkeypatch.setattr(prices, "get_currencies", lambda syms: {s: "EUR" for s in syms})

    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [dict(VWCE, currency="USD")])
    client.get("/api/dashboard/portfolio", params={"live": "true"})  # fill the cache
    held = client.get("/api/dashboard/summary").json()["investments_total"]
    assert held == 1000.0, "10 units at 100, in the currency the ticker trades in"

    _situation(client, iid, SECOND, [])

    assert [o["last_value"] for o in _omissions(client)] == [held], (
        "the notice must name the value that actually left the totals"
    )



# --- What "accounted for" means ---------------------------------------------
#
# The comparison used to ask whether some row in the newer situation carried
# the same key. Three kinds of loss fit through that, and one thing that was
# not a loss at all kept being reported as one. Everything below fails at
# `668ea30`.


def _summary(client) -> dict:
    return client.get("/api/dashboard/summary").json()


def test_units_that_stop_being_claimed_are_named(client):
    """A situation with a quantity makes TWO assertions — "I hold this" and "I
    hold this much" — and only the first was ever read.

    So a situation restating 1 unit of a position the app believed was 10 kept
    the name, the check saw the name, and 900.00 left the totals in silence.
    It is the same defect as a row vanishing, wearing the one disguise the old
    comparison could not see through."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [VWCE])
    assert _summary(client)["investments_total"] == 1000.0

    _situation(client, iid, SECOND, [dict(VWCE, quantity=1)])

    summary = _summary(client)
    assert summary["investments_total"] == 100.0, "900.00 really did leave"
    named = summary["unresolved_omissions"]
    assert [(o["asset_name"], o["last_value"]) for o in named] == [
        ("Vanguard All-World", 900.0)
    ]
    # The row is still there; nine of its units are not. Saying "this is gone"
    # about a position the reader can see in the table would read as a bug in
    # the notice rather than a question about the situation.
    assert named[0]["units_missing"] == 9.0
    assert named[0]["dropped_on"] == SECOND


def test_a_partial_sell_accounts_for_its_part_and_no_more(client):
    """The old rule asked whether a sell EXISTED, never how much it sold — so
    one unit sold out of ten explained the whole position vanishing.

    It is not a rule any more. The projection applies disposals itself, using
    the average-cost walk written once in `replay`, so what the app believes is
    already net of everything the ledger disposed of: the sold unit is gone
    from the question, and the nine that were not sold are still in it."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [VWCE])
    assert client.post(
        "/api/transactions",
        json={"kind": "sell", "date": SECOND, "institution_id": iid,
              "asset_name": "Vanguard All-World", "symbol": "VWCE.MI",
              "quantity": 1, "unit_price": 100, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201

    _situation(client, iid, THIRD, [])  # and then the whole row goes

    named = _summary(client)["unresolved_omissions"]
    assert [(o["asset_name"], o["last_value"]) for o in named] == [
        ("Vanguard All-World", 900.0)
    ], "the one unit sold is explained; the nine that were not are not"


def test_a_disposal_recorded_late_still_explains_the_absence(client):
    """The notice says "Sold → record a close". The form dates the close today.
    The situation that dropped the row is months old, and the window ended at
    that situation — so the reader did exactly what the warning asked and the
    warning stayed, with nothing anywhere saying it had to be backdated.

    A record is a record. The date of a disposal decides when its proceeds land
    in the history, which is a different kind of correctness from whether
    anything on record says where the value went — and the totals come out the
    same either way. A warning its own prescribed remedy cannot clear teaches
    the reader to ignore it, and then the true one goes unread."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": FIRST, "amount": 1000, "currency": "EUR"}
    )
    _situation(client, iid, FIRST, [GOLD])
    _situation(client, iid, SECOND, [])
    assert [o["asset_name"] for o in _omissions(client)] == ["Gold bar"]

    assert client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 430, "currency": "EUR"},
    ).status_code == 201

    summary = _summary(client)
    assert summary["unresolved_omissions"] == []
    # 1000.00 of cash and a 400.00 bar, sold for 430.00.
    assert summary["net_worth"] == 1430.0, "the totals were right all along"


def test_a_disposal_recorded_before_the_row_was_last_seen_does_not_explain_it(client):
    """The other edge of that window, which stays where it is.

    A sale is about the units held when it happened. One recorded before the
    app last saw this position cannot account for the units it was still
    holding afterwards — otherwise a position bought back after an old sale
    would be explained forever by that sale."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": FIRST, "amount": 5000, "currency": "EUR"}
    )
    _situation(client, iid, FIRST, [VWCE])
    assert client.post(
        "/api/transactions",
        json={"kind": "sell", "date": SECOND, "institution_id": iid,
              "asset_name": "Vanguard All-World", "symbol": "VWCE.MI",
              "quantity": 10, "unit_price": 100, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201
    # Sold out, then bought again, and only then dropped by a situation.
    assert client.post(
        "/api/transactions",
        json={"kind": "buy", "date": THIRD, "institution_id": iid,
              "asset_name": "Vanguard All-World", "symbol": "VWCE.MI",
              "asset_class": "fund_etf", "quantity": 4, "unit_price": 100, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201
    _situation(client, iid, TODAY, [])

    named = _omissions(client)
    assert [(o["symbol"], o["last_value"]) for o in named] == [("VWCE.MI", 400.0)], (
        "the old sale is not an account of the units bought after it"
    )


def test_giving_a_row_its_ticker_is_not_a_loss(client):
    """Identity and quotation are two different fields, and a row is allowed to
    gain the second one.

    Matching on `symbol or asset_name` meant the key CHANGED when the reader
    did the thing this app most wants them to do, so one position read as
    leaving and another as arriving — a 1000.00 loss announced against a total
    that had not moved. A warning that fires when nothing happened is the one
    failure that costs more than staying silent."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [
        {"asset_name": "Vanguard All-World", "asset_class": "fund_etf", "value": 1000, "currency": "EUR"}
    ])
    _situation(client, iid, SECOND, [VWCE])  # the same row, now with its ticker

    summary = _summary(client)
    assert summary["investments_total"] == 1000.0, "nothing moved"
    assert summary["unresolved_omissions"] == []


def test_a_reformulated_holding_reports_both_numbers(client):
    """Three rows replaced by one row each is the same money described better, and
    the app could only say the first half of it — "7,500.00 stopped being
    accounted for" — which reads as a loss. Naming what the same situation
    declared instead is what lets a reader tell a reformulation from a
    disappearance at a glance.

    It does not claim the two ARE the same money: nothing here can know that,
    and saying which row replaced which needs a stable identity this schema
    has not got. Both numbers is the whole of what is
    needed to answer the question by eye."""
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    _situation(client, iid, FIRST, [
        {"asset_name": "Stocks (Siemens, Unilever, Toyota, …)",
         "asset_class": "equity", "value": 6400, "currency": "EUR"},
        {"asset_name": "Bond ETFs", "asset_class": "bond", "value": 1100, "currency": "EUR"},
        {"asset_name": "Bitcoin", "asset_class": "crypto", "value": 150, "currency": "EUR"},
    ])
    _situation(client, iid, SECOND, [
        {"asset_name": n, "asset_class": "equity", "value": v, "currency": "EUR"}
        for n, v in (("Siemens", 1200), ("Unilever", 900), ("Toyota", 700),
                     ("Bond ETF Dec 2027", 500), ("Bond ETF Dec 2028", 300))
    ] + [{"asset_name": "Bitcoin", "asset_class": "crypto", "value": 60, "currency": "EUR"}])

    summary = _summary(client)
    gone = summary["unresolved_omissions"]
    instead = summary["declared_instead"]
    assert sum(o["last_value"] for o in gone) == 7500.0, "the two rows nothing named"
    assert sum(a["value"] for a in instead) == 3600.0, "what it declared instead"
    # Bitcoin is in both situations under the same name, so it is on neither
    # list — it was never unaccounted for, and its value moving is the market.
    assert "Bitcoin" not in [o["asset_name"] for o in gone]
    assert "Bitcoin" not in [a["asset_name"] for a in instead]
    assert {a["appeared_on"] for a in instead} == {SECOND}


def test_what_a_situation_declares_is_not_reported_on_its_own(client):
    """Value ARRIVING breaks no rule — a reader may declare whatever they hold,
    and a first situation is nothing but arrivals. Reporting it on its own
    would turn every ordinary purchase into a notice, which is how a warning
    surface stops being read."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    _situation(client, iid, FIRST, [VWCE])
    _situation(client, iid, SECOND, [VWCE, GOLD])  # something new, nothing lost

    summary = _summary(client)
    assert summary["unresolved_omissions"] == []
    assert summary["declared_instead"] == []



def test_every_row_says_which_account_it_belongs_to(client):
    """The account page shows only its OWN unaccounted-for rows, and it has an
    id in hand — so the rows have to carry one.

    Filtering on the display name would have worked until two accounts shared
    one, and a warning that attaches another account's missing 1,500.00 to the
    situation you are about to declare is worse than no warning at all."""
    a = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    b = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    _situation(client, a, FIRST, [VWCE])
    _situation(client, a, SECOND, [])
    _situation(client, b, FIRST, [GOLD])
    _situation(client, b, SECOND, [dict(VWCE, quantity=3)])

    summary = _summary(client)
    by_account = {o["institution_id"]: o for o in summary["unresolved_omissions"]}
    assert by_account.keys() == {a, b}
    assert by_account[a]["asset_name"] == "Vanguard All-World"
    assert by_account[b]["asset_name"] == "Gold bar"
    # The same id on what arrived, so the two halves of one sentence cannot end
    # up describing two different accounts.
    assert {x["institution_id"] for x in summary["declared_instead"]} == {b}

    # And on the portfolio rows the page reads to know what it currently holds.
    rows = client.get("/api/dashboard/portfolio").json()["rows"]
    assert {r["institution_id"] for r in rows} == {b}, "only Broker B still holds anything"


# --- P0c: an exit for a position with no units ------------------------------


def _opaque(client) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker B"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": BEFORE}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Gold bar", "asset_class": "commodity",
              "value": 400, "cost_basis": 350, "currency": "EUR"},
    )
    return iid


def test_a_row_with_no_units_can_now_be_disposed_of(client):
    """Before this, the only way out of a value-only row was to make it vanish
    from a photograph — which is the silent deletion, not an exit."""
    iid = _opaque(client)
    before = client.get("/api/dashboard/summary").json()
    assert before["investments_total"] == 400.0

    r = client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 430, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text

    p = client.get("/api/dashboard/portfolio").json()
    row = next(x for x in p["rows"] if x["asset_name"] == "Gold bar")
    assert row["closed_on"] == TODAY and row["quantity"] == 0
    assert row["realized_pl"] == 430 - 350, "the gain it locked in is kept"
    assert p["total_book"] == 0.0


def test_the_proceeds_land_in_cash_so_nothing_evaporates(client):
    """The whole invariant: value may move, but never simply disappear."""
    iid = _opaque(client)
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": BEFORE, "amount": 1000, "currency": "EUR"}
    )
    before = client.get("/api/dashboard/summary").json()["net_worth"]

    client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 400, "currency": "EUR"},
    )
    after = client.get("/api/dashboard/summary").json()
    assert client.get(f"/api/institutions/{iid}/cash").json()["projected"] == 1400
    assert abs(after["net_worth"] - before) < 1e-9, "sold at its value: net worth is unchanged"


def test_a_close_must_say_what_came_back(client):
    """Zero is allowed — it just has to be said, because that is the difference
    between a disposal and an omission."""
    iid = _opaque(client)
    r = client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Gold bar", "currency": "EUR"},
    )
    assert r.status_code == 422
    ok = client.post(
        "/api/transactions",
        json={"kind": "close", "date": TODAY, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 0, "currency": "EUR"},
    )
    assert ok.status_code == 201


def test_loosening_close_did_not_loosen_a_buy(client):
    """A buy without a ticker would create a position no price could reach."""
    iid = _opaque(client)
    r = client.post(
        "/api/transactions",
        json={"date": TODAY, "institution_id": iid, "asset_name": "Mystery",
              "quantity": 1, "unit_price": 10, "currency": "EUR", "price_currency": "EUR"},
    )
    assert r.status_code == 422


# --- The same rule backwards: value that should have LEFT, and stayed --------

BOUGHT = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
CLOSED = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()


def _never_photographed(client, *, proceeds: float) -> int:
    """A position no photograph ever saw: bought after the last snapshot,
    then closed. The anchor holding is only there so the institution has a
    photo at all — the row under test is born and dies entirely in the ledger,
    which is the one path `_closure` never reaches."""
    iid = client.post("/api/institutions", json={"name": "Broker C"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": BEFORE}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Anchor fund", "asset_class": "fund_etf",
              "symbol": "AAA.MI", "quantity": 10, "unit_price": 10, "currency": "EUR"},
    )
    client.post(
        f"/api/institutions/{iid}/cash-anchors", json={"date": BEFORE, "amount": 1000, "currency": "EUR"}
    )
    assert client.post(
        "/api/transactions",
        json={"kind": "buy", "date": BOUGHT, "institution_id": iid,
              "asset_name": "Zeta", "symbol": "ZZZ.MI", "asset_class": "fund_etf",
              "quantity": 10, "unit_price": 10, "currency": "EUR", "price_currency": "EUR"},
    ).status_code == 201
    assert client.post(
        "/api/transactions",
        json={"kind": "close", "date": CLOSED, "institution_id": iid,
              "asset_name": "Zeta", "symbol": "ZZZ.MI", "amount": proceeds, "currency": "EUR"},
    ).status_code == 201
    return iid


def test_a_close_disposes_of_a_position_no_photograph_ever_saw(client):
    """A `close` is not a buy. Routing it into the buy branch ADDS its proceeds
    to the book value and leaves the position open — so a position that was
    sold reads as one that doubled."""
    _never_photographed(client, proceeds=150)

    p = client.get("/api/dashboard/portfolio").json()
    row = next(x for x in p["rows"] if x["asset_name"] == "Zeta")
    assert row["closed_on"] == CLOSED, "the exit is on record, not inferred"
    assert row["quantity"] == 0
    assert row["realized_pl"] == 150 - 100, "proceeds less what it cost"
    assert p["total_book"] == 100.0, "only the anchor fund is still held"


def test_a_close_at_cost_moves_value_and_creates_none(client):
    """Across the whole series: the proceeds leave the position and land in
    cash on the same day, so `financial` never moves. Counting them as cost
    instead makes the same money appear in both places at once."""
    _never_photographed(client, proceeds=100)

    series = client.get("/api/dashboard/net-worth-series").json()
    assert [round(pt["financial"], 6) for pt in series] == [1100.0] * len(series)


def test_a_close_settles_one_row_and_not_two(client):
    """The other direction of the same rule: value may not APPEAR twice
    either. A close with no ticker belongs to the photographed row it names;
    reaching it again as a position of its own reports its proceeds as a
    second, invented gain."""
    iid = _opaque(client)
    client.post(
        "/api/transactions",
        json={"kind": "buy", "date": BOUGHT, "institution_id": iid,
              "asset_name": "Zeta", "symbol": "ZZZ.MI", "asset_class": "fund_etf",
              "quantity": 10, "unit_price": 10, "currency": "EUR", "price_currency": "EUR"},
    )
    client.post(
        "/api/transactions",
        json={"kind": "close", "date": CLOSED, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 430, "currency": "EUR"},
    )

    r = client.get("/api/dashboard/portfolio")
    assert r.status_code == 200, "a null ticker used to be sorted against a real one"
    p = r.json()
    assert [x["asset_name"] for x in p["rows"]] == ["Gold bar", "Zeta"]
    assert p["total_realized"] == 430 - 350, "once, on the row that held it"


def test_the_history_stops_counting_a_position_the_day_it_was_closed(client):
    """The same rule, applied BEHIND today's point.

    Today comes from `project()`, which honours the close; every earlier point
    came from a carry-forward of the photographs, which does not. So a row
    disposed of ten days ago was still in the net worth at every historical
    date after its own exit — the wrong number is the one a user is looking
    at, and it is only right on the last day of the chart.

    The row is deliberately symbol-less: it is the one an overlay matching on
    `h.symbol == t.symbol` can never find, and the one that most needs an exit
    that is not "vanish from the next photograph"."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": BEFORE}
    ).json()["id"]
    for payload in (
        {"asset_name": "Vanguard All-World", "asset_class": "fund_etf",
         "symbol": "VWCE.MI", "quantity": 10, "unit_price": 70, "currency": "EUR"},
        {"asset_name": "Gold bar", "asset_class": "commodity", "value": 400, "currency": "EUR"},
    ):
        client.post(f"/api/snapshots/{sid}/holdings", json=payload)
    assert client.post(
        "/api/transactions",
        json={"kind": "close", "date": CLOSED, "institution_id": iid,
              "asset_name": "Gold bar", "amount": 400, "currency": "EUR"},
    ).status_code == 201

    by_date = {
        pt["date"]: round(pt["financial"], 6)
        for pt in client.get("/api/dashboard/net-worth-series").json()
    }
    assert by_date[BEFORE] == 1100.0, "before the exit both rows are held"
    assert by_date[CLOSED] == 700.0, "the day it was closed it stops counting"
    assert by_date[TODAY] == 700.0, "and today already knows"
