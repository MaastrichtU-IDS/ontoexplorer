"""Recursively resolve owl:imports closures and cache each import in MinIO."""

import hashlib
import logging
from dataclasses import dataclass, field

import httpx
import rdflib
from rdflib.namespace import OWL

from ontoexplorer.modules.storage.minio_client import import_exists, import_key, store_import

logger = logging.getLogger(__name__)

_OWL_IMPORTS = OWL.imports
_TIMEOUT = httpx.Timeout(60.0)
_MAX_DEPTH = 20  # guard against circular imports


@dataclass
class ResolvedImport:
    key: str        # MinIO key; empty string if fetch failed
    data: bytes     # raw bytes; empty if fetch failed
    ext: str        # file extension (rdf/ttl/nt/obo/jsonld)


def resolve_imports_sparql(ontology_id: str, version_id: str) -> dict[str, ResolvedImport]:
    """
    Extract owl:imports from an already-loaded Oxigraph graph via SPARQL, then fetch each.

    Returns a dict mapping import IRI → ResolvedImport.
    """
    from ontoexplorer.clients.oxigraph import sparql_query, graph_iri

    g = graph_iri(ontology_id, version_id)
    results = sparql_query(f"""
        SELECT ?import FROM <{g}> WHERE {{
            ?ont <http://www.w3.org/2002/07/owl#imports> ?import .
        }}
    """)
    import_iris = [str(row["import"]) for row in results]
    if not import_iris:
        return {}

    visited: set[str] = set()
    all_results: dict[str, ResolvedImport] = {}
    for iri in import_iris:
        _resolve_single_import(iri, visited, all_results, depth=0)
    return all_results


def _resolve_single_import(
    iri: str,
    visited: set[str],
    results: dict[str, ResolvedImport],
    depth: int,
) -> None:
    if iri in visited or depth > _MAX_DEPTH:
        return
    visited.add(iri)
    try:
        data, ext = _fetch_import(iri)
        sha256 = hashlib.sha256(data).hexdigest()
        if not import_exists(sha256, ext):
            store_import(sha256, ext, data)
        key = import_key(sha256, ext)
        results[iri] = ResolvedImport(key=key, data=data, ext=ext)
        logger.info("Resolved import %s → %s", iri, key)
        sub_graph = rdflib.Graph()
        try:
            sub_graph.parse(data=data, format=_guess_format(data))
            for sub_iri in sub_graph.objects(None, _OWL_IMPORTS):
                _resolve_single_import(str(sub_iri), visited, results, depth + 1)
        except Exception as exc:
            logger.warning("Could not parse import %s for sub-imports: %s", iri, exc)
    except Exception as exc:
        logger.warning("Failed to fetch import %s: %s (continuing with partial closure)", iri, exc)
        results[iri] = ResolvedImport(key="", data=b"", ext="")


def resolve_imports(graph: rdflib.Graph, visited: set[str] | None = None, depth: int = 0) -> dict[str, ResolvedImport]:
    """
    Recursively fetch all owl:imports from graph.

    Returns a dict mapping import IRI → ResolvedImport.
    Already-cached imports are not re-fetched.
    """
    if visited is None:
        visited = set()

    results: dict[str, ResolvedImport] = {}

    if depth > _MAX_DEPTH:
        logger.warning("Maximum import depth (%d) reached; stopping recursion", _MAX_DEPTH)
        return results

    import_iris = [str(o) for o in graph.objects(None, _OWL_IMPORTS)]

    for iri in import_iris:
        if iri in visited:
            continue
        visited.add(iri)

        try:
            data, ext = _fetch_import(iri)
            sha256 = hashlib.sha256(data).hexdigest()

            if not import_exists(sha256, ext):
                store_import(sha256, ext, data)

            key = import_key(sha256, ext)
            results[iri] = ResolvedImport(key=key, data=data, ext=ext)
            logger.info("Resolved import %s → %s", iri, key)

            # Recurse into the fetched import's own imports
            sub_graph = rdflib.Graph()
            try:
                sub_graph.parse(data=data, format=_guess_format(data))
                sub_results = resolve_imports(sub_graph, visited=visited, depth=depth + 1)
                results.update(sub_results)
            except Exception as exc:
                logger.warning("Could not parse import %s for sub-import resolution: %s", iri, exc)

        except Exception as exc:
            logger.warning("Failed to fetch import %s: %s (continuing with partial closure)", iri, exc)
            results[iri] = ResolvedImport(key="", data=b"", ext="")

    return results


def _fetch_import(iri: str) -> tuple[bytes, str]:
    """Fetch an import IRI, returning (bytes, file_extension)."""
    from ontoexplorer.modules.ingestion.source_resolver import _RDF_ACCEPT

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(iri, headers={"Accept": _RDF_ACCEPT})
        resp.raise_for_status()

    ct = resp.headers.get("content-type", "")
    ext = _content_type_to_ext(ct)
    return resp.content, ext


def _content_type_to_ext(content_type: str) -> str:
    mime = content_type.split(";")[0].strip().lower()
    return {
        "application/rdf+xml": "rdf",
        "application/owl+xml": "owl",
        "text/turtle": "ttl",
        "application/x-turtle": "ttl",
        "application/n-triples": "nt",
        "application/ld+json": "jsonld",
        "text/plain": "obo",
    }.get(mime, "rdf")


def _guess_format(data: bytes) -> str:
    head = data[:512].lstrip()
    if head.startswith(b"<?xml"):
        return "xml"
    if head.startswith(b"@prefix") or head.startswith(b"PREFIX") or head.startswith(b"@base"):
        return "turtle"
    if head.startswith(b"{"):
        return "json-ld"
    if head.startswith(b"format-version:"):
        return "obo"
    return "xml"  # safe default for most OWL files
