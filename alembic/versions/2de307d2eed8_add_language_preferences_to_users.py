"""add_language_preferences_to_users

Revision ID: 2de307d2eed8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-15 20:47:15.577819

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2de307d2eed8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_lang", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "lang_fallback_strategy",
            sa.String(),
            nullable=False,
            server_default="silent",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "lang_fallback_strategy")
    op.drop_column("users", "preferred_lang")
