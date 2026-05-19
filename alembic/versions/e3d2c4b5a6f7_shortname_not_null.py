"""shortname_not_null

Enforce NOT NULL on ontologies.shortname. Assumes the
`backfill_ontology_shortnames` migration has run and every row has a value.

Revision ID: e3d2c4b5a6f7
Revises: d2c1b3a4e5f6
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa


revision = "e3d2c4b5a6f7"
down_revision = "d2c1b3a4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safety check before altering — if any nulls slipped through, abort
    # with a useful error rather than mid-statement.
    conn = op.get_bind()
    null_count = conn.execute(sa.text(
        "SELECT COUNT(*) FROM ontologies WHERE shortname IS NULL"
    )).scalar()
    if null_count and null_count > 0:
        raise RuntimeError(
            f"Cannot enforce NOT NULL on ontologies.shortname: {null_count} rows "
            "still have a null shortname. Run the backfill migration first."
        )
    op.alter_column("ontologies", "shortname", nullable=False)


def downgrade() -> None:
    op.alter_column("ontologies", "shortname", nullable=True)
