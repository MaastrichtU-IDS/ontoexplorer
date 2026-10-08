"""versions.lang_counts — materialized per-version {lang: count}

The catalogue list/search built per-version language counts by aggregating
entity_index.labels (jsonb_object_keys) per request — ~638ms on a large ontology,
run over the whole catalogue on every filtered request (#286). Materialize the
count on the version row (written at index time, same value the aggregation
produces) so readers do an O(1) batch read instead. Nullable: NULL = not yet
computed → readers fall back to the aggregation until backfilled.

Revision ID: 3b7c1e9f24a0
Revises: 1a9ed193c325
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3b7c1e9f24a0"
down_revision = "1a9ed193c325"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column(
            "lang_counts",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("versions", "lang_counts")
