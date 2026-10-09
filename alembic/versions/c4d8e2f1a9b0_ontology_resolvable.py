"""ontology resolvability columns

Revision ID: c4d8e2f1a9b0
Revises: 3b7c1e9f24a0
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c4d8e2f1a9b0"
down_revision = "3b7c1e9f24a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ontologies", sa.Column("resolvable", sa.Boolean(), nullable=True))
    op.add_column("ontologies", sa.Column("resolve_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ontologies", sa.Column(
        "resolve_detail", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True))


def downgrade() -> None:
    op.drop_column("ontologies", "resolve_detail")
    op.drop_column("ontologies", "resolve_checked_at")
    op.drop_column("ontologies", "resolvable")
