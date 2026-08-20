"""Allow version-less job rows so early ingestion failures are recorded.

An "ingestion" job row is created from the Celery task id the moment the task
starts — before the pipeline has produced an OntologyVersion. With
``jobs.version_id`` NOT NULL, a submission that failed early (unreachable IRI,
source over the download cap, unparseable file) could not be recorded at all,
so the error lived only in the worker log and the caller saw a queued
submission that never appeared. The column is filled in on success.

Revision ID: a7b8c9d0e1f2
Revises: b8c9d0e1f2a3
Create Date: 2026-08-20
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("jobs", "version_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Version-less rows cannot satisfy the FK; drop them before restoring NOT NULL.
    op.execute(sa.text("DELETE FROM jobs WHERE version_id IS NULL"))
    op.alter_column("jobs", "version_id", existing_type=sa.String(), nullable=False)
