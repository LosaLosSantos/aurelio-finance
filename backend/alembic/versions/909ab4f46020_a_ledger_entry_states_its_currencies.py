"""A ledger entry states the currency of its price and of its cash.

A purchase made in another currency has two amounts: what was invested, in the
listing's currency, and what left the account, in the account's. The ledger
stored one `amount` and no currency at all, so the app read every entry as
euro: a buy of one share at 100 dollars from a euro account took 100 out of
the euro cash and set a book of 100 against a market value converted from
dollars — a P/L of -13.73% on a share whose price had not moved.

Three columns:

* `currency` — what `amount` and `fees` are in: the cash that left or reached
  the account. Required, like every other currency since a7d2e94c10b8.
* `price_currency` — what `unit_price` is in. Required for a buy, a sell and a
  dividend; empty for a close, which has no price, and there the empty value
  means exactly that.
* `fx_as_of` — the ECB day of the rate the app used to derive `amount` from the
  price, when the two currencies differ and nobody typed the debit. Empty when
  there was nothing to convert or the figure came from the reader.

WHAT IS WRITTEN. Every existing entry was read as euro on both sides, so it
gets EUR for `currency`, and EUR for `price_currency` unless it is a close.
That is what the app already did with them — no figure moves — and it is also
the whole of what it can know: whether a 100.00 typed against a dollar listing
was dollars or euro is not in the row. An entry whose price currency now
disagrees with its listing's is pointed out to the reader rather than guessed
at (`TransactionRead.currency_note`).

Revision ID: 909ab4f46020
Revises: ddf7204891cd
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "909ab4f46020"
down_revision = "ddf7204891cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("currency", sa.String(), nullable=True))
        batch.add_column(sa.Column("price_currency", sa.String(), nullable=True))
        batch.add_column(sa.Column("fx_as_of", sa.String(), nullable=True))
    op.execute("UPDATE transactions SET currency = 'EUR'")
    op.execute("UPDATE transactions SET price_currency = 'EUR' WHERE kind != 'close'")
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("currency", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("fx_as_of")
        batch.drop_column("price_currency")
        batch.drop_column("currency")
