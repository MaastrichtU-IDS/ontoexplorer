"""add reasoner_profiles (admin-defined reasoner + params configurations)

Named reasoner configurations an admin defines and end users/admins select when
adding or re-indexing an ontology. Seeds one default profile per available
reasoner (whelk removed). Soft-delete via `archived`.

Revision ID: a3f1c2d4e5b6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f1c2d4e5b6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reasoner_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("reasoner", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("dashboard_selectable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Seed one profile per known reasoner (availability is filtered at selection
    # time from the live reasoner-service, not here). rustdl is the default and
    # dashboard-selectable; the rest are admin-only until an admin opts them in.
    seed = sa.table(
        "reasoner_profiles",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("reasoner", sa.String),
        sa.column("params", sa.JSON),
        sa.column("dashboard_selectable", sa.Boolean),
        sa.column("is_default", sa.Boolean),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(seed, [
        {"id": "seed-rustdl-default", "name": "rustdl (default)", "reasoner": "rustdl",
         "params": {}, "dashboard_selectable": True, "is_default": True,
         "description": "SROIQ DL reasoner; auto EL-saturation on EL-profile ontologies."},
        {"id": "seed-konclude", "name": "konclude", "reasoner": "konclude",
         "params": {}, "dashboard_selectable": False, "is_default": False,
         "description": "OWL 2 DL reasoner (all profiles). Complete but slower on large ontologies."},
        {"id": "seed-km", "name": "km", "reasoner": "km",
         "params": {}, "dashboard_selectable": False, "is_default": False,
         "description": "Consequence-based SROIQ/OWL 2 DL reasoner (route=auto)."},
        {"id": "seed-rdflib", "name": "rdflib (legacy)", "reasoner": "rdflib",
         "params": {}, "dashboard_selectable": False, "is_default": False,
         "description": "Legacy RDFS/EL-ish classifier."},
    ])


def downgrade() -> None:
    op.drop_table("reasoner_profiles")
