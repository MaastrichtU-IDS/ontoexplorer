"""add ontology_comparisons table

Revision ID: c1c0a1b2c3d4
Revises: a2b3c4d5e6f7
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa


revision = "c1c0a1b2c3d4"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_comparisons",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "from_ontology_id",
            sa.String(),
            sa.ForeignKey("ontologies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_ontology_id",
            sa.String(),
            sa.ForeignKey("ontologies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_from_id",
            sa.String(),
            sa.ForeignKey("versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_to_id",
            sa.String(),
            sa.ForeignKey("versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("diff_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "version_from_id", "version_to_id",
            name="uq_ontology_comparisons_version_pair",
        ),
    )


def downgrade() -> None:
    op.drop_table("ontology_comparisons")
