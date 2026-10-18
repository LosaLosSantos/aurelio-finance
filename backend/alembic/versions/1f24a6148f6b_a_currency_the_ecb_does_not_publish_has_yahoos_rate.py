"""A currency the ECB does not publish is converted at Yahoo's rate.

Brief BA (2026-10-16), the reader's decision D1. Every rate came from the ECB
through Frankfurter, about thirty currencies, so an amount in any other (TWD,
AED, VND) converted to nothing and was counted as written. Yahoo's daily close
of `USD{code}=X` is kept for those, one row a day, the history kept, and
crossed at the ECB's dollar of the same day (`yahoo_rates`).

One table created: `fx_rates_yahoo` (currency, as_of, rate, fetched_at; key
currency and day). No existing table or row is touched: the ECB's `fx_rates`
is read exactly as before. The table starts empty and fills as the app reads
a currency the ECB does not publish. The app copies the database before it
runs this (brief W part 1); run by hand through Alembic's command line,
nothing does.

The downgrade drops the table, and with it every Yahoo close kept: the code
before this revision counts those currencies as written again.

Revision ID: 1f24a6148f6b
Revises: 0e29ce42774e
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1f24a6148f6b"
down_revision = "0e29ce42774e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_rates_yahoo",
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("currency", "as_of"),
    )


def downgrade() -> None:
    op.drop_table("fx_rates_yahoo")
