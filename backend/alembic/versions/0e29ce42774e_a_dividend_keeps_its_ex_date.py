"""A dividend keeps its ex-date, whatever day its row is dated.

Brief AZ (2026-10-16). The catch-up recorded each dividend on its ex-date, and
that day was also the only key it found the dividend by: a row corrected with
the broker's credit and moved to the day the money arrived left its ex-date
empty, and the next page load recorded the dividend there again (measured on
an invented household: 5.00 gross recorded beside the 3.70 the reader had
corrected, the cash and the tax estimate counting both). So the ex-date gets a
column of its own, and the row's date is free to say when the money came.

One column added: `transactions.ex_date`, nullable. It is filled only where it
is certain: on the dividends the catch-up recorded and nobody has edited since,
which are still marked estimated, since any edit clears the mark, and so still
sit on their ex-date. Every other row keeps null, and the catch-up keeps
finding those by their date as before, or adopts the ex-date onto a row of its
own once Yahoo lists that day (`pac.execute_dividends`). No other table is
touched. The app copies the database before it runs this (brief W part 1); run
by hand through Alembic's command line, nothing does.

The downgrade drops the column, and with it every ex-date a moved row kept:
the code before this revision would then record those dividends again.

Revision ID: 0e29ce42774e
Revises: 31668ac923e3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0e29ce42774e"
down_revision = "31668ac923e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("ex_date", sa.String(), nullable=True))
    op.execute(
        "UPDATE transactions SET ex_date = date WHERE kind = 'dividend' AND estimated = 1"
    )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("ex_date")
