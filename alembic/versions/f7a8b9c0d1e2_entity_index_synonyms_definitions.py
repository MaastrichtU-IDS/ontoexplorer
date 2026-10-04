"""add synonyms + definitions to entity_index (#242 Stage 0)

First step of consolidating the per-entity Redis working set into Postgres (#242):
mirror the `synonyms` and `definitions` that only the Redis `:iri:` hash held into
entity_index, so readers (OLS API, term detail, ...) can later source them from PG
and Redis can eventually be bounded.

Additive and reader-neutral: new JSONB columns default to '[]'. A constant default
is a metadata-only add in PG 11+ (no rewrite of the multi-GB table). Existing rows
read as [] until re-indexed; populate_entity_index now writes the real values, so a
re-index backfills them.

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_index", sa.Column(
        "synonyms", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("entity_index", sa.Column(
        "definitions", postgresql.JSONB(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("entity_index", "definitions")
    op.drop_column("entity_index", "synonyms")
