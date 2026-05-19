"""Integration tests for the OLS4-compat v2 flat surface.

Covers /ols/api/v2/classes, /v2/properties, /v2/individuals, /v2/entities,
/v2/stats, and /v2/defined-fields.

All responses use the flat v2 envelope:
  {"elements": [...], "page": {...}, "facetFieldsToCounts": {}}
with no ``_links`` or ``_embedded`` keys.
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import (
    _iri_key,
    _meta_key,
    _prefix_key,
    _type_key,
    normalise_label,
)


# ---------------------------------------------------------------------------
# Additional fixture: seed class + property + individual in one ontology
# ---------------------------------------------------------------------------

@pytest.fixture()
async def v2_seed(db_session, sample_ontology, fake_redis):
    """Seed one class, one property, and one individual into the same version."""
    result = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == sample_ontology.id)
    )
    ver = result.scalar_one()
    vid = str(ver.id)
    onto_id = str(sample_ontology.id)

    class_iri  = "http://example.org/testonto#MyClass"
    prop_iri   = "http://example.org/testonto#myProperty"
    ind_iri    = "http://example.org/testonto#myIndividual"

    def _seed(iri: str, label: str, etype: str, extra: dict | None = None):
        mapping = {
            "iri":           iri,
            "primary_label": label,
            "label":         label,
            "short":         label,
            "type":          etype,
            "source":        onto_id,
            "labels":        json.dumps([{"value": label, "lang": "en"}]),
            "synonyms":      json.dumps([]),
            "definitions":   json.dumps([]),
            "parents":       json.dumps([]),
        }
        if extra:
            mapping.update(extra)
        fake_redis.hset(_iri_key(vid, iri), mapping=mapping)
        fake_redis.sadd(_type_key(vid, etype), iri)
        fake_redis.zadd(_prefix_key(vid), {f"{normalise_label(label)}|en|{etype}|{iri}": 0})

    _seed(class_iri, "MyClass",     "class")
    _seed(prop_iri,  "myProperty",  "object_property", {"parents": json.dumps([])})
    _seed(ind_iri,   "myIndividual","individual",
          {"types": json.dumps([class_iri])})

    yield {
        "class_iri":  class_iri,
        "prop_iri":   prop_iri,
        "ind_iri":    ind_iri,
        "ontology":   sample_ontology,
        "version_id": vid,
    }


# ---------------------------------------------------------------------------
# 1. test_v2_list_classes_flat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_list_classes_flat(client: AsyncClient, v2_seed):
    onto_id = str(v2_seed["ontology"].id)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/classes?page=0&size=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "page" in body
    assert "facetFieldsToCounts" in body
    # v2 must NOT have HAL keys
    assert "_links" not in body
    assert "_embedded" not in body
    assert len(body["elements"]) >= 1


# ---------------------------------------------------------------------------
# 2. test_v2_get_class_detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_get_class_detail(client: AsyncClient, v2_seed):
    onto_id   = str(v2_seed["ontology"].id)
    class_iri = v2_seed["class_iri"]
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(class_iri)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/classes/{encoded}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["iri"] == class_iri
    assert body["type"] == ["class", "entity"]
    assert "_links" not in body


# ---------------------------------------------------------------------------
# 3. test_v2_class_children_returns_v2_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_class_children_returns_v2_page(client: AsyncClient, v2_seed):
    """Children of a leaf class should return an empty v2 page (no Oxigraph)."""
    onto_id   = str(v2_seed["ontology"].id)
    class_iri = v2_seed["class_iri"]
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(class_iri)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/classes/{encoded}/children")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_embedded" not in body
    assert "_links" not in body
    assert body["page"]["totalElements"] == 0


# ---------------------------------------------------------------------------
# 4. test_v2_class_hierarchical_children_asserted_only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_class_hierarchical_children_asserted_only(client: AsyncClient, v2_seed, fake_redis):
    """Seed a parent→child relationship via the 'parents' Redis field and check
    that /hierarchicalChildren returns the child in a v2 page."""
    onto_id    = str(v2_seed["ontology"].id)
    parent_iri = v2_seed["class_iri"]
    vid        = v2_seed["version_id"]
    child_iri  = "http://example.org/testonto#ChildClass"

    # Seed the child pointing to our class as parent
    fake_redis.hset(
        _iri_key(vid, child_iri),
        mapping={
            "iri":           child_iri,
            "primary_label": "ChildClass",
            "label":         "ChildClass",
            "short":         "ChildClass",
            "type":          "class",
            "source":        str(v2_seed["ontology"].id),
            "labels":        json.dumps([{"value": "ChildClass", "lang": "en"}]),
            "synonyms":      json.dumps([]),
            "definitions":   json.dumps([]),
            "parents":       json.dumps([parent_iri]),
        },
    )
    fake_redis.sadd(_type_key(vid, "class"), child_iri)

    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(parent_iri)
    resp = await client.get(
        f"/ols/api/v2/ontologies/{onto_id}/classes/{encoded}/hierarchicalChildren"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_embedded" not in body
    iris = [e["iri"] for e in body["elements"]]
    assert child_iri in iris


# ---------------------------------------------------------------------------
# 5. test_v2_list_properties
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_list_properties(client: AsyncClient, v2_seed):
    onto_id = str(v2_seed["ontology"].id)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/properties")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_embedded" not in body
    assert len(body["elements"]) >= 1
    # Each element should have type containing "property"
    for el in body["elements"]:
        assert "property" in el["type"]


# ---------------------------------------------------------------------------
# 6. test_v2_get_property_detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_get_property_detail(client: AsyncClient, v2_seed):
    onto_id  = str(v2_seed["ontology"].id)
    prop_iri = v2_seed["prop_iri"]
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(prop_iri)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/properties/{encoded}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["iri"] == prop_iri
    assert "property" in body["type"]
    assert "_links" not in body


# ---------------------------------------------------------------------------
# 7. test_v2_list_individuals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_list_individuals(client: AsyncClient, v2_seed):
    onto_id = str(v2_seed["ontology"].id)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/individuals")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_embedded" not in body
    assert len(body["elements"]) >= 1
    for el in body["elements"]:
        assert "individual" in el["type"]


# ---------------------------------------------------------------------------
# 8. test_v2_get_individual_detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_get_individual_detail(client: AsyncClient, v2_seed):
    onto_id = str(v2_seed["ontology"].id)
    ind_iri = v2_seed["ind_iri"]
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(ind_iri)
    resp = await client.get(f"/ols/api/v2/ontologies/{onto_id}/individuals/{encoded}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["iri"] == ind_iri
    assert "individual" in body["type"]
    assert "_links" not in body


# ---------------------------------------------------------------------------
# 9. test_v2_entities_union
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_entities_union(client: AsyncClient, v2_seed):
    """?type=class returns only classes; no type filter returns all three entities."""
    onto_id = str(v2_seed["ontology"].id)

    # Filter by class only
    resp_class = await client.get(f"/ols/api/v2/ontologies/{onto_id}/entities?type=class")
    assert resp_class.status_code == 200
    body_class = resp_class.json()
    assert "elements" in body_class
    for el in body_class["elements"]:
        assert el["type"] == ["class", "entity"]

    # No filter — should return all
    resp_all = await client.get(f"/ols/api/v2/ontologies/{onto_id}/entities")
    assert resp_all.status_code == 200
    body_all = resp_all.json()
    assert body_all["page"]["totalElements"] >= 3


# ---------------------------------------------------------------------------
# 10. test_v2_stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_stats(client: AsyncClient, sample_ontology, fake_redis):
    """Stats aggregates class_count + property_count + individual_count from all versions."""
    resp = await client.get("/ols/api/v2/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "numberOfOntologies" in body
    assert "numberOfClasses"    in body
    assert "numberOfProperties" in body
    assert "numberOfIndividuals" in body
    # sample_ontology fixture seeds class_count=100, property_count=5, individual_count=0
    assert body["numberOfOntologies"] >= 1
    assert body["numberOfClasses"]    >= 100


# ---------------------------------------------------------------------------
# 11. test_v2_defined_fields_returns_static_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_defined_fields_returns_static_list(client: AsyncClient):
    resp = await client.get("/ols/api/v2/defined-fields")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert "iri" in body
    assert "label" in body


# ---------------------------------------------------------------------------
# 12. test_v2_class_individuals_returns_typed_individuals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_class_individuals_returns_typed_individuals(client: AsyncClient, v2_seed):
    """Individuals that are rdf:type of MyClass should appear under /classes/MyClass/individuals."""
    onto_id   = str(v2_seed["ontology"].id)
    class_iri = v2_seed["class_iri"]
    ind_iri   = v2_seed["ind_iri"]

    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(class_iri)
    resp = await client.get(
        f"/ols/api/v2/ontologies/{onto_id}/classes/{encoded}/individuals"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_embedded" not in body
    iris = [e["iri"] for e in body["elements"]]
    assert ind_iri in iris


# ---------------------------------------------------------------------------
# Bonus: relatedFrom returns empty v2 page (not 404 or 501)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_related_from_returns_empty_page(client: AsyncClient, v2_seed):
    onto_id   = str(v2_seed["ontology"].id)
    class_iri = v2_seed["class_iri"]
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    encoded = encode_iri_for_ols_path(class_iri)
    resp = await client.get(
        f"/ols/api/v2/ontologies/{onto_id}/entities/{encoded}/relatedFrom"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert body["elements"] == []


# ---------------------------------------------------------------------------
# Global list endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_global_classes_list(client: AsyncClient, v2_seed):
    resp = await client.get("/ols/api/v2/classes?page=0&size=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_links" not in body
    assert "_embedded" not in body


@pytest.mark.asyncio
async def test_v2_global_properties_list(client: AsyncClient, v2_seed):
    resp = await client.get("/ols/api/v2/properties?page=0&size=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_links" not in body


@pytest.mark.asyncio
async def test_v2_global_individuals_list(client: AsyncClient, v2_seed):
    resp = await client.get("/ols/api/v2/individuals?page=0&size=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_links" not in body
