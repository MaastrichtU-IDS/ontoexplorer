"""add users.email_verified

Groundwork for routing auth through the platform Keycloak realm (#368): the
provider's email_verified claim lands here and will gate granting upload rights.
Defaults false; nothing reads it as a gate until Keycloak populates it.

Revision ID: a9e8d7c6b5f4
Revises: e3b1c7a9d2f4
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "a9e8d7c6b5f4"
down_revision = "e3b1c7a9d2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified")
