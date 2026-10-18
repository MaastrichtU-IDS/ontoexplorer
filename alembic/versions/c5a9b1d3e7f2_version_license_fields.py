"""add versions.license + versions.license_compliant

Persist the declared license (canonicalized to SPDX) and whether it's on the
platform compliance allowlist (#364), so the ingested->ready quality gate can
require a compliant license. Defaults null/false; existing ready versions are
untouched (the gate never demotes an already-ready version).

Revision ID: c5a9b1d3e7f2
Revises: e3b1c7a9d2f4
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op

revision = "c5a9b1d3e7f2"
down_revision = "e3b1c7a9d2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("license", sa.String(), nullable=True))
    op.add_column(
        "versions",
        sa.Column("license_compliant", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("versions", "license_compliant")
    op.drop_column("versions", "license")
