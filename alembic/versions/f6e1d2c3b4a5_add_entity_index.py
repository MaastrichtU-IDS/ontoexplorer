"""add entity_index table for Postgres-backed search

Revision ID: f6e1d2c3b4a5
Revises: c4d5e6f7a8b9
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa

revision = "f6e1d2c3b4a5"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "entity_index",
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("ontology_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("primary_label", sa.Text(), nullable=False),
        sa.Column("primary_label_norm", sa.Text(), nullable=False),
        sa.Column("short", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_tsv",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', search_text)", persisted=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ontology_id"], ["ontologies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version_id", "iri"),
    )

    op.execute("CREATE INDEX entity_index_tsv ON entity_index USING GIN (search_tsv)")
    # Btree with text_pattern_ops gives range-scan prefix lookups (`LIKE 'cell%'`).
    # Faster than gin_trgm_ops for prefix matches because there's no recheck overhead.
    op.execute(
        "CREATE INDEX entity_index_norm_prefix ON entity_index (primary_label_norm text_pattern_ops)"
    )
    op.execute("CREATE INDEX entity_index_version ON entity_index (version_id)")
    op.execute("CREATE INDEX entity_index_ontology ON entity_index (ontology_id)")


def downgrade() -> None:
    op.drop_table("entity_index")
