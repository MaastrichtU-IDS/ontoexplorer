"""add MOD and example props to profiles

Revision ID: a2b3c4d5e6f7
Revises: e2f3a4b5c6d7
Create Date: 2026-05-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ontology_profiles', sa.Column('example_props', sa.JSON(), nullable=False, server_default='[]'))

    for col in [
        'version_iri_props',
        'see_also_props',
        'is_defined_by_props',
        'competency_question_props',
        'endorsed_by_props',
        'relies_on_props',
        'similar_props',
        'generalizes_props',
        'specializes_props',
        'known_usage_props',
        'used_in_project_props',
    ]:
        op.add_column('ontology_meta_profiles', sa.Column(col, sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('ontology_profiles', 'example_props')
    for col in [
        'version_iri_props', 'see_also_props', 'is_defined_by_props',
        'competency_question_props', 'endorsed_by_props', 'relies_on_props',
        'similar_props', 'generalizes_props', 'specializes_props',
        'known_usage_props', 'used_in_project_props',
    ]:
        op.drop_column('ontology_meta_profiles', col)
