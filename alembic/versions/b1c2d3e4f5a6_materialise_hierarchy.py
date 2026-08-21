"""Materialise the asserted hierarchy so the navigation tree is served from SQL.

The tree was answered from Oxigraph. Root detection is a whole-graph question —
every entity, minus every entity that has a parent — which on DRON (784,921
classes) took 61.8 s before optimisation and ~12.8 s after. Mirroring the
subClassOf/subPropertyOf edges into Postgres alongside the entities already in
`entity_index` answers the same question in ~0.8 s, and turns a child page plus
its has-children probe into one indexed join.

Two changes:

* `hierarchy_edge` — one row per asserted named edge, per version. `kind`
  separates the class hierarchy from the property one so a single table serves
  both trees. Indexed both ways: by parent to expand a node, by child to find
  the entities that are not roots.
* `entity_index.deprecated` — the tree hides obsolete terms by default, and the
  SQL path cannot apply that filter without knowing which entities are
  deprecated. The indexer already computes this set (it keeps one in Redis);
  this column mirrors it so the query stays self-contained.

Existing versions have no edge rows until they are re-indexed. Callers must
treat "no rows for this version" as "not materialised" and fall back, rather
than as "this ontology has no hierarchy".

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-21
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_index",
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Precomputed rather than derived per request. As an anti-join against
    # hierarchy_edge, "which entities have no parent" is a LIMIT trap: only 5 of
    # DRON's 771,512 classes are roots, so the planner assumes it can stop early
    # and picks a nested loop, sorting every row to disk and probing the index
    # 771,512 times — 26 s. Indexing already knows the child set, so the answer
    # is written once and read back as an indexed filter.
    op.add_column(
        "entity_index",
        sa.Column("is_root", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_entity_index_roots", "entity_index", ["version_id", "type"],
        postgresql_where=sa.text("is_root"),
    )

    op.create_table(
        "hierarchy_edge",
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("child", sa.Text(), nullable=False),
        sa.Column("parent", sa.Text(), nullable=False),
        # 'class' (rdfs:subClassOf) | 'property' (rdfs:subPropertyOf)
        sa.Column("kind", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
    )
    # Two indexes, no primary key. A graph is a set of triples, so an edge
    # cannot repeat (verified on DRON: 777,706 edges, 0 duplicates) — a key
    # would enforce something that cannot happen, and its four-column index
    # measured 186 MB against 84 MB for the narrow child index that serves the
    # same lookups. ~100 MB per DRON-scale ontology. The ORM model still
    # declares the columns as a composite key because SQLAlchemy requires one
    # to map a table.
    #
    # Sizes on DRON (777,706 edges): table 248 MB, parent index 17 MB, child
    # index 84 MB — the parent index is far smaller because parents repeat
    # heavily while children are near-unique.
    op.create_index(
        # Expanding a node: every child of one parent.
        "ix_hierarchy_edge_parent", "hierarchy_edge", ["version_id", "kind", "parent"]
    )
    op.create_index(
        # Root detection and has-children: does this entity appear as a child.
        "ix_hierarchy_edge_child", "hierarchy_edge", ["version_id", "kind", "child"]
    )


def downgrade() -> None:
    op.drop_index("ix_hierarchy_edge_child", table_name="hierarchy_edge")
    op.drop_index("ix_hierarchy_edge_parent", table_name="hierarchy_edge")
    op.drop_table("hierarchy_edge")
    op.drop_index("ix_entity_index_roots", table_name="entity_index")
    op.drop_column("entity_index", "is_root")
    op.drop_column("entity_index", "deprecated")
