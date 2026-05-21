"""add is_starter + category to saved_queries; seed starters

Revision ID: a0b1c2d3e4f5
Revises: e3d2c4b5a6f7
Create Date: 2026-05-21
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "e3d2c4b5a6f7"
branch_labels = None
depends_on = None


SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"

STARTERS: list[dict] = [
    {
        "name": "All classes in scope",
        "description": "Every owl:Class declared in the scoped named graphs, with rdfs:label if any.",
        "category": "Exploration",
        "tags": ["owl", "class"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?cls ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?cls a owl:Class .\n"
            "    OPTIONAL { ?cls rdfs:label ?label }\n"
            "  }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
    {
        "name": "All properties in scope",
        "description": "Every owl:ObjectProperty / owl:DatatypeProperty / owl:AnnotationProperty in the scoped graphs.",
        "category": "Exploration",
        "tags": ["owl", "property"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?p ?type ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    VALUES ?type { owl:ObjectProperty owl:DatatypeProperty owl:AnnotationProperty }\n"
            "    ?p a ?type .\n"
            "    OPTIONAL { ?p rdfs:label ?label }\n"
            "  }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
    {
        "name": "All named individuals in scope",
        "description": "Every owl:NamedIndividual declared in the scoped graphs.",
        "category": "Exploration",
        "tags": ["owl", "individual"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?ind ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?ind a owl:NamedIndividual .\n"
            "    OPTIONAL { ?ind rdfs:label ?label }\n"
            "  }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
    {
        "name": "Find term by label",
        "description": 'Replace "search text" with a partial or exact label. Case-insensitive.',
        "category": "Term lookup",
        "tags": ["label", "search"],
        "query_text": (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?term ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?term rdfs:label ?label .\n"
            "    FILTER(CONTAINS(LCASE(STR(?label)), \"search text\"))\n"
            "  }\n"
            "}\n"
            "LIMIT 100"
        ),
    },
    {
        "name": "Subclasses of class",
        "description": "Replace <URI_HERE> with a class IRI. Returns asserted direct subclasses.",
        "category": "Term lookup",
        "tags": ["subclass", "hierarchy"],
        "query_text": (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?sub ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?sub rdfs:subClassOf <URI_HERE> .\n"
            "    OPTIONAL { ?sub rdfs:label ?label }\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "Inferred subClassOf chain",
        "description": "Use the Inferred reasoning mode on the scope toolbar; replace <URI_HERE>.",
        "category": "Reasoning",
        "tags": ["inferred", "subclass"],
        "query_text": (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?ancestor WHERE {\n"
            "  GRAPH ?g {\n"
            "    <URI_HERE> rdfs:subClassOf+ ?ancestor .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "Equivalents of class",
        "description": "Replace <URI_HERE> with a class IRI.",
        "category": "Reasoning",
        "tags": ["equivalent"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "SELECT ?eq WHERE {\n"
            "  GRAPH ?g {\n"
            "    <URI_HERE> owl:equivalentClass ?eq .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "OWL 2 DL violations: punning",
        "description": "Entities used as both class and individual (one common DL violation pattern).",
        "category": "Profile",
        "tags": ["dl", "violation", "punning"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "SELECT DISTINCT ?entity WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?entity a owl:Class .\n"
            "    ?entity a owl:NamedIndividual .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "OWL 2 EL violations: universal restrictions",
        "description": "owl:allValuesFrom restrictions are not permitted in OWL 2 EL.",
        "category": "Profile",
        "tags": ["el", "violation"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "SELECT DISTINCT ?restriction ?on ?type WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?restriction a owl:Restriction ;\n"
            "                 owl:onProperty ?on ;\n"
            "                 owl:allValuesFrom ?type .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "Triples in V2 not in V1",
        "description": "Replace <V1_URI_HERE> and <V2_URI_HERE> with the two version graph URIs. Asymmetric diff.",
        "category": "Diff",
        "tags": ["diff", "version"],
        "query_text": (
            "SELECT ?s ?p ?o WHERE {\n"
            "  GRAPH <V2_URI_HERE> { ?s ?p ?o }\n"
            "  FILTER NOT EXISTS { GRAPH <V1_URI_HERE> { ?s ?p ?o } }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
]


def upgrade() -> None:
    op.add_column(
        "saved_queries",
        sa.Column("is_starter", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "saved_queries",
        sa.Column("category", sa.String(length=64), nullable=True),
    )

    # Create the system user (owns all starter rows). Idempotent via ON CONFLICT.
    # The users table columns: id (PK), email (nullable), display_name (nullable),
    # created_at (server_default), preferred_lang (nullable),
    # lang_fallback_strategy (NOT NULL, server_default="silent").
    # Note: no provider/subject/is_admin columns — those live in oauth_accounts.
    op.execute(
        sa.text(
            "INSERT INTO users (id, display_name) "
            "VALUES (:id, 'System') "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(id=SYSTEM_USER_ID)
    )

    # Seed starters
    sq_table = sa.table(
        "saved_queries",
        sa.column("id", sa.String),
        sa.column("user_id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("query_text", sa.Text),
        sa.column("tags", sa.JSON),
        sa.column("is_public", sa.Boolean),
        sa.column("is_starter", sa.Boolean),
        sa.column("category", sa.String),
    )
    rows = [
        {
            "id": str(uuid.uuid4()),
            "user_id": SYSTEM_USER_ID,
            "name": s["name"],
            "description": s["description"],
            "query_text": s["query_text"],
            "tags": s["tags"],
            "is_public": True,
            "is_starter": True,
            "category": s["category"],
        }
        for s in STARTERS
    ]
    op.bulk_insert(sq_table, rows)


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM saved_queries WHERE is_starter = true AND user_id = :uid"
        ).bindparams(uid=SYSTEM_USER_ID)
    )
    op.execute(
        sa.text("DELETE FROM users WHERE id = :uid").bindparams(uid=SYSTEM_USER_ID)
    )
    op.drop_column("saved_queries", "category")
    op.drop_column("saved_queries", "is_starter")
