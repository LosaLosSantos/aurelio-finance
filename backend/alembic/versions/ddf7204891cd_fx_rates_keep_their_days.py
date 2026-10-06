"""A rate is kept for the day it was published, not replaced by the next one.

`fx_rates` held one row per (base, currency): each refresh overwrote the rate
and its `as_of`. That is enough to convert at today's rate and nothing else,
and three things now need another day's: the net worth history (each point at
its own day), a purchase paid in another currency (the rate of its date), and
the plan and dividend catch-up (the close day, the ex-date). Two designs for
that were on the table — an on-demand historical read, and a second table
beside this one — which would have meant two places that know what a rate was
on a day. This keeps one: the same table, keyed by the day as well.

Every existing row is a rate for the day its `as_of` says, so it becomes that
day's row as it stands: nothing is rewritten, and nothing is lost. The next
refresh adds the days after it instead of overwriting it.

SQLite cannot change a primary key in place, so the table is rebuilt and the
rows copied across. The downgrade keeps, per (base, currency), the row of the
latest day — which is what the table held before.

Revision ID: ddf7204891cd
Revises: a7d2e94c10b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ddf7204891cd"
down_revision = "a7d2e94c10b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_rates_new",
        sa.Column("base", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("base", "currency", "as_of"),
    )
    op.execute(
        "INSERT INTO fx_rates_new (base, currency, as_of, rate, fetched_at)"
        " SELECT base, currency, as_of, rate, fetched_at FROM fx_rates"
    )
    op.drop_table("fx_rates")
    op.rename_table("fx_rates_new", "fx_rates")


def downgrade() -> None:
    op.create_table(
        "fx_rates_old",
        sa.Column("base", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("base", "currency"),
    )
    op.execute(
        "INSERT INTO fx_rates_old (base, currency, rate, as_of, fetched_at)"
        " SELECT r.base, r.currency, r.rate, r.as_of, r.fetched_at FROM fx_rates r"
        " WHERE r.as_of = (SELECT max(l.as_of) FROM fx_rates l"
        "                  WHERE l.base = r.base AND l.currency = r.currency)"
    )
    op.drop_table("fx_rates")
    op.rename_table("fx_rates_old", "fx_rates")
