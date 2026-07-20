"""add reasoner column to versions

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column("reasoner", sa.String(), nullable=False, server_default="whelk"),
    )
    # Existing versions were classified by whelk; the server_default already
    # backfills them, but be explicit for databases that don't apply the default
    # to existing rows on ADD COLUMN.
    op.execute("UPDATE versions SET reasoner = 'whelk' WHERE reasoner IS NULL")


def downgrade() -> None:
    op.drop_column("versions", "reasoner")
