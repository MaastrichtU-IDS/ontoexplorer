"""Integration tests for OLS4-compat Solr-style search endpoints.

Covers /ols/api/search, /ols/api/select, and /ols/api/suggest.

All tests use the shared fake-Redis fixture from conftest.py.  The search
routes call entity_lookup (for /search) and get_completions (for /select and
/suggest), both of which read from the fake Redis populated by the fixtures.
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
# Helpers
# ---------------------------------------------------------------------------

def _assert_solr_shape(body: dict) -> None:
    """Assert that `body` has the top-level Solr envelope keys."""
    assert "responseHeader" in body, f"Missing responseHeader: {body}"
    assert "response" in body, f"Missing response: {body}"
    assert "facet_counts" in body, f"Missing facet_counts: {body}"
    assert "highlighting" in body, f"Missing highlighting: {body}"
    assert "status" in body["responseHeader"]
    assert "QTime" in body["responseHeader"]
    assert "numFound" in body["response"]
    assert "start" in body["response"]
    assert "docs" in body["response"]


# ---------------------------------------------------------------------------
# /api/search tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_search_returns_solr_shape(client: AsyncClient, sample_term):
    """GET /search?q=Foo returns the Solr envelope shape with numFound >= 1."""
    resp = await client.get("/ols/api/search?q=Foo")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    assert body["response"]["numFound"] >= 1, f"Expected hits for 'Foo', got: {body}"
    docs = body["response"]["docs"]
    assert len(docs) >= 1
    # Verify doc shape
    doc = docs[0]
    assert "iri" in doc
    assert "label" in doc
    assert "ontology_name" in doc
    assert "type" in doc
    assert "is_defining_ontology" in doc


@pytest.mark.anyio
async def test_search_filter_by_ontology(client: AsyncClient, sample_term):
    """ontology=<id> restricts results to that ontology; nonexistent ontology returns 0."""
    ontology = sample_term["ontology"]

    # Known ontology should return results
    resp = await client.get(f"/ols/api/search?q=Foo&ontology={ontology.id}")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    assert body["response"]["numFound"] >= 1

    # Nonexistent ontology should return 0
    resp2 = await client.get("/ols/api/search?q=Foo&ontology=nonexistent_onto_xyz")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["response"]["numFound"] == 0
    assert body2["response"]["docs"] == []


@pytest.mark.anyio
async def test_search_filter_by_type_class(client: AsyncClient, sample_term, sample_property):
    """type=class returns only class entities."""
    # Both sample_term (class "Foo") and sample_property (properties) are in same ontology
    resp = await client.get("/ols/api/search?q=Foo&type=class")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    # All returned docs must be of type "class"
    for doc in body["response"]["docs"]:
        assert doc["type"] == "class", f"Expected class, got {doc['type']} for {doc['iri']}"


@pytest.mark.anyio
async def test_search_filter_by_type_property(client: AsyncClient, sample_property):
    """type=property returns only property entities."""
    resp = await client.get("/ols/api/search?q=has&type=property")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    # All returned docs must be type "property"
    for doc in body["response"]["docs"]:
        assert doc["type"] == "property", f"Expected property, got {doc['type']} for {doc['iri']}"
    assert body["response"]["numFound"] >= 1, "Expected at least one property hit for 'has'"


@pytest.mark.anyio
async def test_search_group_field_iri_dedups(
    client: AsyncClient, db_session, fake_redis, sample_term
):
    """groupField=iri deduplicates results with the same IRI across two versions."""
    # Create a second version of the same ontology with the same entity
    ontology = sample_term["ontology"]
    iri = sample_term["iri"]

    ver2 = OntologyVersion(
        ontology_id=ontology.id,
        minio_key=f"testonto/test-v2-{uuid.uuid4().hex[:8]}.owl",
        sha256=f"testonto_sha256_v2_{uuid.uuid4().hex[:8]}",
        format="owl",
        status="ready",
        version_iri="2025-02-01",
    )
    db_session.add(ver2)
    await db_session.commit()

    vid2 = str(ver2.id)
    # Seed the same IRI in the second version
    fake_redis.hset(
        _meta_key(ver2.id),
        mapping={"class_count": "1", "property_count": "0", "individual_count": "0",
                 "schema_version": "v2", "indexed_at": "2025-02-01T00:00:00+00:00"},
    )
    fake_redis.hset(
        _iri_key(vid2, iri),
        mapping={
            "iri": iri, "primary_label": "Foo", "label": "Foo",
            "short": "Foo", "type": "class", "source": str(ontology.id),
            "labels": json.dumps([{"value": "Foo", "lang": "en"}]),
            "synonyms": json.dumps([]), "definitions": json.dumps([]),
        },
    )
    fake_redis.sadd(_type_key(vid2, "class"), iri)
    fake_redis.zadd(_prefix_key(vid2), {f"{normalise_label('Foo')}|en|class|{iri}": 0})

    # Without dedup: might see the IRI twice (from two versions of the SAME ontology)
    # Note: latest_ready_versions only returns ONE version per ontology (the most recent),
    # so this tests dedup when versions are artificially the same ontology queried.
    # With groupField=iri: should never see the same IRI twice in docs
    resp = await client.get("/ols/api/search?q=Foo&groupField=iri")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    returned_iris = [d["iri"] for d in body["response"]["docs"]]
    assert len(returned_iris) == len(set(returned_iris)), (
        f"Duplicate IRIs found in docs: {returned_iris}"
    )


@pytest.mark.anyio
async def test_search_paginates(client: AsyncClient, db_session, fake_redis):
    """rows=2&start=2 returns exactly 2 docs from offset 2 of 5 seeded entities."""
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/paginateonto-{uid}.owl",
        shortname=f"paginateonto{uid}",
        title="Pagination Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"paginateonto/test-{uid}.owl",
        sha256=f"paginate_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={"class_count": "5", "property_count": "0", "individual_count": "0",
                 "schema_version": "v2", "indexed_at": "2025-01-01T00:00:00+00:00"},
    )

    # Seed 5 entities with labels "Alpha", "Alphaone", "Alphatwo", "Alphathree", "Alphafour"
    labels = ["Alpha", "Alphaone", "Alphatwo", "Alphathree", "Alphafour"]
    for label in labels:
        iri = f"http://example.org/paginateonto#{label}"
        fake_redis.hset(
            _iri_key(vid, iri),
            mapping={
                "iri": iri, "primary_label": label, "label": label,
                "short": label, "type": "class", "source": str(ont.id),
                "labels": json.dumps([{"value": label, "lang": "en"}]),
                "synonyms": json.dumps([]), "definitions": json.dumps([]),
            },
        )
        fake_redis.sadd(_type_key(vid, "class"), iri)
        fake_redis.zadd(
            _prefix_key(vid),
            {f"{normalise_label(label)}|en|class|{iri}": 0},
        )

    resp = await client.get(
        f"/ols/api/search?q=alpha&ontology={ont.id}&rows=2&start=2"
    )
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    assert body["response"]["numFound"] == 5, (
        f"Expected numFound=5, got {body['response']['numFound']}"
    )
    assert body["response"]["start"] == 2
    assert len(body["response"]["docs"]) == 2, (
        f"Expected 2 docs in slice, got {len(body['response']['docs'])}"
    )


@pytest.mark.anyio
async def test_search_local_filter(client: AsyncClient, db_session, fake_redis):
    """local=true excludes entities whose source differs from their host ontology."""
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/localonto-{uid}.owl",
        shortname=f"localonto{uid}",
        title="Local Filter Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"localonto/test-{uid}.owl",
        sha256=f"local_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={"class_count": "2", "property_count": "0", "individual_count": "0",
                 "schema_version": "v2", "indexed_at": "2025-01-01T00:00:00+00:00"},
    )

    local_iri = f"http://example.org/localonto#{uid}#LocalTerm"
    imported_iri = f"http://example.org/externalonto#ImportedTerm"

    # Seed a local entity (source == ontology.id)
    fake_redis.hset(
        _iri_key(vid, local_iri),
        mapping={
            "iri": local_iri, "primary_label": "LocalTerm", "label": "LocalTerm",
            "short": "LocalTerm", "type": "class", "source": str(ont.id),
            "labels": json.dumps([{"value": "LocalTerm", "lang": "en"}]),
            "synonyms": json.dumps([]), "definitions": json.dumps([]),
        },
    )
    fake_redis.sadd(_type_key(vid, "class"), local_iri)
    fake_redis.zadd(_prefix_key(vid), {f"{normalise_label('LocalTerm')}|en|class|{local_iri}": 0})

    # Seed an imported entity (source == some other ontology)
    fake_redis.hset(
        _iri_key(vid, imported_iri),
        mapping={
            "iri": imported_iri, "primary_label": "ImportedTerm", "label": "ImportedTerm",
            "short": "ImportedTerm", "type": "class", "source": "externalonto",
            "labels": json.dumps([{"value": "ImportedTerm", "lang": "en"}]),
            "synonyms": json.dumps([]), "definitions": json.dumps([]),
        },
    )
    fake_redis.sadd(_type_key(vid, "class"), imported_iri)
    fake_redis.zadd(
        _prefix_key(vid),
        {f"{normalise_label('ImportedTerm')}|en|class|{imported_iri}": 0},
    )

    # Without local filter: LocalTerm appears (search by its label prefix)
    resp_local_term = await client.get(f"/ols/api/search?q=Local&ontology={ont.id}")
    assert resp_local_term.status_code == 200
    body_local_term = resp_local_term.json()
    assert local_iri in {d["iri"] for d in body_local_term["response"]["docs"]}, (
        "LocalTerm should appear without local filter"
    )

    # ImportedTerm appears (search by its label prefix)
    resp_imported = await client.get(f"/ols/api/search?q=Import&ontology={ont.id}")
    assert resp_imported.status_code == 200
    body_imported = resp_imported.json()
    assert imported_iri in {d["iri"] for d in body_imported["response"]["docs"]}, (
        "ImportedTerm should appear without local filter"
    )

    # With local=true: LocalTerm still appears (it is the defining entity)
    resp_local_filtered = await client.get(f"/ols/api/search?q=Local&ontology={ont.id}&local=true")
    assert resp_local_filtered.status_code == 200
    body_filtered = resp_local_filtered.json()
    assert local_iri in {d["iri"] for d in body_filtered["response"]["docs"]}, (
        "LocalTerm should appear with local=true"
    )

    # With local=true: ImportedTerm is excluded
    resp_imp_local = await client.get(f"/ols/api/search?q=Import&ontology={ont.id}&local=true")
    assert resp_imp_local.status_code == 200
    body_imp_local = resp_imp_local.json()
    assert imported_iri not in {d["iri"] for d in body_imp_local["response"]["docs"]}, (
        "ImportedTerm should NOT appear with local=true"
    )


# ---------------------------------------------------------------------------
# /api/select tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_select_returns_solr_shape(client: AsyncClient, sample_term):
    """GET /select?q=Foo returns a Solr envelope with prefix-match results."""
    resp = await client.get("/ols/api/select?q=Foo")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    # Autocomplete for "Foo" should find the seeded "Foo" class
    assert body["response"]["numFound"] >= 1, (
        f"Expected at least one completion for 'Foo', got numFound={body['response']['numFound']}"
    )
    docs = body["response"]["docs"]
    assert len(docs) >= 1
    # Each doc should have at minimum: label
    doc = docs[0]
    assert "label" in doc


@pytest.mark.anyio
async def test_select_ontology_filter(client: AsyncClient, sample_term):
    """GET /select?q=Foo&ontology=<id> restricts to given ontology."""
    ontology = sample_term["ontology"]
    resp = await client.get(f"/ols/api/select?q=Foo&ontology={ontology.id}")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    assert body["response"]["numFound"] >= 1

    resp2 = await client.get("/ols/api/select?q=Foo&ontology=nonexistent_xyz")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["response"]["numFound"] == 0


# ---------------------------------------------------------------------------
# /api/suggest tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_suggest_returns_label_only(client: AsyncClient, sample_term):
    """GET /suggest?q=Foo returns lightweight autosuggest docs with only the label."""
    resp = await client.get("/ols/api/suggest?q=Foo")
    assert resp.status_code == 200
    body = resp.json()
    _assert_solr_shape(body)
    assert body["response"]["numFound"] >= 1, (
        f"Expected at least one suggestion for 'Foo', got: {body}"
    )
    docs = body["response"]["docs"]
    assert len(docs) >= 1
    # Each doc in suggest should only have the "autosuggest" key
    for doc in docs:
        assert "autosuggest" in doc, f"Expected 'autosuggest' key in doc: {doc}"
        assert isinstance(doc["autosuggest"], str)


@pytest.mark.anyio
async def test_suggest_ontology_filter(client: AsyncClient, sample_term):
    """GET /suggest?q=Foo&ontology=nonexistent returns 0 results."""
    resp = await client.get("/ols/api/suggest?q=Foo&ontology=nonexistent_xyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"]["numFound"] == 0
    assert body["response"]["docs"] == []


@pytest.mark.anyio
async def test_search_q_required(client: AsyncClient, sample_term):
    """GET /search without q= returns 422 Unprocessable Entity."""
    resp = await client.get("/ols/api/search")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_select_q_required(client: AsyncClient, sample_term):
    """GET /select without q= returns 422 Unprocessable Entity."""
    resp = await client.get("/ols/api/select")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_suggest_q_required(client: AsyncClient, sample_term):
    """GET /suggest without q= returns 422 Unprocessable Entity."""
    resp = await client.get("/ols/api/suggest")
    assert resp.status_code == 422
