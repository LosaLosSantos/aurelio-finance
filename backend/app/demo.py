"""Demo data: an invented household to try Aurelio on before entering your own.

`python -m app.demo` builds `backend/demo.db`, a NEW database file, and fills it
through the app's own HTTP API, so every row passes the rules a form's would. It
never opens `data.db`: it refuses that name, and it refuses any file that
already exists. `./start.ps1 -Demo` and `./start.sh --demo` build it on first use
and start the app on it by setting DATABASE_URL; started without the flag, the
app is on your own `data.db` again, which the demo never touched.

Every name is invented (a "Demo Bank" and a "Demo Broker"), and every date is
counted back from the day the file is built, so the demo always ends today. The
positions are real, widely held listings, so that prices, dividends and the
look-through have something to find once the app is running; they are entered
at prices near the market's of October 2026, and the Portfolio compares them
with what the market says on the day you look. Building it needs no network: every amount is in euros, so no
exchange rate is asked for, and nothing below calls a price.

Why a file of its own and not rows mixed into yours: a demo you can delete
whole is one that can never leave a stray row in your records.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path
from typing import Any

# backend/, without importing app.database: that module reads DATABASE_URL once,
# at import, so nothing here may import it before `build` has set the variable.
BACKEND = Path(__file__).resolve().parent.parent
DEMO_PATH = BACKEND / "demo.db"
REAL_NAME = "data.db"

BANK = "Demo Bank"
BROKER = "Demo Broker"

# Real listings, chosen because they are widely held and Yahoo prices them in
# euros on Xetra; the ISINs are justETF's, so the look-through finds each fund.
WORLD = {"asset_name": "iShares Core MSCI World UCITS ETF USD (Acc)", "symbol": "EUNL.DE",
         "isin": "IE00B4L5Y983", "asset_class": "fund_etf", "distribution_policy": "acc"}
EMERGING = {"asset_name": "iShares Core MSCI Emerging Markets IMI UCITS ETF (Acc)",
            "symbol": "IS3N.DE", "isin": "IE00BKM4GZ66", "asset_class": "fund_etf",
            "distribution_policy": "acc"}
SHARE = {"asset_name": "SAP", "symbol": "SAP.DE", "asset_class": "equity"}
# Entered as a total with no ticker, the way many people record a bond fund:
# the demo shows a position the market cannot price beside the ones it can.
BONDS = {"asset_name": "iShares Core Euro Government Bond UCITS ETF (Dist)",
         "isin": "IE00B4WXJJ64", "asset_class": "bond", "distribution_policy": "dist"}


class DemoRefused(RuntimeError):
    """The demo will not be built where it was asked to be, and says why."""


def _day(d: datetime.date) -> str:
    return d.isoformat()


def _months_back(today: datetime.date, months: int, day: int) -> datetime.date:
    """The `day` of the month `months` before today's (a day no month lacks)."""
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return datetime.date(year, month, min(day, 28))


def _next_month(today: datetime.date, day: int) -> datetime.date:
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return datetime.date(year, month, min(day, 28))


def _made(response) -> dict[str, Any] | list[Any]:
    """The body of a write the API accepted, or the API's own sentence."""
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"the demo's {response.request.method} {response.request.url.path} was "
            f"refused ({response.status_code}): {response.text}"
        )
    return response.json()


def _situation(client, institution_id: int, date: datetime.date, rows: list[dict]) -> int:
    snapshot = _made(client.post(f"/api/institutions/{institution_id}/snapshots",
                                 json={"date": _day(date)}))
    for row in rows:
        _made(client.post(f"/api/snapshots/{snapshot['id']}/holdings",
                          json={"currency": "EUR", **row}))
    return snapshot["id"]


