"""revert the entity_index covering index, restore the key-only norm_c

The covering index from b8d4e2f1a6c7 was a mistake in two ways:

1. It built the ~1GB index with CREATE INDEX CONCURRENTLY and dropped the old
   key-only entity_index_norm_c in the SAME migration. When the concurrent build
   was interrupted (a pod restart during the ~1GB build), Postgres left an
   INVALID index behind; the migration's retry hit `IF NOT EXISTS`, skipped
   rebuilding it, and still dropped norm_c — leaving NO valid C-collation index.
   The Stage-1 LIMIT-fence then had nothing to early-terminate on and fell back
   to norm_prefix (text_pattern_ops) + a full top-N sort, re-regressing large
   prefixes (`protein` back to ~11s on dev).

2. The index-only benefit over the key-only norm_c was marginal (~0.4s) and, on
   a table under active ingest, gated on the visibility map being autovacuumed —
   so it rarely paid off while the BioPortal backfill runs.

This migration is self-healing: it drops entity_index_norm_c_cov whether it is
valid or invalid (DROP INDEX IF EXISTS handles both), and (re)creates the
key-only entity_index_norm_c. The key-only index is small (~205MB) and builds
fast, so a plain CREATE INDEX is reliable and can't leave an invalid index — no
CONCURRENTLY, no autocommit_block, no footgun. On a fresh deploy where
b8d4e2f1a6c7 ran just before this, the net end state is: norm_c present,
norm_c_cov absent.

A covering / index-only approach can be revisited post-backfill, when a
concurrent build is far less likely to be interrupted and the visibility map is
stable — but as a standalone, carefully-run change, not bundled with dropping the
index it replaces.

Revision ID: c9e5f3a2b8d1
Revises: b8d4e2f1a6c7
Create Date: 2026-09-26
"""
from alembic import op

revision = "c9e5f3a2b8d1"
down_revision = "b8d4e2f1a6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the covering index regardless of valid/invalid state.
    op.execute("DROP INDEX IF EXISTS entity_index_norm_c_cov")
    # Restore the key-only C-collation index the Stage-1 fence relies on.
    # Plain (non-concurrent) build: ~205MB, fast, and cannot leave an invalid
    # index. Briefly locks entity_index writes during the build.
    op.execute(
        "CREATE INDEX IF NOT EXISTS entity_index_norm_c "
        'ON entity_index (primary_label_norm COLLATE "C")'
    )


def downgrade() -> None:
    # Repair migration — nothing sensible to restore (the prior state was the
    # broken invalid-covering-index state). No-op.
    pass
