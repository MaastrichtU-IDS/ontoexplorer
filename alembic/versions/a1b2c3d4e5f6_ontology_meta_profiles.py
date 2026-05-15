"""add ontology_meta_profiles table

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_meta_profiles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('version_id', sa.String(), nullable=False),
        sa.Column('title_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('shortname_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('description_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('creator_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('contributor_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('publisher_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('license_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('homepage_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('version_info_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('prefix_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('namespace_uri_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('modified_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('language_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('citation_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('funding_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('syntax_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('resolved', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('candidates_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(), nullable=False, server_default='auto_detected'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_id'),
    )


def downgrade() -> None:
    op.drop_table('ontology_meta_profiles')
