"""Fetch MIREOT source ontologies for the host+imports+MIREOT reasoning scope.

The resolver reads Phase 1's reuse cache payload to know which source-prefixes
are MIREOT'd (foreign-IRI + minimal-axiomatization + NOT in imports closure).
For each such prefix it:
  1. Derives the canonical source IRI via bioregistry
  2. Calls the existing OntoExplorer import_resolver to fetch + MinIO-cache it
  3. Converts the fetched bytes to N-Triples format
  4. Writes to `out_dir` so the merger can include it

Fails soft per source: a single unreachable source goes into `skipped`, the
overall result still includes whatever WAS fetched.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import rdflib

from ontoexplorer.modules.reuse.bioregistry import prefix_to_canonical_iri


log = logging.getLogger(__name__)


@dataclass
class MireotSourceResolveResult:
    fetched: dict[str, Path] = field(default_factory=dict)  # prefix -> path to .nt file
    skipped: list[str] = field(default_factory=list)        # prefixes that failed to fetch


def fetch_mireot_sources(
    *,
    reuse_payload: dict,
    out_dir: Path,
) -> MireotSourceResolveResult:
    """Resolve all MIREOT source prefixes for one version.

    Args:
        reuse_payload: the JSON dict from `reuse:{version_id}` Redis cache (Phase 1).
        out_dir: where to write the fetched N-Triples files.

    Returns:
        MireotSourceResolveResult mapping prefixes to .nt paths (success) and
        a list of skipped prefixes (failure or no canonical IRI).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = MireotSourceResolveResult()

    imported_prefixes = {
        edge.get("target_prefix")
        for edge in reuse_payload.get("imports", [])
        if edge.get("target_prefix")
    }

    needed_prefixes: set[str] = set()
    for term in reuse_payload.get("mireot_terms", []):
        prefix = term.get("source_prefix")
        if not prefix:
            continue
        if prefix in imported_prefixes:
            continue  # already in import closure — covered by host_plus_imports scope
        needed_prefixes.add(prefix)

    for prefix in sorted(needed_prefixes):
        canonical_iri = prefix_to_canonical_iri(prefix)
        if not canonical_iri:
            result.skipped.append(prefix)
            log.warning("mireot_source_no_canonical_iri prefix=%s", prefix)
            continue
        # bioregistry's URI-prefix is the namespace, not the ontology file. For OBO
        # Foundry, we conventionally fetch `<canonical_iri>.owl` or use the ontology IRI.
        # For non-OBO sources this won't work uniformly; treat as best-effort.
        source_url = _derive_ontology_url(prefix, canonical_iri)
        try:
            nt_path = _fetch_and_convert_to_nt(prefix, source_url, out_dir)
            result.fetched[prefix] = nt_path
        except Exception as exc:
            log.warning("mireot_source_fetch_failed prefix=%s url=%s err=%s",
                        prefix, source_url, exc)
            result.skipped.append(prefix)
    return result


def _derive_ontology_url(prefix: str, canonical_iri: str) -> str:
    """Best-effort derivation of an ontology document URL from a bioregistry prefix.

    Convention for OBO Foundry: http://purl.obolibrary.org/obo/{prefix}.owl
    Falls back to the canonical bioregistry URI prefix for non-OBO sources.
    """
    if "purl.obolibrary.org/obo/" in canonical_iri:
        return f"http://purl.obolibrary.org/obo/{prefix}.owl"
    return canonical_iri


def _fetch_and_convert_to_nt(prefix: str, source_url: str, out_dir: Path) -> Path:
    """Fetch the ontology bytes (via import_resolver) and write as N-Triples to out_dir.

    Returns the path to the .nt file.
    Raises RuntimeError on fetch failure.
    """
    from ontoexplorer.modules.ingestion.import_resolver import _fetch_import

    data, ext = _fetch_import(source_url)
    if not data:
        raise RuntimeError(f"empty body fetching {source_url}")

    # Parse via rdflib (handles owl/turtle/rdf/xml/obo), re-serialize as N-Triples
    g = rdflib.Graph()
    rdflib_format = _ext_to_rdflib_format(ext)
    g.parse(data=data, format=rdflib_format)

    nt_path = out_dir / f"mireot_{prefix}.nt"
    nt_path.write_bytes(g.serialize(format="nt").encode("utf-8"))
    return nt_path


def _ext_to_rdflib_format(ext: str) -> str:
    return {
        "owl": "xml",
        "rdf": "xml",
        "ttl": "turtle",
        "nt": "nt",
        "obo": "obo",   # rdflib may not handle .obo natively; fall back to xml on failure
    }.get(ext.lstrip("."), "xml")
