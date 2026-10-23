"""add versions.declared_license overlay (contributor-asserted license)

Part of the "Add Ontology" contributor flow (#364 follow-on): lets a contributor
assert an SPDX license when the content declares none, so the quality gate can be
cleared and re-evaluated without rewriting the ontology's triples. Fills an
absence only; never overrides a license the content declares. declared_by/at carry
provenance for honest display ("declared by contributor").

Revision ID: 9f8e7d6c5b4a
Revises: a9e8d7c6b5f4
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "9f8e7d6c5b4a"
down_revision = "a9e8d7c6b5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("declared_license", sa.String(), nullable=True))
    op.add_column("versions", sa.Column("declared_by", sa.String(), nullable=True))
    op.add_column("versions", sa.Column("declared_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "versions_declared_by_fkey", "versions", "users",
        ["declared_by"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("versions_declared_by_fkey", "versions", type_="foreignkey")
    op.drop_column("versions", "declared_at")
    op.drop_column("versions", "declared_by")
    op.drop_column("versions", "declared_license")
