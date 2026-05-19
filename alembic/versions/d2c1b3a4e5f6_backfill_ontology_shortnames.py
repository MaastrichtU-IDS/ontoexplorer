"""backfill_ontology_shortnames

Derive a unique shortname for every Ontology row that doesn't have one,
and normalize any non-lowercase shortnames (e.g. SULO -> sulo).

Revision ID: d2c1b3a4e5f6
Revises: c1c0a1b2c3d4
Create Date: 2026-05-19
"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "d2c1b3a4e5f6"
down_revision = "c1c0a1b2c3d4"
branch_labels = None
depends_on = None


# Mirror of ontoexplorer.modules.ingestion.shortname (inlined here so the
# migration doesn't depend on application code that may evolve).
_VALID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")
_EXTS = ("owl", "ttl", "rdf", "obo", "json", "xml", "nt", "rdfs", "n3", "jsonld")


def _infer_shortname_from_iri(iri: str) -> str | None:
    if not iri:
        return None
    trimmed = re.sub(r"[/#]+$", "", iri)
    if not trimmed:
        return None
    last = re.split(r"[/#]", trimmed)[-1]
    parts = last.rsplit(".", 1)
    if len(parts) == 2 and parts[1].lower() in _EXTS:
        last = parts[0]
    last = last.lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", last)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    if len(cleaned) < 2 or len(cleaned) > 64:
        return None
    if not _VALID_RE.match(cleaned):
        return None
    return cleaned


def _uniquify(candidate: str, taken: set[str]) -> str | None:
    suffix = 0
    while True:
        attempt = candidate if suffix == 0 else f"{candidate}-{suffix + 1}"
        if len(attempt) > 64:
            return None
        if attempt not in taken:
            return attempt
        suffix += 1


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(sa.text(
        "SELECT id, iri, shortname FROM ontologies"
    )).fetchall()

    taken: set[str] = set()
    plan: list[tuple[str, str | None, str]] = []  # (id, current, new)

    for row_id, iri, current in rows:
        # Pass 1: build a `taken` set from any row whose shortname is already
        # valid (lowercase + regex match). Non-conforming rows are queued for
        # rewrite below.
        if current is not None and _VALID_RE.match(current):
            taken.add(current)
        else:
            plan.append((row_id, current, ""))

    for i, (row_id, current, _) in enumerate(plan):
        # Try to lowercase the existing shortname first (handles SULO -> sulo).
        # If that fails the validator, fall back to inferring from the IRI.
        if current is not None:
            lowered = current.lower()
            if _VALID_RE.match(lowered) and lowered not in taken:
                taken.add(lowered)
                plan[i] = (row_id, current, lowered)
                continue
        iri = conn.execute(sa.text(
            "SELECT iri FROM ontologies WHERE id = :id"
        ), {"id": row_id}).scalar()
        candidate = _infer_shortname_from_iri(iri or "")
        if candidate is None:
            # Last-ditch fallback: synthetic name from the row's primary key.
            # Keeps the column populated so the subsequent NOT NULL migration
            # has something to enforce against. Admin can rename via PATCH.
            candidate = f"ont-{row_id[:8]}"
        unique = _uniquify(candidate, taken)
        if unique is None:
            raise RuntimeError(
                f"Cannot generate unique shortname for ontology {row_id}; "
                "all suffixes exhausted",
            )
        taken.add(unique)
        plan[i] = (row_id, current, unique)

    for row_id, current, new in plan:
        if new and new != current:
            conn.execute(
                sa.text("UPDATE ontologies SET shortname = :s WHERE id = :id"),
                {"s": new, "id": row_id},
            )


def downgrade() -> None:
    # No-op: shortnames are not destructively recoverable (we don't know which
    # were inferred vs. user-set). Leaving them in place is harmless.
    pass
