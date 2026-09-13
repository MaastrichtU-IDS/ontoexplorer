"""Oxigraph triplestore client via pyoxigraph.

Stores one named graph per ontology version:
  urn:ontology:{ontology_id}:{version_id}            — asserted triples
  urn:ontology:{ontology_id}:{version_id}:inferred   — reasoning output (Phase 6)
"""

import asyncio
import logging
import time
from io import BytesIO
from pathlib import Path

import httpx
import pyoxigraph
import rdflib

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

_store: pyoxigraph.Store | None = None
_ro_store: pyoxigraph.Store | None = None
_ro_store_opened_at: float = 0.0
_RO_STORE_TTL: float = 60.0  # refresh read-only snapshot every 60 s

# Pooled, keep-alive HTTP clients for the oxigraph server (oxigraph-as-a-service).
# A fresh client per request meant a new TCP+HTTP handshake on every /sparql
# call — a perf run showed that capping content throughput and *collapsing* it
# under concurrency (connection churn), while a pooled client held ~1.7 ms/req.
# One long-lived pooled client per process removes that. httpx.Client is
# thread-safe, so the sync one is shared across the to_thread/celery threads that
# drive the store proxy; the async one is bound to the running event loop.
_HTTP_LIMITS = httpx.Limits(max_keepalive_connections=64, max_connections=256, keepalive_expiry=30.0)
_sync_http: "tuple[type, httpx.Client] | None" = None
_async_http: "tuple[tuple, httpx.AsyncClient] | None" = None


def _sync_http_client() -> httpx.Client:
    """Process-wide pooled sync client. Keyed on the httpx.Client class so a test
    monkeypatch (which swaps the class) transparently rebuilds it."""
    global _sync_http
    cls = httpx.Client
    if _sync_http is None or _sync_http[0] is not cls:
        _sync_http = (cls, cls(limits=_HTTP_LIMITS, trust_env=False))
    return _sync_http[1]


def _async_http_client() -> httpx.AsyncClient:
    """Pooled async client for the current event loop. Keyed on (class, loop id)
    so each uvicorn worker process reuses one, and a per-test loop (or a test
    monkeypatch) rebuilds cleanly."""
    global _async_http
    key = (httpx.AsyncClient, id(asyncio.get_running_loop()))
    if _async_http is None or _async_http[0] != key:
        _async_http = (key, httpx.AsyncClient(limits=_HTTP_LIMITS, trust_env=False))
    return _async_http[1]


class _HttpStoreProxy:
    """Read-only stand-in for a pyoxigraph.Store backed by an `oxigraph serve`
    HTTP server (oxigraph-as-a-service). Returned by get_store() in the API when
    OXIGRAPH_HTTP_ENDPOINT is set, so the ~34 `store.query()` and ~24
    `store.quads_for_pattern()` call sites route to the server unchanged and the
    API needs no RocksDB mount. Only read ops are supported — writers keep the
    embedded RW store.
    """

    def __init__(self, endpoint: str) -> None:
        self._ep = endpoint.rstrip("/")

    def query(self, query, default_graph=None, named_graphs=None):
        dg = [n.value for n in default_graph] if default_graph else None
        ng = [n.value for n in named_graphs] if named_graphs else None
        return _http_query(self._ep, query, dg, ng)

    def quads_for_pattern(self, subject=None, predicate=None, object=None, graph_name=None):
        # Rebuild the pattern as SPARQL (bound terms inlined via their N-Triples
        # form; unbound as vars), run it, and reconstruct native Quads from the
        # solution — so callers get the same Quad objects as the embedded store.
        triple = " ".join(
            (str(t) if t is not None else f"?{v}")
            for v, t in (("s", subject), ("p", predicate), ("o", object))
        )
        if graph_name is not None:
            body = f"GRAPH {graph_name} {{ {triple} }}"
        else:
            body = f"GRAPH ?g {{ {triple} }}"
        for row in self.query(f"SELECT * WHERE {{ {body} }}"):
            yield pyoxigraph.Quad(
                subject if subject is not None else row["s"],
                predicate if predicate is not None else row["p"],
                object if object is not None else row["o"],
                graph_name if graph_name is not None else row["g"],
            )

    def __len__(self) -> int:
        return int(next(iter(self.query("SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g {?s ?p ?o} }")))["n"].value)


