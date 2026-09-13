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
