"""watchlist_items: the ideas a suggestion card parks, with what they rested on

Revision ID: e1c74b930af2
Revises: c9f4a2e18b70
Create Date: 2026-09-05 17:40:00.000000

The chat can now suggest an instrument, and a suggestion is not a write: it
buys nothing, records no position and moves no total. What accepting it does is
put the idea here, with the ISIN of the catalogue row it was built from — which
is what makes a hallucinated ticker impossible, since the card can only name a
row `search_catalogue` returned.

Three text columns rather than one, and that is the part worth defending.
`reason`, `based_on` and `unknowns` are the three things a suggestion has to
say — why this, on the basis of what you declared, and what it does not know —
and the third is precisely the one a single free-text field loses, because it
is the uncomfortable half. In a month the useful question about a line here is
what it rested on and what it was blind to, not what it was.

`isin` is deliberately not a foreign key onto `instruments`: that table is
replaced wholesale on every catalogue refresh, so a constraint would delete the
reasoning about a fund that left the market. The reasoning outlives the row it
named.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1c74b930af2"
down_revision: Union[str, Sequence[str], None] = "c9f4a2e18b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("based_on", sa.Text(), nullable=False),
        sa.Column("unknowns", sa.Text(), nullable=False),
        sa.Column("added_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_watchlist_items_isin"), "watchlist_items", ["isin"])


def downgrade() -> None:
    op.drop_index(op.f("ix_watchlist_items_isin"), table_name="watchlist_items")
    op.drop_table("watchlist_items")
