"""A plan states the currency its contribution is paid in.

A plan's `amount` is cash that leaves its source account every period, and the
catch-up spends it on targets that are priced in whatever their listings trade
in. With no currency on either side it divided a euro budget by a dollar
price: floor(250 / 100) units of a 100-dollar share, when on a day the dollar
stood at 1.25 to the euro that share cost 80 euro and 250 bought three.

Every existing plan was read as euro, so it gets EUR — the reading it had, and
no plan's behaviour changes for it. The column is required from here on, like
every other currency since a7d2e94c10b8.

Revision ID: 2e12a4db4c86
Revises: 909ab4f46020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2e12a4db4c86"
down_revision = "909ab4f46020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accumulation_plans") as batch:
        batch.add_column(sa.Column("currency", sa.String(), nullable=True))
    op.execute("UPDATE accumulation_plans SET currency = 'EUR'")
    with op.batch_alter_table("accumulation_plans") as batch:
        batch.alter_column("currency", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("accumulation_plans") as batch:
        batch.drop_column("currency")
