"""Every monthly figure counts the income and expenses in force today.

Until brief AI (2026-10-07) the Cash flow page, the Dashboard and the chat read
a run-rate that ignored the dates: a salary that starts next month was summed
as one running now, an expense that had ended as one still paid, and nothing on
screen or in the chat's context said either. Brief Z had moved the analysis to
the flows in force; every other reader now reads the same computation,
`analytics.compute_flows_in_force`, and is told which flows it leaves out.

Every name and amount here is invented.
"""

from __future__ import annotations

import datetime

import pytest

from app import advisor
from app.database import SessionLocal

TODAY = datetime.date.today()
YESTERDAY = (TODAY - datetime.timedelta(days=1)).isoformat()
TOMORROW = (TODAY + datetime.timedelta(days=1)).isoformat()
LONG_AGO = (TODAY - datetime.timedelta(days=400)).isoformat()
ENDED = (TODAY - datetime.timedelta(days=20)).isoformat()
SOON = (TODAY + datetime.timedelta(days=25)).isoformat()
LATER = (TODAY + datetime.timedelta(days=80)).isoformat()


def _made(response) -> int:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _income(client, name, amount, start, kind="active", category="salary", **extra) -> int:
    return _made(client.post("/api/income-sources", json={
        "name": name, "amount": amount, "currency": "EUR", "frequency": "monthly",
        "kind": kind, "category": category, "start_date": start, **extra}))


def _expense(client, name, amount, start, nature, category, **extra) -> int:
    return _made(client.post("/api/expenses", json={
        "name": name, "amount": amount, "currency": "EUR", "frequency": "monthly",
        "nature": nature, "category": category, "start_date": start, **extra}))


@pytest.fixture
def flows(client) -> dict[str, int]:
    """Two incomes in force and one still to start; rent in force, an undated
    gift, a gym that ended and a car bought once, later. Linked to no
    account, so no cash register moves."""
    return {
        "salary": _income(client, "Salary", 2500, LONG_AGO),
        "coupon": _income(client, "Coupon", 100, LONG_AGO, kind="passive", category="interest"),
        "new job": _income(client, "New job", 4000, SOON),
        "rent": _expense(client, "Rent", 900, LONG_AGO, "essential", "housing"),
        "gift": _expense(client, "Gift", 100, None, "discretionary", "other"),
        "gym": _expense(client, "Gym", 40, LONG_AGO, "discretionary", "leisure", end_date=ENDED),
        "car": _expense(client, "Car", 12000, LATER, "discretionary", "transport",
                        frequency="one_off"),
    }


