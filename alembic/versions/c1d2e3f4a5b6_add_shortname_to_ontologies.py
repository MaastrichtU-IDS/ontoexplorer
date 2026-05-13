"""add shortname to ontologies

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ontologies', sa.Column('shortname', sa.String(), nullable=True))
    op.create_unique_constraint('uq_ontologies_shortname', 'ontologies', ['shortname'])


def downgrade() -> None:
    op.drop_constraint('uq_ontologies_shortname', 'ontologies', type_='unique')
    op.drop_column('ontologies', 'shortname')
