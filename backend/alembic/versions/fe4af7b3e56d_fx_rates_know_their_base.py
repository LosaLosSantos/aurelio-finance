"""A cached rate says which base it was fetched against.

frankfurter answers for whatever base it is asked and never lists that base
among its own rates: `?base=USD` returns 29 rates and no USD, `?base=EUR`
returns 29 and no EUR (measured 2026-09-14). A row reading "USD 1.1592" is
dollars per EUR only because the fetch that wrote it happened to ask for EUR,
and nothing in the row said so. The day the base can be something else, that
row is read as dollars per dollar.

Every existing row gets `EUR`, and that is a statement of fact rather than a
default: `fx._fetch_rates` has sent `params={"base": "EUR"}` since this table
was created in f01a59d0d830, so no row in it was ever fetched against anything
else. The column carries no server default afterwards — the only writer is the
refresh, and it always knows which base it asked for.

The key becomes (base, currency). SQLite cannot change a primary key in place,
so the table is rebuilt and the rows copied across.

Revision ID: fe4af7b3e56d
Revises: e1c74b930af2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "fe4af7b3e56d"
down_revision = "e1c74b930af2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_rates_new",
        sa.Column("base", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("base", "currency"),
    )
    op.execute(
        "INSERT INTO fx_rates_new (base, currency, rate, as_of, fetched_at)"
        " SELECT 'EUR', currency, rate, as_of, fetched_at FROM fx_rates"
    )
    op.drop_table("fx_rates")
    op.rename_table("fx_rates_new", "fx_rates")


def downgrade() -> None:
    # A cache: the rows of any other base are dropped rather than squeezed into
    # a table that cannot say which base they belong to, which is the exact
    # confusion the upgrade removed. The next refresh refills it.
    op.create_table(
        "fx_rates_old",
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("currency"),
    )
    op.execute(
        "INSERT INTO fx_rates_old (currency, rate, as_of, fetched_at)"
        " SELECT currency, rate, as_of, fetched_at FROM fx_rates WHERE base = 'EUR'"
    )
    op.drop_table("fx_rates")
    op.rename_table("fx_rates_old", "fx_rates")
