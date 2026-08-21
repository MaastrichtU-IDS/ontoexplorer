"""Materialise the inferred hierarchy so the inferred tree is served from SQL.

`/inferred-children` re-derived everything per click: it fetched and parsed the
whole classification (12.1 s on DRON) and then reduced 771,507 classes to their
direct parents in Python (1.06 s), to return two terms. Measured: 16.0 s for the
inferred root, 2.1 s to expand a node, with no response cache.

The reduction only changes when the ontology is re-reasoned, so it is done once
and stored. Direct inferred parents go into `hierarchy_edge` under
`kind='inferred'`, beside the asserted edges.

Roots need their own table rather than a flag on `entity_index`. Reasoning and
indexing are queued concurrently onto different Celery queues, and indexing
rebuilds `entity_index` with DELETE + INSERT — a column written there by
reasoning would be erased by an interleaved re-index. `inferred_root` is owned
by reasoning alone. (It cannot be an anti-join at query time either: only a
handful of DRON's 771,512 classes are roots, and with a LIMIT the planner picks
a nested loop and spends ~26 s, exactly as on the asserted side.)

Revision ID: c9d0e1f2a3b4
Revises: b1c2d3e4f5a6
Create Date: 2026-08-21
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inferred_root",
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version_id", "iri"),
    )
    # No separate index: the primary key already covers lookup by version.


def downgrade() -> None:
    op.drop_table("inferred_root")