def get_store():
    """Return the content store.

    - Worker (read-write): embedded singleton for the process lifetime.
    - API (read-only): the HTTP proxy when OXIGRAPH_HTTP_ENDPOINT is set
      (oxigraph-as-a-service), else an embedded read-only secondary refreshed
      every 60 s so the API sees recent writes without a per-request open cost.
    """
    global _store, _ro_store, _ro_store_opened_at
    settings = get_settings()
    if settings.oxigraph_http_endpoint:
        # Server owns the volume (sole opener): every process reads via the proxy
        # and writes via the routed write functions — none opens embedded, avoiding
        # the "read-only alongside a writer is undefined behaviour" trap.
        return _HttpStoreProxy(settings.oxigraph_http_endpoint)
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


def _http_query(endpoint: str, query: str, default_graph_uris=None, named_graph_uris=None):
    """POST a SELECT/ASK/CONSTRUCT to the oxigraph server and return native results.

    SELECT/ASK come back as SPARQL-results JSON and are parsed to QuerySolutions /
    bool; CONSTRUCT/DESCRIBE come back as N-Triples parsed to a triple iterator.
    """
    import re
    from urllib.parse import urlencode

    is_graph = re.match(r"\s*(?:#[^\n]*\n\s*|PREFIX\b[^\n]*\n\s*|BASE\b[^\n]*\n\s*)*(CONSTRUCT|DESCRIBE)\b",
                        query, re.IGNORECASE) is not None
    accept = "application/n-triples" if is_graph else "application/sparql-results+json"
    params: list[tuple[str, str]] = [("query", query)]
    for u in (default_graph_uris or []):
        params.append(("default-graph-uri", u))
    for u in (named_graph_uris or []):
        params.append(("named-graph-uri", u))
    resp = _sync_http_client().post(
        f"{endpoint.rstrip('/')}/query",
        content=urlencode(params).encode(),
        headers={"Accept": accept, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=get_settings().sparql_query_timeout_seconds,
    )
    resp.raise_for_status()
    if is_graph:
        return pyoxigraph.parse(resp.content, format=pyoxigraph.RdfFormat.N_TRIPLES)
    return pyoxigraph.parse_query_results(resp.content, pyoxigraph.QueryResultsFormat.JSON)


def graph_iri(ontology_id: str, version_id: str, inferred: bool = False) -> str:
    base = f"urn:ontology:{ontology_id}:{version_id}"
    return f"{base}:inferred" if inferred else base


def _graph_triple_count(iri: str) -> int:
    """Triple count of a named graph via the routed store (embedded or HTTP)."""
    ng = pyoxigraph.NamedNode(iri)
    return sum(1 for _ in get_store().quads_for_pattern(None, None, None, ng))


def _http_write_endpoint() -> str | None:
    """The oxigraph server to write through (sole owner in oxigraph-as-a-service
    mode). Reads/writes both go via HTTP then, so the volume is opened by nobody
    but the server."""
    return get_settings().oxigraph_http_endpoint or None


def _http_load_graph(endpoint: str, iri: str, data: bytes, content_type: str, *, replace: bool) -> None:
    """DROP (if replace) then bulk-load `data` into graph `iri` on the server."""
    client = _sync_http_client()
    if replace:
        r = client.post(
            f"{endpoint.rstrip('/')}/update",
            content=f"DROP SILENT GRAPH <{iri}>".encode(),
            headers={"Content-Type": "application/sparql-update"},
            timeout=600.0,
        )
        r.raise_for_status()
    r = client.post(
        f"{endpoint.rstrip('/')}/store",
        params={"graph": iri},
        content=data,
        headers={"Content-Type": content_type},
        timeout=600.0,
    )
    r.raise_for_status()


def load_graph(ontology_id: str, version_id: str, graph: rdflib.Graph) -> int:
    """Load an rdflib Graph into a named graph, replacing existing content.

    Returns the number of triples loaded. Routes to the HTTP server when
    OXIGRAPH_HTTP_ENDPOINT is set, else embedded.
    """
    iri = graph_iri(ontology_id, version_id)
    nt_bytes = graph.serialize(format="nt").encode("utf-8")
    ep = _http_write_endpoint()
    if ep:
        _http_load_graph(ep, iri, nt_bytes, "application/n-triples", replace=True)
    else:
        store = get_store()
        named_graph = pyoxigraph.NamedNode(iri)
        store.remove_graph(named_graph)
        store.add_graph(named_graph)
        store.bulk_load(BytesIO(nt_bytes), "application/n-triples", base_iri=iri, to_graph=named_graph)
    count = _graph_triple_count(iri)
    logger.info("Loaded %d triples into <%s>", count, iri)
    return count


def bulk_load_bytes(ontology_id: str, version_id: str, data: bytes, mime_type: str) -> int:
    """Load raw ontology bytes into a named graph, replacing existing content.
    Routes HTTP when configured, else embedded."""
    iri = graph_iri(ontology_id, version_id)
    ep = _http_write_endpoint()
    if ep:
        _http_load_graph(ep, iri, data, mime_type, replace=True)
    else:
        store = get_store()
        named_graph = pyoxigraph.NamedNode(iri)
        store.remove_graph(named_graph)
        store.add_graph(named_graph)
        store.bulk_load(BytesIO(data), mime_type, base_iri=iri, to_graph=named_graph)
    count = _graph_triple_count(iri)
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
    iri = graph_iri(ontology_id, version_id)
    named_graph = pyoxigraph.NamedNode(iri)

    mime = _EXT_TO_MIME.get(ext)
    if mime:
        payload, content_type = data, mime
    else:
        # OBO or unrecognised format: use rdflib as intermediary
        import rdflib as _rdflib
        from ontoexplorer.modules.ingestion.import_resolver import _guess_format
        fmt = _guess_format(data)
        g = _rdflib.Graph()
        g.parse(data=data, format=fmt)
        payload, content_type = g.serialize(format="nt").encode("utf-8"), "application/n-triples"

    ep = _http_write_endpoint()
    if ep:
        _http_load_graph(ep, iri, payload, content_type, replace=False)  # append
    else:
        get_store().bulk_load(BytesIO(payload), content_type, to_graph=named_graph)
    return _graph_triple_count(iri)


def delete_graph(ontology_id: str, version_id: str, inferred: bool = False) -> None:
    iri = graph_iri(ontology_id, version_id, inferred)
    ep = _http_write_endpoint()
    if ep:
        r = _sync_http_client().post(
            f"{ep.rstrip('/')}/update",
            content=f"DROP SILENT GRAPH <{iri}>".encode(),
            headers={"Content-Type": "application/sparql-update"},
            timeout=120.0,
        )
        r.raise_for_status()
    else:
        get_store().remove_graph(pyoxigraph.NamedNode(iri))


def sparql_query(
    query: str,
    default_graph_uris: list[str] | None = None,
    named_graph_uris: list[str] | None = None,
) -> pyoxigraph.QuerySolutions | pyoxigraph.QueryTriples | bool:
    """Execute a SPARQL query — embedded, or against the HTTP server if configured.

    When OXIGRAPH_HTTP_ENDPOINT is set the query is POSTed to the `oxigraph serve`
    server and the SPARQL-results JSON is parsed back into a native
    `QuerySolutions` via pyoxigraph.parse_query_results — so callers see the exact
    same result type (and `.value` / `str()` semantics) whether embedded or HTTP,
    and need no changes. Only SELECT/ASK go through here (no sparql_query caller
    uses CONSTRUCT/DESCRIBE).
    """
    kwargs: dict = {}
    if default_graph_uris:
        kwargs["default_graph"] = [pyoxigraph.NamedNode(u) for u in default_graph_uris]
    if named_graph_uris:
        kwargs["named_graphs"] = [pyoxigraph.NamedNode(u) for u in named_graph_uris]
    # get_store() returns the HTTP proxy when OXIGRAPH_HTTP_ENDPOINT is set, so
    # this one call routes embedded-or-HTTP; the proxy parses server results back
    # to native QuerySolutions, so the return type is identical either way.
    return get_store().query(query, **kwargs)


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

    # SPARQL protocol: query + dataset URIs form-encoded in the body. Encoded
    # explicitly to bytes (repeated keys for multiple graph URIs).
    params: list[tuple[str, str]] = [("query", query)]
    for u in (default_graph_uris or []):
        params.append(("default-graph-uri", u))
    for u in (named_graph_uris or []):
        params.append(("named-graph-uri", u))
    body = urlencode(params).encode()

    resp = await _async_http_client().post(
        endpoint.rstrip("/") + "/query",
        content=body,
        headers={"Accept": accept, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "application/sparql-results+json")
