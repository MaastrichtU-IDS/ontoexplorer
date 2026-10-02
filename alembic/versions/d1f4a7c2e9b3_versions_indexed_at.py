"""versions.indexed_at — timestamp of the last successful search index.

The other pipeline-stage times derive from existing tables (ingested=created_at,
profiled=ontology_profiles.created_at, reasoned/embedded=jobs.finished_at), but
the index step only recorded its time in Redis. Add a column so the admin
coverage cards and the ontology-page pipeline block can show it from SQL.
Nullable + not backfilled: existing indexed versions (entity_index rows present)
simply show "indexed, time not recorded" until their next re-index stamps it.

Revision ID: d1f4a7c2e9b3
Revises: c9e5f3a2b8d1
"""
from alembic import op
import sqlalchemy as sa

revision = "d1f4a7c2e9b3"
down_revision = "c9e5f3a2b8d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("versions", "indexed_at")
