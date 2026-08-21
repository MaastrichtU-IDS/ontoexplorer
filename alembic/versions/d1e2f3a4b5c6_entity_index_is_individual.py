"""Mark individuals independently of an entity's primary type.

The individuals tab was answered from Oxigraph by a query that joined labels
and sorted every individual before applying LIMIT. On a synthetic 200,000
individual ontology that is 2.3-3.4 s for the first page and 4.8 s at offset
100,000 — it degrades with depth because each page re-sorts the whole set.

Serving it from `entity_index` needs a marker that `type` cannot provide.
`type` is single-valued and assigned first-wins, so an OWL 2 punned entity —
declared both a Class and a NamedIndividual, as DRON's UO_* unit terms are —
is recorded as a class and would silently disappear from the tab. Measured on
DRON: SPARQL finds 27 named individuals, `type='individual'` finds 19.

`is_individual` is therefore its own flag, true for every NamedIndividual
whatever else the entity also is.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-21
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_index",
        sa.Column("is_individual", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Partial, and ordered the way the listing reads. Indexing only the filter
    # left Postgres sorting all 200,050 rows to disk for every page ("external
    # merge Disk: 14920kB", 884 ms at offset 100,000) because the sort key was
    # not in the index. Carrying lower(primary_label) lets it walk the index in
    # order and skip the sort.
    op.create_index(
        "ix_entity_index_individuals", "entity_index",
        ["version_id", sa.text("lower(primary_label)"), "iri"],
        postgresql_where=sa.text("is_individual"),
    )
    # version_id and is_individual are perfectly correlated — an ontology's
    # individuals all share its version — but the planner multiplies their
    # selectivities as if independent and underestimated 200,050 rows as
    # 41,858. That made a disk sort look cheaper than the index above, so the
    # index went unused. With the dependency declared it picks the index:
    # 884 ms -> 147 ms at offset 100,000.
    op.execute(
        "CREATE STATISTICS entity_index_ind_stats (dependencies, ndistinct) "
        "ON version_id, is_individual FROM entity_index"
    )


def downgrade() -> None:
    op.execute("DROP STATISTICS IF EXISTS entity_index_ind_stats")
    op.drop_index("ix_entity_index_individuals", table_name="entity_index")
    op.drop_column("entity_index", "is_individual")
