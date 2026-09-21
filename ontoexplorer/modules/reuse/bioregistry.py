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

# Common vocabularies bioregistry does not yet resolve, because it has no
# `providers` entry for the namespace variant we see (e.g. the Erlangen OWL-DL
# rendering of CIDOC-CRM, the OCLC/ssnx namespace for SSN) or no `part_of`
# entry for a modular ontology network (e.g. ArCo's per-module namespaces).
# Each key is a namespace prefix (matched by str.startswith, so a single family
# entry covers every module under it); the value is the prefix an upstream
# bioregistry contribution would produce. These are being submitted upstream as
# `providers`/`part_of` entries — see docs/bioregistry-contributions.md — so
# drop each row here once its PR lands in a bioregistry release.
_LOCAL_NS_PREFIX: dict[str, str] = {
    "http://erlangen-crm.org/current/": "ecrm",
    "http://erlangen-crm.org/efrbroo/": "efrbroo",
    "http://purl.oclc.org/NET/ssnx/ssn#": "ssn",
    "http://purl.oclc.org/NET/ssnx/qu/qu#": "qu",
    "http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#": "dul",
    "http://www.ontologydesignpatterns.org/ont/dul/IOLite.owl#": "iolite",
    "http://www.loa-cnr.it/ontologies/DUL.owl#": "dul",
    "http://spinrdf.org/sp#": "sp",
    "https://www.gleif.org/ontology/Base/": "gleif",
    "https://www.omg.org/spec/LCC/Languages/LanguageRepresentation/": "lcc",
    "https://www.omg.org/spec/LCC/Countries/CountryRepresentation/": "lcc",
    # Family roots (str.startswith covers every module under them).
    "https://w3id.org/arco/ontology/": "arco",
    "https://w3id.org/italia/onto/": "italia",
}
# Longest-first so a more specific namespace wins over a broader family root.
_LOCAL_NS_KEYS: list[str] = sorted(_LOCAL_NS_PREFIX, key=len, reverse=True)


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
    if parsed is not None:
        prefix, _identifier = parsed
        if prefix is not None:
            return prefix, True

    # Curated supplement for vocabularies bioregistry hasn't registered yet.
    local = _local_prefix(iri)
    if local is not None:
        return local, True

    return _raw_namespace(iri), False


def _local_prefix(iri: str) -> str | None:
    """Resolve an IRI against the curated `_LOCAL_NS_PREFIX` supplement."""
    for ns in _LOCAL_NS_KEYS:
        if iri.startswith(ns):
            return _LOCAL_NS_PREFIX[ns]
    return None


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
