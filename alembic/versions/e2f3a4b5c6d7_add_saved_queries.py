"""add saved_queries table

Revision ID: e2f3a4b5c6d7
Revises: f58beb3f4610
Create Date: 2026-05-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'f58beb3f4610'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saved_queries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_saved_queries_user_id', 'saved_queries', ['user_id'])
    op.create_index('ix_saved_queries_is_public', 'saved_queries', ['is_public'])


def downgrade() -> None:
    op.drop_index('ix_saved_queries_is_public', table_name='saved_queries')
    op.drop_index('ix_saved_queries_user_id', table_name='saved_queries')
    op.drop_table('saved_queries')
