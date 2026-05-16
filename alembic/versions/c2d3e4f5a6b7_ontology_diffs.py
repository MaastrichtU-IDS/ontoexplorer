"""add ontology_diffs table

Revision ID: c2d3e4f5a6b7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_diffs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('ontology_id', sa.String(), nullable=False),
        sa.Column('version_from_id', sa.String(), nullable=False),
        sa.Column('version_to_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('summary', sa.JSON(), nullable=True),
        sa.Column('diff_data', sa.JSON(), nullable=True),
        sa.Column('narrative', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ontology_id'], ['ontologies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['version_from_id'], ['versions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['version_to_id'], ['versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_from_id', 'version_to_id'),
    )


def downgrade() -> None:
    op.drop_table('ontology_diffs')
