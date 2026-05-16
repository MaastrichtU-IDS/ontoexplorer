"""add_term_embeddings

Revision ID: f58beb3f4610
Revises: c2d3e4f5a6b7
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "f58beb3f4610"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "term_embeddings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("entity_iri", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "entity_iri", name="uq_term_embeddings_version_iri"),
    )
    op.execute("CREATE INDEX ON term_embeddings USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ON term_embeddings (version_id)")


def downgrade() -> None:
    op.drop_table("term_embeddings")
