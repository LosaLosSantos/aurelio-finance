"""An occurrence that ran is not an occurrence that bought.

The catch-up decided a PAC occurrence was finished by asking whether a
Transaction carried its key. That is the right question for "did it buy" and
the wrong one for "did it run": a contribution too small to reach one whole
unit of any target is folded into the plan's carried remainder and writes no
transaction, so the occurrence read as never having run. It came back on the
next catch-up with a fresh contribution on top of a carry a LATER occurrence
had already spent — and the catch-up runs at every app start, so the trigger
was restarting the app. Two 100 EUR contributions bought two 150 EUR units.

This table is where such an occurrence says it ran, with the reason it bought
nothing. Only unfilled ones: an occurrence that bought is still recognised by
its transactions, so deleting an auto-created buy still puts it back in the
queue. A priced failure records nothing and is still retried, which is the
distinction the old rule could not make.

Nothing is backfilled, and nothing needs to be. A plan that has been running
for months keeps every occurrence it bought — those are read from the ledger,
as before. Its past occurrences that bought nothing have no row here, so they
are still due: they run ONCE more, record themselves, commit the carry they
absorb, and then stop coming back. That is one catch-up, not a replay of the
plan's history.

Revision ID: d84f2b6c1a03
Revises: a1d7f39c62b4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d84f2b6c1a03"
down_revision = "a1d7f39c62b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_unfilled_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.String(), nullable=False),  # YYYY-MM-DD
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["accumulation_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # The idempotency key. One row per occurrence, so a second run of the
        # same date cannot record it twice.
        sa.UniqueConstraint("plan_id", "occurrence", name="uq_unfilled_plan_occurrence"),
    )
    op.create_index(
        "ix_plan_unfilled_occurrences_plan_id", "plan_unfilled_occurrences", ["plan_id"]
    )


def downgrade() -> None:
    # Going back re-derives done-ness from transactions alone, which is the bug
    # this table exists to end: every unfilled occurrence recorded here becomes
    # due again on the next catch-up.
    op.drop_index(
        "ix_plan_unfilled_occurrences_plan_id", table_name="plan_unfilled_occurrences"
    )
    op.drop_table("plan_unfilled_occurrences")
