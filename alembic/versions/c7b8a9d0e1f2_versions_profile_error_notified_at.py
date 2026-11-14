"""versions.profile_error_notified_at — dedup for owner OWL-profile-failure emails

Revision ID: c7b8a9d0e1f2
Revises: a7b3e0d5f2c4
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "c7b8a9d0e1f2"
down_revision = "a7b3e0d5f2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set when the owner has been emailed that this version's OWL 2 profile could not
    # be computed (actionable categories only). NULL = not yet notified, so a
    # re-ingest/backfill does not re-email. See modules/notifications/email.py.
    op.add_column(
        "versions",
        sa.Column("profile_error_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("versions", "profile_error_notified_at")
