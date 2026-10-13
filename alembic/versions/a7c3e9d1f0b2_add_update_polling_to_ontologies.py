"""add upstream-update polling columns to ontologies

Revision ID: a7c3e9d1f0b2
Revises: f3a9c1e7b2d4
Create Date: 2026-10-13

Stage 2 of upstream-update polling: the daily catalogue poll records when a newer
release is available (notify-by-default) and stores conditional-GET validators so
an unchanged upstream costs a 304.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a7c3e9d1f0b2'
down_revision: str = 'f3a9c1e7b2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ontologies', sa.Column(
        'update_available', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('ontologies', sa.Column(
        'update_detail', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True))
    op.add_column('ontologies', sa.Column(
        'last_polled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('ontologies', sa.Column('upstream_etag', sa.String(), nullable=True))
    op.add_column('ontologies', sa.Column('upstream_last_modified', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('ontologies', 'upstream_last_modified')
    op.drop_column('ontologies', 'upstream_etag')
    op.drop_column('ontologies', 'last_polled_at')
    op.drop_column('ontologies', 'update_detail')
    op.drop_column('ontologies', 'update_available')
