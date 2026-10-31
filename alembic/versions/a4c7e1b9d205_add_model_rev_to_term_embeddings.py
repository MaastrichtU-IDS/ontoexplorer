"""add term_embeddings.model_rev (embedding producer stamp)

Records which producer wrote each embedding row. NULL = legacy (pre-GGUF) embedder.
Lets the one-time re-embed tell legacy rows apart and lets normal embed_ontology
runs re-embed any straggler rows whose model_rev != the current MODEL_REV (#229).

Revision ID: a4c7e1b9d205
Revises: 7f3a9c1e5b2d
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from alembic import op

revision = "a4c7e1b9d205"
down_revision = "7f3a9c1e5b2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("term_embeddings", sa.Column("model_rev", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("term_embeddings", "model_rev")