def _survey() -> list[dict[str, str]]:
    """Answers in the Profile form's own keys and words, as it sends them."""
    answers = [
        ("about_country", "About you", "Which country do you live in?", "Germany"),
        ("about_area", "About you", "Which city or area?", "Hamburg"),
        ("about_age", "About you", "Your age?", "36"),
        ("about_employment", "About you", "Employment status?", "Employee"),
        ("about_household", "About you", "Household?", "Couple"),
        ("about_dependents", "About you", "How many people depend on you financially?", "0"),
        ("about_home", "About you", "Your housing situation?", "Own (with mortgage)"),
        ("lit_why_invest", "Financial literacy", "Do you know why people invest?", "yes"),
        ("lit_inflation", "Financial literacy", "Do you know what inflation is?", "yes"),
        ("lit_risk_return", "Financial literacy", "Do you know the risk/return trade-off?", "yes"),
        ("lit_diversification", "Financial literacy", "Do you know what diversification is?", "yes"),
        ("ret_age", "Retirement & horizon",
         "At what age would you like to retire or be financially independent?", "60"),
        ("risk_tolerance", "Risk & values", "How would you describe your risk tolerance?", "Medium"),
        ("values_esg", "Risk & values",
         "Do ethical / ESG considerations matter for your investments?", "unsure"),
        ("self_narrative", "In your words",
         "Write freely about yourself and your money: what you are working towards, what "
         "worries you, what you would never give up, how you want Aurelio to talk to you. "
         "Nothing here is validated or scored: it is context.",
         "We bought the flat six years ago and would like the mortgage gone well before "
         "retirement. I prefer a few cheap index funds to picking shares, and I do not want "
         "to watch the markets every day. Be direct with me, and tell me when I am wrong."),
    ]
    return [{"question_key": k, "topic": t, "question": q, "answer": a} for k, t, q, a in answers]


def populate(client, today: datetime.date) -> dict[str, int]:
    """Fill an empty database with the demo, through `client` (any client of
    this app's API). Returns the ids a caller may want; raises on the first
    write the API refuses, with the API's own sentence."""
    # The whole history fits inside a year: the Dashboard's chart names its
    # days without their year, and two "Oct 6" on one axis read as a bug.
    first = today - datetime.timedelta(days=330)
    earlier = today - datetime.timedelta(days=300)
    quarter_ago = today - datetime.timedelta(days=90)

    bank = _made(client.post("/api/institutions", json={"name": BANK}))["id"]
    broker = _made(client.post("/api/institutions", json={"name": BROKER}))["id"]

    # Two photographs months apart, the newer one naming everything the older
    # did: the net worth over time has a history, and nothing has gone missing.
    _situation(client, broker, earlier, [
        {**WORLD, "quantity": 45, "unit_price": 122.0},
        {**EMERGING, "quantity": 120, "unit_price": 44.0},
        {**BONDS, "value": 2400.0},
    ])
    newest = _situation(client, broker, quarter_ago, [
        {**WORLD, "quantity": 70, "unit_price": 128.0},
        {**EMERGING, "quantity": 160, "unit_price": 47.5},
        {**SHARE, "quantity": 6, "unit_price": 195.0},
        {**BONDS, "value": 2450.0},
    ])

    for institution, before, later in ((bank, 7800.0, 10400.0), (broker, 600.0, 900.0)):
        for date, amount in ((earlier, before), (quarter_ago, later)):
            _made(client.post(f"/api/institutions/{institution}/cash-anchors",
                              json={"date": _day(date), "amount": amount, "currency": "EUR"}))

    started = _months_back(today, 11, 1)
    _made(client.post("/api/income-sources", json={
        "name": "Salary", "kind": "active", "category": "salary", "amount": 3400.0,
        "currency": "EUR", "frequency": "monthly", "institution_id": bank,
        "start_date": _day(_months_back(today, 11, 27)),
    }))
    for name, category, nature, amount, frequency in (
        ("Mortgage payment", "debt", "essential", 1050.0, "monthly"),
        ("Groceries", "food", "essential", 480.0, "monthly"),
        ("Electricity and heating", "utilities", "essential", 190.0, "monthly"),
        ("Public transport", "transport", "essential", 140.0, "monthly"),
        ("Eating out and leisure", "leisure", "discretionary", 260.0, "monthly"),
        ("Home insurance", "insurance", "essential", 540.0, "annual"),
    ):
        _made(client.post("/api/expenses", json={
            "name": name, "category": category, "nature": nature, "amount": amount,
            "currency": "EUR", "frequency": frequency, "institution_id": bank,
            "start_date": _day(started),
        }))

    _made(client.post("/api/transfers", json={
        "date": _day(today - datetime.timedelta(days=60)), "amount": 1000.0,
        "currency": "EUR", "to_currency": "EUR",
        "from_institution_id": bank, "to_institution_id": broker,
        "note": "Topping up the broker for the monthly plan",
    }))
    _made(client.post("/api/transactions", json={
        "kind": "buy", "date": _day(today - datetime.timedelta(days=20)),
        "institution_id": broker, **SHARE, "quantity": 4, "unit_price": 191.0,
        "fees": 2.0, "currency": "EUR", "price_currency": "EUR",
    }))
    # Starts next month, so it has bought nothing yet and asks no price today.
    _made(client.post("/api/accumulation-plans", json={
        "name": "Monthly world fund", "amount": 300.0, "currency": "EUR",
        "frequency": "monthly", "execution": "whole_units",
        "start_date": _day(_next_month(today, 5)), "source_institution_id": broker,
        "targets": [{"symbol": WORLD["symbol"], "asset_name": WORLD["asset_name"],
                     "isin": WORLD["isin"], "institution_id": broker, "weight": 1}],
    }))

    flat = _made(client.post("/api/real-assets", json={
        "name": "Apartment", "category": "real_estate", "currency": "EUR",
        "acquisition_date": _day(_months_back(today, 72, 15)), "acquisition_value": 265000.0,
    }))["id"]
    mortgage = _made(client.post("/api/liabilities", json={
        "name": "Mortgage", "kind": "mortgage", "interest_rate": 2.1,
        "real_asset_id": flat, "currency": "EUR",
    }))["id"]
    month_ago = today - datetime.timedelta(days=30)
    for date, value in ((first, 296000.0), (month_ago, 305000.0)):
        _made(client.post(f"/api/real-assets/{flat}/valuations",
                          json={"date": _day(date), "value": value}))
    for date, balance in ((first, 207000.0), (month_ago, 199500.0)):
        _made(client.post(f"/api/liabilities/{mortgage}/balances",
                          json={"date": _day(date), "balance": balance}))

    for goal in (
        {"name": "Emergency fund", "type": "emergency_fund",
         "notes": "Six months of expenses, kept at the bank."},
        {"name": "Retire at 60", "type": "long_term_growth"},
        {"name": "A new car", "type": "target_amount", "target_amount": 18000.0,
         "target_date": _day(datetime.date(today.year + 3, today.month, min(today.day, 28))),
         "current_amount": 4000.0, "monthly_contribution": 250.0},
    ):
        _made(client.post("/api/goals", json={"currency": "EUR", **goal}))

    _made(client.put("/api/survey", json=_survey()))
    return {"bank": bank, "broker": broker, "situation": newest, "apartment": flat,
            "mortgage": mortgage}


