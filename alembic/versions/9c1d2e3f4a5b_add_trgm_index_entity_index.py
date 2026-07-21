"""add trigram GIN index on entity_index.primary_label_norm

Enables fast word-similarity (`<%`) fuzzy matching for typo-tolerant
autocomplete. pg_trgm itself was created in f6e1d2c3b4a5.

Revision ID: 9c1d2e3f4a5b
Revises: c8d9e0f1a2b3
Create Date: 2026-07-21
"""
from alembic import op

revision = "9c1d2e3f4a5b"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS entity_index_norm_trgm "
        "ON entity_index USING gin (primary_label_norm gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS entity_index_norm_trgm")
