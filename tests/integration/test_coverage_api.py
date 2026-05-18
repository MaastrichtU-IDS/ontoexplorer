"""Integration tests for the coverage endpoints."""
import json
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.coverage import coverage_cache_key


def _sample_payload(version_id: str) -> dict:
    return {
        "version_id": version_id,
        "indexed_at": "2026-05-18T00:00:00+00:00",
        "by_type": {
            "class":               {"total": 100, "with_label": 90, "with_definition": 50, "multilingual": 10, "by_lang": {"en": 90, "de": 10}},
            "object_property":     {"total": 20,  "with_label": 18, "with_definition": 5,  "multilingual": 0,  "by_lang": {"en": 18}},
            "data_property":       {"total": 5,   "with_label": 5,  "with_definition": 0,  "multilingual": 0,  "by_lang": {"en": 5}},
            "annotation_property": {"total": 3,   "with_label": 3,  "with_definition": 0,  "multilingual": 0,  "by_lang": {"en": 3}},
            "individual":          {"total": 0,   "with_label": 0,  "with_definition": 0,  "multilingual": 0,  "by_lang": {}},
        },
    }


@pytest.mark.anyio
async def test_version_coverage_returns_cached_payload(client, db_session):
    ont = Ontology(iri="http://example.org/cov-test.owl", shortname="cov", title="Cov Test")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="cov/test.ttl",
        sha256="cov_test_001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(coverage_cache_key(ver.id), json.dumps(_sample_payload(ver.id)))

    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/coverage")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version_id"] == ver.id
    assert body["by_type"]["class"]["total"] == 100
    assert body["by_type"]["class"]["by_lang"]["de"] == 10


@pytest.mark.anyio
async def test_version_coverage_returns_404_when_cache_missing(client, db_session):
    ont = Ontology(iri="http://example.org/cov-missing.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="cov/missing.ttl",
        sha256="cov_missing_001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/coverage")

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_fleet_coverage_aggregates_and_omits_by_lang(client, db_session):
    ont_a = Ontology(iri="http://example.org/a.owl", shortname="a", title="A")
    ont_b = Ontology(iri="http://example.org/b.owl", shortname="b", title="B")
    db_session.add_all([ont_a, ont_b])
    await db_session.flush()
    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="a.ttl", sha256="a001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="b.ttl", sha256="b001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(coverage_cache_key(ver_a.id), json.dumps(_sample_payload(ver_a.id)))
    r.set(coverage_cache_key(ver_b.id), json.dumps(_sample_payload(ver_b.id)))

    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get("/api/v1/coverage/public")

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["class"]["total"] == 200
    assert body["totals"]["class"]["with_label"] == 180
    assert len(body["by_ontology"]) == 2
    for entry in body["by_ontology"]:
        for bucket in entry["by_type"].values():
            assert "by_lang" not in bucket


@pytest.mark.anyio
async def test_fleet_coverage_skips_versions_without_cache(client, db_session):
    ont = Ontology(iri="http://example.org/skip.owl", shortname="skip", title="Skip")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(ontology_id=ont.id, minio_key="skip.ttl", sha256="skip001", format="turtle", status="ready")
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get("/api/v1/coverage/public")

    assert resp.status_code == 200
    body = resp.json()
    assert body["by_ontology"] == []
    for bucket in body["totals"].values():
        assert bucket == {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0}


@pytest.mark.anyio
async def test_fleet_coverage_partial_cache(client, db_session):
    """Ontologies with cache contribute to totals; ontologies without cache are skipped."""
    ont_a = Ontology(iri="http://example.org/partial-a.owl", shortname="pa", title="Partial A")
    ont_b = Ontology(iri="http://example.org/partial-b.owl", shortname="pb", title="Partial B")
    db_session.add_all([ont_a, ont_b])
    await db_session.flush()
    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="pa.ttl", sha256="pa001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="pb.ttl", sha256="pb001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    # Only ont_a has cache; ont_b is skipped
    r.set(coverage_cache_key(ver_a.id), json.dumps(_sample_payload(ver_a.id)))

    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get("/api/v1/coverage/public")

    assert resp.status_code == 200
    body = resp.json()
    # Only ont_a appears in by_ontology
    assert len(body["by_ontology"]) == 1
    assert body["by_ontology"][0]["ontology_id"] == ont_a.id
    # Totals reflect ont_a's payload (single-ontology sum)
    assert body["totals"]["class"]["total"] == 100
    assert body["totals"]["class"]["with_label"] == 90
