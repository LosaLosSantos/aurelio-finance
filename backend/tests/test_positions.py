"""The Position type: the one definition of what a holding is worth today.

`current_value` used to be written out twice, in two modules, and the two
bodies disagreed — which is how the Dashboard once showed two financial
totals, one above the other, differing by the size of the portfolio's
unrealised gain. There is now one body and nowhere to put a second, so what
these tests pin down is the rule itself.
"""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from app import fx, positions
from app.database import SessionLocal

TODAY = datetime.date.today().isoformat()


def _position(**over) -> positions.Position:
    """A minimal Position; override only the field under test."""
    base = dict(
        institution_id=1,
        asset_name="Something",
        symbol=None,
        isin=None,
        asset_class=None,
        distribution_policy=None,
        quantity=None,
        book_value=0.0,
        observed_value=0.0,
        market_value=None,
        realized_pl=0.0,
        dividends=0.0,
        dividends_estimated=0.0,
        cost_known=False,
        cost_estimated=False,
        observed_on=TODAY,
        closed_on=None,
        currency_note=None,
    )
    return positions.Position(**{**base, **over})


def test_current_value_is_the_market_where_there_is_one_and_the_observation_where_there_is_not():
    """What it is worth, and never what it cost.

    This assertion used to read `current_value == book_value` when nothing
    could price the row, and that was the defect rather than the rule: a
    position whose photograph said 500 and whose receipt said 400 answered 400
    to a question about worth. The fallback is the last OBSERVED value; the
    book stays what was paid, which is what the P/L is measured against."""
    assert _position(observed_value=100.0, market_value=130.0).current_value == 130.0
    assert _position(observed_value=100.0, market_value=None).current_value == 100.0
    assert _position(observed_value=100.0, market_value=130.0).is_priced is True
    assert _position(observed_value=100.0, market_value=None).is_priced is False
    # The two readings of one row, kept apart: the receipt does not answer for
    # the statement, in either direction.
    unpriced = _position(book_value=400.0, observed_value=500.0)
    assert unpriced.current_value == 500.0 and unpriced.book_value == 400.0


def test_a_market_value_of_zero_is_a_price_not_a_missing_one():
    """`is not None`, never truthiness. A position the market says is worth
    nothing is a priced position — falling back to its basis there would
    resurrect an observation the market has already written off."""
    p = _position(observed_value=100.0, market_value=0.0)
    assert p.is_priced is True and p.current_value == 0.0


def test_a_position_cannot_be_edited_after_it_is_projected():
    """A projection is a reading, not a record: no consumer gets to adjust a
    number and have the adjustment travel to the next one."""
    p = _position(book_value=100.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.book_value = 999.0


def test_project_carries_one_converter_so_the_rate_date_survives(client, monkeypatch):
    """The caller's converter is the one that does the work, so `used_as_of`
    afterwards covers the book values too — not only the market values the
    caller happens to convert itself."""
    monkeypatch.setattr(
        fx, "_fetch_rates", lambda base, start, end=None: {"2026-08-20": {"USD": 1.25}}
    )
    iid = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    sid = client.post(
        f"/api/institutions/{iid}/snapshots", json={"date": TODAY}
    ).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "US stock", "asset_class": "equity", "value": 125,
              "currency": "USD"},
    )

    with SessionLocal() as db:
        conv = fx.Converter(db)
        assert conv.used_as_of is None
        held = positions.project(db, conv)
        assert [type(p) for p in held] == [positions.Position]
        assert held[0].book_value == 100.0  # 125 USD / 1.25
        assert conv.used_as_of == "2026-08-20"
