"""add keyset browse index on entity_index (cross-repo /browse)

Btree over (type, primary_label_norm, iri, version_id) so the keyset-paginated
entity listing can seek by (type, label, iri) within a version without a sort.

Revision ID: b5d8e2f1a9c3
Revises: a4c7e1b9d205
Create Date: 2026-10-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b5d8e2f1a9c3"
down_revision: Union[str, Sequence[str], None] = "a4c7e1b9d205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLS = ["type", "primary_label_norm", "iri", "version_id"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # sqlite (tests): small tables, plain create.
        op.create_index("ix_entity_index_browse", "entity_index", _COLS)
        return
    # entity_index is ~6M rows: build CONCURRENTLY so writes aren't blocked.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_entity_index_browse",
            "entity_index",
            _COLS,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        op.drop_index("ix_entity_index_browse", table_name="entity_index")
        return
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_entity_index_browse",
            table_name="entity_index",
            postgresql_concurrently=True,
            if_exists=True,
        )
