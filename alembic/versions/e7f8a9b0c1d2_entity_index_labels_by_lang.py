"""Record each entity's labels per language, so the fast paths can serve them.

The materialised tree, the individuals listing and the inferred tree all read
`entity_index`, which stored a single `primary_label` and no record of what
language it was in. Two consequences:

* Any language selection bypassed those paths entirely — they were gated on
  `lang is None` — putting DRON's tree back to 12.0 s against 0.033 s. An
  ontology with `preferred_lang` set never got the fast path at all, and the
  session language is sticky in localStorage, so one visit to the language
  picker made every ontology slow indefinitely.
* The tree's language badge renders only when a node reports a `lang`, and the
  SQL paths returned null for every node, so the badges silently disappeared
  wherever the fast path was used.

`labels` is a lang -> label map (untagged labels under ""), and `primary_lang`
records the language `primary_label` came from. The Redis index already held
this; it simply was not mirrored.

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-08-22
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_index",
        sa.Column("labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("entity_index", sa.Column("primary_lang", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("entity_index", "primary_lang")
    op.drop_column("entity_index", "labels")
