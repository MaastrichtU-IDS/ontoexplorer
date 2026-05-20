"""Thin wrapper over the `bioregistry` PyPI package.

`bioregistry` ships an offline-curated map of biomedical-ontology prefixes
to canonical IRIs. We normalize entity IRIs to a stable prefix so reuse
counts collapse variant forms (e.g. purl.obolibrary.org/obo/RO_ and
purl.org/obo/RO_ both resolve to `ro`).

Unresolved IRIs are flagged so the UI can surface them; callers should fall
back to the raw namespace as a stand-in key.
"""
from __future__ import annotations

import bioregistry


def iri_to_prefix(iri: str) -> tuple[str | None, bool]:
    """Resolve an IRI to a canonical bioregistry prefix.

    Returns (prefix, resolved). When `resolved` is False, `prefix` is either
    `None` (no match at all) or the raw namespace (best-effort fallback).
    """
    parsed = bioregistry.parse_iri(iri)
    if parsed is None:
        return _raw_namespace(iri), False
    prefix, _identifier = parsed
    if prefix is None:
        return _raw_namespace(iri), False
    return prefix, True


def prefix_to_canonical_iri(prefix: str) -> str | None:
    """Return the canonical URI-prefix for a bioregistry prefix, or None."""
    return bioregistry.get_uri_prefix(prefix)


def _raw_namespace(iri: str) -> str | None:
    """Best-effort namespace stripping when bioregistry doesn't recognize the IRI."""
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[0] + sep
    return None
