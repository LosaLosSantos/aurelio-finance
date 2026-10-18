from __future__ import annotations

import datetime
import types
from zoneinfo import ZoneInfo

import pytest

from app import dated, prices
from tests.yahoo_chart import Listing, install

REAL_FETCH_CLOSE_WINDOW = prices._fetch_close_window


@pytest.fixture
def chart(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "_fetch_close_window", REAL_FETCH_CLOSE_WINDOW)
    monkeypatch.setattr(dated, "today", lambda: "2026-01-10")
    return install(monkeypatch, tmp_path)


@pytest.mark.parametrize("on", [None, "2026-01-09"])
@pytest.mark.parametrize("failure", ["delisted", "service", "transport"])
def test_quote_failures_use_the_price_error_response(client, chart, monkeypatch, on, failure):
    if failure != "delisted":
        chart.listings["XFAIL.DE"] = Listing(closes={"2026-01-09": 50.0})
        answer = chart.answer

        def unavailable(url, params):
            if "period1" not in params:
                return answer(url, params)
            if failure == "transport":
                raise TimeoutError("Yahoo unavailable")
            return types.SimpleNamespace(
                status_code=200, text="", json=lambda: {
                    "chart": {"result": None, "error": {
                        "code": "Internal Server Error", "description": "Yahoo unavailable",
                    }},
                },
            )

        monkeypatch.setattr(chart, "answer", unavailable)
    params = {"symbol": "XFAIL.DE"}
    if on:
        params["on"] = on
    response = client.get("/api/prices/quote", params=params)
    assert response.status_code in (502, 503)
    assert response.json()["detail"]


def test_catch_up_skips_a_delisted_target_and_runs_later_plans(client, chart, monkeypatch):
    monkeypatch.setattr(prices, "_fetch_currency", lambda symbol: "EUR")
    chart.listings["XGOOD.DE"] = Listing(closes={"2026-01-09": 50.0})
    broker = client.post("/api/institutions", json={"name": "Broker"}).json()["id"]
    for name, symbol in (("Delisted", "XGONE.DE"), ("Healthy", "XGOOD.DE")):
        response = client.post("/api/accumulation-plans", json={
            "name": name, "amount": 100, "currency": "EUR", "frequency": "annual",
            "start_date": "2026-01-09", "source_institution_id": broker,
            "targets": [{
                "symbol": symbol, "asset_name": name, "institution_id": broker,
            }],
        })
        assert response.status_code == 201, response.text
    response = client.post("/api/transactions/catch-up")
    assert response.status_code == 200, response.text
    skipped = response.json()["skipped"]
    assert any(row["label"] == "Delisted" and "XGONE.DE" in row["reason"] for row in skipped)
    (buy,) = client.get("/api/transactions").json()
    assert (buy["symbol"], buy["quantity"], buy["unit_price"]) == ("XGOOD.DE", 2, 50.0)


@pytest.mark.parametrize("timezone", ["Asia/Tokyo", "America/New_York"])
def test_dated_closes_keep_the_exchanges_calendar_day(chart, monkeypatch, timezone):
    chart.listings["XDAY"] = Listing(
        closes={"2026-01-08": 90.0, "2026-01-09": 100.0}, timezone=timezone,
    )
    answer = chart.answer

    def local_midnight(url, params):
        response = answer(url, params)
        body = response.json()
        result = body["chart"]["result"][0]
        result["timestamp"] = [
            int(datetime.datetime.combine(
                datetime.date(2026, 1, day), datetime.time(), ZoneInfo(timezone),
            ).timestamp())
            for day in (8, 9)
        ]
        return types.SimpleNamespace(status_code=200, text="", json=lambda: body)

    monkeypatch.setattr(chart, "answer", local_midnight)
    quote = prices.get_price_on("XDAY", datetime.date(2026, 1, 9))
    assert (quote["price"], quote["as_of"]) == (100.0, "2026-01-09")
