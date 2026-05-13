"""add source_url and auto_sync

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "d7e8f9a0b1c2"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("source_url", sa.String(), nullable=True))
    op.add_column(
        "ontologies",
        sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("versions", "source_url")
    op.drop_column("ontologies", "auto_sync")
