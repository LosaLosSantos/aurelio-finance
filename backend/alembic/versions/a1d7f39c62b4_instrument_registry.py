"""A local registry of instruments, so identity is chosen rather than typed.

Eight fields are typed by hand for every position, and the ones nobody fills
switch features off in silence: 22 of 25 positions have no ISIN (which is what
the look-through hands to the issuer), and until they were entered one by one,
23 collected no dividends because `distribution_policy` was empty. The code
worked perfectly; the data never arrived.

Keyed as a REGISTRY, deliberately, and not as a third cache-by-symbol. There
are already two half-registries over the same instruments — `price_cache`
(symbol -> price) and `composition_cache` (symbol -> isin, name, source) —
neither of which knows both halves. So identity lives here by ISIN, and the
QUOTATIONS that price it stay separate: which listing you actually own is the
one fact no source can give, because only your broker knows it.

`share_class_currency` is stored and must never fill a holding's currency:
justETF reports USD for VWCE, which quotes in EUR in Milan, and trusting it is
exactly the phantom 17% gain already documented in analytics.py. `base_ticker`
is not a Yahoo symbol either: the catalogue gives one code per fund, and a
holding is priced by the symbol of the listing it trades on.

Revision ID: a1d7f39c62b4
Revises: f2c9e4b71d35
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1d7f39c62b4"
down_revision = "f2c9e4b71d35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        # Grouping key for the Acc/Dist twins: a quarter of the catalogue
        # shares a name with a sibling and differs only in what it does with
        # dividends, so a search must never show one of a pair alone. The
        # count itself belongs to the live table and not to a frozen
        # migration, so it lives once, next to catalogue.family_key, with the
        # query that regenerates it.
        sa.Column("family_key", sa.String(), nullable=False),
        sa.Column("base_ticker", sa.String(), nullable=True),
        sa.Column("distribution_policy", sa.String(), nullable=True),  # acc | dist
        sa.Column("ter", sa.Float(), nullable=True),
        sa.Column("size_meur", sa.Integer(), nullable=True),
        sa.Column("replication", sa.String(), nullable=True),
        sa.Column("domicile", sa.String(), nullable=True),
        sa.Column("share_class_currency", sa.String(), nullable=True),
        sa.Column("holdings_count", sa.Integer(), nullable=True),
        sa.Column("hedged", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("isin"),
    )
    op.create_index("ix_instruments_family_key", "instruments", ["family_key"])
    # Full-text search so the picker works with no network at all. Rebuilt
    # wholesale on refresh, which is simpler and safer than keeping an
    # external-content index in step with 4.5k upserts.
    op.execute(
        "CREATE VIRTUAL TABLE instruments_fts USING fts5("
        "isin UNINDEXED, name, base_ticker, tokenize='unicode61')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS instruments_fts")
    op.drop_index("ix_instruments_family_key", table_name="instruments")
    op.drop_table("instruments")
