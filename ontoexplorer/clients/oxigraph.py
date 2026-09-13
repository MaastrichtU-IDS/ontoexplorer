"""Oxigraph triplestore client via pyoxigraph.

Stores one named graph per ontology version:
  urn:ontology:{ontology_id}:{version_id}            — asserted triples
  urn:ontology:{ontology_id}:{version_id}:inferred   — reasoning output (Phase 6)
"""

import logging
import time
from io import BytesIO
from pathlib import Path

import pyoxigraph
import rdflib

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

_store: pyoxigraph.Store | None = None
_ro_store: pyoxigraph.Store | None = None
_ro_store_opened_at: float = 0.0
_RO_STORE_TTL: float = 60.0  # refresh read-only snapshot every 60 s


def get_store() -> pyoxigraph.Store:
    """Return the Oxigraph store.

    Write mode (worker): singleton for the process lifetime.
    Read-only mode (API): singleton refreshed every 60 s so the API sees recent writes
    without paying the RocksDB secondary-open cost on every request.
    """
    global _store, _ro_store, _ro_store_opened_at
    settings = get_settings()
    path = settings.oxigraph_data_path
    Path(path).mkdir(parents=True, exist_ok=True)
    if settings.oxigraph_read_only:
        now = time.monotonic()
        if _ro_store is None or (now - _ro_store_opened_at) > _RO_STORE_TTL:
            _ro_store = pyoxigraph.Store.read_only(path)
            _ro_store_opened_at = now
        return _ro_store
    if _store is None:
        _store = pyoxigraph.Store(path)
    return _store


def graph_iri(ontology_id: str, version_id: str, inferred: bool = False) -> str:
    base = f"urn:ontology:{ontology_id}:{version_id}"
    return f"{base}:inferred" if inferred else base


def load_graph(ontology_id: str, version_id: str, graph: rdflib.Graph) -> int:
    """
    Load an rdflib Graph into a named Oxigraph graph.

    Returns the number of triples loaded.
    Replaces any existing content in the named graph.
    """
    store = get_store()
    iri = graph_iri(ontology_id, version_id)
    named_graph = pyoxigraph.NamedNode(iri)

    # Serialise rdflib graph to N-Triples for fast bulk load
    nt_bytes = graph.serialize(format="nt").encode("utf-8")

    # Clear existing content in this named graph
    store.remove_graph(named_graph)
    store.add_graph(named_graph)

    # Bulk-load via N-Triples
    store.bulk_load(BytesIO(nt_bytes), "application/n-triples", base_iri=iri, to_graph=named_graph)

    count = sum(1 for _ in store.quads_for_pattern(None, None, None, named_graph))
    logger.info("Loaded %d triples into <%s>", count, iri)
    return count


def bulk_load_bytes(ontology_id: str, version_id: str, data: bytes, mime_type: str) -> int:
    """
    Load raw ontology bytes directly into a named Oxigraph graph, bypassing rdflib.

    Returns the number of triples loaded.
    Replaces any existing content in the named graph.
    """
    store = get_store()
    iri = graph_iri(ontology_id, version_id)
    named_graph = pyoxigraph.NamedNode(iri)
    store.remove_graph(named_graph)
    store.add_graph(named_graph)
    store.bulk_load(BytesIO(data), mime_type, base_iri=iri, to_graph=named_graph)
    count = sum(1 for _ in store.quads_for_pattern(None, None, None, named_graph))
    logger.info("Loaded %d triples into <%s>", count, iri)
    return count


_EXT_TO_MIME: dict[str, str] = {
    "rdf": "application/rdf+xml",
    "owl": "application/rdf+xml",
    "ttl": "text/turtle",
    "nt":  "application/n-triples",
    "jsonld": "application/ld+json",
}


