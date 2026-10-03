"""index jobs and ontology_profiles by version_id

The admin panel's coverage query (one row per ontology, ~1,900 on dev) probes
four tables per ontology with a correlated EXISTS. entity_index (PK
(version_id, iri)) and term_embeddings (unique (version_id, entity_iri)) already
have version_id as the leading column of an index, so those probes are index
seeks. jobs and ontology_profiles did not — Postgres does not auto-index a
foreign-key column — so the `reasoned` probe
    EXISTS (SELECT 1 FROM jobs WHERE version_id = l.id
            AND type = 'reason' AND status = 'done')
fell back to scanning jobs, a table that grows a row per pipeline task across
the whole LOV + BioPortal backfill. The same unindexed column also slows
/admin/overview's running-reason lookup and the per-version pipeline status.

Add a composite (version_id, type, status) on jobs so both admin probes are
index-only, and a plain (version_id) on ontology_profiles. No query changes —
the existing SQL uses them immediately.

Revision ID: c3d4e5f6a7b8
Revises: d1f4a7c2e9b3
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "d1f4a7c2e9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (version_id, type, status) serves both the coverage `reasoned` EXISTS and
    # the overview running-reason IN-query as index-only lookups; the version_id
    # prefix also covers plain job-history-by-version reads.
    op.create_index(
        "ix_jobs_version_id_type_status", "jobs", ["version_id", "type", "status"]
    )
    op.create_index(
        "ix_ontology_profiles_version_id", "ontology_profiles", ["version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ontology_profiles_version_id", table_name="ontology_profiles")
    op.drop_index("ix_jobs_version_id_type_status", table_name="jobs")
