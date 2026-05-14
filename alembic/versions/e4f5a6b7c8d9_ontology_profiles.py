"""add ontology_profiles table

Revision ID: e4f5a6b7c8d9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_profiles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('version_id', sa.String(), nullable=False),
        sa.Column('label_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('definition_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('synonym_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('deprecated_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('candidates_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(), nullable=False, server_default='auto_detected'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_id'),
    )


def downgrade() -> None:
    op.drop_table('ontology_profiles')
