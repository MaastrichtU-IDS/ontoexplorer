"""Helpers for inferring and uniqueifying ontology shortnames.

The shortname is the canonical user-facing identifier for an ontology
(referenced from URLs, OLS-compat routes, the dashboard, etc.). It is
derived from the ontology IRI when not explicitly provided, and made
unique by appending a numeric suffix on collision.

Validation regex (mirrored from `ontoexplorer/api/ontologies.py`):
    ^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology

# Match the validator used by PATCH /ontologies/{id}.
_VALID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")

# File extensions stripped from the end of an IRI's last segment.
_EXTS = ("owl", "ttl", "rdf", "obo", "json", "xml", "nt", "rdfs", "n3", "jsonld")


def infer_shortname_from_iri(iri: str) -> str | None:
    """Best-effort shortname inference from an ontology IRI.

    Mirrors the frontend's `slugFromIri` but with validator-compliant output:
    lowercased, leading/trailing non-alphanumerics stripped, internal runs of
    invalid characters collapsed to a single hyphen.

    Returns None if no compliant shortname can be derived (caller should leave
    the column null and let an admin set it manually).
    """
    if not iri:
        return None
    # Drop trailing path separators / fragment markers.
    trimmed = re.sub(r"[/#]+$", "", iri)
    if not trimmed:
        return None
    # Last path or fragment segment.
    last = re.split(r"[/#]", trimmed)[-1]
    # Strip file extension.
    parts = last.rsplit(".", 1)
    if len(parts) == 2 and parts[1].lower() in _EXTS:
        last = parts[0]
    last = last.lower()
    # Replace invalid characters with hyphen; collapse runs.
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", last)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    if len(cleaned) < 2 or len(cleaned) > 64:
        return None
    if not _VALID_RE.match(cleaned):
        return None
    return cleaned


async def unique_shortname(
    db: AsyncSession,
    candidate: str,
    *,
    exclude_id: str | None = None,
) -> str:
    """Return `candidate` if not taken, else the first free `<candidate>-N`.

    Probes the database for collisions. Pass `exclude_id` to ignore a row
    that's being renamed (so e.g. renaming SULO to sulo doesn't collide
    with itself).
    """
    suffix = 0
    while True:
        attempt = candidate if suffix == 0 else f"{candidate}-{suffix + 1}"
        # Validator only allows length 2-64; suffix shouldn't violate.
        if len(attempt) > 64:
            raise ValueError(
                f"Cannot uniquify shortname '{candidate}': suffix exceeded 64 chars",
            )
        stmt = select(Ontology.id).where(Ontology.shortname == attempt)
        if exclude_id is not None:
            stmt = stmt.where(Ontology.id != exclude_id)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            return attempt
        suffix += 1
