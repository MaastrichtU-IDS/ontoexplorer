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
    # entity_index is HASH-partitioned. PostgreSQL rejects CREATE INDEX
    # CONCURRENTLY on a partitioned parent ("cannot create index on partitioned
    # table ... concurrently"), so a concurrent build is simply not possible
    # here -- the earlier postgresql_concurrently=True version crashed the
    # migrate init on every real (partitioned) database. A plain CREATE INDEX on
    # the parent creates the index on all partitions in one statement. This runs
    # in the migrate init (advisory-locked, before the new app pods serve), where
    # the brief SHARE lock -- which still allows reads -- is acceptable at deploy
    # time. if_not_exists keeps it idempotent and also covers the sqlite tests.
    op.create_index(
        "ix_entity_index_browse",
        "entity_index",
        _COLS,
        if_not_exists=True,
    )


def downgrade() -> None:
    # Plain (non-concurrent) drop: CONCURRENTLY is likewise unavailable on a
    # partitioned parent, and dropping the parent index removes the partition
    # indexes with it.
    op.drop_index(
        "ix_entity_index_browse",
        table_name="entity_index",
        if_exists=True,
    )
