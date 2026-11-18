"""versions FAIR score cache — fair_overall/f/a/i/r + fair_checks

Derived cache of the per-version FAIR assessment so /fair/fleet aggregates
column reads instead of recomputing ~1,900 reports per request, and so
fairness can be snapshotted over time. NULL = not yet computed → self-heal.

Revision ID: d8e4f1a2b3c5
Revises: c7b8a9d0e1f2
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "d8e4f1a2b3c5"
down_revision = "c7b8a9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("fair_overall", sa.Float(), nullable=True))
    op.add_column("versions", sa.Column("fair_f", sa.Float(), nullable=True))
    op.add_column("versions", sa.Column("fair_a", sa.Float(), nullable=True))
    op.add_column("versions", sa.Column("fair_i", sa.Float(), nullable=True))
    op.add_column("versions", sa.Column("fair_r", sa.Float(), nullable=True))
    op.add_column(
        "versions",
        sa.Column("fair_checks", JSONB(), nullable=True),
    )


def downgrade() -> None:
    for col in ("fair_checks", "fair_r", "fair_i", "fair_a", "fair_f", "fair_overall"):
        op.drop_column("versions", col)
