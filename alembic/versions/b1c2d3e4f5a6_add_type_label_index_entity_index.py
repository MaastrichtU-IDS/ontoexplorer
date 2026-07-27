"""add keyset index on entity_index (type, primary_label_norm, iri, version_id)

Backs the cross-repository /entities keyset listing: equality on type, then a
range scan over the (primary_label_norm, iri, version_id) sort tuple.

Revision ID: b1c2d3e4f5a6
Revises: f0a1b2c3d4e5
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_entity_index_type_label",
        "entity_index",
        ["type", "primary_label_norm", "iri", "version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_index_type_label", table_name="entity_index")
