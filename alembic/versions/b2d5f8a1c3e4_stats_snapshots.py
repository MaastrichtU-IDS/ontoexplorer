"""stats_snapshots — durable last-good copy of the public-stats aggregate

Revision ID: b2d5f8a1c3e4
Revises: e9a5b2c7d13f
Create Date: 2026-11-23

The home-page /stats/public aggregate is cached in Redis (stats:public:v1), but a
cold miss (first boot, eviction, or a Redis wipe like services #670) forces a
~110s recompute on the request path — dominated by the entity_index distinct-IRI
scan in _unique_counts. This table keeps the last computed payload durably so a
cold read serves the last-good value instantly and triggers the recompute in the
background instead of blocking. One row, keyed by id (e.g. "public").
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b2d5f8a1c3e4"
down_revision = "e9a5b2c7d13f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stats_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stats_snapshots")
