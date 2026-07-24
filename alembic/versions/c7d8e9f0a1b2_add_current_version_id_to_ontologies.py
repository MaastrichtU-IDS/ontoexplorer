"""add current_version_id to ontologies

Admin-pinned default version. When set (and the version is still ready), it
overrides the automatic version-aware "latest" selection. Nullable FK to
versions.id with ON DELETE SET NULL.

Revision ID: c7d8e9f0a1b2
Revises: d0e1f2a3b4c5
Create Date: 2026-07-24
"""
import sqlalchemy as sa
from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ontologies",
        sa.Column("current_version_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ontologies_current_version",
        "ontologies",
        "versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ontologies_current_version", "ontologies", type_="foreignkey")
    op.drop_column("ontologies", "current_version_id")
