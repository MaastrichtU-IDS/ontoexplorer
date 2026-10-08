"""entity_index: index lower(primary_label) and short for the scoped resolver query

The MOS expression evaluator scopes its per-version resolver with
``primary_label_norm IN (...) OR lower(primary_label) IN (...) OR short IN (...)``
(ontoexplorer/modules/search/evaluator.py:_scope_conditions). Only
primary_label_norm was indexed, so the OR degraded to a parallel seq scan over
the whole entity_index (~6M rows, ~3.9s) on every global expression search —
the dominant cost once the full-classification fetch was removed (#277).

Add btree indexes on the two unindexed disjuncts so the planner can BitmapOr all
three and fetch only the matching rows. CONCURRENTLY (hence autocommit) so the
build doesn't lock out the indexer/backfill writes during the deploy.

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = "1a9ed193c325"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # sqlite (tests) builds the schema from the models; these are PG-only
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_entity_index_lower_label",
            "entity_index",
            [sa.text("lower(primary_label)")],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_entity_index_short",
            "entity_index",
            ["short"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_entity_index_short",
            table_name="entity_index",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_entity_index_lower_label",
            table_name="entity_index",
            postgresql_concurrently=True,
            if_exists=True,
        )
