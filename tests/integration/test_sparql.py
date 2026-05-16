"""Integration tests for SPARQL proxy endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.anyio
async def test_sparql_content_blocks_insert(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400
    assert "not permitted" in resp.json()["detail"]


@pytest.mark.anyio
async def test_sparql_content_blocks_delete(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"DELETE WHERE { ?s ?p ?o }",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sparql_content_blocks_drop(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"DROP ALL",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sparql_content_proxies_select(client):
    fake = MagicMock()
    fake.status_code = 200
    fake.content = b'{"results":{"bindings":[]}}'
    fake.headers = {"content-type": "application/sparql-results+json"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { ?s ?p ?o } LIMIT 1",
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 200
    mock_http.post.assert_called_once()
    call_args = mock_http.post.call_args
    assert "/query" in call_args.args[0]


@pytest.mark.anyio
async def test_sparql_content_timeout_returns_504(client):
    import httpx

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { ?s ?p ?o }",
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_sparql_content_get_proxies_query_param(client):
    fake = MagicMock()
    fake.status_code = 200
    fake.content = b'{"results":{"bindings":[]}}'
    fake.headers = {"content-type": "application/sparql-results+json"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.get(
            "/api/v1/sparql/content",
            params={"query": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"},
        )

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_sparql_iri_fragment_does_not_bypass_guard(client):
    """An IRI containing a fragment (#) must not allow INSERT to evade the guard."""
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"SELECT * WHERE { <http://ex.org#foo> ?p ?o } INSERT DATA { <a> <b> <c> }",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sparql_upstream_error_code_forwarded(client):
    """HTTP error from Oxigraph (e.g. 400 bad syntax) must be relayed to caller."""
    fake = MagicMock()
    fake.status_code = 400
    fake.content = b"Parse error"
    fake.headers = {"content-type": "text/plain"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { BAD SYNTAX }",
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sparql_comment_does_not_trigger_guard(client):
    """A SPARQL comment containing 'INSERT' must not be blocked."""
    fake = MagicMock()
    fake.status_code = 200
    fake.content = b'{"results":{"bindings":[]}}'
    fake.headers = {"content-type": "application/sparql-results+json"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    query = b"# INSERT is mentioned in this comment\nSELECT * WHERE { ?s ?p ?o } LIMIT 1"
    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=query,
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 200
