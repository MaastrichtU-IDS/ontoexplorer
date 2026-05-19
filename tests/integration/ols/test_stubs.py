"""Integration tests for OLS4-compat Tier 3 stub endpoints.

All stub endpoints return 501 Not Implemented with:
    {"error": "not_implemented", "message": "…", "ols_path": "<path>"}

This test module verifies that all 9 stub surfaces are reachable and
return the expected 501 shape.
"""
import pytest
from httpx import AsyncClient


def _assert_stub_response(body: dict, path: str) -> None:
    """Assert that body has the stub 501 shape."""
    assert body["error"] == "not_implemented", f"Expected error='not_implemented', got {body}"
    assert "message" in body, f"Missing message in {body}"
    assert isinstance(body["message"], str), f"message should be string, got {body}"
    assert len(body["message"]) > 0, "message should not be empty"
    assert body["ols_path"] == path, f"Expected path={path}, got {body['ols_path']}"


# ---------------------------------------------------------------------------
# Tag text (text annotation / NER)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tag_text_get_returns_501(client: AsyncClient):
    """GET /api/v2/tag_text returns 501 with stub shape."""
    resp = await client.get("/ols/api/v2/tag_text")
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(body, "/ols/api/v2/tag_text")
    assert "annotation" in body["message"].lower() or "ner" in body["message"].lower()


@pytest.mark.anyio
async def test_tag_text_post_returns_501(client: AsyncClient):
    """POST /api/v2/tag_text returns 501 with stub shape."""
    resp = await client.post("/ols/api/v2/tag_text", json={"text": "example"})
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(body, "/ols/api/v2/tag_text")
    assert "annotation" in body["message"].lower() or "ner" in body["message"].lower()


# ---------------------------------------------------------------------------
# Curation sources (SSSOM mappings)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_curation_sources_returns_501(client: AsyncClient):
    """GET /api/v2/curation_sources returns 501 with stub shape."""
    resp = await client.get("/ols/api/v2/curation_sources")
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(body, "/ols/api/v2/curation_sources")
    assert "sssom" in body["message"].lower() or "mapping" in body["message"].lower()


# ---------------------------------------------------------------------------
# Ontology grouping (by-tag, by-domain)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ontologies_by_tag_returns_501(client: AsyncClient):
    """GET /api/v2/ontologies/by-tag returns 501 with stub shape."""
    resp = await client.get("/ols/api/v2/ontologies/by-tag")
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(body, "/ols/api/v2/ontologies/by-tag")
    assert "tag" in body["message"].lower()


@pytest.mark.anyio
async def test_ontologies_by_domain_returns_501(client: AsyncClient):
    """GET /api/v2/ontologies/by-domain returns 501 with stub shape."""
    resp = await client.get("/ols/api/v2/ontologies/by-domain")
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(body, "/ols/api/v2/ontologies/by-domain")
    assert "domain" in body["message"].lower()


# ---------------------------------------------------------------------------
# Term curation (preferred roots)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_preferred_roots_returns_501(client: AsyncClient, sample_ontology):
    """GET /api/ontologies/{onto}/terms/preferredRoots returns 501."""
    resp = await client.get(
        f"/ols/api/ontologies/{sample_ontology.id}/terms/preferredRoots"
    )
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(
        body, f"/ols/api/ontologies/{sample_ontology.id}/terms/preferredRoots"
    )
    assert "preferred" in body["message"].lower() and "root" in body["message"].lower()


# ---------------------------------------------------------------------------
# LLM embedding write surfaces
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_class_embedding_write_global_returns_501(client: AsyncClient):
    """POST /api/v2/classes/llm_embedding returns 501."""
    resp = await client.post(
        "/ols/api/v2/classes/llm_embedding",
        json={"iri": "http://example.org/test", "embedding": [0.1, 0.2]},
    )
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(body, "/ols/api/v2/classes/llm_embedding")
    assert "write" in body["message"].lower() or "embedding" in body["message"].lower()


@pytest.mark.anyio
async def test_class_embedding_write_scoped_returns_501(
    client: AsyncClient, sample_ontology
):
    """POST /api/v2/ontologies/{onto}/classes/llm_embedding returns 501."""
    resp = await client.post(
        f"/ols/api/v2/ontologies/{sample_ontology.id}/classes/llm_embedding",
        json={"iri": "http://example.org/test", "embedding": [0.1, 0.2]},
    )
    assert resp.status_code == 501
    body = resp.json()
    _assert_stub_response(
        body, f"/ols/api/v2/ontologies/{sample_ontology.id}/classes/llm_embedding"
    )
    assert "write" in body["message"].lower() or "embedding" in body["message"].lower()


# ---------------------------------------------------------------------------
# LLM embedding read surfaces
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_class_embedding_read_returns_501(client: AsyncClient):
    """GET /api/v2/classes/{iri}/llm_embedding returns 501."""
    # Use a double-encoded IRI in the path
    iri_encoded = "http%253A%252F%252Fexample.org%252Ftest"
    resp = await client.get(f"/ols/api/v2/classes/{iri_encoded}/llm_embedding")
    assert resp.status_code == 501
    body = resp.json()
    # The path in ols_path should reflect the actual request path
    assert body["error"] == "not_implemented"
    assert "embedding" in body["message"].lower()
    assert "bandwidth" in body["message"].lower()


@pytest.mark.anyio
async def test_llm_similarity_pair_returns_501(client: AsyncClient):
    """GET /api/v2/classes/{c1}/llm_similarity/{c2} returns 501."""
    # Use double-encoded IRIs
    iri1_encoded = "http%253A%252F%252Fexample.org%252Fclass1"
    iri2_encoded = "http%253A%252F%252Fexample.org%252Fclass2"
    resp = await client.get(
        f"/ols/api/v2/classes/{iri1_encoded}/llm_similarity/{iri2_encoded}"
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"] == "not_implemented"
    assert "similarity" in body["message"].lower()
    # Should suggest using llm_similar instead
    assert "llm_similar" in body["message"].lower()
