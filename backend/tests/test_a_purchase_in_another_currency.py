"""A purchase paid in one currency and listed in another has two amounts.

What was invested is in the listing's currency; what left the account is in
the account's, fixed on the day at that day's rate. The ledger kept one amount
and no currency, so it read every entry as euro: one share at 100 dollars from
a euro account took 100 out of the euro cash and set a book of 100 against a
market value converted from dollars — measured on 2026-09-14, a P/L of -13.73%
on a share whose price had not moved.

The fix is the second currency, not a conversion at today's rate. The account
was debited a fixed sum; restating that sum at the current rate would make the
balance of a euro account drift with the dollar — a wrong number replaced by
one that moves by itself.

The feed below publishes 1.25 dollars to the euro on the day of the purchase
and 1.00 today, so the rate of the wrong day cannot pass for rounding: one
share at 100 dollars is 80.00 euro on its day and 100.00 today.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import text

from app import fx, models
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()
BUY_DAY = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
ANCHOR_DAY = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()


@pytest.fixture()
def feed(monkeypatch) -> list[tuple]:
    asked: list[tuple] = []

    def fetch(base, start, end=None):
        asked.append((base, start, end))
        return {
            BUY_DAY: {"USD": 1.25, "GBP": 0.80},
            TODAY: {"USD": 1.00, "GBP": 0.80},
        }

    monkeypatch.setattr(fx, "_fetch_rates", fetch)
    return asked


def _account(client, cash: float = 1000.0) -> int:
    iid = client.post("/api/institutions", json={"name": "Broker A"}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": ANCHOR_DAY, "amount": cash, "currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    return iid


def _entry(client, iid: int, **fields) -> dict:
    body = {
        "kind": "buy",
        "date": BUY_DAY,
        "institution_id": iid,
        "asset_name": "Apple",
        "symbol": "AAPL",
        "asset_class": "equity",
        "quantity": 1,
        "unit_price": 100.0,
        "currency": "EUR",
        "price_currency": "USD",
        **fields,
    }
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _quote_today(price: float, currency: str = "USD", symbol: str = "AAPL") -> None:
    with SessionLocal() as db:
        db.merge(models.PriceCache(symbol=symbol, price=price, currency=currency, as_of=TODAY))
        db.commit()


def test_a_dollar_purchase_takes_a_fixed_euro_sum_out_of_a_euro_account(client, feed):
    iid = _account(client)

    buy = _entry(client, iid)
    _quote_today(100.0)

    assert (buy["amount"], buy["currency"], buy["fx_as_of"]) == (80.0, "EUR", BUY_DAY)
    assert client.get(f"/api/institutions/{iid}/cash").json()["projected"] == 920.0
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    # The book is what the account paid; the market value is today's dollars.
    # The difference is real: the dollar rose from 1.25 to 1.00 per euro.
    assert (row["book_value"], row["market_value"], row["delta"]) == (80.0, 100.0, 20.0)
    assert client.get("/api/dashboard/summary").json()["net_worth"] == 1020.0


def test_the_debit_stays_where_it_was_when_the_rate_moves(client, feed):
    """The euro account paid 80.00 and nothing about today changes that. A
    later rate moves what the share is worth, never what it cost."""
    iid = _account(client)
    _entry(client, iid)
    _quote_today(100.0)
    client.get("/api/dashboard/summary")  # today's rates are stored now

    with SessionLocal() as db:
        db.execute(text("UPDATE fx_rates SET rate = 2.0 WHERE currency = 'USD' AND as_of = :d"), {"d": TODAY})
        db.commit()

    assert client.get(f"/api/institutions/{iid}/cash").json()["projected"] == 920.0
    row = client.get("/api/dashboard/portfolio").json()["rows"][0]
    assert (row["book_value"], row["market_value"]) == (80.0, 50.0)


def test_a_debit_copied_from_a_statement_is_kept_as_typed(client, feed):
    """The broker's rate is not the ECB's, and fees in the spread are real
    money: the figure on the statement wins, and says it was not derived."""
    iid = _account(client)

    buy = _entry(client, iid, amount=81.37)

    assert (buy["amount"], buy["fx_as_of"]) == (81.37, None)
    assert client.get(f"/api/institutions/{iid}/cash").json()["projected"] == 1000.0 - 81.37


def test_moving_a_derived_debit_to_another_day_works_it_out_at_that_day(client, feed):
    iid = _account(client)
    buy = _entry(client, iid)

    body = {k: buy[k] for k in ("kind", "institution_id", "asset_name", "symbol", "asset_class",
                                "quantity", "unit_price", "currency", "price_currency")}
    # `amount: null` is the gesture the form makes for a debit the app worked
    # out: the edit form puts a figure the READER typed back in its box and
    # leaves this one empty, precisely so that moving the date works it out
    # again (Portfolio.tsx, startEdit). Said rather than left out, because an
    # edit no longer touches what it did not mention — see `crud._update`.
    moved = client.put(
        f"/api/transactions/{buy['id']}", json={**body, "date": TODAY, "amount": None}
    ).json()

    assert (moved["amount"], moved["fx_as_of"]) == (100.0, TODAY)


def test_no_rate_for_the_day_is_refused_not_guessed(client, monkeypatch):
    monkeypatch.setattr(fx, "_fetch_rates", lambda base, start, end=None: {})
    iid = _account(client)
    body = {"kind": "buy", "date": BUY_DAY, "institution_id": iid, "asset_name": "Apple",
            "symbol": "AAPL", "quantity": 1, "unit_price": 100.0,
            "currency": "EUR", "price_currency": "USD"}

    refused = client.post("/api/transactions", json=body)
    typed = client.post("/api/transactions", json={**body, "amount": 86.66})

    assert refused.status_code == 422
    assert "State the amount from your statement" in refused.text
    assert typed.status_code == 201 and typed.json()["amount"] == 86.66


def test_pence_from_a_pound_account_are_divided_not_converted(client, feed):
    """The minor-unit rule, on the cash side: 3361 pence a unit, ten units, is
    336.10 pounds — and no rate was used to get there."""
    iid = _account(client)

    buy = _entry(client, iid, symbol="VUKE.L", asset_name="UK fund", unit_price=3361.0,
                 quantity=10, currency="GBP", price_currency="GBp")

    assert (buy["amount"], buy["fx_as_of"]) == (336.1, None)
    assert feed == []


def test_one_currency_on_both_sides_is_the_arithmetic_it_always_was(client, feed):
    iid = _account(client)

    buy = _entry(client, iid, symbol="VWCE.MI", asset_name="Vanguard", quantity=4,
                 unit_price=110.0, fees=2.95, price_currency="EUR")

    assert (buy["amount"], buy["fx_as_of"]) == (442.95, None)
    assert feed == []


def test_a_sale_in_dollars_realizes_its_gain_in_euro(client, feed):
    """Bought at 100 dollars on a 1.25 day (80.00 euro), sold at 150 dollars on
    a 1.00 day (150.00 euro, less a 2.00 euro fee): 68.00 euro realized, and
    the cash has both legs."""
    iid = _account(client)
    _entry(client, iid)

    sale = _entry(client, iid, kind="sell", date=TODAY, unit_price=150.0, fees=2.0)

    assert (sale["amount"], sale["fx_as_of"]) == (148.0, TODAY)
    row = next(r for r in client.get("/api/dashboard/portfolio").json()["rows"] if r["symbol"] == "AAPL")
    assert row["realized_pl"] == 68.0
    assert client.get(f"/api/institutions/{iid}/cash").json()["projected"] == 1000.0 - 80.0 + 148.0


def test_a_manual_dividend_in_dollars_is_not_taken_for_a_gross_one(client, feed):
    """`estimated` is what the tax estimate reads to find the dividends still
    gross of withholding. A manual dividend whose credit was worked out from a
    rate is an approximation of a different kind, and it must not start
    attracting the withholding — the rate day records it, the flag stays off."""
    iid = _account(client)
    _entry(client, iid, quantity=10)

    dividend = _entry(client, iid, kind="dividend", quantity=10, unit_price=1.0)
    portfolio = client.get("/api/dashboard/portfolio").json()

    assert (dividend["amount"], dividend["fx_as_of"], dividend["estimated"]) == (8.0, BUY_DAY, False)
    assert portfolio["total_dividends"] == 8.0
    assert portfolio["total_dividends_estimated"] == 0.0


def test_a_close_has_no_price_and_a_buy_must_say_what_its_price_is_in(client, feed):
    iid = _account(client)
    _entry(client, iid)

    close = client.post("/api/transactions", json={
        "kind": "close", "date": TODAY, "institution_id": iid, "asset_name": "Apple",
        "symbol": "AAPL", "amount": 90.0, "currency": "EUR"})
    no_price_currency = client.post("/api/transactions", json={
        "kind": "buy", "date": TODAY, "institution_id": iid, "asset_name": "Apple",
        "symbol": "AAPL", "quantity": 1, "unit_price": 100.0, "currency": "EUR"})

    assert close.status_code == 201 and close.json()["price_currency"] is None
    assert no_price_currency.status_code == 422
    assert "needs the currency its price is in" in no_price_currency.text


def test_an_old_entry_whose_listing_trades_in_another_currency_is_pointed_out(client, feed):
    """Every entry written before this could say what its price was in was read
    as euro, and that is what it was given. Whether its 100.00 was dollars or
    euro is not in the row, so a listing that trades in dollars is pointed out,
    not rewritten."""
    iid = _account(client)
    old = _entry(client, iid, price_currency="EUR", currency="EUR")
    _quote_today(100.0, currency="USD")

    listed = {t["id"]: t for t in client.get("/api/transactions").json()}

    assert old["amount"] == 100.0
    assert "recorded in EUR, but AAPL trades in USD" in listed[old["id"]]["currency_note"]


def test_an_account_that_pays_in_dollars_moves_in_dollars(client, monkeypatch):
    """The cash side in a currency that is not the base: a dollar account buys
    a dollar share, so nothing is derived — and the register and the book still
    have to convert the entry, at the day they are read. With today's dollar at
    2.00 to the euro, a copy that took the entry's 100 as euro would be off by
    half. A close in dollars goes through the other door into the book, the one
    for positions a photograph took."""
    monkeypatch.setattr(
        fx, "_fetch_rates",
        lambda base, start, end=None: {BUY_DAY: {"USD": 1.25}, TODAY: {"USD": 2.00}},
    )
    iid = client.post("/api/institutions", json={"name": "Schwab"}).json()["id"]
    client.post(f"/api/institutions/{iid}/cash-anchors",
                json={"date": ANCHOR_DAY, "amount": 1000.0, "currency": "USD"})
    sid = client.post(f"/api/institutions/{iid}/snapshots",
                      json={"date": ANCHOR_DAY}).json()["id"]
    client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "A private fund", "asset_class": "other", "value": 500.0,
        "cost_basis": 400.0, "currency": "USD"})

    buy = _entry(client, iid, currency="USD", price_currency="USD")
    close = client.post("/api/transactions", json={
        "kind": "close", "date": TODAY, "institution_id": iid,
        "asset_name": "A private fund", "amount": 600.0, "currency": "USD"}).json()

    assert (buy["amount"], buy["fx_as_of"]) == (100.0, None)
    then = client.get(f"/api/institutions/{iid}/cash", params={"as_of": BUY_DAY}).json()
    now = client.get(f"/api/institutions/{iid}/cash").json()
    assert then["projected"] == (1000.0 - 100.0) / 1.25
    assert now["projected"] == (1000.0 - 100.0 + 600.0) / 2.00
    rows = {r["asset_name"]: r for r in client.get("/api/dashboard/portfolio").json()["rows"]}
    assert rows["Apple"]["book_value"] == 100.0 / 2.00
    assert close["amount"] == 600.0 and rows["A private fund"]["realized_pl"] == (600.0 - 400.0) / 2.00
