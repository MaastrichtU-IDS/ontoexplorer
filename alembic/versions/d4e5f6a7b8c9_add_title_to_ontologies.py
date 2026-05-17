"""add title column to ontologies

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: str = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ontologies', sa.Column('title', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('ontologies', 'title')