def append_bytes_to_graph(ontology_id: str, version_id: str, data: bytes, ext: str) -> int:
    """
    Append triples from bytes into a named graph without clearing existing content.

    Used to merge resolved owl:imports into the same named graph as the importing ontology.
    Formats not directly supported by Oxigraph (e.g. OBO) are converted via rdflib first.
    Returns the updated total triple count for the named graph.
    """
    store = get_store()
    iri = graph_iri(ontology_id, version_id)
    named_graph = pyoxigraph.NamedNode(iri)

    mime = _EXT_TO_MIME.get(ext)
    if mime:
        store.bulk_load(BytesIO(data), mime, to_graph=named_graph)
    else:
        # OBO or unrecognised format: use rdflib as intermediary
        import rdflib as _rdflib
        from ontoexplorer.modules.ingestion.import_resolver import _guess_format
        fmt = _guess_format(data)
        g = _rdflib.Graph()
        g.parse(data=data, format=fmt)
        nt_bytes = g.serialize(format="nt").encode("utf-8")
        store.bulk_load(BytesIO(nt_bytes), "application/n-triples", to_graph=named_graph)

    return sum(1 for _ in store.quads_for_pattern(None, None, None, named_graph))


def delete_graph(ontology_id: str, version_id: str, inferred: bool = False) -> None:
    store = get_store()
    iri = graph_iri(ontology_id, version_id, inferred)
    store.remove_graph(pyoxigraph.NamedNode(iri))


def sparql_query(query: str) -> pyoxigraph.QuerySolutions | pyoxigraph.QueryTriples | bool:
    """Execute a SPARQL query against the full store (all named graphs)."""
    return get_store().query(query)


def graph_exists(ontology_id: str, version_id: str) -> bool:
    store = get_store()
    iri = graph_iri(ontology_id, version_id)
    return pyoxigraph.NamedNode(iri) in store


_RDFS_SUBCLASSOF = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")


def inferred_subclass_page(
    store: pyoxigraph.Store, inferred_iri: str, offset: int, limit: int
) -> list[dict]:
    """One page of inferred ``rdfs:subClassOf`` axioms from the :inferred graph.

    Scans the predicate-bound index (``?s rdfs:subClassOf ?o`` in the given graph)
    and takes the ``[offset:offset+limit]`` window, so a page costs O(offset+limit)
    reads. The old caller sorted the whole graph with SPARQL ``ORDER BY`` before
    paging, which was >59 s on sphn's 404k-triple :inferred graph.

    Only IRI–IRI pairs are returned (matching the old ``FILTER(isIRI && isIRI)``).
    Order is the store's stable index order — deterministic across requests, since
    the :inferred graph is immutable once reasoning has written it — not alphabetical.
    """
    from itertools import islice

    graph = pyoxigraph.NamedNode(inferred_iri)
    quads = store.quads_for_pattern(None, _RDFS_SUBCLASSOF, None, graph)
    iri_pairs = (
        {"subClass": q.subject.value, "superClass": q.object.value}
        for q in quads
        if isinstance(q.subject, pyoxigraph.NamedNode)
        and isinstance(q.object, pyoxigraph.NamedNode)
    )
    return list(islice(iri_pairs, offset, offset + limit))


async def content_query_http(
    query: str,
    accept: str,
    endpoint: str,
    default_graph_uris: list[str] | None = None,
    named_graph_uris: list[str] | None = None,
    timeout: float = 30.0,
) -> tuple[bytes, str]:
    """Proxy a content SPARQL *query* to an `oxigraph serve` HTTP endpoint.

    Used by the API when OXIGRAPH_HTTP_ENDPOINT is set, so the API needs no
    embedded RocksDB mount (see docs/design/2026-09-oxigraph-as-a-service.md).
    The server serialises per the Accept header, so we return its bytes directly.

    trust_env=False: the endpoint is an in-cluster Service, reached directly — it
    must not go through the egress proxy, and there is no untrusted host here to
    guard (unlike the ingestion fetch path).
    """
    from urllib.parse import urlencode

    import httpx

    # SPARQL protocol: query + dataset URIs form-encoded in the body. Encoded
    # explicitly to bytes (repeated keys for multiple graph URIs).
    params: list[tuple[str, str]] = [("query", query)]
    for u in (default_graph_uris or []):
        params.append(("default-graph-uri", u))
    for u in (named_graph_uris or []):
        params.append(("named-graph-uri", u))
    body = urlencode(params).encode()

    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.post(
            endpoint.rstrip("/") + "/query",
            content=body,
            headers={"Accept": accept, "Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/sparql-results+json")
