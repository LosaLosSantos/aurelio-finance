"""The cash line the chat and the analyst read adds up to its own figure.

`advisor._render_cash` printed the anchor, the income, the expenses and the
transfers, while the figure in front of them (`compute_cash_position`) also
takes off the buys and adds the sells, the dividends and the closes. With a
buy or a dividend on record after the anchor the parts did not make the
total, as brief AI measured on a copy of the test database on 2026-10-07.
Every name and amount here is invented.
"""

from __future__ import annotations

import datetime
import re

import pytest

from app import advisor
from app.database import SessionLocal

TODAY = datetime.date.today()


def _day(days_ago: int) -> str:
    return (TODAY - datetime.timedelta(days=days_ago)).isoformat()


def _made(response) -> int:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.fixture
def accounts(client) -> None:
    """Every kind of term after one anchor, each on its own day, none of them
    repeating, so the projection is the same whatever today is."""
    alfa = _made(client.post("/api/institutions", json={"name": "Banca Alfa"}))
    beta = _made(client.post("/api/institutions", json={"name": "Banca Beta"}))
    for bank, cash in ((alfa, 1000), (beta, 0)):
        _made(client.post(f"/api/institutions/{bank}/cash-anchors",
                          json={"date": _day(30), "amount": cash, "currency": "EUR"}))
    _made(client.post("/api/income-sources", json={
        "name": "Bonus", "amount": 500, "currency": "EUR", "frequency": "one_off",
        "institution_id": alfa, "start_date": _day(5)}))
    _made(client.post("/api/expenses", json={
        "name": "Repair", "amount": 30, "currency": "EUR", "frequency": "one_off",
        "institution_id": alfa, "start_date": _day(15)}))
    _made(client.post("/api/transfers", json={
        "date": _day(12), "from_institution_id": beta, "to_institution_id": alfa,
        "amount": 100, "currency": "EUR", "to_currency": "EUR"}))
    entry = {"institution_id": alfa, "asset_name": "Fondo Alfa", "symbol": "ALFA.MI",
             "currency": "EUR", "price_currency": "EUR"}
    _made(client.post("/api/transactions", json={
        **entry, "kind": "buy", "date": _day(20), "quantity": 2, "unit_price": 100}))
    _made(client.post("/api/transactions", json={
        **entry, "kind": "dividend", "date": _day(8), "quantity": 2, "unit_price": 7.5}))
    _made(client.post("/api/transactions", json={
        **entry, "kind": "sell", "date": _day(3), "quantity": 1, "unit_price": 110}))


def _cash_lines(context: str) -> list[str]:
    return [line for line in context.splitlines() if line.startswith("- Banca ")]


def test_the_line_names_the_ledger_beside_the_flows(accounts):
    with SessionLocal() as db:
        chat = advisor.build_context(db)

    assert _cash_lines(chat) == [
        f"- Banca Alfa: 1495.00 (anchor 1000.00 on {_day(30)}; +income 500.00 −expenses 30.00; "
        "transfers +100.00/−0.00; −buys 200.00 +sells, dividends and closes 125.00)",
        f"- Banca Beta: -100.00 (anchor 0.00 on {_day(30)}; +income 0.00 −expenses 0.00; "
        "transfers +0.00/−100.00; −buys 0.00 +sells, dividends and closes 0.00)",
    ]


TERM = re.compile(
    r": (?P<figure>-?\d+\.\d\d) \(anchor (?P<anchor>-?\d+\.\d\d) on \S+; "
    r"\+income (?P<income>\d+\.\d\d) −expenses (?P<expenses>\d+\.\d\d); "
    r"transfers \+(?P<t_in>\d+\.\d\d)/−(?P<t_out>\d+\.\d\d); "
    r"−buys (?P<buys>\d+\.\d\d) \+sells, dividends and closes (?P<sells>\d+\.\d\d)\)$"
)


def test_the_parts_on_each_line_make_its_figure_for_the_chat_and_the_analyst(accounts):
    with SessionLocal() as db:
        contexts = (advisor.build_context(db), advisor.build_portfolio_context(db))

    for context in contexts:
        lines = _cash_lines(context)
        assert len(lines) == 2
        for line in lines:
            m = TERM.search(line)
            assert m, line
            v = {k: float(x) for k, x in m.groupdict().items()}
            parts = (v["anchor"] + v["income"] - v["expenses"] + v["t_in"] - v["t_out"]
                     - v["buys"] + v["sells"])
            assert parts == pytest.approx(v["figure"], abs=0.005), line
