"""A chat turn records what it read from the cache and what it cost.

Since the chat asks Anthropic's models to cache what a round read, the count of
tokens a turn was sent no longer says what it cost: on 2026-10-05, on Opus 5.5,
a token read from the cache was billed at a twentieth of the input price and a
token written to it at 1.25 times. So beside `prompt_tokens` the turn keeps how
many of them came from the cache, and what OpenRouter says the turn cost: the
chat's own figure next to `chain_steps.cost`.

Two columns added, no row rewritten. Nullable, and null is the honest value for
every turn already on record: the provider reported a cost for many of them, but
nothing kept it.

Autogenerate also proposes dropping `instruments_fts` and its shadow tables, as
it does every time (see 11d7cc20e53e). Not included here.

Revision ID: e9346d9cfd3f
Revises: 3a409af96e3c
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9346d9cfd3f"
down_revision = "3a409af96e3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("cached_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cost", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("cost")
        batch.drop_column("cached_tokens")