def _refusal(path: Path) -> str | None:
    if path.name == REAL_NAME or path == (BACKEND / REAL_NAME).resolve():
        return (f"The demo is never built into {REAL_NAME}, which is where your own "
                f"records live. Give it another file name.")
    if path.exists():
        return (f"{path} already exists, and the demo is only ever written into a new "
                f"file. Delete it first to build the demo again.")
    return None


def build(path: Path = DEMO_PATH, today: datetime.date | None = None) -> Path:
    """Build the demo into `path`, a file that must not exist yet.

    Runs the app in this process against that file, so it refuses a process
    whose app is already bound to another database: that is how a demo would
    end up in someone's records."""
    path = Path(path).resolve()
    why = _refusal(path)
    if why:
        raise DemoRefused(why)
    url = f"sqlite:///{path}"
    bound = sys.modules.get("app.database")
    if bound is not None and bound.DATABASE_URL != url:
        raise DemoRefused(
            f"This process already runs the app on {bound.DATABASE_URL}; the demo is "
            f"built in a fresh one (python -m app.demo), never into another database."
        )
    os.environ["DATABASE_URL"] = url

    from fastapi.testclient import TestClient

    from app import database
    from app.main import app

    try:
        with TestClient(app) as client:
            populate(client, today or datetime.date.today())
    except BaseException:
        # Ours since a moment ago and incomplete: a half-built demo would be
        # refused next time as a file that exists.
        database.engine.dispose()
        path.unlink(missing_ok=True)
        raise
    database.engine.dispose()
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.demo",
        description="Build Aurelio's demo database: an invented household, never your data.",
    )
    parser.add_argument("--path", type=Path, default=DEMO_PATH,
                        help="the new file to build (default: backend/demo.db)")
    parser.add_argument("--if-missing", action="store_true",
                        help="if the file is already there, keep it and say so")
    args = parser.parse_args(argv)
    path = args.path.resolve()
    if args.if_missing and path.exists() and path.name != REAL_NAME:
        print(f"Demo database already there: {path}")
        return 0
    try:
        build(path)
    except DemoRefused as refused:
        print(refused, file=sys.stderr)
        return 2
    print(f"Demo database built: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
