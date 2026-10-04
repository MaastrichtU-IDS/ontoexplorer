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

# Same extension set, for the canonicalisation regex below.
_EXT_ALT = "ttl|owl|rdf|xml|n3|nt|rdfs|jsonld|json|obo|ofn|omn"
# A file whose stem equals its parent path segment, e.g. `…/sulo/sulo.ttl`.
# Captures the base up to (but excluding) that redundant `/<stem>.<ext>`.
_FILE_AT_NS_ROOT = re.compile(
    rf"^(?P<base>.*/(?P<seg>[^/]+))/(?P=seg)\.(?:{_EXT_ALT})$", re.IGNORECASE
)


def canonicalize_ontology_iri(iri: str) -> str:
    """Normalise an ontology IRI to a stable identity key for dedup (#250).

    Two real-world patterns split one vocabulary into several catalogue rows
    because the served file's self-declared ``owl:Ontology`` IRI varies:

    * trailing fragment/slash — ``…/22-rdf-syntax-ns`` vs ``…/22-rdf-syntax-ns#``
    * a file sitting at its own namespace root — ``https://w3id.org/sulo/`` vs
      ``https://w3id.org/sulo/sulo.ttl`` (SULO 0.2.0 declared the file URL)

    Both collapse to the same key here. The file strip is deliberately narrow:
    only when the file *stem equals the parent segment* (``…/sulo/sulo.ttl``),
    so shared registry roots like ``…/obo/caro.owl`` are left untouched (``caro``
    != ``obo``). The result is an identity key, not a display IRI — callers keep
    the declared IRI for display and use this only to match duplicates.
    """
    if not iri:
        return iri
    s = iri.strip()
    # A file at its own namespace root → drop the redundant `/<stem>.<ext>`.
    m = _FILE_AT_NS_ROOT.match(s)
    if m:
        s = m.group("base")
    # Trailing fragment marker / path separators don't change identity.
    s = re.sub(r"[#/]+$", "", s)
    return s


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


# Instrumentation for #250 Layer 3: a version-like segment (v1.2, 0.2.0, 1_0) or an
# embedded date (2025-07-11) in the identity IRI, signalling a version-specific subject.
_VERSION_SEG = re.compile(r"(?:^|[/#._-])v?\d+(?:[._-]\d+)+", re.IGNORECASE)
_DATE_SEG = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}")


def identity_instability_reason(iri: str) -> str:
    """Classify why an identity IRI looks version/file-specific, or "" if it looks stable.

    Used only for instrumentation (#250 Layer 3): these are the ontologies a content-
    negotiation resolver would target — a file extension that survived canonicalisation,
    an embedded date, or a version-number segment. Not a decision input; it over-counts
    slightly on purpose so the Layer-3 population is not under-estimated.
    """
    if not iri:
        return ""
    c = canonicalize_ontology_iri(iri)
    last = re.split(r"[/#]", c)[-1] if c else ""
    if "." in last and last.rsplit(".", 1)[1].lower() in _EXTS:
        return "file"
    if _DATE_SEG.search(c):
        return "date"
    if _VERSION_SEG.search(c):
        return "version"
    return ""


def select_identity_iri(subject_iri: str | None, preferred_ns: str | None) -> str | None:
    """Choose the ontology's identity/dedup IRI (#250 Layer 2).

    Prefer the vocabulary's declared canonical namespace (``vann:preferredNamespaceUri``)
    — it's stable across versions and is the content-negotiation base — but only when
    the ``owl:Ontology`` subject lives *within* that namespace. That maps a version-file
    subject (``…/sulo/sulo-0.2.0.ttl``) to ``…/sulo/`` while refusing to adopt a namespace
    an ontology declares that is unrelated to itself (which would cause a false merge).
    Falls back to the subject IRI.
    """
    if not preferred_ns:
        return subject_iri
    cn = canonicalize_ontology_iri(preferred_ns)
    cs = canonicalize_ontology_iri(subject_iri or "")
    if subject_iri is None or cs == cn or cs.startswith((cn + "/", cn + "#")):
        return preferred_ns
    return subject_iri


async def find_ontology_by_canonical_iri(
    db: AsyncSession, iri: str, *, exclude_id: str | None = None
):
    """Return an existing Ontology whose IRI is the *same vocabulary* as ``iri``.

    Dedup key is :func:`canonicalize_ontology_iri`, so a file-at-namespace-root or
    a trailing-``#`` variant matches the clean namespace row even though the stored
    IRIs differ (#250). Tries the exact IRI first (indexed), then the small set of
    rows sharing the canonical prefix. Stored IRIs are never rewritten here.
    """
    exact = (await db.execute(
        select(Ontology).where(Ontology.iri == iri)
    )).scalar_one_or_none()
    if exact and exact.id != exclude_id:
        return exact

    canon = canonicalize_ontology_iri(iri)
    if not canon:
        return None
    # Candidates share the canonical prefix (canon, canon#, canon/, canon/<file>).
    # Bounded by the prefix, then confirmed by recomputing the key both sides.
    like = canon.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (await db.execute(
        select(Ontology).where(Ontology.iri.like(like, escape="\\"))
    )).scalars().all()
    for row in rows:
        if row.id != exclude_id and canonicalize_ontology_iri(row.iri) == canon:
            return row
    return None


def slugify_name(text: str) -> str | None:
    """Slugify free text (a title/label) into a validator-compliant shortname.

    Lowercases, replaces runs of invalid characters with a single hyphen, trims,
    and truncates to the 64-char limit at a hyphen boundary. Returns None if no
    compliant slug results.
    """
    if not text:
        return None
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", text.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    if len(cleaned) > 64:
        cleaned = cleaned[:64].rstrip("-_")
    if len(cleaned) < 2 or len(cleaned) > 64 or not _VALID_RE.match(cleaned):
        return None
    return cleaned


def derive_shortname(
    iri: str, *, prefix: str | None = None, title: str | None = None
) -> str | None:
    """Best shortname from ontology metadata, falling back to the IRI (#249).

    Order: ``vann:preferredNamespacePrefix`` (the vocabulary's own declared short
    name) → a slug of ``dcterms:title``/``rdfs:label`` → the IRI tail. Each candidate
    must pass the shortname validator; the first that does wins. Returns None only
    when nothing compliant can be produced.
    """
    for candidate in (slugify_name(prefix or ""), slugify_name(title or "")):
        if candidate:
            return candidate
    return infer_shortname_from_iri(iri)


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
