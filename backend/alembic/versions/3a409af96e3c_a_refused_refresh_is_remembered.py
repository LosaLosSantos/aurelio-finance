"""A cached composition remembers when a refresh of it was refused.

A refresh that is poorer than the cached entry (it falls from a source that
lists every holding to one that publishes an extract, or it loses an axis) is
refused and the entry kept. Without a record of the attempt, a stale entry that
keeps being refused runs the whole waterfall again on every page load.

The attempt gets a column of its own. `fetched_at` keeps meaning one thing, how
old the cached data is: a kept entry whose date moved forward on a failed try
would claim a freshness its data does not have. One date carrying two meanings
has cost this project once already, in the rate store.

Nullable, and null for every entry on record: none has been refused yet.

Revision ID: 3a409af96e3c
Revises: 11d7cc20e53e
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "3a409af96e3c"
down_revision = "11d7cc20e53e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("composition_cache") as batch:
        batch.add_column(sa.Column("refused_at", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("composition_cache") as batch:
        batch.drop_column("refused_at")
