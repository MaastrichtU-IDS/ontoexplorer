"""update Inferred subClassOf chain starter: add DISTINCT, generalise URI to ?class

Revision ID: c4d5e6f7a8b9
Revises: a0b1c2d3e4f5
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


_OLD_QUERY_TEXT = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "SELECT ?ancestor WHERE {\n"
    "  GRAPH ?g {\n"
    "    <URI_HERE> rdfs:subClassOf+ ?ancestor .\n"
    "  }\n"
    "}"
)
_NEW_QUERY_TEXT = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "SELECT DISTINCT ?class ?ancestor WHERE {\n"
    "  GRAPH ?g {\n"
    "    ?class rdfs:subClassOf+ ?ancestor .\n"
    "  }\n"
    "}"
)

_OLD_DESCRIPTION = "Use the Inferred reasoning mode on the scope toolbar; replace <URI_HERE>."
_NEW_DESCRIPTION = (
    "Every (class, ancestor) pair reachable via rdfs:subClassOf+. "
    "Use the Inferred reasoning mode on the scope toolbar for transitively-closed results."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE saved_queries "
            "SET query_text = :new_query, description = :new_desc "
            "WHERE is_starter = true AND name = 'Inferred subClassOf chain'"
        ).bindparams(new_query=_NEW_QUERY_TEXT, new_desc=_NEW_DESCRIPTION)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE saved_queries "
            "SET query_text = :old_query, description = :old_desc "
            "WHERE is_starter = true AND name = 'Inferred subClassOf chain'"
        ).bindparams(old_query=_OLD_QUERY_TEXT, old_desc=_OLD_DESCRIPTION)
    )
