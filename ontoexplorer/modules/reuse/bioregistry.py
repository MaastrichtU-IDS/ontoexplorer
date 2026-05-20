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

    Special handling for OBO IRIs: if the IRI matches purl.obolibrary.org/obo/*,
    we extract the ontology code (e.g., 'bfo' from 'http://purl.obolibrary.org/obo/bfo.owl')
    and validate it against bioregistry.
    """
    # Special case for OBO Foundry IRIs
    if "purl.obolibrary.org/obo/" in iri:
        obo_prefix = _extract_obo_prefix(iri)
        if obo_prefix:
            return obo_prefix, True

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


def _extract_obo_prefix(iri: str) -> str | None:
    """Extract OBO ontology prefix from purl.obolibrary.org/obo/* IRIs.

    Examples:
        http://purl.obolibrary.org/obo/bfo.owl -> 'bfo'
        http://purl.obolibrary.org/obo/RO_ -> 'ro' (case-normalized)
    """
    if "purl.obolibrary.org/obo/" not in iri:
        return None

    try:
        # Extract the part after '/obo/'
        parts = iri.split("purl.obolibrary.org/obo/")
        if len(parts) < 2:
            return None
        onto_part = parts[1]

        # Remove file extensions (.owl, .rdf, etc.) and underscores
        onto_code = onto_part.split(".")[0].split("#")[0].rstrip("_").lower()

        # Validate that this is a known prefix in bioregistry
        if bioregistry.get_uri_prefix(onto_code):
            return onto_code
    except (IndexError, AttributeError):
        pass

    return None


def _raw_namespace(iri: str) -> str | None:
    """Best-effort namespace stripping when bioregistry doesn't recognize the IRI."""
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[0] + sep
    return None
