"""Integration tests for OLS4-compat term hierarchy endpoints.

These tests exercise the 7 hierarchy routes:
  /parents, /children, /ancestors, /descendants,
  /hierarchicalParents, /hierarchicalAncestors, /hierarchicalDescendants

The ELK reasoning service is NOT available in tests; all inferred-path
fetchers fall back to asserted (via the Redis `parents` field) on any
exception.  The tests seed the `parents` field explicitly.
"""
import json
import uuid

import pytest
from httpx import AsyncClient

from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import _iri_key, _meta_key, _type_key


# ---------------------------------------------------------------------------
# Fixture: ontology + two-level hierarchy  (grandparent → parent → child)
# ---------------------------------------------------------------------------

@pytest.fixture()
async def hierarchy_sample(db_session, fake_redis):
    """
    Seed an ontology with a three-node class hierarchy:

        GrandParent ← Parent ← Child

    Entity hashes include a `parents` JSON array field so that the
    asserted-fallback path can resolve relationships without Oxigraph.
    """
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/hieronto-{uid}.owl",
        shortname=f"hieronto{uid}",
        title="Hierarchy Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"hieronto/test-{uid}.owl",
        sha256=f"hieronto_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)

    # Populate meta hash
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={
            "class_count": "3",
            "property_count": "0",
            "individual_count": "0",
            "schema_version": "v2",
            "indexed_at": "2025-01-01T00:00:00+00:00",
        },
    )

    gp_iri = "http://example.org/hieronto#GrandParent"
    p_iri  = "http://example.org/hieronto#Parent"
    c_iri  = "http://example.org/hieronto#Child"

    def _seed(iri: str, label: str, parents: list[str]):
        fake_redis.hset(
            _iri_key(vid, iri),
            mapping={
                "iri":           iri,
                "primary_label": label,
                "label":         label,
                "short":         label,
                "type":          "class",
                "source":        str(ont.id),
                "labels":        json.dumps([{"value": label, "lang": "en"}]),
                "synonyms":      json.dumps([]),
                "definitions":   json.dumps([]),
                "parents":       json.dumps(parents),
            },
        )
        fake_redis.sadd(_type_key(vid, "class"), iri)

    _seed(gp_iri, "GrandParent", [])
    _seed(p_iri,  "Parent",      [gp_iri])
    _seed(c_iri,  "Child",       [p_iri])

    yield {
        "ontology":    ont,
        "version_id":  vid,
        "gp_iri":      gp_iri,
        "parent_iri":  p_iri,
        "child_iri":   c_iri,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _enc(iri: str) -> str:
    return encode_iri_for_ols_path(iri)


# ---------------------------------------------------------------------------
# Test 1: /parents returns inferred (or asserted-fallback) parent
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_term_parents_returns_inferred_or_asserted(
    client: AsyncClient, hierarchy_sample
):
    """Child's /parents should include Parent (asserted fallback)."""
    onto_id = hierarchy_sample["ontology"].id
    c_iri   = hierarchy_sample["child_iri"]
    p_iri   = hierarchy_sample["parent_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(c_iri)}/parents"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    terms = body["_embedded"]["terms"]
    assert len(terms) >= 1
    iris = [t["iri"] for t in terms]
    assert p_iri in iris
    # Page metadata
    assert body["page"]["totalElements"] >= 1


# ---------------------------------------------------------------------------
# Test 2: /hierarchicalParents is asserted-only
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_term_hierarchical_parents_asserted_only(
    client: AsyncClient, hierarchy_sample
):
    """hierarchicalParents must return the direct asserted parent."""
    onto_id = hierarchy_sample["ontology"].id
    c_iri   = hierarchy_sample["child_iri"]
    p_iri   = hierarchy_sample["parent_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(c_iri)}/hierarchicalParents"
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    iris = [t["iri"] for t in terms]
    assert p_iri in iris
    # GrandParent must NOT appear (it's transitive, not direct)
    assert hierarchy_sample["gp_iri"] not in iris


# ---------------------------------------------------------------------------
# Test 3: /children returns direct children
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_term_children(client: AsyncClient, hierarchy_sample):
    """Parent's /children should include Child."""
    onto_id = hierarchy_sample["ontology"].id
    p_iri   = hierarchy_sample["parent_iri"]
    c_iri   = hierarchy_sample["child_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(p_iri)}/children"
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    iris = [t["iri"] for t in terms]
    assert c_iri in iris


# ---------------------------------------------------------------------------
# Test 4: /ancestors returns transitive ancestors
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_term_ancestors_transitive(client: AsyncClient, hierarchy_sample):
    """Child's /ancestors should include both Parent and GrandParent."""
    onto_id = hierarchy_sample["ontology"].id
    c_iri   = hierarchy_sample["child_iri"]
    p_iri   = hierarchy_sample["parent_iri"]
    gp_iri  = hierarchy_sample["gp_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(c_iri)}/ancestors"
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    iris = [t["iri"] for t in terms]
    assert p_iri  in iris, f"Expected parent in ancestors, got {iris}"
    assert gp_iri in iris, f"Expected grandparent in ancestors, got {iris}"


# ---------------------------------------------------------------------------
# Test 5: /descendants returns transitive descendants
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_term_descendants_transitive(client: AsyncClient, hierarchy_sample):
    """GrandParent's /descendants should include both Parent and Child."""
    onto_id = hierarchy_sample["ontology"].id
    gp_iri  = hierarchy_sample["gp_iri"]
    p_iri   = hierarchy_sample["parent_iri"]
    c_iri   = hierarchy_sample["child_iri"]

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(gp_iri)}/descendants"
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    iris = [t["iri"] for t in terms]
    assert p_iri in iris, f"Expected parent in descendants, got {iris}"
    assert c_iri in iris, f"Expected child in descendants, got {iris}"


# ---------------------------------------------------------------------------
# Test 6: unknown IRI in known ontology → empty paged list (not 404)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_hierarchy_unknown_iri_returns_empty(
    client: AsyncClient, hierarchy_sample
):
    """OLS4 behaviour: unknown term IRI → empty list, not 404."""
    onto_id    = hierarchy_sample["ontology"].id
    ghost_iri  = "http://example.org/hieronto#Ghost"

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(ghost_iri)}/parents"
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    assert terms == []
    assert body["page"]["totalElements"] == 0


# ---------------------------------------------------------------------------
# Test 7: pagination works on hierarchy results
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_hierarchy_paginated(client: AsyncClient, db_session, fake_redis):
    """Seed 5 children of one parent; request page=1&size=2 → 2 items."""
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/pagingonto-{uid}.owl",
        shortname=f"pagingonto{uid}",
        title="Paging Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"pagingonto/test-{uid}.owl",
        sha256=f"pagingonto_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={"class_count": "6", "property_count": "0",
                 "individual_count": "0", "schema_version": "v2",
                 "indexed_at": "2025-01-01T00:00:00+00:00"},
    )

    parent_iri = "http://example.org/pagingonto#Parent"
    child_iris = [f"http://example.org/pagingonto#Child{i}" for i in range(5)]

    # Seed parent
    fake_redis.hset(_iri_key(vid, parent_iri), mapping={
        "iri": parent_iri, "primary_label": "Parent", "label": "Parent",
        "short": "Parent", "type": "class", "source": str(ont.id),
        "labels": json.dumps([{"value": "Parent", "lang": "en"}]),
        "synonyms": json.dumps([]), "definitions": json.dumps([]),
        "parents": json.dumps([]),
    })
    fake_redis.sadd(_type_key(vid, "class"), parent_iri)

    # Seed 5 children
    for c in child_iris:
        fake_redis.hset(_iri_key(vid, c), mapping={
            "iri": c, "primary_label": c.split("#")[1],
            "label": c.split("#")[1], "short": c.split("#")[1],
            "type": "class", "source": str(ont.id),
            "labels": json.dumps([{"value": c.split("#")[1], "lang": "en"}]),
            "synonyms": json.dumps([]), "definitions": json.dumps([]),
            "parents": json.dumps([parent_iri]),
        })
        fake_redis.sadd(_type_key(vid, "class"), c)

    resp = await client.get(
        f"/ols/api/ontologies/{ont.id}/terms/{_enc(parent_iri)}/children",
        params={"page": "1", "size": "2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    terms = body["_embedded"]["terms"]
    assert len(terms) == 2
    assert body["page"]["totalElements"] == 5
    assert body["page"]["number"] == 1
    # next/prev links
    assert "prev" in body["_links"]


# ---------------------------------------------------------------------------
# Test 8: routing does NOT capture /parents segment into the IRI path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_routing_does_not_capture_segment_into_iri(
    client: AsyncClient, hierarchy_sample
):
    """
    /terms/{iri} must return a term-detail dict (has 'iri', 'label' keys at top level).
    /terms/{iri}/parents must return an HAL paged list (has '_embedded', 'page' keys).
    If route ordering is wrong, the /parents request would 404 with 'Term ...#Child/parents not found'.
    """
    onto_id = hierarchy_sample["ontology"].id
    c_iri   = hierarchy_sample["child_iri"]

    # Detail route
    detail_resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(c_iri)}"
    )
    assert detail_resp.status_code == 200
    detail_body = detail_resp.json()
    assert "iri" in detail_body
    assert detail_body["iri"] == c_iri

    # Hierarchy route
    parents_resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{_enc(c_iri)}/parents"
    )
    assert parents_resp.status_code == 200
    parents_body = parents_resp.json()
    assert "_embedded" in parents_body
    assert "page" in parents_body
    # Make sure this did NOT return a term-detail shape
    assert "iri" not in parents_body
