"""Integration tests for OLS4-compat term endpoints."""

import pytest
from httpx import AsyncClient

from ontoexplorer.api.ols._iri import encode_iri_for_ols_path


# ---------------------------------------------------------------------------
# Test 1: paged list of terms returns seeded term in _embedded.terms
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_terms_hal_paged(client: AsyncClient, sample_term):
    ontology = sample_term["ontology"]
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/terms?page=0&size=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    assert "terms" in body["_embedded"]
    assert len(body["_embedded"]["terms"]) >= 1
    assert body["page"]["number"] == 0
    # Check seeded term is present
    iris = [t["iri"] for t in body["_embedded"]["terms"]]
    assert sample_term["iri"] in iris


# ---------------------------------------------------------------------------
# Test 2: unknown ontology → 404
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_terms_empty_for_unknown_ontology(client: AsyncClient):
    resp = await client.get("/ols/api/ontologies/nonexistent_xyz_123/terms")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 3: filter by IRI query param
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_terms_filter_by_iri(client: AsyncClient, sample_term):
    ontology = sample_term["ontology"]
    iri = sample_term["iri"]
    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/terms",
        params={"iri": iri},
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    assert len(terms) == 1
    assert terms[0]["iri"] == iri


# ---------------------------------------------------------------------------
# Test 4: double-encoded IRI in path returns term shape
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_term_detail(client: AsyncClient, sample_term):
    ontology = sample_term["ontology"]
    iri = sample_term["iri"]
    encoded = encode_iri_for_ols_path(iri)
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/terms/{encoded}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["iri"] == iri
    assert body["label"] == "Foo"
    assert body["ontology_name"] == ontology.shortname
    assert "_links" in body
    assert "self" in body["_links"]


# ---------------------------------------------------------------------------
# Test 5: unknown IRI in known ontology → 404
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_term_detail_404(client: AsyncClient, sample_term):
    ontology = sample_term["ontology"]
    unknown_iri = "http://example.org/testonto#NotExist"
    encoded = encode_iri_for_ols_path(unknown_iri)
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/terms/{encoded}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 6: roots endpoint returns term marked is_root=True
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_terms_roots(client: AsyncClient, sample_term):
    ontology = sample_term["ontology"]
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/terms/roots")
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    terms = body["_embedded"]["terms"]
    assert len(terms) >= 1
    # All returned terms must be marked is_root
    for t in terms:
        assert t["is_root"] is True
    # Our seeded term should be in the list
    iris = [t["iri"] for t in terms]
    assert sample_term["iri"] in iris


# ---------------------------------------------------------------------------
# Test 7: global /terms?iri=... returns matching term
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_global_term_lookup(client: AsyncClient, sample_term):
    iri = sample_term["iri"]
    resp = await client.get("/ols/api/terms", params={"iri": iri})
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    assert len(terms) >= 1
    assert any(t["iri"] == iri for t in terms)


# ---------------------------------------------------------------------------
# Test 8: findByIdAndIsDefiningOntology filters to source-match hits
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_find_by_id_defining_ontology(client: AsyncClient, sample_term):
    iri = sample_term["iri"]
    resp = await client.get(
        "/ols/api/terms/findByIdAndIsDefiningOntology",
        params={"iri": iri},
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    # The seeded term has source == ontology.id (set in fixture) so it must appear
    assert len(terms) >= 1
    assert any(t["iri"] == iri for t in terms)
    # All returned terms must be the defining ontology
    for t in terms:
        assert t["is_defining_ontology"] is True
