"""content_query_http proxies a content SPARQL query to an oxigraph HTTP server.

Wiring/encoding is unit-tested with a mocked httpx (CI has no server); the live
round-trip against `oxigraph serve` is validated during the spike, not in CI.
"""
import httpx
import pytest

from ontoexplorer.clients import oxigraph


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    class _Resp:
        content = b'{"head":{},"results":{"bindings":[]}}'
        headers = {"content-type": "application/sparql-results+json"}
        def raise_for_status(self): pass

    class _Client:
        def __init__(self, *a, **k): seen["client_kwargs"] = k
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, headers=None, params=None, timeout=None, **kw):
            seen.update(url=url, body=content.decode(), headers=headers)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return seen


@pytest.mark.anyio
async def test_posts_query_and_dataset_to_query_endpoint(captured):
    body, ctype = await oxigraph.content_query_http(
        "SELECT * WHERE {?s ?p ?o}", "application/sparql-results+json",
        "http://oxi.svc:7878/",
        default_graph_uris=["urn:g1"], named_graph_uris=["urn:n1", "urn:n2"],
    )
    assert captured["url"] == "http://oxi.svc:7878/query"           # trailing slash handled
    assert "query=SELECT" in captured["body"]
    assert "default-graph-uri=urn%3Ag1" in captured["body"]
    assert captured["body"].count("named-graph-uri=") == 2
    assert captured["headers"]["Accept"] == "application/sparql-results+json"
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["client_kwargs"].get("trust_env") is False      # never via egress proxy
    assert ctype == "application/sparql-results+json"


@pytest.mark.anyio
async def test_get_store_returns_proxy_when_endpoint_set(monkeypatch):
    from ontoexplorer.config import get_settings
    from ontoexplorer.clients import oxigraph as ox
    monkeypatch.setattr(get_settings(), "oxigraph_read_only", True, raising=False)
    monkeypatch.setattr(get_settings(), "oxigraph_http_endpoint", "http://oxi.svc:7878", raising=False)
    store = ox.get_store()
    assert type(store).__name__ == "_HttpStoreProxy"


def test_quads_for_pattern_builds_sparql_and_rebuilds_quads(monkeypatch):
    """The proxy turns a pattern into SPARQL and reconstructs native Quads from
    the (embedded-run) solution — verified here without a server."""
    import pyoxigraph
    from ontoexplorer.clients import oxigraph as ox

    # A real embedded store to answer the SELECT the proxy generates.
    backing = pyoxigraph.Store()
    g = pyoxigraph.NamedNode("urn:g")
    backing.add(pyoxigraph.Quad(pyoxigraph.NamedNode("urn:a"), pyoxigraph.NamedNode("urn:p"),
                                pyoxigraph.NamedNode("urn:o"), g))
    proxy = ox._HttpStoreProxy("http://unused")
    monkeypatch.setattr(proxy, "query", lambda q, **k: backing.query(q))
    quads = list(proxy.quads_for_pattern(None, pyoxigraph.NamedNode("urn:p"), None, g))
    assert len(quads) == 1 and isinstance(quads[0], pyoxigraph.Quad)
    assert quads[0].subject.value == "urn:a" and quads[0].object.value == "urn:o"
    assert quads[0].graph_name.value == "urn:g"


def test_get_store_returns_proxy_even_when_writable(monkeypatch):
    """In server mode the WORKER (read_only=False) must also get the proxy, so it
    never opens the embedded RocksDB the server owns (undefined-behaviour trap)."""
    from ontoexplorer.config import get_settings
    from ontoexplorer.clients import oxigraph as ox
    monkeypatch.setattr(get_settings(), "oxigraph_read_only", False, raising=False)
    monkeypatch.setattr(get_settings(), "oxigraph_http_endpoint", "http://oxi.svc:7878", raising=False)
    assert type(ox.get_store()).__name__ == "_HttpStoreProxy"


@pytest.fixture
def sync_http(monkeypatch):
    """Capture every sync httpx POST the write path makes (no server in CI)."""
    calls = []

    class _Resp:
        def raise_for_status(self): pass

    class _Client:
        def __init__(self, *a, **k): _Client.kwargs = k
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, params=None, content=None, headers=None, timeout=None, **kw):
            calls.append({"url": url, "params": params,
                          "body": content.decode() if content else None, "headers": headers})
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    return calls


def _endpoint(monkeypatch, which="oxigraph_http_endpoint"):
    from ontoexplorer.config import get_settings
    monkeypatch.setattr(get_settings(), which, "http://oxi.svc:7878", raising=False)


