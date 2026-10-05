"""add types (rdf:type classes) to entity_index (#242 Stage 1 PR 5)

Mirror each individual's rdf:type class IRIs (minus owl:NamedIndividual) — held
only in the Redis `:iri:` hash — into entity_index, so the OLS `/types` endpoint
and the class→individuals filter can source them from Postgres instead of a
per-request SPARQL query against Oxigraph.

Additive and reader-neutral: a new JSONB column defaulting to '[]'. A constant
default is a metadata-only add in PG 11+ (no rewrite of the multi-GB table).
Existing rows read as [] until re-indexed; populate_entity_index now writes the
real values, so a re-index backfills them.

Revision ID: f3a4b5c6d7e8
Revises: f7a8b9c0d1e2
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_index", sa.Column(
        "types", postgresql.JSONB(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("entity_index", "types")
