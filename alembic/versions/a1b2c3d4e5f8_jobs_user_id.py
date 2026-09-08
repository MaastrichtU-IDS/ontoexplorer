"""attribute jobs to the user who submitted them

/api/v1/jobs returned every row to any caller, so one user could read another's
job history — and, before the error text was withheld from anonymous callers,
their failure messages too. Scoping the listing needs an owner, and Job had
none: only a nullable version_id, because an ingestion row is created from the
Celery task id before any version exists.

Nullable and unbackfilled. Existing rows predate attribution and there is no
sound way to infer who submitted them; guessing via version -> ontology -> owner
would be wrong for anything a maintainer or admin ran. They stay visible to
admins only, which is the safe reading of "unknown owner".

Revision ID: a1b2c3d4e5f8
Revises: f1a2b3c4d5e7
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f8"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("user_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_user_id", "jobs", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )
    # The listing filters on it for every non-admin request.
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_constraint("fk_jobs_user_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "user_id")
