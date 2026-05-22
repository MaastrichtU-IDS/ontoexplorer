"""add elucidation_props column to ontology_profiles

Revision ID: b7c8d9e0f1a2
Revises: f6e1d2c3b4a5
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "f6e1d2c3b4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ontology_profiles",
        sa.Column("elucidation_props", sa.JSON(), nullable=False, server_default="[]"),
    )
    # Seed existing rows with the canonical default so the UI shows the role
    # immediately for already-ingested ontologies.
    op.execute(
        "UPDATE ontology_profiles "
        "SET elucidation_props = '[\"http://purl.obolibrary.org/obo/IAO_0000600\"]' "
        "WHERE elucidation_props::text = '[]'"
    )


def downgrade() -> None:
    op.drop_column("ontology_profiles", "elucidation_props")
