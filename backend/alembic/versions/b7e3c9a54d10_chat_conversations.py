"""A conversation with the chat is a record, not a browser tab's memory.

The chat's first version kept its history in the browser's sessionStorage:
one conversation, gone with the tab. But an answer that told this person
"you are up 1,100 on that position" is a dated statement about their money,
the same kind of thing a chain run is, and the app keeps those. So the
conversation moves into the database, next to chain_runs, with the same
shape of guarantee: what was said, when, by which model, and how the answer
ended — complete, stopped by an error the detail records, or cut off before it
finished.

Messages carry their content as JSON `blocks`, each with a `kind`. Only text
exists today; the cards that come later — a proposed write to confirm, a
suggested instrument — are new kinds in the same column, not new columns.

Nothing to backfill: before this table there was nothing on the server.

Revision ID: b7e3c9a54d10
Revises: d84f2b6c1a03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e3c9a54d10"
down_revision = "d84f2b6c1a03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),  # user | assistant
        sa.Column("blocks", sa.Text(), nullable=False),  # JSON list of {kind, ...}
        sa.Column("status", sa.String(), nullable=True),  # done | error | cut
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
