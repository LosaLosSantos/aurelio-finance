"""What a position cost, told apart from what it is worth.

`holdings.value` was answering four different questions at once: three consumers
(net worth, asset allocation, look-through weights) wanted "what is this worth
now", and one (average cost, and therefore P/L) wanted "what did this cost".
All four got "what the photograph said", which is neither — so P/L measured
movement since a snapshot rather than gain, and net worth never moved unless a
new photograph was taken.

Market value now comes from the price cache, so `value` is free to stop being
the answer to "what is it worth". This column carries the remaining question.
It is nullable on purpose: an unknown cost must stay unknown rather than be
inferred from a photograph, which is exactly the confusion being undone here.

Recorded in the holding's own currency, like `value`.

Revision ID: d5a2c8f31b94
Revises: c3e91a70d215
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5a2c8f31b94"
down_revision = "c3e91a70d215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("holdings") as batch:
        batch.add_column(sa.Column("cost_basis", sa.Float(), nullable=True))
        batch.add_column(sa.Column("cost_estimated", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("holdings") as batch:
        batch.drop_column("cost_estimated")
        batch.drop_column("cost_basis")
