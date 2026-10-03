"""denormalise per-version embedding count onto versions

/admin/overview (polled every 10s) computed the per-version embedding count with a
GROUP BY over the whole term_embeddings table — ~2.2s on the dev catalogue, every
refresh. Store the count on the version row instead; embed_ontology maintains it at
completion, and overview reads it from its existing version query.

Additive and expand/contract-safe: the column defaults to 0 and is backfilled from
term_embeddings here, so the previous app version keeps working during the rollout.

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-10-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column("embed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # One-time backfill from the live counts (the same GROUP BY, run once).
    op.execute(
        """
        UPDATE versions v
        SET embed_count = sub.cnt
        FROM (SELECT version_id, COUNT(*) AS cnt FROM term_embeddings GROUP BY version_id) sub
        WHERE v.id = sub.version_id
        """
    )


def downgrade() -> None:
    op.drop_column("versions", "embed_count")
