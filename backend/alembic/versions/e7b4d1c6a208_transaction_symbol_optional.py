"""A position with no units needs a way out too.

Every ledger entry required a ticker, so for Bitcoin — and for any value-only
row — there was no way to record a sale. The only exit was to leave it out of
the next photograph, which is the silent deletion the ledger exists to replace:
the value left the net worth and nothing said where it went.

`close` states that a position is gone in its entirety and what came back, so
the rows that most need an exit are the ones no ticker describes. Its shape is
enforced in the schema, not here: a close must state its proceeds (zero is
allowed, but it has to be SAID), and buy/sell/dividend still require a ticker
and a quantity, because a buy without a ticker would create a position no price
could ever reach.

Revision ID: e7b4d1c6a208
Revises: d5a2c8f31b94
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7b4d1c6a208"
down_revision = "d5a2c8f31b94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("symbol", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # A row with no ticker cannot exist under the old constraint; the closes
    # that have one keep it, and the rest would block the downgrade, so they
    # are given the asset name to hold the place.
    op.execute(
        "UPDATE transactions SET symbol = asset_name WHERE symbol IS NULL"
    )
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("symbol", existing_type=sa.String(), nullable=False)
