"""A fund's watchlist line keeps no symbol that is the word for nothing.

Brief AJ (2026-10-08). In the reader's test round the chat's fund cards
carried "symbol": "null", the word and not JSON's null, and accepting them
stored its upper case, "NULL", as the symbol of both watchlist lines; "Record a
buy" then put it in the ticker box. The cards can no longer carry it
(`tools.MaybeText`). This clears what was already written.

Data only: no column, no table, no index changes. One UPDATE, on the lines of a
FUND (an ISIN on them), where the symbol is only a hint beside the ISIN, and
only where that symbol is one of the words `tools._ABSENT` reads as nothing,
in any case and with any spaces around it. A share's line (no ISIN) is named by
its symbol, which Yahoo vouched for when its card was accepted, and is not
touched. The app copies the database before it runs this (brief W part 1); run
by hand through Alembic's command line, nothing does.

The downgrade writes nothing back: which lines held the word is not recorded,
and putting it back would restore the defect, not a value.

Revision ID: e62c6f6c8060
Revises: 5a4336780500
"""

from __future__ import annotations

from alembic import op

revision = "e62c6f6c8060"
down_revision = "5a4336780500"
branch_labels = None
depends_on = None

# `tools._ABSENT`, copied rather than imported: a migration must keep doing
# what it did when it was written, whatever the app's code becomes.
_ABSENT = ("", "null", "none", "nil", "undefined", "n/a")


def upgrade() -> None:
    words = ", ".join(f"'{w}'" for w in _ABSENT)
    op.execute(
        "UPDATE watchlist_items SET symbol = NULL "
        "WHERE isin IS NOT NULL AND symbol IS NOT NULL "
        f"AND LOWER(TRIM(symbol)) IN ({words})"
    )


def downgrade() -> None:
    pass
