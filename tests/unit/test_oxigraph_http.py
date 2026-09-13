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
        async def post(self, url, content=None, headers=None):
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
