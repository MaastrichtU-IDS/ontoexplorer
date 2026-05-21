"""Integration tests for the reuse-analysis endpoints."""
import json
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.reuse.cache import reuse_cache_key


def _reuse_payload(version_id: str, *, host_prefix: str = "host",
                   imports: list | None = None,
                   term_iri_reuse: dict | None = None,
                   mireot_terms: list | None = None,
                   mappings: dict | None = None) -> dict:
    return {
        "version_id": version_id,
        "host_prefix": host_prefix,
        "host_iri": "http://example.org/host",
        "imports": imports or [],
        "term_iri_reuse": term_iri_reuse or {},
        "mireot_terms": mireot_terms or [],
        "mappings": mappings or {},
        "indexed_at": "2026-05-20T00:00:00+00:00",
    }


@pytest.mark.anyio
async def test_get_reuse_404_when_not_cached(client, db_session):
    ont = Ontology(iri="http://example.org/r1.owl", shortname="r1", title="Reuse Test 1")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="r1.ttl", sha256="r1_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.reuse._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/reuse")

    assert resp.status_code == 404
    assert "reindex pending" in resp.json()["detail"]


@pytest.mark.anyio
async def test_get_reuse_returns_cached_payload(client, db_session):
    ont = Ontology(iri="http://example.org/r2.owl", shortname="r2", title="Reuse Test 2")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="r2.ttl", sha256="r2_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    payload = _reuse_payload(
        str(ver.id),
        imports=[{"target_iri": "http://purl.obolibrary.org/obo/bfo.owl",
                  "target_prefix": "bfo", "depth": 1, "resolved": True}],
        term_iri_reuse={
            "bfo": {"class_count": 3, "property_count": 0,
                    "sample_iris": ["http://purl.obolibrary.org/obo/BFO_0000001"],
                    "resolved": True}
        },
    )
    r.set(reuse_cache_key(str(ver.id)), json.dumps(payload))

    with patch("ontoexplorer.api.reuse._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/reuse")

    assert resp.status_code == 200
    body = resp.json()
    assert body["imports"][0]["target_prefix"] == "bfo"
    assert body["term_iri_reuse"]["bfo"]["class_count"] == 3


@pytest.mark.anyio
async def test_reuse_fleet_aggregates_across_versions(client, db_session):
    ont_a = Ontology(iri="http://example.org/fa.owl", shortname="fa", title="Fleet A")
    ont_b = Ontology(iri="http://example.org/fb.owl", shortname="fb", title="Fleet B")
    db_session.add_all([ont_a, ont_b])
    await db_session.flush()
    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="fa.ttl",
                            sha256="fa001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="fb.ttl",
                            sha256="fb001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(reuse_cache_key(str(ver_a.id)),
          json.dumps(_reuse_payload(str(ver_a.id),
                                    imports=[{"target_iri": "x", "target_prefix": "bfo",
                                              "depth": 1, "resolved": True}],
                                    mireot_terms=[{"iri": "y", "source_prefix": "iao",
                                                   "has_imported_from": False}])))
    r.set(reuse_cache_key(str(ver_b.id)),
          json.dumps(_reuse_payload(str(ver_b.id),
                                    term_iri_reuse={"ro": {"class_count": 5,
                                                           "property_count": 1,
                                                           "sample_iris": [],
                                                           "resolved": True}})))

    with patch("ontoexplorer.api.reuse._get_redis", return_value=r):
        resp = await client.get("/api/v1/reuse/fleet")

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["fleet_size"] == 2
    assert body["totals"]["total_import_edges"] == 1
    assert body["totals"]["total_mireot_terms"] == 1
    assert body["totals"]["ontologies_with_mireot"] == 1
    # ro appears in 1 ontology (ver_b)
    assert {"prefix": "ro", "reusers_count": 1} in body["top_reused_sources"]
