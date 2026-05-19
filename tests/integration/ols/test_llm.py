"""Integration tests for OLS4-compat LLM endpoints.

Covers:
  GET /ols/api/v2/llm_models
  GET /ols/api/v2/classes/llm_search?q=...
  GET /ols/api/v2/ontologies/{onto}/classes/llm_search?q=...
  GET /ols/api/v2/classes/{iri_path:path}/llm_similar?rows=...

The embedder pipeline (nomic-embed-text) is not available in the test
environment, so llm_search tests mock `semantic_search` at the import
site in the llm module.  llm_similar tests mock `db.execute` at the
AsyncSession level so that no pgvector SQL touches SQLite.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_semantic_result(iri: str, label: str, ontology_id: str) -> dict:
    return {
        "iri": iri,
        "label": label,
        "short": label.replace(" ", "_"),
        "type": "class",
        "source": ontology_id,
        "match_type": "semantic",
        "score": 0.95,
        "version_id": str(uuid.uuid4()),
        "ontology_id": ontology_id,
    }


# ---------------------------------------------------------------------------
# /v2/llm_models
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_llm_models_returns_static_list(client: AsyncClient, sample_ontology):
    """GET /v2/llm_models returns a v2-page with one model element."""
    resp = await client.get("/ols/api/v2/llm_models")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "page" in body
    assert len(body["elements"]) == 1
    model = body["elements"][0]
    assert model["id"] == "nomic-embed-text"
    assert model["modelName"] == "nomic-embed-text-v1"
    assert model["dimensions"] == 768
    assert body["page"]["totalElements"] == 1
    assert body["page"]["size"] == 1


# ---------------------------------------------------------------------------
# /v2/classes/llm_search
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_llm_search_global_mocked(client: AsyncClient, sample_ontology):
    """GET /v2/classes/llm_search?q=foo returns v2-shaped elements with a score field."""
    stub = [_make_semantic_result(
        "http://example.org/testonto#Foo", "Foo", str(sample_ontology.id)
    )]
    with patch("ontoexplorer.api.ols.llm.semantic_search", return_value=stub) as mock_ss:
        resp = await client.get("/ols/api/v2/classes/llm_search?q=foo")

    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "page" in body
    assert len(body["elements"]) == 1
    elem = body["elements"][0]
    assert elem["iri"] == "http://example.org/testonto#Foo"
    assert elem["label"] == "Foo"
    assert "score" in elem
    assert elem["score"] == 0.95
    assert "type" in elem
    assert "class" in elem["type"]
    mock_ss.assert_called_once()


@pytest.mark.anyio
async def test_llm_search_global_q_required(client: AsyncClient, sample_ontology):
    """GET /v2/classes/llm_search without q= returns 422."""
    resp = await client.get("/ols/api/v2/classes/llm_search")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_llm_search_global_returns_empty_on_no_results(client: AsyncClient, sample_ontology):
    """GET /v2/classes/llm_search?q=foo returns empty elements when semantic_search returns []."""
    with patch("ontoexplorer.api.ols.llm.semantic_search", return_value=[]):
        resp = await client.get("/ols/api/v2/classes/llm_search?q=nothing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["elements"] == []
    assert body["page"]["totalElements"] == 0


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/classes/llm_search
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_llm_search_scoped_to_ontology(client: AsyncClient, sample_ontology):
    """GET /v2/ontologies/{onto}/classes/llm_search scopes the call to a single version."""
    stub = [_make_semantic_result(
        "http://example.org/testonto#Bar", "Bar", str(sample_ontology.id)
    )]
    call_args_store = {}
    async def _capture(*args, **kwargs):
        call_args_store["version_ids"] = args[2] if len(args) > 2 else kwargs.get("version_ids")
        return stub

    with patch("ontoexplorer.api.ols.llm.semantic_search", side_effect=_capture):
        resp = await client.get(
            f"/ols/api/v2/ontologies/{sample_ontology.id}/classes/llm_search?q=bar"
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["elements"]) == 1
    # semantic_search must have been called with exactly one version id
    assert len(call_args_store["version_ids"]) == 1


@pytest.mark.anyio
async def test_llm_search_scoped_404_for_unknown_ontology(client: AsyncClient, sample_ontology):
    """GET /v2/ontologies/nonexistent/classes/llm_search?q=x returns 404."""
    resp = await client.get("/ols/api/v2/ontologies/nonexistent_xyz/classes/llm_search?q=test")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /v2/classes/{iri_path:path}/llm_similar
# ---------------------------------------------------------------------------

def _make_fake_execute(src_embedding, neighbours):
    """Return an AsyncMock for db.execute that:
    - First call (lookup): returns a mock whose .first() is (src_embedding,)
    - Second call (neighbours): returns a mock whose .all() is neighbours
    """
    first_result = MagicMock()
    first_result.first.return_value = (src_embedding,)

    second_result = MagicMock()
    second_result.all.return_value = neighbours

    execute_mock = AsyncMock(side_effect=[first_result, second_result])
    return execute_mock


@pytest.mark.anyio
async def test_llm_similar_no_embedding_404(client: AsyncClient, sample_ontology):
    """GET /v2/classes/{iri}/llm_similar returns 404 when no embedding is stored."""
    from urllib.parse import quote

    iri = "http://example.org/testonto#Foo"
    iri_path = quote(quote(iri, safe=""), safe="")

    first_result = MagicMock()
    first_result.first.return_value = None
    execute_mock = AsyncMock(return_value=first_result)

    with patch("ontoexplorer.api.ols.llm._db_execute", execute_mock):
        resp = await client.get(f"/ols/api/v2/classes/{iri_path}/llm_similar")

    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    assert iri in body["detail"]


@pytest.mark.anyio
async def test_llm_similar_excludes_self_and_returns_neighbours(
    client: AsyncClient, sample_ontology
):
    """GET /v2/classes/{iri}/llm_similar returns v2-shaped neighbours, excluding self."""
    from urllib.parse import quote

    iri = "http://example.org/testonto#Foo"
    iri_path = quote(quote(iri, safe=""), safe="")
    fake_embedding = [0.1] * 768

    # Build two neighbour rows with .iri, .ontology_id, .score attributes
    def _make_row(neighbour_iri, onto_id, score):
        row = MagicMock()
        row.iri = neighbour_iri
        row.ontology_id = onto_id
        row.score = score
        return row

    neighbours = [
        _make_row("http://example.org/testonto#Bar", str(sample_ontology.id), 0.92),
        _make_row("http://example.org/testonto#Baz", str(sample_ontology.id), 0.88),
    ]
    execute_mock = _make_fake_execute(fake_embedding, neighbours)

    with patch("ontoexplorer.api.ols.llm._db_execute", execute_mock):
        resp = await client.get(f"/ols/api/v2/classes/{iri_path}/llm_similar?rows=5")

    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert len(body["elements"]) == 2

    returned_iris = [e["iri"] for e in body["elements"]]
    assert iri not in returned_iris, "Self IRI must be excluded from results"
    assert "http://example.org/testonto#Bar" in returned_iris
    assert "http://example.org/testonto#Baz" in returned_iris

    # Each element has the required v2 shape fields
    for elem in body["elements"]:
        assert "iri" in elem
        assert "score" in elem
        assert "type" in elem
        assert "class" in elem["type"]
