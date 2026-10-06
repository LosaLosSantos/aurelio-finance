"""A situation has no currency of its own.

`snapshots.currency` looked like a fact about a situation and was not one. No
total read it — every holding states its own currency, and the situation's
worth is its holdings converted one by one — no screen showed it, and the
backend only copied it into the API response. On a dollar account it said EUR,
because every form wrote the new-row currency into it. A field that looks
authoritative and is not is how the Turkish lira reached a screen under a euro
sign (0bf262b): the next reader to trust it would have been wrong in the same
way. Deriving it from the account would only make a second claim beside the
one the holdings already make, so it is removed.

Downgrade puts the column back holding the database's base currency (EUR when
none was chosen): the only value that was ever written into it that no row can
contradict.

Revision ID: 01f722f11058
Revises: 9e4b8085f412
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "01f722f11058"
down_revision = "9e4b8085f412"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("snapshots") as batch:
        batch.drop_column("currency")


def downgrade() -> None:
    with op.batch_alter_table("snapshots") as batch:
        batch.add_column(sa.Column("currency", sa.String(), nullable=True))
    op.execute(
        "UPDATE snapshots SET currency = COALESCE("
        "(SELECT UPPER(TRIM(value)) FROM settings WHERE key = 'base_currency' "
        "AND TRIM(COALESCE(value, '')) <> ''), 'EUR')"
    )
    with op.batch_alter_table("snapshots") as batch:
        batch.alter_column("currency", existing_type=sa.String(), nullable=False)
