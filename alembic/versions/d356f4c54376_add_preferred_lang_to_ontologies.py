"""add_preferred_lang_to_ontologies

Revision ID: d356f4c54376
Revises: 2de307d2eed8
Create Date: 2026-05-15 20:47:49.535068

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd356f4c54376'
down_revision: Union[str, Sequence[str], None] = '2de307d2eed8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ontologies", sa.Column("preferred_lang", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ontologies", "preferred_lang")
