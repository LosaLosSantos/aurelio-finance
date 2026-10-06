"""A whole-unit plan leaves change, and the change was being forgotten.

With whole units the budget almost never divides exactly: the leftover stayed
in cash and was never contributed again, so a target priced above its share of
one contribution was never bought AT ALL — the app said so, but saying so is
not solving it. A real standing order does not work that way: the unspent part
is still money you set aside, and it goes in next time.

A running balance rather than a derived figure, deliberately. Deriving it from
past occurrences would break the moment the contribution amount changed, since
old occurrences would be measured against the new budget.

It is bookkeeping about INTENT, not about where money sits: cash is only ever
debited by what was actually spent, so the carried amount never left the
account and is not double counted anywhere.

Revision ID: f2c9e4b71d35
Revises: e7b4d1c6a208
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2c9e4b71d35"
down_revision = "e7b4d1c6a208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accumulation_plans") as batch:
        batch.add_column(
            sa.Column("carried_remainder", sa.Float(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("accumulation_plans") as batch:
        batch.drop_column("carried_remainder")
