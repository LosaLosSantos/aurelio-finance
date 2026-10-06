"""A transfer states what arrived as well as what left.

A transfer had one amount and one currency, and the register took that same
figure out of the source and put it into the destination. Between two accounts
in two currencies that is two different sums: 500 dollars leave the dollar
account and what reaches the euro account is whatever the conversion made of
them on the day — a fixed sum, not the 500 dollars restated at every reading.

So the destination side gets its own `to_amount` in its own `to_currency`, and
`fx_as_of` says which ECB day it was worked out at when it was not copied from
a statement — the same three facts a ledger entry across two currencies keeps
(909ab4f46020).

Every existing transfer was read as one sum in one currency on both sides, so
it gets exactly that: `to_amount` = `amount`, `to_currency` = `currency`, no
rate day. The register reads each of them as it did.

Revision ID: 9e4b8085f412
Revises: 2e12a4db4c86
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9e4b8085f412"
down_revision = "2e12a4db4c86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transfers") as batch:
        batch.add_column(sa.Column("to_amount", sa.Float(), nullable=True))
        batch.add_column(sa.Column("to_currency", sa.String(), nullable=True))
        batch.add_column(sa.Column("fx_as_of", sa.String(), nullable=True))
    op.execute("UPDATE transfers SET to_amount = amount, to_currency = currency")
    with op.batch_alter_table("transfers") as batch:
        batch.alter_column("to_amount", existing_type=sa.Float(), nullable=False)
        batch.alter_column("to_currency", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("transfers") as batch:
        batch.drop_column("fx_as_of")
        batch.drop_column("to_currency")
        batch.drop_column("to_amount")
