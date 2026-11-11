"""versions.graph_counts — materialized graph-level VoID counts

The ontology-page statistics (triples, classes, the three OWL property kinds,
named individuals) were computed live on a stats-cache miss with six SPARQL
COUNT queries against Oxigraph. The full-graph COUNT(*) and the owl:Class count
are O(graph size) — ~6.8s and ~5.5s on NCIt (10.7M triples) — so a cold request
ran 13-30s on large ontologies and timed out (HTTP 500) on the biggest; the 500
cached nothing, so every first viewer paid it again.

Materialize the six counts on the version row (written at index time, same
queries → identical values) so /stats does an O(1) read. Nullable: NULL = not
yet computed → the endpoint falls back to the live compute and persists the row
(self-heal), and the backfill populates existing versions.

Revision ID: b4e9c2a7f015
Revises: b5d8e2f1a9c3
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b4e9c2a7f015"
down_revision = "b5d8e2f1a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column(
            "graph_counts",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("versions", "graph_counts")
