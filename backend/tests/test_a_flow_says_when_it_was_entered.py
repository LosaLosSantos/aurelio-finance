"""Each flow the models read says the day it was entered, beside the day it
starts.

Brief AC's paid run (2026-10-05, a planted conflict on a test database): the
revision wrote that an answer dated 2026-09-20 "likely predates the entry,
which carries a start date of 2026-09-01". Every line said "since <start>" and
nothing said when it was entered, so a model told "not entered yet" by an
answer could not place it before or after the line. Measured at `c61e5bc`
(brief BE): the analyst's line read "..., on no account, since 2026-09-01" and
ended there. Now the chat, the analyst and the MCP server read ", entered
<day>" after it, the reader's day of `created_at`. Every name is invented.
"""

from __future__ import annotations

from sqlalchemy import text

from app import advisor
from app.database import SessionLocal

# Midday in UTC: the same day on this machine's clock and on CI's.
ENTERED_AT = "2026-10-03T10:00:00+00:00"


def _made(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()


def _expense(client, name: str, start: str, **extra) -> int:
    row = _made(client.post("/api/expenses", json={
        "name": name, "amount": 120, "currency": "EUR", "frequency": "monthly",
        "nature": "discretionary", "category": "leisure", "start_date": start, **extra}))
    with SessionLocal() as db:
        db.execute(text("UPDATE expenses SET created_at = :at WHERE id = :id"),
                   {"at": ENTERED_AT, "id": row["id"]})
        db.commit()
    return row["id"]


def test_a_flow_in_force_says_its_start_and_the_day_it_was_entered(client):
    _expense(client, "Cene fuori", "2026-09-01")
    line = "  - Cene fuori [discretionary/leisure] 120.00 EUR monthly, on no account, since 2026-09-01, entered 2026-10-03"
    with SessionLocal() as db:
        assert line in advisor.build_context(db).splitlines()
        assert line in advisor.build_portfolio_context(db).splitlines()


def test_a_flow_still_to_come_and_an_ended_one_say_it_too(client):
    _expense(client, "Corso di vela", "2099-05-01")
    _expense(client, "Abbonamento", "2025-01-10", end_date="2025-06-10")
    with SessionLocal() as db:
        picture = advisor.build_context(db).splitlines()
    assert (
        "  - expense: Corso di vela [discretionary/leisure] 120.00 EUR monthly, on no account, "
        "from 2099-05-01, entered 2026-10-03"
    ) in picture
    assert (
        "  - expense: Abbonamento [discretionary/leisure] 120.00 EUR monthly, on no account, "
        "since 2025-01-10, until 2025-06-10, entered 2026-10-03"
    ) in picture
