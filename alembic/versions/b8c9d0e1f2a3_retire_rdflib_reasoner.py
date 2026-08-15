"""Retire the legacy rdflib reasoner.

The pure-Python rdflib CR1–CR6 EL classifier was removed from the reasoner
service. This archives the seeded ``rdflib (legacy)`` profile and remaps any
versions still bound to rdflib onto the default (rustdl) so re-reasoning keeps
working. Cached classifications are unaffected.

Revision ID: b8c9d0e1f2a3
Revises: b4c2d3e5f6a7
Create Date: 2026-08-15
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "b4c2d3e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop versions' link to any rdflib profile, then remap the reasoner itself
    # to the default so a future re-reason doesn't hit an unknown reasoner.
    op.execute(sa.text(
        "UPDATE versions SET reasoner_profile_id = NULL "
        "WHERE reasoner_profile_id IN "
        "(SELECT id FROM reasoner_profiles WHERE reasoner = 'rdflib')"
    ))
    op.execute(sa.text("UPDATE versions SET reasoner = 'rustdl' WHERE reasoner = 'rdflib'"))
    # Soft-delete the seeded rdflib profile(s).
    op.execute(sa.text("UPDATE reasoner_profiles SET archived = true WHERE reasoner = 'rdflib'"))


def downgrade() -> None:
    # Un-archive the profile. The version reasoner remap is not reversible (the
    # original per-version reasoner is not recorded), so those stay on rustdl.
    op.execute(sa.text("UPDATE reasoner_profiles SET archived = false WHERE reasoner = 'rdflib'"))
