"""A distributing ticker Yahoo knows nothing of is asked about once a day.

Brief X keeps an answer and never a silence, so an outage is asked again at
the next start (the reader's choice for less noise, 2026-09-30). yfinance
reports a ticker it does not know exactly as an outage, so such a ticker was
asked at every catch-up, which the page posts at every load: measured at
`c61e5bc` (brief BE), three catch-ups in a day, three asks, while its price was
already asked once a day (`unpriced:`, brief AK). Now the market's canary tells
the two apart for dividends too: Yahoo silent while the market answers is kept
for the reader's day; an outage is kept nowhere. Every name is invented.
"""

from __future__ import annotations

import pytest

from app import dated, models, prices
from app.database import SessionLocal

UNKNOWN = "ZZUNK.MI"


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


@pytest.fixture()
def asked(client, monkeypatch) -> list[str]:
    bank = _made(client.post("/api/institutions", json={"name": "Broker Epsilon"}))["id"]
    sid = _made(client.post(f"/api/institutions/{bank}/snapshots", json={"date": "2026-09-01"}))["id"]
    _made(client.post(f"/api/snapshots/{sid}/holdings", json={
        "asset_name": "Azione Epsilon", "asset_class": "equity", "symbol": UNKNOWN,
        "quantity": 10, "unit_price": 10, "currency": "EUR", "distribution_policy": "dist"}))
    seen: list[str] = []

    def dividends(symbol, period="max"):
        seen.append(symbol)
        return prices.DividendWindow(answered=False, dividends=[])

    monkeypatch.setattr(prices, "_fetch_dividends", dividends)
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    monkeypatch.setattr(prices, "_fetch_recent_closes", lambda symbols: {})
    monkeypatch.setattr(dated, "today", lambda: "2026-10-21")
    return seen


def _market(monkeypatch, answers: bool) -> None:
    monkeypatch.setattr(prices, "market_reachable", lambda: answers)


def _catch_ups(client, n: int) -> None:
    for _ in range(n):
        _made(client.post("/api/transactions/catch-up"))


def test_three_page_loads_ask_once_while_the_market_answers(client, monkeypatch, asked):
    _market(monkeypatch, True)

    _catch_ups(client, 3)

    assert asked == [UNKNOWN]


def test_an_outage_is_asked_again_at_every_load_as_decided(client, monkeypatch, asked):
    _market(monkeypatch, False)

    _catch_ups(client, 3)

    assert asked == [UNKNOWN] * 3


def test_the_next_day_it_is_asked_again(client, monkeypatch, asked):
    _market(monkeypatch, True)
    _catch_ups(client, 2)
    monkeypatch.setattr(dated, "today", lambda: "2026-10-22")

    _catch_ups(client, 2)

    assert asked == [UNKNOWN] * 2
    with SessionLocal() as db:
        kept = {s.key: s.value for s in db.query(models.Setting) if s.key.startswith("dividends_unanswered:")}
    assert kept == {f"dividends_unanswered:{UNKNOWN}": "2026-10-22"}, "the earlier day's row goes"
