"""Remove the per-ontology default display language.

An ontology carried a `preferred_lang` that resolve_lang ranked *above* the
user's own preference, so a reader who had chosen French was shown English
anyway if an owner had set that ontology to English. A dataset default
overriding a stated personal preference is backwards.

Rather than reorder it, the concept is dropped: the display language belongs to
the reader, not to the ontology. A reader picks a language in the navigation
bar (this session) or in their profile (every session). Nothing about an
ontology should decide what language a different person reads it in.

The column is dropped rather than left dormant — an unused column that once
influenced behaviour is a trap for the next person. The values it held were
only ever defaults for readers with no preference of their own, so nothing is
lost that a reader cannot restate.

Revision ID: f1a2b3c4d5e7
Revises: e7f8a9b0c1d2
Create Date: 2026-08-22
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("ontologies", "preferred_lang")


def downgrade() -> None:
    # Restored empty: the previous per-ontology defaults are not recoverable,
    # and reinstating stale ones would silently override readers again.
    op.add_column("ontologies", sa.Column("preferred_lang", sa.String(), nullable=True))
