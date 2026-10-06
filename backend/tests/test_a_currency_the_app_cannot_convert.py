"""A currency code is checked for its shape, and an amount nobody can convert
says so instead of joining the total as if it were already in the base.

Two independent halves, because "a real currency" and "a currency we can
convert" are two different questions and the app used to ask neither:

  * `Dollari` and `EURO` are not codes at all. Four real assets of 1,000 in
    EUR, USD, `EURO` and `Dollari` totalled 3,800.00 at a rate of 1.25 (audit T
    measured 3,871.00 against the real rate), because an amount that cannot be
    converted is added AS STORED — so each invented code contributed its whole
    1,000.00 to the net worth. A shape check on the one place every payload
    states a currency stops that at the door.

  * `TWD` IS a real currency, a Taipei-listed fund is a legitimate holding, and
    the ECB does not quote it — so the allowed list the base-currency setting
    validates against would refuse something the reader owns. `GBp` is the same
    case. For those the total cannot be made right, only HONEST: the amount
    stays in (a total quietly short by a holding is as wrong as one quietly
    inflated) and the payload says what could not be converted.

The second half is the one that makes a total honest for a code the reader is
right to type, so it is the one to break last.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import BaseModel, ValidationError

from app import models, schemas
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()
EARLIER = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
# Strictly after the situation: `prices.get_dividends_since` is exclusive.
EX_DATE = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()


@pytest.fixture(autouse=True)
def dollars_at_one_twenty_five(monkeypatch):
    """The suite's fixed feed: 1.25 dollars per euro, and nothing else quoted.

    Only USD, so a euro base can convert dollars and nothing else — which is
    what makes a legitimate unquoted code testable without inventing a feed
    outage."""
    from app import fx

    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {EARLIER: {"USD": 1.25}})


# --- The shape, in one place ------------------------------------------------

# Every field that says what currency an AMOUNT is in, on every payload a caller
# may send. Discovered by name rather than listed, for the reason `_columns`
# exists: a thirteenth currency column added next month is covered next month,
# by nobody. `*Write` is included beside `*Create` because it is the door a
# person actually posts through, and a subclass re-declaring the field would
# otherwise slip past.
CURRENCY_FIELDS = sorted(
    (name, field)
    for name, obj in vars(schemas).items()
    if isinstance(obj, type)
    and issubclass(obj, BaseModel)
    and name.endswith(("Create", "Write"))
    for field in obj.model_fields
    if field == "currency" or field.endswith("_currency")
)

# `BaseCurrencySetting.base_currency` is deliberately NOT in that list, and the
# test below names it so its absence is a decision rather than a gap: it is not
# the currency an amount is written in, it is the unit every total is converted
# INTO, and a base with no rates is not a base at all. The router checks it
# against `fx.feed_currencies` (422 otherwise), which is stricter than a shape.
NOT_AN_AMOUNTS_CURRENCY = {("BaseCurrencySetting", "base_currency")}


@pytest.mark.parametrize(
    "name,field", CURRENCY_FIELDS, ids=[f"{n}.{f}" for n, f in CURRENCY_FIELDS]
)
def test_a_word_is_not_a_currency_code_on_any_payload(name, field):
    """`Dollari` is refused wherever an amount states its currency.

    Asserted against the schema rather than screen by screen: the rule lives in
    `schemas.StatedCurrency`, one place, and what this holds is that every field
    of this kind is wearing it.
    """
    schema = getattr(schemas, name)
    # A box left blank keeps the sentence it has had since `265b54a`: "you have
    # not said" and "that is not a code" are two different things to be told.
    for written, said in (
        ("Dollari", "currency code"),
        ("EURO", "currency code"),
        ("€", "currency code"),
        ("eu", "currency code"),
        ("USDT", "currency code"),
        ("US1", "currency code"),
        ("", "say which currency"),
        ("   ", "say which currency"),
    ):
        with pytest.raises(ValidationError) as refused:
            schema.model_validate({field: written})
        # Other fields are missing too — this asks only that the currency was
        # refused, and refused for what it is rather than for being absent.
        assert any(
            error["loc"] == (field,) and said in error["msg"]
            for error in refused.value.errors()
        ), f"{name}.{field} accepted {written!r}"


def test_the_scan_found_the_fields_it_is_about():
    """The test above is worth having only if it looked at anything: a discovery
    that matched nothing would pass every future mistake."""
    assert ("TransferCreate", "to_currency") in CURRENCY_FIELDS
    assert ("TransactionWrite", "price_currency") in CURRENCY_FIELDS
    assert ("HoldingCreate", "currency") in CURRENCY_FIELDS
    assert len(CURRENCY_FIELDS) >= 12, CURRENCY_FIELDS
    assert not NOT_AN_AMOUNTS_CURRENCY & set(CURRENCY_FIELDS)


def test_a_real_code_the_feed_does_not_quote_is_accepted(client):
    """The trap, asserted so that tightening the rule to the feed's list later
    fails here first.

    `TWD` is a real currency the ECB does not publish a rate for, and a
    Taipei-listed fund is an ordinary thing to own. `GBp` is pence, which London
    genuinely quotes and the ECB genuinely does not. Validating the boxes against
    `fx.feed_currencies` — the list the BASE is chosen from — would refuse both.
    """
    for code in ("TWD", "GBp", "twd"):
        made = client.post("/api/real-assets", json={"name": f"Asset {code}", "currency": code})
        assert made.status_code == 201, (code, made.text)
        assert made.json()["currency"] == code  # kept as typed: GBp is not GBP

    # And the base, which is a different question, still refuses it.
    refused = client.put("/api/settings/base-currency", json={"base_currency": "TWD"})
    assert refused.status_code == 422
    assert "not a currency the ECB rate feed quotes" in refused.json()["detail"]


def test_a_row_stored_before_the_rule_can_still_be_read_and_corrected(client):
    """The reader's own database holds one: a real asset written in `Doll`.

    The rule is on the ...Create only, never on the ...Base the response shares,
    for the reason written above `ObservedDate`: FastAPI validates what it
    SERIALIZES too, so a refusal on the shared base would answer 500 for the
    very row the reader has to open in order to fix it — taking away the only
    screen it can be corrected from.
    """
    with SessionLocal() as db:
        db.add(models.RealAsset(name="Mira", currency="Doll"))
        db.commit()
        asset_id = db.scalar(
            models.RealAsset.__table__.select().with_only_columns(models.RealAsset.id)
        )

    listed = client.get("/api/real-assets")
    assert listed.status_code == 200, listed.text
    assert [a["currency"] for a in listed.json()] == ["Doll"]

    # The save is what refuses it, with a sentence that names the box.
    refused = client.put(
        f"/api/real-assets/{asset_id}", json={"name": "Mira", "currency": "Doll"}
    )
    assert refused.status_code == 422
    assert "not a currency code" in refused.text

    fixed = client.put(
        f"/api/real-assets/{asset_id}", json={"name": "Mira", "currency": "USD"}
    )
    assert fixed.status_code == 200 and fixed.json()["currency"] == "USD"


# --- What the reader sees when nobody can convert it -----------------------


def _asset_worth(client, name: str, currency: str, value: float) -> int:
    made = client.post("/api/real-assets", json={"name": name, "currency": currency})
    assert made.status_code == 201, made.text
    client.post(
        f"/api/real-assets/{made.json()['id']}/valuations",
        json={"date": EARLIER, "value": value},
    ).raise_for_status()
    return made.json()["id"]


def test_audit_ts_four_assets_now_total_what_can_be_converted(client):
    """The measured case, with the two invented codes refused at the door.

    1,000 EUR + 1,000 USD at 1.25 is 1,800.00, and the other two never exist —
    which is the whole difference from the 3,800.00 this totalled before.
    """
    _asset_worth(client, "Asset EUR", "EUR", 1000.0)
    _asset_worth(client, "Asset USD", "USD", 1000.0)
    for invented in ("EURO", "Dollari"):
        assert client.post(
            "/api/real-assets", json={"name": f"Asset {invented}", "currency": invented}
        ).status_code == 422

    summary = client.get("/api/dashboard/summary").json()
    assert summary["real_total"] == 1800.0
    assert summary["net_worth"] == 1800.0
    assert summary["unconverted"] == []


def test_an_amount_nobody_can_convert_is_kept_and_named(client):
    """Kept, because dropping it is the other way to be wrong — and named, so
    the figure above it is not read as if it were all in one unit."""
    _asset_worth(client, "Milan flat", "EUR", 1000.0)
    _asset_worth(client, "Yuanta Taiwan 50", "TWD", 9000.0)

    summary = client.get("/api/dashboard/summary").json()
    # The fallback stands: 9,000 TWD is in there as 9,000, which is why it has
    # to be said out loud.
    assert summary["real_total"] == 10000.0
    assert summary["unconverted"] == [
        {"currency": "TWD", "amount": 9000.0, "count": 1}
    ]
    assert summary["base_currency"] == "EUR"


def test_the_portfolio_says_it_of_its_own_total(client):
    """Same converter, same sentence, on the page that prints the holdings."""
    iid = client.post("/api/institutions", json={"name": "Taipei broker"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": EARLIER}
    ).json()["id"]
    for currency, value in (("EUR", 500.0), ("TWD", 9000.0)):
        made = client.post(
            f"/api/snapshots/{sid}/holdings",
            json={"asset_name": f"Fund {currency}", "value": value, "currency": currency},
        )
        assert made.status_code == 201, made.text

    portfolio = client.get("/api/dashboard/portfolio").json()
    assert portfolio["total_book"] == 9500.0
    assert portfolio["unconverted"] == [{"currency": "TWD", "amount": 9000.0, "count": 1}]


def test_one_holding_over_three_photographs_is_counted_once(client):
    """The figure is a sum, so it has to be a sum of each amount ONCE.

    `_unaccounted` replays every photograph an institution has — that is how it
    finds what a newer one stopped accounting for — and it runs on the same
    converter. Measured with the guard off: three photographs each naming one
    holding of 1,000 in an unquoted currency reported 3,000.00 over 3 amounts,
    against an investments total of 1,000.00. A warning that overstates by the
    length of the history teaches the reader to stop reading warnings.
    """
    iid = client.post("/api/institutions", json={"name": "Taipei broker"}).json()["id"]
    for day in ("2026-06-01", "2026-07-01", "2026-08-01"):
        sid = client.post(
            f"/api/institutions/{iid}/snapshots", json={"date": day}
        ).json()["id"]
        client.post(
            f"/api/snapshots/{sid}/holdings",
            json={"asset_name": "Yuanta Taiwan 50", "value": 1000.0, "currency": "TWD"},
        ).raise_for_status()

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 1000.0
    assert summary["unconverted"] == [{"currency": "TWD", "amount": 1000.0, "count": 1}]


def test_the_figure_is_a_sum_over_rows_and_says_so(client):
    """What the number IS, pinned — because it reads like something it is not.

    One converter serves several totals, so an amount can reach them in roles
    that do not add up, and the figure is a volume of rows rather than the error
    in any total. Both cases are measured here rather than argued:

    * a holding worth 1,000 TWD that COST 900 reports 1,900.00 over 2, against
      an investments total of 1,000.00 — a cost basis converts too, and it feeds
      the book value;
    * an asset and a debt of 1,000 TWD each add 2,000.00 more, and the net worth
      does not move by a cent: the debt subtracts exactly what the asset adds.

    An earlier draft of the notice read "3,900.00 TWD is counted above as if
    already in EUR" under a net worth that figure had no such effect on. If this
    test ever fails because the number changed meaning, the sentence beside it
    (`UnconvertedNotice.tsx`) has to change in the same commit.
    """
    iid = client.post("/api/institutions", json={"name": "Taipei broker"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": EARLIER}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "Yuanta Taiwan 50", "value": 1000.0,
              "cost_basis": 900.0, "currency": "TWD"},
    ).raise_for_status()

    summary = client.get("/api/dashboard/summary").json()
    assert summary["investments_total"] == 1000.0 and summary["net_worth"] == 1000.0
    assert summary["unconverted"] == [{"currency": "TWD", "amount": 1900.0, "count": 2}]

    _asset_worth(client, "Taipei flat", "TWD", 1000.0)
    lid = client.post(
        "/api/liabilities", json={"name": "Taipei mortgage", "currency": "TWD"}
    ).json()["id"]
    client.post(
        f"/api/liabilities/{lid}/balances", json={"date": EARLIER, "balance": 1000.0}
    ).raise_for_status()

    after = client.get("/api/dashboard/summary").json()
    assert (after["real_total"], after["liabilities_total"]) == (1000.0, 1000.0)
    assert after["net_worth"] == 1000.0  # unmoved: the debt cancels the asset
    assert after["unconverted"] == [{"currency": "TWD", "amount": 3900.0, "count": 4}]


def test_the_figure_understates_a_recurring_flow_by_its_whole_multiplier(client):
    """And it is not a bound in the other direction either.

    A flow is converted ONCE — one row, one amount — and then multiplied by the
    occurrences between the anchor and today. So the figure can be short of
    what actually reached the totals by any factor the calendar likes, which is
    what killed the one purpose a mere volume still seemed to serve: saying
    whether to expect five or five thousand. It does not.
    """
    a_year_ago = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    iid = client.post("/api/institutions", json={"name": "Taipei"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": a_year_ago, "amount": 0.0, "currency": "EUR"},
    ).raise_for_status()
    client.post(
        "/api/income-sources",
        json={"name": "Taipei rent", "amount": 100.0, "currency": "TWD",
              "frequency": "monthly", "institution_id": iid, "start_date": a_year_ago},
    ).raise_for_status()

    summary = client.get("/api/dashboard/summary").json()
    assert summary["cash_total"] == 1200.0 and summary["net_worth"] == 1200.0
    assert summary["unconverted"] == [{"currency": "TWD", "amount": 100.0, "count": 1}]


def test_an_amount_of_zero_is_not_a_warning(client):
    """Nothing to act on in a figure that changes no total, and a notice that
    fires on one is a notice the reader learns to close."""
    _asset_worth(client, "Yuanta Taiwan 50", "TWD", 0.0)
    summary = client.get("/api/dashboard/summary").json()
    assert summary["unconverted"] == []


# --- A stored value meeting the rule where no reader can answer ------------


def _dist_position(client, *, anchor_currency: str, holding_currency: str = "EUR") -> int:
    """An account with cash and one distributing position, ready to catch up."""
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": EARLIER, "amount": 1000.0, "currency": anchor_currency},
    ).raise_for_status()
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": EARLIER}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={
            "asset_name": "Vanguard All-World", "symbol": "VWCE.MI",
            "quantity": 10.0, "unit_price": 100.0, "currency": holding_currency,
            "distribution_policy": "dist",
        },
    ).raise_for_status()
    return iid


def _write_past_the_schema(table, **values) -> None:
    """Write a value the API would now refuse, the way a migrated database
    holds one: straight onto the table, no schema in the path."""
    with SessionLocal() as db:
        db.execute(table.__table__.update().values(**values))
        db.commit()


def test_a_legacy_code_on_the_dividend_path_is_skipped_not_a_500(client, monkeypatch):
    """The catch-up meets stored values, and there is no reader standing there.

    `POST /api/transactions/catch-up` is documented "safe to call at every app
    start", and it builds its entries out of rows: a cash anchor's currency, a
    holding's, the listing currency the price cache learned. None of those is
    re-typed, so the shape check meets them again with no box to correct them
    in — which is the same failure the rule is kept off the ...Read models to
    avoid, one level down, where the screen it takes away is the whole app.

    Measured before the guard: an uncaught `ValidationError` out of
    `pac.execute_dividends`, and the route answered 500. At `59ef644` the same
    database answered 200 with the occurrence skipped, so this is a regression
    the currency rule would otherwise have introduced.
    """
    from app import prices

    monkeypatch.setattr(prices, "_fetch_dividends", lambda symbol, period="max": [{"date": EX_DATE, "dps": 0.5}])
    monkeypatch.setattr(prices, "_fetch_probe", lambda *a, **k: True)
    _dist_position(client, anchor_currency="EUR")
    _write_past_the_schema(models.CashAnchor, currency="Doll")

    answer = client.post("/api/transactions/catch-up")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["created"] == []
    assert len(body["skipped"]) == 1
    reason = body["skipped"][0]["reason"]
    assert "'Doll' is not a currency code" in reason
    # And it says the value is on a row rather than in this request, because
    # nothing the reader could type here would have changed it.
    assert "recorded on a row" in reason


def test_a_legacy_code_on_the_plan_path_skips_the_whole_occurrence(client, monkeypatch):
    """Same rule, the other catch-up path — and the occurrence stays pending.

    One occurrence is one unit of work: a mix missing a leg is not the mix that
    was asked for, so a refused leg skips all of them and nothing is written.
    That is the answer a price that did not answer already gets.
    """
    from app import prices

    monkeypatch.setattr(
        prices, "get_price_on",
        lambda symbol, on: {"symbol": symbol, "price": 100.0, "as_of": on.isoformat()},
    )
    # The listing trades in the SAME bad code, so `fx.convert_on` short-circuits
    # (two spellings of one currency need no rate) and the payload is reached.
    # A bad code that DIFFERS from the listing's never gets this far: the rate
    # lookup above has nothing to convert with and skips the occurrence first,
    # which is a second guard on the same failure rather than a gap.
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "Doll")
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": EARLIER, "amount": 1000.0, "currency": "EUR"},
    ).raise_for_status()
    client.post(
        "/api/accumulation-plans",
        json={
            "name": "PAC All-World", "amount": 250.0, "currency": "EUR",
            "frequency": "annual", "start_date": EARLIER,
            "source_institution_id": iid,
            "targets": [{"symbol": "VWCE.MI", "asset_name": "All-World",
                         "institution_id": iid}],
        },
    ).raise_for_status()
    _write_past_the_schema(models.AccumulationPlan, currency="Doll")

    answer = client.post("/api/transactions/catch-up")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["created"] == []
    assert len(body["skipped"]) == 1
    assert "'Doll' is not a currency code" in body["skipped"][0]["reason"]
    # Nothing written, so the next run tries again once the code is corrected.
    assert client.get("/api/transactions").json() == []
