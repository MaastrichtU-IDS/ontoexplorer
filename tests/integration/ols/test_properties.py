"""Integration tests for OLS4-compat properties endpoints.

Mirrors the structure of test_terms.py and test_terms_hierarchy.py,
but scoped to the /properties surface and property entity types
(object_property, data_property, annotation_property).
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import _iri_key, _meta_key, _type_key


def _enc(iri: str) -> str:
    return encode_iri_for_ols_path(iri)


# ---------------------------------------------------------------------------
# Test 1: list all properties — union of all three property types
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_properties_includes_all_three_types(
    client: AsyncClient, sample_property
):
    """GET /properties should return all object_property + data_property + annotation_property."""
    ontology = sample_property["ontology"]
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/properties?page=0&size=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    assert "properties" in body["_embedded"]
    props = body["_embedded"]["properties"]
    returned_iris = [p["iri"] for p in props]

    # All three seeded property types must appear
    assert sample_property["obj_iri"] in returned_iris, (
        f"object_property {sample_property['obj_iri']} not in {returned_iris}"
    )
    assert sample_property["data_iri"] in returned_iris, (
        f"data_property {sample_property['data_iri']} not in {returned_iris}"
    )
    assert sample_property["ann_iri"] in returned_iris, (
        f"annotation_property {sample_property['ann_iri']} not in {returned_iris}"
    )
    # Total count must be 3
    assert body["page"]["totalElements"] == 3


# ---------------------------------------------------------------------------
# Test 2: detail by double-encoded IRI in path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_property_detail_double_encoded_iri(
    client: AsyncClient, sample_property
):
    """GET /ontologies/{onto}/properties/{iri} returns property shape."""
    ontology = sample_property["ontology"]
    iri = sample_property["obj_iri"]
    encoded = _enc(iri)
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/properties/{encoded}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["iri"] == iri
    assert body["label"] == "hasRelation"
    assert body["ontology_name"] == ontology.id
    assert "_links" in body
    assert "self" in body["_links"]


# ---------------------------------------------------------------------------
# Test 3: unknown property IRI → 404
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_property_detail_404(client: AsyncClient, sample_property):
    """GET /properties/{unknown_iri} must return 404."""
    ontology = sample_property["ontology"]
    ghost_iri = "http://example.org/onto#nonexistentProp"
    encoded = _enc(ghost_iri)
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/properties/{encoded}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 4: _links.self.href contains /properties/ not /terms/
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_links_self_url_is_properties_not_terms(
    client: AsyncClient, sample_property
):
    """The _links.self.href must contain /properties/, never /terms/."""
    ontology = sample_property["ontology"]
    iri = sample_property["obj_iri"]
    encoded = _enc(iri)
    resp = await client.get(f"/ols/api/ontologies/{ontology.id}/properties/{encoded}")
    assert resp.status_code == 200
    body = resp.json()
    self_href = body["_links"]["self"]["href"]
    assert "/properties/" in self_href, f"Expected /properties/ in href, got: {self_href}"
    assert "/terms/" not in self_href, f"Expected no /terms/ in href for property, got: {self_href}"


# ---------------------------------------------------------------------------
# Test 5: /parents returns asserted parent property (via Redis parents field)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_parents_asserted(client: AsyncClient, property_hierarchy):
    """GET /properties/{iri}/parents returns seeded parent property."""
    onto_id = property_hierarchy["ontology"].id
    child_iri = property_hierarchy["child_iri"]
    parent_iri = property_hierarchy["parent_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/properties/{_enc(child_iri)}/parents"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    props = body["_embedded"]["properties"]
    assert len(props) >= 1
    returned_iris = [p["iri"] for p in props]
    assert parent_iri in returned_iris


# ---------------------------------------------------------------------------
# Test 6: /children returns direct children
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_children(client: AsyncClient, property_hierarchy):
    """GET /properties/{iri}/children returns direct child properties."""
    onto_id = property_hierarchy["ontology"].id
    parent_iri = property_hierarchy["parent_iri"]
    child_iri = property_hierarchy["child_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/properties/{_enc(parent_iri)}/children"
    )
    assert resp.status_code == 200
    body = resp.json()
    props = body["_embedded"]["properties"]
    returned_iris = [p["iri"] for p in props]
    assert child_iri in returned_iris


# ---------------------------------------------------------------------------
# Test 7: global /properties?iri=... lookup
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_global_lookup(client: AsyncClient, sample_property):
    """GET /ols/api/properties?iri=... returns matching property across all ontologies."""
    iri = sample_property["obj_iri"]
    resp = await client.get("/ols/api/properties", params={"iri": iri})
    assert resp.status_code == 200
    body = resp.json()
    props = body["_embedded"]["properties"]
    assert len(props) >= 1
    assert any(p["iri"] == iri for p in props)


# ---------------------------------------------------------------------------
# Test 8: findByIdAndIsDefiningOntology — query-param form
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_find_by_id_defining_ontology(client: AsyncClient, sample_property):
    """GET /ols/api/properties/findByIdAndIsDefiningOntology?iri=... returns only defining-ontology hits."""
    iri = sample_property["obj_iri"]
    resp = await client.get(
        "/ols/api/properties/findByIdAndIsDefiningOntology",
        params={"iri": iri},
    )
    assert resp.status_code == 200
    body = resp.json()
    props = body["_embedded"]["properties"]
    assert len(props) >= 1
    assert any(p["iri"] == iri for p in props)
    for p in props:
        assert p["is_defining_ontology"] is True


# ---------------------------------------------------------------------------
# Test 9: route ordering — /properties/findByIdAndIsDefiningOntology must not
#         be captured as an IRI path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_route_ordering_find_by_id_not_captured_as_iri(
    client: AsyncClient, sample_property
):
    """
    The findByIdAndIsDefiningOntology path must not be treated as a double-encoded
    IRI.  A wrong route order would decode 'findByIdAndIsDefiningOntology' as an IRI
    and return 404 (no such entity in Redis).
    """
    iri = sample_property["obj_iri"]
    resp = await client.get(
        "/ols/api/properties/findByIdAndIsDefiningOntology",
        params={"iri": iri},
    )
    # Must succeed, not 404
    assert resp.status_code == 200
    body = resp.json()
    # Response is a HAL page (not a single property detail dict)
    assert "_embedded" in body
    assert "page" in body


# ---------------------------------------------------------------------------
# Test 10: /ancestors and /descendants are transitive
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_property_ancestors_transitive(client: AsyncClient, property_hierarchy):
    """Child /ancestors includes both parent and grandparent."""
    onto_id = property_hierarchy["ontology"].id
    child_iri = property_hierarchy["child_iri"]
    parent_iri = property_hierarchy["parent_iri"]
    gp_iri = property_hierarchy["gp_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/properties/{_enc(child_iri)}/ancestors"
    )
    assert resp.status_code == 200
    body = resp.json()
    iris = [p["iri"] for p in body["_embedded"]["properties"]]
    assert parent_iri in iris
    assert gp_iri in iris


@pytest.mark.anyio
async def test_property_descendants_transitive(client: AsyncClient, property_hierarchy):
    """Grandparent /descendants includes both parent and child."""
    onto_id = property_hierarchy["ontology"].id
    gp_iri = property_hierarchy["gp_iri"]
    parent_iri = property_hierarchy["parent_iri"]
    child_iri = property_hierarchy["child_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/properties/{_enc(gp_iri)}/descendants"
    )
    assert resp.status_code == 200
    body = resp.json()
    iris = [p["iri"] for p in body["_embedded"]["properties"]]
    assert parent_iri in iris
    assert child_iri in iris
