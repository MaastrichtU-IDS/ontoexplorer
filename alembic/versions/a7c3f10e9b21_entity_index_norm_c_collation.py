"""add C-collation btree on entity_index.primary_label_norm for ordered prefix scans

Keyword search / autocomplete Stage-1 fetches a bounded pool in
`primary_label_norm COLLATE "C"` order so the scan terminates early instead of
materialising + joining + sorting *every* `LIKE 'x%'` match (which made common
prefixes like `cell` take tens of seconds — the whole match set is fetched
before the LIMIT).

The existing `entity_index_norm_prefix` (text_pattern_ops) index serves the LIKE
range but lives in a different operator family, so it cannot satisfy an
`ORDER BY primary_label_norm COLLATE "C"` — Postgres would still full-scan + sort.
A default-opfamily C-collation btree serves BOTH the prefix range and the
ordering from one index, so the planner does an index scan that stops at LIMIT.
Verified with EXPLAIN ANALYZE: 40k-match full-scan+sort → index scan fetching
~pool rows only.

Revision ID: a7c3f10e9b21
Revises: a1b2c3d4e5f8
Create Date: 2026-09-25
"""
from alembic import op

revision = "a7c3f10e9b21"
down_revision = "a1b2c3d4e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'CREATE INDEX IF NOT EXISTS entity_index_norm_c '
        'ON entity_index (primary_label_norm COLLATE "C")'
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS entity_index_norm_c")
