"""Accumulation plans buy several instruments, not one.

A plan carried its target inline (target_symbol / target_isin /
target_asset_name / target_institution_id), which forced one plan per fund.
That is not how people save — one standing order, split across a few funds —
and with whole-unit brokers it is actively wasteful: split by hand, every slice
keeps its own unspendable remainder, and none of them can buy a unit.

The targets move to their own table with a weight, and any inline target is
carried over as the plan's first (and only) target so nothing is lost.

Revision ID: c3e91a70d215
Revises: 86dd2a380597
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3e91a70d215"
down_revision = "86dd2a380597"
branch_labels = None
depends_on = None

_LEGACY = ("target_symbol", "target_isin", "target_asset_name", "target_institution_id")


def _plan_columns() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("accumulation_plans")}


def upgrade() -> None:
    op.create_table(
        "plan_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("asset_name", sa.String(), nullable=True),
        sa.Column("institution_id", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_id"], ["accumulation_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_targets_plan_id", "plan_targets", ["plan_id"])
    op.create_index("ix_plan_targets_institution_id", "plan_targets", ["institution_id"])

    # Carry every inline target over as the plan's first target. Plans without
    # a ticker had nothing to execute anyway, so they simply arrive with none.
    existing = _plan_columns()
    if "target_symbol" in existing:
        op.execute(
            """
            INSERT INTO plan_targets
                (plan_id, symbol, isin, asset_name, institution_id, weight, position)
            SELECT id, target_symbol, target_isin, target_asset_name,
                   target_institution_id, 1.0, 0
            FROM accumulation_plans
            WHERE target_symbol IS NOT NULL AND TRIM(target_symbol) <> ''
            """
        )

    # The index on target_institution_id must go BEFORE the column: SQLite has
    # no DROP COLUMN, so batch mode rebuilds the table and replays every index
    # it finds — including one pointing at a column that no longer exists.
    insp = sa.inspect(op.get_bind())
    index_names = {ix["name"] for ix in insp.get_indexes("accumulation_plans")}
    if "ix_accumulation_plans_target_institution_id" in index_names:
        op.drop_index("ix_accumulation_plans_target_institution_id", "accumulation_plans")

    with op.batch_alter_table("accumulation_plans") as batch:
        for column in _LEGACY:
            if column in existing:
                batch.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("accumulation_plans") as batch:
        batch.add_column(sa.Column("target_symbol", sa.String(), nullable=True))
        batch.add_column(sa.Column("target_isin", sa.String(), nullable=True))
        batch.add_column(sa.Column("target_asset_name", sa.String(), nullable=True))
        batch.add_column(sa.Column("target_institution_id", sa.Integer(), nullable=True))

    # Only the first target survives a downgrade — the schema below cannot hold
    # more than one, which is the whole reason for this migration.
    op.execute(
        """
        UPDATE accumulation_plans SET
            target_symbol = (SELECT symbol FROM plan_targets t
                             WHERE t.plan_id = accumulation_plans.id
                             ORDER BY t.position, t.id LIMIT 1),
            target_isin = (SELECT isin FROM plan_targets t
                           WHERE t.plan_id = accumulation_plans.id
                           ORDER BY t.position, t.id LIMIT 1),
            target_asset_name = (SELECT asset_name FROM plan_targets t
                                 WHERE t.plan_id = accumulation_plans.id
                                 ORDER BY t.position, t.id LIMIT 1),
            target_institution_id = (SELECT institution_id FROM plan_targets t
                                     WHERE t.plan_id = accumulation_plans.id
                                     ORDER BY t.position, t.id LIMIT 1)
        """
    )
    op.drop_index("ix_plan_targets_institution_id", table_name="plan_targets")
    op.drop_index("ix_plan_targets_plan_id", table_name="plan_targets")
    op.drop_table("plan_targets")
