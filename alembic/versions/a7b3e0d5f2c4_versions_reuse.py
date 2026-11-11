"""versions.reuse — materialized per-version reuse report

The reuse report (imports, MIREOT terms, term-IRI reuse by source, mappings) was
stored only in a 30-day-TTL Redis cache, written at index time. Once a version
aged past the TTL, the /reuse/fleet rollup and the reuse catalogue filter
silently dropped it — the same failure mode as coverage/owl_profile. By the time
this shipped only 4 of 2013 ready versions still had a live Redis key.

Materialize the payload on the version row (same shape as the Redis payload).
Nullable: NULL = not yet computed → endpoints fall back to Redis; the backfill
populates existing versions (copying the still-live Redis payload where present,
recomputing via detect_reuse over entity_index + the store otherwise).

Revision ID: a7b3e0d5f2c4
Revises: f6a2d9c4e1b3
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7b3e0d5f2c4"
down_revision = "f6a2d9c4e1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column(
            "reuse",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("versions", "reuse")