def test_load_graph_http_drops_then_loads(monkeypatch, sync_http):
    import rdflib
    from ontoexplorer.clients import oxigraph as ox
    _endpoint(monkeypatch)
    # _graph_triple_count issues a query via the proxy; stub it to avoid a server.
    monkeypatch.setattr(ox, "_graph_triple_count", lambda iri: 1)
    g = rdflib.Graph()
    g.add((rdflib.URIRef("urn:a"), rdflib.URIRef("urn:p"), rdflib.URIRef("urn:b")))
    ox.load_graph("ont", "v1", g)
    assert sync_http[0]["url"].endswith("/update") and "DROP SILENT GRAPH" in sync_http[0]["body"]
    assert sync_http[1]["url"].endswith("/store") and sync_http[1]["params"]["graph"] == ox.graph_iri("ont", "v1")
    assert _Client_trust_env_false()


def test_append_http_loads_without_drop(monkeypatch, sync_http):
    from ontoexplorer.clients import oxigraph as ox
    _endpoint(monkeypatch)
    monkeypatch.setattr(ox, "_graph_triple_count", lambda iri: 1)
    ox.append_bytes_to_graph("ont", "v1", b"<urn:a> <urn:p> <urn:b> .", "ttl")
    assert len(sync_http) == 1
    assert sync_http[0]["url"].endswith("/store")  # append: no DROP


def test_delete_graph_http_drops(monkeypatch, sync_http):
    from ontoexplorer.clients import oxigraph as ox
    _endpoint(monkeypatch)
    ox.delete_graph("ont", "v1")
    assert sync_http[0]["url"].endswith("/update") and "DROP SILENT GRAPH" in sync_http[0]["body"]


def test_metadata_writes_route_http(monkeypatch, sync_http):
    import asyncio
    from ontoexplorer.clients import metadata_store as ms
    _endpoint(monkeypatch, "metadata_http_endpoint")
    asyncio.run(ms.insert_turtle("<urn:s> <urn:p> <urn:o> .", graph_iri="urn:meta"))
    assert sync_http[-1]["url"].endswith("/store") and sync_http[-1]["params"]["graph"] == "urn:meta"
    asyncio.run(ms.sparql_update("DELETE WHERE { GRAPH <urn:meta> { ?s ?p ?o } }"))
    assert sync_http[-1]["url"].endswith("/update") and "DELETE" in sync_http[-1]["body"]
    asyncio.run(ms.delete_graph("urn:meta"))
    assert "DROP SILENT GRAPH" in sync_http[-1]["body"]


def _Client_trust_env_false():
    return httpx.Client.kwargs.get("trust_env") is False


def test_sync_http_client_is_pooled(monkeypatch):
    """The sync client is created once and reused (keep-alive pool), not per call."""
    from ontoexplorer.clients import oxigraph as ox
    made = []

    class _C:
        def __init__(self, *a, **k): made.append(self)

    monkeypatch.setattr(httpx, "Client", _C)
    a = ox._sync_http_client()
    b = ox._sync_http_client()
    assert a is b and len(made) == 1


@pytest.mark.anyio
async def test_async_http_client_is_pooled(monkeypatch):
    """The async client is reused within an event loop."""
    from ontoexplorer.clients import oxigraph as ox
    made = []

    class _AC:
        def __init__(self, *a, **k): made.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", _AC)
    a = ox._async_http_client()
    b = ox._async_http_client()
    assert a is b and len(made) == 1


# --- Blank-node handling over the HTTP proxy -------------------------------
# A blank node has no SPARQL syntax that references a specific stored node, so
# the proxy serves blank-node-subject lookups from a per-graph adjacency index
# instead of the (wrong) `GRAPH g { _:label ?p ?o }` translation, which matches
# the whole graph. These tests pin that behaviour.

