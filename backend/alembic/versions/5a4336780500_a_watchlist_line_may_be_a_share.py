"""A watchlist line can be a share, named by the symbol Yahoo lists it under.

Brief AG (2026-10-06). The chat may now put up a card for a single share it has
checked on Yahoo, and a share has no ISIN anywhere this app can verify: Yahoo's
lookup returns none, and OpenFIGI maps an ISIN to tickers, not back. So `isin`
stops being required. A line with an ISIN is a fund from the catalogue, as
before; a line without one is a share, and its `symbol` is then the identity
and not a hint.

SQLite cannot drop a NOT NULL in place, so batch mode rebuilds the table: a new
table, every row copied as it is (ids kept), the old one dropped, its index on
`isin` made again. No other table is touched and no value changes. The app
copies the database before it runs this (brief W part 1); run by hand through
Alembic's command line, nothing does.

The downgrade refuses while any line has no ISIN: writing the symbol into the
column would call a share a fund, and dropping the line would lose the
reasoning it keeps.

Revision ID: 5a4336780500
Revises: e9346d9cfd3f
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5a4336780500"
down_revision = "e9346d9cfd3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("watchlist_items") as batch:
        batch.alter_column("isin", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    shares = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM watchlist_items WHERE isin IS NULL")
    ).scalar()
    if shares:
        raise RuntimeError(
            f"{shares} watchlist line(s) name a share by its symbol and have no "
            "ISIN, and the schema below this one has no place for them. Drop them "
            "from the watchlist first."
        )
    with op.batch_alter_table("watchlist_items") as batch:
        batch.alter_column("isin", existing_type=sa.String(), nullable=False)
