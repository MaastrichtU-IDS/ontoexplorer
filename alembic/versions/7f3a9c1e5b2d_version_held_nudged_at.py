"""add versions.held_nudged_at (held-draft lifecycle marker)

Part of the "Add Ontology" contributor flow (#364 Phase 3): the held-draft lifecycle
beat task nudges an owner once when a version has sat in needs_review past the nudge
window, and auto-deprecates it (reversibly) past the retire window. held_nudged_at
records that the version entered the lifecycle — it keeps the one-time nudge from
re-firing, and marks an auto-retired held draft so the owner can reactivate it back
to needs_review (vs. an ordinary deprecate).

Revision ID: 7f3a9c1e5b2d
Revises: 9f8e7d6c5b4a
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "7f3a9c1e5b2d"
down_revision = "9f8e7d6c5b4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("held_nudged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("versions", "held_nudged_at")
