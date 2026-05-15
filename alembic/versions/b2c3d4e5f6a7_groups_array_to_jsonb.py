"""convert groups column from ARRAY to jsonb

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: str = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ontologies ALTER COLUMN groups TYPE jsonb USING to_jsonb(groups)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ontologies ALTER COLUMN groups TYPE varchar[] "
        "USING array(SELECT jsonb_array_elements_text(groups))"
    )
