"""fair_snapshots — daily fleet FAIR aggregate for fairness-over-time

Revision ID: e9a5b2c7d13f
Revises: d8e4f1a2b3c5
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e9a5b2c7d13f"
down_revision = "d8e4f1a2b3c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fair_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overall_mean", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overall_stddev", sa.Float(), nullable=False, server_default="0"),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("day", name="uq_fair_snapshot_day"),
    )
    op.create_index("ix_fair_snapshot_day", "fair_snapshots", ["day"])


def downgrade() -> None:
    op.drop_index("ix_fair_snapshot_day", table_name="fair_snapshots")
    op.drop_table("fair_snapshots")