def _restriction_backing():
    """Embedded store: `urn:C subClassOf [a Restriction; onProperty p; someValuesFrom D]`
    plus an unrelated blank node, so leakage is detectable."""
    import pyoxigraph
    _OWL = "http://www.w3.org/2002/07/owl#"
    store = pyoxigraph.Store()
    g = pyoxigraph.NamedNode("urn:g")
    bn = pyoxigraph.BlankNode()
    add = lambda s, p, o: store.add(pyoxigraph.Quad(s, pyoxigraph.NamedNode(p) if isinstance(p, str) else p,
                                                    pyoxigraph.NamedNode(o) if isinstance(o, str) else o, g))
    add(pyoxigraph.NamedNode("urn:C"), "http://www.w3.org/2000/01/rdf-schema#subClassOf", bn)
    add(bn, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", _OWL + "Restriction")
    add(bn, _OWL + "onProperty", "urn:p")
    add(bn, _OWL + "someValuesFrom", "urn:D")
    bn2 = pyoxigraph.BlankNode()
    add(bn2, "urn:q", "urn:unrelated")
    return store, g


@pytest.fixture(autouse=True)
def _clear_bnode_index():
    from ontoexplorer.clients import oxigraph as ox
    ox._BNODE_IDX.clear()
    yield
    ox._BNODE_IDX.clear()


def test_blank_subject_served_from_index_not_wildcard(monkeypatch):
    import pyoxigraph
    from ontoexplorer.clients import oxigraph as ox
    backing, g = _restriction_backing()
    proxy = ox._HttpStoreProxy("http://unused")
    monkeypatch.setattr(proxy, "query", lambda q, **k: backing.query(q))
    monkeypatch.setattr(ox, "_http_query", lambda ep, q, **k: backing.query(q))

    # Discover the restriction bnode as the object of subClassOf (NamedNode path).
    sc = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
    obj = next(proxy.quads_for_pattern(pyoxigraph.NamedNode("urn:C"), sc, None, g)).object
    assert isinstance(obj, pyoxigraph.BlankNode)

    # Its outgoing triples: exactly the restriction's three, never the whole graph.
    preds = {q.predicate.value for q in proxy.quads_for_pattern(obj, None, None, g)}
    assert preds == {
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        "http://www.w3.org/2002/07/owl#onProperty",
        "http://www.w3.org/2002/07/owl#someValuesFrom",
    }
    # No leakage from the unrelated bnode.
    assert "urn:q" not in preds


def test_blank_subject_predicate_filter(monkeypatch):
    import pyoxigraph
    from ontoexplorer.clients import oxigraph as ox
    backing, g = _restriction_backing()
    proxy = ox._HttpStoreProxy("http://unused")
    monkeypatch.setattr(proxy, "query", lambda q, **k: backing.query(q))
    monkeypatch.setattr(ox, "_http_query", lambda ep, q, **k: backing.query(q))
    sc = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
    obj = next(proxy.quads_for_pattern(pyoxigraph.NamedNode("urn:C"), sc, None, g)).object

    on_prop = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#onProperty")
    quads = list(proxy.quads_for_pattern(obj, on_prop, None, g))
    assert len(quads) == 1
    assert quads[0].object.value == "urn:p"
    assert quads[0].subject == obj and quads[0].graph_name == g


def test_blank_object_raises(monkeypatch):
    import pyoxigraph
    from ontoexplorer.clients import oxigraph as ox
    proxy = ox._HttpStoreProxy("http://unused")
    with pytest.raises(NotImplementedError):
        list(proxy.quads_for_pattern(None, None, pyoxigraph.BlankNode("x"), pyoxigraph.NamedNode("urn:g")))


def test_blank_subject_requires_graph(monkeypatch):
    import pyoxigraph
    from ontoexplorer.clients import oxigraph as ox
    proxy = ox._HttpStoreProxy("http://unused")
    with pytest.raises(NotImplementedError):
        list(proxy.quads_for_pattern(pyoxigraph.BlankNode("x"), None, None, None))


def test_bnode_index_is_cached(monkeypatch):
    import pyoxigraph
    from ontoexplorer.clients import oxigraph as ox
    backing, g = _restriction_backing()
    calls = {"n": 0}

    def _counting_http_query(ep, q, **k):
        calls["n"] += 1
        return backing.query(q)

    proxy = ox._HttpStoreProxy("http://unused")
    monkeypatch.setattr(proxy, "query", lambda q, **k: backing.query(q))
    monkeypatch.setattr(ox, "_http_query", _counting_http_query)
    sc = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
    obj = next(proxy.quads_for_pattern(pyoxigraph.NamedNode("urn:C"), sc, None, g)).object

    list(proxy.quads_for_pattern(obj, None, None, g))
    list(proxy.quads_for_pattern(obj, None, None, g))
    assert calls["n"] == 1  # index built once, reused

    ox._invalidate_bnode_index(g.value)
    list(proxy.quads_for_pattern(obj, None, None, g))
    assert calls["n"] == 2  # rebuilt after invalidation
