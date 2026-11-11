"""versions.owl_profile — materialized per-version OWL 2 profile payload

The OWL 2 profile classification (EL/QL/RL/DL verdicts + language tier) was
stored only in a 30-day-TTL Redis cache, written at index time. Once a version
aged past the TTL, the /owl-profile/public fleet rollup and the profile/language
catalogue filters silently dropped it — the same failure mode that reduced the
coverage tab to 4 ontologies.

Materialize the payload on the version row (same shape as the Redis payload).
Nullable: NULL = not yet computed → endpoints fall back to Redis; the backfill
populates existing versions (copying the still-live Redis payload where present,
recomputing from the stored file otherwise).

Revision ID: f6a2d9c4e1b3
Revises: c5f1a8d3b204
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a2d9c4e1b3"
down_revision = "c5f1a8d3b204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column(
            "owl_profile",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("versions", "owl_profile")
