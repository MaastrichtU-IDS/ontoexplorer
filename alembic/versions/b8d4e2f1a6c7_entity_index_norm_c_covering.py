"""covering index on entity_index for index-only Stage-1 prefix scans

The Stage-1 prefix query (pg_entity_search / pg_autocomplete_entities) fences its
`ORDER BY primary_label_norm COLLATE "C" LIMIT :pool` on entity_index alone, so
the C-collation btree drives an ordered index scan that stops at ~:pool rows.
But `entity_index_norm_c` is key-only, so each of those ~pool rows still needs a
heap fetch to read the selected columns. EXPLAIN (ANALYZE, BUFFERS) on dev for a
cold prefix showed the fenced inner scan doing ~500 random heap reads
(`read=497`, ~1 cold page per row) → ~970ms, the residual after the fence fix
took the cold path down from ~23s.

Replacing it with a covering index — same key + collation, INCLUDEing every
column the inner subquery selects — makes that scan Index-Only (Heap Fetches: 0),
so the pool is served entirely from the index. Verified with EXPLAIN ANALYZE on
Postgres 16: `Index Only Scan ... Heap Fetches: 0`, sub-millisecond for the pool,
and it stays index-only under the forced hash-join plan the production planner
picks. (Full benefit requires the pages to be all-visible, i.e. autovacuumed;
during heavy ingest the newest pages still incur heap fetches until VACUUM.)

The covering index has the identical key (`primary_label_norm COLLATE "C"`) as
`entity_index_norm_c`, so it fully subsumes it for the LIKE range + ORDER BY;
we drop the old key-only index to avoid maintaining two btrees on the same key.

Built CONCURRENTLY so the ~1GB build does not lock entity_index writes while the
BioPortal backfill is still running.

Revision ID: b8d4e2f1a6c7
Revises: a7c3f10e9b21
Create Date: 2026-09-26
"""
from alembic import op

revision = "b8d4e2f1a6c7"
down_revision = "a7c3f10e9b21"
branch_labels = None
depends_on = None


# The columns the Stage-1 inner subqueries select (superset of both functions'
# projections; primary_label_norm is the index key). Keep in sync with the
# prefix_sql SELECT lists in ontoexplorer/modules/search/pg_search.py.
_COVER = "iri, primary_label, short, type, version_id, ontology_id, source"


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS entity_index_norm_c_cov "
            'ON entity_index (primary_label_norm COLLATE "C") '
            f"INCLUDE ({_COVER})"
        )
        # Redundant once the covering index exists (same key/collation).
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS entity_index_norm_c")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS entity_index_norm_c "
            'ON entity_index (primary_label_norm COLLATE "C")'
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS entity_index_norm_c_cov")
