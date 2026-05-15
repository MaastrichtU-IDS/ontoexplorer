"""merge title and language preference heads

Revision ID: e1f2a3b4c5d6
Revises: d356f4c54376, d4e5f6a7b8c9
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = ('d356f4c54376', 'd4e5f6a7b8c9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
