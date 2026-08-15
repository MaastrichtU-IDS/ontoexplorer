"""bind versions to reasoner profiles + job provenance meta

versions.reasoner_profile_id (FK -> reasoner_profiles, SET NULL) records which
profile a version was reasoned with; jobs.meta holds the effective
{reasoner, params, profile_id} for a reasoning run.

Revision ID: b4c2d3e5f6a7
Revises: a3f1c2d4e5b6
Create Date: 2026-08-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c2d3e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a3f1c2d4e5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("reasoner_profile_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_versions_reasoner_profile_id", "versions", "reasoner_profiles",
        ["reasoner_profile_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column("jobs", sa.Column("meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "meta")
    op.drop_constraint("fk_versions_reasoner_profile_id", "versions", type_="foreignkey")
    op.drop_column("versions", "reasoner_profile_id")
