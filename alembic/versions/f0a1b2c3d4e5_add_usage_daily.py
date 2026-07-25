"""add usage_daily (view/download aggregates)

Per-ontology daily view/download counts (unique + total). Written by the Celery
rollup task from ephemeral Redis counters (absolute counts → idempotent upsert).
Daily grain so week/month/year trends derive on read; no raw event log and no
per-visitor rows are stored.

Revision ID: f0a1b2c3d4e5
Revises: c7d8e9f0a1b2
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_daily",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ontology_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("unique_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ontology_id"], ["ontologies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ontology_id", "kind", "day", name="uq_usage_daily"),
    )
    op.create_index("ix_usage_daily_day", "usage_daily", ["day"])
    op.create_index("ix_usage_daily_onto_day", "usage_daily", ["ontology_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_usage_daily_onto_day", table_name="usage_daily")
    op.drop_index("ix_usage_daily_day", table_name="usage_daily")
    op.drop_table("usage_daily")
