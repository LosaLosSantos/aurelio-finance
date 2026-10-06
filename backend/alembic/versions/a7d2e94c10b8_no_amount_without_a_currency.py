"""No amount is stored without saying what currency it is in.

An empty `currency` has meant EUR everywhere it was read: `fx._in_major_units`
starts from `currency or BASE_CURRENCY`, the cash register and every other
total summed these amounts as the base, and the base has only ever been EUR.
That was true of every row written so far, and it stops being true the day the
base can be something else — a balance typed as 1000 dollars, stored with no
currency, would be read back as 1000 euro.

Two ways to close it were weighed. Stamping the current base on a write that
omits the currency keeps absence meaning two things at two times — EUR in the
table, "whatever the base is now" in a request — and `crud._update` replaces
every settable column, so a form that does not send the field would rewrite a
row's stated currency with the base on every save. So the absence is removed
instead: this writes what the empty value already meant, once, into the rows,
and the columns stop accepting it. The API requires the field from this
revision on, so a form that forgets it is refused at the door, not guessed at.

WHAT IS WRITTEN. `EUR`, on rows whose currency is NULL or blank, in the nine
tables that carry a currency for an amount. A currency somebody stated is not
touched — the WHERE clause cannot reach it. `price_cache.currency` is left
nullable on purpose: there an empty value is a different fact, "this listing's
currency has not been learned yet", and nothing is summed in it.

The columns become NOT NULL. SQLite rebuilds a table to change that, and three
of these tables have children that cascade on delete (holdings under
snapshots, valuations under real assets, balances under liabilities); the
rebuild is safe only because Alembic's own connection does not enable
`PRAGMA foreign_keys` — the app's engine listener that does is not attached to
it. The row counts of every table were compared before and after on copies of
the reader's databases.

The downgrade makes the columns nullable again and cannot give back which rows
were empty: they all read EUR, which is what they meant.

Revision ID: a7d2e94c10b8
Revises: fe4af7b3e56d
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7d2e94c10b8"
down_revision = "fe4af7b3e56d"
branch_labels = None
depends_on = None

TABLES = (
    "snapshots",
    "holdings",
    "real_assets",
    "liabilities",
    "income_sources",
    "expenses",
    "cash_anchors",
    "transfers",
    "goals",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"UPDATE {table} SET currency = 'EUR'"
            " WHERE currency IS NULL OR trim(currency) = ''"
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("currency", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("currency", existing_type=sa.String(), nullable=True)
