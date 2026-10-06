"""chain step cost, and the two single-shot analyses go away

Revision ID: c9f4a2e18b70
Revises: b7e3c9a54d10
Create Date: 2026-09-05 12:10:00.000000

Two halves of one decision, so they travel together.

`chain_steps.cost` is what OpenRouter reports on the final chunk's `usage`,
and the repo was throwing it away. It is here because the card that asks the
reader to spend a minute and a few cents has to quote a MEASUREMENT — the same
reason `duration_ms` is beside it — and "a few cents" written into an
interface is a guess printed as a fact.

`advisor_reports` goes because the two single-shot analyses it saved are gone:
the unbiased portfolio read is the chain's first step, on the analyst's own
model, and the whole-picture one is what the chat does over the same context on
every turn. Three doors to one thing, two of them with no page left to open
them. The table was empty when this was written, and dropping it is how the
schema stops advertising a feature that no longer exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9f4a2e18b70"
down_revision: Union[str, Sequence[str], None] = "b7e3c9a54d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chain_steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cost", sa.Float(), nullable=True))
    op.drop_table("advisor_reports")


def downgrade() -> None:
    op.create_table(
        "advisor_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("chain_steps", schema=None) as batch_op:
        batch_op.drop_column("cost")
