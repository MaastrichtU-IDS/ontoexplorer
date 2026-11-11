"""versions.coverage — materialized per-version coverage payload

Coverage (per-entity-type label / definition / multilingual counts) was stored
only in a 30-day-TTL Redis cache, written at index time. Once the bulk of the
fleet aged past the TTL, the /coverage rollup silently dropped every version
whose key had expired — 2009 of 2013 ready versions, so the public coverage tab
showed only 4 ontologies, and the per-version /coverage endpoint 404'd for the
rest.

Materialize the payload on the version row (recomputed from the durable
entity_index mirror, same shape as the Redis payload). Nullable: NULL = not yet
computed → endpoints fall back to Redis, then recompute + self-heal; the backfill
populates existing versions.

Revision ID: c5f1a8d3b204
Revises: b4e9c2a7f015
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5f1a8d3b204"
down_revision = "b4e9c2a7f015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column(
            "coverage",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("versions", "coverage")
