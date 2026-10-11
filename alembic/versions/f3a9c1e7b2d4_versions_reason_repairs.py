"""versions.reason_repairs — input repairs the reasoner applied to a version

The reasoner (rustdl) applies store-level work-arounds so horned-owl's strict RDF
reader can parse non-conformant published ontologies: stripping extra rdf:type on
the ontology node ("Invalid annotation found") and injecting owl:Class declarations
for undeclared owl:equivalentClass operands ("Unknown entity in equivalent class
statement"). Those repairs were previously log-only and invisible. Record them per
version so the fact that an ontology was patched to reason is surfaced as repository
metadata. Nullable: NULL = not yet reasoned on a build that records repairs; {} =
reasoned with nothing to repair.

Revision ID: f3a9c1e7b2d4
Revises: c4d8e2f1a9b0
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f3a9c1e7b2d4"
down_revision = "c4d8e2f1a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column(
            "reason_repairs",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("versions", "reason_repairs")