def _section(text: str, heading: str) -> list[str]:
    """The lines of one section: from its heading to the blank line after it."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next((i for i in range(start, len(lines)) if not lines[i]), len(lines))
    return lines[start:end]


# --- The page and the Dashboard ---------------------------------------------------


def test_the_page_counts_only_the_flows_in_force_today(flows, client):
    cf = client.get("/api/dashboard/cashflow").json()

    assert cf["on"] == TODAY.isoformat()
    # The new job is not counted until it starts, the gym no longer, the car
    # never (a one-off adds nothing a month); the undated gift is counted.
    assert (cf["monthly_income"], cf["active_income"], cf["passive_income"]) == (2600.0, 2500.0, 100.0)
    assert (cf["monthly_expenses"], cf["essential_expenses"], cf["discretionary_expenses"]) == (
        1000.0, 900.0, 100.0,
    )
    assert cf["monthly_net"] == 1600.0
    assert cf["savings_rate"] == pytest.approx(1600 / 2600)
    assert (cf["incomes_in_force"], cf["expenses_in_force"], cf["undated"]) == (2, 2, 1)


def test_the_page_is_told_which_flows_are_left_out_and_why(flows, client):
    cf = client.get("/api/dashboard/cashflow").json()

    assert cf["scheduled"] == [
        {"side": "income", "id": flows["new job"], "name": "New job", "frequency": "monthly",
         "start_date": SOON, "end_date": None},
        {"side": "expense", "id": flows["car"], "name": "Car", "frequency": "one_off",
         "start_date": LATER, "end_date": None},
    ]
    assert cf["ended"] == [
        {"side": "expense", "id": flows["gym"], "name": "Gym", "frequency": "monthly",
         "start_date": LONG_AGO, "end_date": ENDED},
    ]


def test_a_flow_is_in_force_on_its_first_day_and_on_its_last(client):
    first = _income(client, "Starts today", 1000, TODAY.isoformat())
    last = _expense(client, "Ends today", 300, LONG_AGO, "essential", "housing",
                    end_date=TODAY.isoformat())
    gone = _expense(client, "Ended yesterday", 50, LONG_AGO, "essential", "food",
                    end_date=YESTERDAY)
    coming = _income(client, "Starts tomorrow", 700, TOMORROW)

    cf = client.get("/api/dashboard/cashflow").json()

    assert (cf["monthly_income"], cf["monthly_expenses"]) == (1000.0, 300.0)
    assert [f["id"] for f in cf["scheduled"]] == [coming]
    assert [f["id"] for f in cf["ended"]] == [gone]
    assert first not in [f["id"] for f in cf["scheduled"] + cf["ended"]]
    assert last not in [f["id"] for f in cf["scheduled"] + cf["ended"]]


# --- The chat ----------------------------------------------------------------------


def test_the_chat_counts_the_flows_in_force_and_lists_the_others_apart(flows):
    with SessionLocal() as db:
        chat = advisor.build_context(db)

    assert _section(chat, "## Income and expenses in force today") == [
        f"## Income and expenses in force today ({TODAY}), as a monthly run-rate",
        "- Income: 2600.00 a month (active 2500.00, passive 100.00)",
        "- Expenses: 1000.00 a month (essential 900.00, discretionary 100.00)",
        "- Left each month (income minus expenses): 1600.00, a savings rate of 61.5%",
        "- 1 of these flows has no start date, so it is counted as in force.",
        "- Income in force today:",
        f"  - Salary [active/salary] 2500.00 EUR monthly, since {LONG_AGO}",
        f"  - Coupon [passive/interest] 100.00 EUR monthly, since {LONG_AGO}",
        "- Expenses in force today:",
        f"  - Rent [essential/housing] 900.00 EUR monthly, since {LONG_AGO}",
        "  - Gift [discretionary/other] 100.00 EUR monthly, no start date",
        "- Starting after today, so NOT counted above:",
        f"  - income: New job [active/salary] 4000.00 EUR monthly, from {SOON}",
        f"  - expense: Car [discretionary/transport] 12000.00 EUR one_off, from {LATER}",
        "- Ended before today, so NOT counted above:",
        f"  - expense: Gym [discretionary/leisure] 40.00 EUR monthly, since {LONG_AGO}, until {ENDED}",
    ]


def test_the_chat_has_no_second_list_of_flows_without_dates(flows):
    """The run-rate block and the two dateless lists the chat read: the job
    that had not started was printed there as a running income."""
    with SessionLocal() as db:
        chat = advisor.build_context(db)

    assert "## Monthly cash flow (run-rate)" not in chat
    assert "## Income sources" not in chat.splitlines()
    assert "## Expenses" not in chat.splitlines()
    assert sum("New job" in line for line in chat.splitlines()) == 1


def test_the_chat_and_the_analyst_read_one_block(flows):
    with SessionLocal() as db:
        chat, analyst = advisor.build_context(db), advisor.build_portfolio_context(db)

    heading = "## Income and expenses in force today"
    assert _section(chat, heading) == _section(analyst, heading)


def test_an_income_still_to_start_is_not_an_income_the_chat_counts(client):
    _income(client, "New job", 4000, SOON)
    _expense(client, "Rent", 900, LONG_AGO, "essential", "housing")
    with SessionLocal() as db:
        chat = advisor.build_context(db)

    assert "- Income: none in force today" in chat
    assert (
        "- What is left each month cannot be said: no income is in force today."
    ) in chat
