"""Integration tests for the consistency-analysis endpoints."""
import json
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.consistency.cache import consistency_cache_key


def _report_payload(version_id: str, *, status: str = "done", host_only="consistent",
                    host_plus_imports="consistent",
                    host_plus_imports_plus_mireot="consistent") -> dict:
    def _scope(name, st):
        return {
            "scope": name,
            "status": st,
            "unsatisfiable_classes": [],
            "mireot_sources_fetched": [],
            "mireot_sources_skipped": [],
            "elapsed_seconds": 1.23,
            "error_message": None,
        }
    return {
        "version_id": version_id,
        "host_iri": "http://example.org/host",
        "scopes": {
            "host_only": _scope("host_only", host_only),
            "host_plus_imports": _scope("host_plus_imports", host_plus_imports),
            "host_plus_imports_plus_mireot": _scope(
                "host_plus_imports_plus_mireot", host_plus_imports_plus_mireot
            ),
        },
        "job_status": status,
        "started_at": "2026-05-21T00:00:00+00:00",
        "finished_at": "2026-05-21T00:00:01+00:00",
    }


@pytest.mark.anyio
async def test_get_consistency_404_when_not_cached(client, db_session):
    ont = Ontology(iri="http://example.org/c1.owl", shortname="c1", title="Cons Test 1")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="c1.ttl", sha256="c1_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/consistency")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_consistency_returns_pending_placeholder(client, db_session):
    ont = Ontology(iri="http://example.org/c2.owl", shortname="c2", title="Cons Test 2")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="c2.ttl", sha256="c2_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    pending = _report_payload(str(ver.id), status="pending",
                              host_only="", host_plus_imports="",
                              host_plus_imports_plus_mireot="")
    pending["scopes"] = {}
    r.set(consistency_cache_key(str(ver.id)), json.dumps(pending))

    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/consistency")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_status"] == "pending"


@pytest.mark.anyio
async def test_get_consistency_returns_full_report(client, db_session):
    ont = Ontology(iri="http://example.org/c3.owl", shortname="c3", title="Cons Test 3")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="c3.ttl", sha256="c3_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(consistency_cache_key(str(ver.id)),
          json.dumps(_report_payload(str(ver.id))))

    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/consistency")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_status"] == "done"
    assert body["scopes"]["host_only"]["status"] == "consistent"


@pytest.mark.anyio
async def test_consistency_fleet_aggregates(client, db_session):
    ont_a = Ontology(iri="http://example.org/fc-a.owl", shortname="fca", title="Fleet C A")
    ont_b = Ontology(iri="http://example.org/fc-b.owl", shortname="fcb", title="Fleet C B")
    db_session.add_all([ont_a, ont_b])
    await db_session.flush()
    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="fca.ttl",
                            sha256="fca001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="fcb.ttl",
                            sha256="fcb001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(consistency_cache_key(str(ver_a.id)),
          json.dumps(_report_payload(str(ver_a.id))))
    r.set(consistency_cache_key(str(ver_b.id)),
          json.dumps(_report_payload(str(ver_b.id),
                                     host_plus_imports="inconsistent")))

    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get("/api/v1/consistency/fleet")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["fleet_size"] == 2
    assert body["totals"]["inconsistent_any_scope"] == 1
