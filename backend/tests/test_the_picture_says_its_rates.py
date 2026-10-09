"""The chat's picture says which exchange rates the app keeps.

The reader's second test round of the chat (2026-10-08): asked about a figure
in dollars, the chat answered that it had no exchange rate, with the app
holding the ECB's and every total in the picture converted at them. Brief AL:
one line under the base, the ECB's rates in force today for every currency on
record that is not the base, with the day they were published; none when
everything is in the base.

The feed is faked at `fx._fetch_rates`. Amounts and names are invented.
"""

from __future__ import annotations

import datetime

import pytest

from app import advisor, fx, models
from app.database import SessionLocal

TODAY = datetime.date.today()
PUBLISHED = (TODAY - datetime.timedelta(days=1)).isoformat()


@pytest.fixture()
def ecb(monkeypatch):
    def fetch(base, start, end=None):
        assert base == "EUR"
        return {PUBLISHED: {"USD": 1.1403, "GBP": 0.8653, "CHF": 0.9312, "TRY": 55.7975}}

    monkeypatch.setattr(fx, "_fetch_rates", fetch)


def _picture() -> str:
    with SessionLocal() as db:
        return advisor.build_context(db)


def _rates_line(picture: str) -> str | None:
    lines = [line for line in picture.split("\n") if line.startswith("Exchange rates:")]
    assert len(lines) <= 1
    return lines[0] if lines else None


def _account(client, name: str, amount: float, currency: str) -> None:
    iid = client.post("/api/institutions", json={"name": name}).json()["id"]
    r = client.post(
        f"/api/institutions/{iid}/cash-anchors",
        json={"date": PUBLISHED, "amount": amount, "currency": currency},
    )
    assert r.status_code == 201, r.text


def test_the_rates_of_the_currencies_on_record_are_in_the_picture(client, ecb):
    _account(client, "Account in dollars", 1000.0, "USD")
    _account(client, "Account in francs", 500.0, "CHF")

    line = _rates_line(_picture())

    assert line == (
        "Exchange rates: the ECB's reference rates, which the app keeps; those in "
        f"force today were published on {PUBLISHED}: 1 EUR = 0.9312 CHF, 1.1403 USD."
    )


def test_only_the_base_on_record_says_nothing_about_rates(client, ecb):
    _account(client, "Account in euro", 1000.0, "EUR")

    assert _rates_line(_picture()) is None


def test_pence_ask_for_the_pounds_rate(client, ecb):
    """A London listing in pence is converted as pounds: the rate said is the
    pound's, under its own code."""
    _account(client, "Account in pounds", 100.0, "GBP")
    with SessionLocal() as db:
        published, rates, missing = fx.rates_for(db, {"GBp", "GBP", "EUR"})

    assert (published, rates, missing) == (PUBLISHED, {"GBP": 0.8653}, [])
    assert _rates_line(_picture()).endswith("1 EUR = 0.8653 GBP.")


def test_a_currency_the_ecb_does_not_publish_is_named_as_such(client, ecb):
    """A currency no feed quotes, written on a row before the forms checked
    one (the kind brief V found), is said to have no rate rather than left for
    the model to guess at."""
    _account(client, "Account in dollars", 1000.0, "USD")
    with SessionLocal() as db:
        db.add(models.RealAsset(name="A car", category="vehicle", currency="Dlr"))
        db.commit()

    line = _rates_line(_picture())

    assert line.endswith("1 EUR = 1.1403 USD. The ECB publishes no rate for Dlr.")


def test_the_rates_are_read_like_any_conversion_of_today(client, ecb, monkeypatch):
    """No new question to the feed: once today's rates are stored, the line is
    read from the store."""
    _account(client, "Account in dollars", 1000.0, "USD")
    _picture()

    def refuse(*args, **kwargs):
        raise AssertionError("the feed was asked again")

    monkeypatch.setattr(fx, "_fetch_rates", refuse)
    assert "1.1403 USD" in _rates_line(_picture())
