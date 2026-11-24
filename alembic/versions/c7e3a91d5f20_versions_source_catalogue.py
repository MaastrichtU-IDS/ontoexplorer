"""versions.source_catalogue — provenance of harvested versions

Records which peer MOD-API catalogue a version was harvested from (project2
harvest). Nullable and additive: NULL for every upload/url/iri/webhook ingest.

Revision ID: c7e3a91d5f20
Revises: b2d5f8a1c3e4
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "c7e3a91d5f20"
down_revision = "b2d5f8a1c3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("source_catalogue", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("versions", "source_catalogue")
