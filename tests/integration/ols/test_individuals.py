"""Integration tests for OLS4-compat individuals endpoints.

Mirrors the structure of test_properties.py scoped to the /individuals surface.
Individuals have no hierarchy (no parents/children), but DO have a /types
endpoint returning the classes the individual is rdf:type of.
"""
import pytest
from httpx import AsyncClient

from ontoexplorer.api.ols._iri import encode_iri_for_ols_path


def _enc(iri: str) -> str:
    return encode_iri_for_ols_path(iri)


# ---------------------------------------------------------------------------
# Test 1: paged list within an ontology
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_individuals_paged(client: AsyncClient, sample_individual):
    """GET /ontologies/{onto}/individuals returns the seeded individual."""
    ontology = sample_individual["ontology"]
    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/individuals?page=0&size=20"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body, f"No _embedded in body: {body}"
    assert "individuals" in body["_embedded"]
    inds = body["_embedded"]["individuals"]
    returned_iris = [i["iri"] for i in inds]
    assert sample_individual["ind_iri"] in returned_iris, (
        f"individual IRI not in {returned_iris}"
    )
    assert body["page"]["totalElements"] >= 1


# ---------------------------------------------------------------------------
# Test 2: detail by double-encoded IRI in path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_individual_detail(client: AsyncClient, sample_individual):
    """GET /ontologies/{onto}/individuals/{iri} returns individual shape."""
    ontology = sample_individual["ontology"]
    iri = sample_individual["ind_iri"]
    encoded = _enc(iri)
    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/individuals/{encoded}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["iri"] == iri
    assert body["label"] == "Alice"
    assert body["ontology_name"] == ontology.shortname
    assert "_links" in body
    assert "self" in body["_links"]


# ---------------------------------------------------------------------------
# Test 3: unknown individual IRI → 404
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_individual_detail_404(client: AsyncClient, sample_individual):
    """GET /individuals/{unknown_iri} must return 404."""
    ontology = sample_individual["ontology"]
    ghost_iri = "http://example.org/onto#nonexistentIndividual"
    encoded = _enc(ghost_iri)
    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/individuals/{encoded}"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 4: _links.self.href contains /individuals/ not /terms/
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_individual_links_self_url_is_individuals_not_terms(
    client: AsyncClient, sample_individual
):
    """The _links.self.href must contain /individuals/, never /terms/."""
    ontology = sample_individual["ontology"]
    iri = sample_individual["ind_iri"]
    encoded = _enc(iri)
    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/individuals/{encoded}"
    )
    assert resp.status_code == 200
    body = resp.json()
    self_href = body["_links"]["self"]["href"]
    assert "/individuals/" in self_href, (
        f"Expected /individuals/ in href, got: {self_href}"
    )
    assert "/terms/" not in self_href, (
        f"Expected no /terms/ in href for individual, got: {self_href}"
    )


# ---------------------------------------------------------------------------
# Test 5: /types returns the class the individual is rdf:type of
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_individual_types(client: AsyncClient, sample_individual):
    """GET /ontologies/{onto}/individuals/{iri}/types returns rdf:type classes."""
    ontology = sample_individual["ontology"]
    iri = sample_individual["ind_iri"]
    class_iri = sample_individual["class_iri"]
    encoded = _enc(iri)

    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/individuals/{encoded}/types"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body, f"No _embedded in body: {body}"
    assert "terms" in body["_embedded"], (
        f"Expected 'terms' embedded key, got: {list(body['_embedded'].keys())}"
    )
    terms = body["_embedded"]["terms"]
    assert len(terms) >= 1
    returned_iris = [t["iri"] for t in terms]
    assert class_iri in returned_iris, (
        f"class IRI {class_iri} not in {returned_iris}"
    )
    # The class shape should have the seeded label
    cls_shape = next(t for t in terms if t["iri"] == class_iri)
    assert cls_shape["label"] == "Person"


# ---------------------------------------------------------------------------
# Test 6: /types for unknown individual → 404
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_individual_types_404(client: AsyncClient, sample_individual):
    """GET /individuals/{unknown_iri}/types returns 404 when individual is absent."""
    ontology = sample_individual["ontology"]
    ghost_iri = "http://example.org/onto#noSuchIndividual"
    encoded = _enc(ghost_iri)
    resp = await client.get(
        f"/ols/api/ontologies/{ontology.id}/individuals/{encoded}/types"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 7: global /individuals?iri=... lookup
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_global_individual_lookup(client: AsyncClient, sample_individual):
    """GET /ols/api/individuals?iri=... returns matching individual across all ontologies."""
    iri = sample_individual["ind_iri"]
    resp = await client.get("/ols/api/individuals", params={"iri": iri})
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    inds = body["_embedded"]["individuals"]
    assert len(inds) >= 1
    assert any(i["iri"] == iri for i in inds)
