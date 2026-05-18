"""Integration tests for the cross-ontology compare API endpoints.

The Celery task (compute_ontology_comparison.delay) is monkey-patched to a
no-op so the tests verify the API contract (row creation, status codes,
idempotency, failed-row reset) without requiring a running worker.
"""
import pytest

from ontoexplorer.models.db import (
    Ontology,
    OntologyComparison,
    OntologyVersion,
)


@pytest.fixture
def no_celery(monkeypatch):
    """Replace compute_ontology_comparison.delay with a no-op."""
    called = []
    def fake_delay(*args, **kwargs):
        called.append((args, kwargs))
        return None
    monkeypatch.setattr(
        "ontoexplorer.modules.jobs.tasks.compute_ontology_comparison.delay",
        fake_delay,
    )
    return called


async def _make_version(db_session, ont_iri: str, sha: str) -> OntologyVersion:
    ont = Ontology(iri=ont_iri)
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"test/{sha}.ttl",
        sha256=sha,
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()
    return ver


@pytest.mark.anyio
async def test_compute_rejects_equal_version_ids(client):
    """from_version_id == to_version_id → 400."""
    r = await client.post(
        "/api/v1/compare/compute",
        params={"from_version_id": "same-vid", "to_version_id": "same-vid"},
    )
    assert r.status_code == 400
    assert "differ" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_compute_rejects_unknown_version_ids(client):
    """Either version ID not in DB → 404."""
    r = await client.post(
        "/api/v1/compare/compute",
        params={"from_version_id": "nope-a", "to_version_id": "nope-b"},
    )
    assert r.status_code == 404


@pytest.mark.anyio
async def test_compute_creates_pending_row_and_queues(client, db_session, no_celery):
    """Happy path: valid versions, no existing row → 202 pending + Celery delayed."""
    v_from = await _make_version(db_session, "http://example.org/a.owl", "cmpa001")
    v_to   = await _make_version(db_session, "http://example.org/b.owl", "cmpb001")

    r = await client.post(
        "/api/v1/compare/compute",
        params={"from_version_id": v_from.id, "to_version_id": v_to.id},
    )
    assert r.status_code == 202
    assert r.json() == {"status": "pending"}
    assert len(no_celery) == 1, "Celery task should have been queued exactly once"
    queued_args = no_celery[0][0]
    assert queued_args == (v_from.id, v_to.id)


@pytest.mark.anyio
async def test_get_returns_404_when_no_row(client, db_session):
    """GET /compare with valid versions but no row in DB → 404."""
    v_from = await _make_version(db_session, "http://example.org/c.owl", "cmpc001")
    v_to   = await _make_version(db_session, "http://example.org/d.owl", "cmpd001")

    r = await client.get(
        "/api/v1/compare",
        params={"from_version_id": v_from.id, "to_version_id": v_to.id},
    )
    assert r.status_code == 404


@pytest.mark.anyio
async def test_get_returns_200_when_ready(client, db_session):
    """GET /compare with status=ready → 200 + payload."""
    v_from = await _make_version(db_session, "http://example.org/e.owl", "cmpe001")
    v_to   = await _make_version(db_session, "http://example.org/f.owl", "cmpf001")
    row = OntologyComparison(
        from_ontology_id=v_from.ontology_id,
        to_ontology_id=v_to.ontology_id,
        version_from_id=v_from.id,
        version_to_id=v_to.id,
        status="ready",
        summary={"added": 0, "removed": 0, "modified": 0, "literal_changes": 0,
                 "axiom_changes": 0, "by_entity_type": {}},
        diff_data={"added": [], "removed": [], "modified": []},
    )
    db_session.add(row)
    await db_session.commit()

    r = await client.get(
        "/api/v1/compare",
        params={"from_version_id": v_from.id, "to_version_id": v_to.id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["summary"]["added"] == 0
    assert body["from_ontology_id"] == v_from.ontology_id
    assert body["to_ontology_id"] == v_to.ontology_id


@pytest.mark.anyio
async def test_get_returns_202_when_pending(client, db_session):
    """GET /compare with status=pending → 202 + just the status."""
    v_from = await _make_version(db_session, "http://example.org/g.owl", "cmpg001")
    v_to   = await _make_version(db_session, "http://example.org/h.owl", "cmph001")
    row = OntologyComparison(
        from_ontology_id=v_from.ontology_id,
        to_ontology_id=v_to.ontology_id,
        version_from_id=v_from.id,
        version_to_id=v_to.id,
        status="pending",
    )
    db_session.add(row)
    await db_session.commit()

    r = await client.get(
        "/api/v1/compare",
        params={"from_version_id": v_from.id, "to_version_id": v_to.id},
    )
    assert r.status_code == 202
    assert r.json() == {"status": "pending"}


@pytest.mark.anyio
async def test_compute_is_idempotent_for_pending_row(client, db_session, no_celery):
    """Existing pending row → 202 with status, NO re-queue."""
    v_from = await _make_version(db_session, "http://example.org/i.owl", "cmpi001")
    v_to   = await _make_version(db_session, "http://example.org/j.owl", "cmpj001")
    db_session.add(OntologyComparison(
        from_ontology_id=v_from.ontology_id,
        to_ontology_id=v_to.ontology_id,
        version_from_id=v_from.id,
        version_to_id=v_to.id,
        status="pending",
    ))
    await db_session.commit()

    r = await client.post(
        "/api/v1/compare/compute",
        params={"from_version_id": v_from.id, "to_version_id": v_to.id},
    )
    assert r.status_code == 202
    assert r.json() == {"status": "pending"}
    assert no_celery == [], "should NOT re-queue when a pending row already exists"


@pytest.mark.anyio
async def test_compute_resets_failed_row_and_requeues(client, db_session, no_celery):
    """Existing failed row → reset to pending, clear summary/diff, re-queue."""
    v_from = await _make_version(db_session, "http://example.org/k.owl", "cmpk001")
    v_to   = await _make_version(db_session, "http://example.org/l.owl", "cmpl001")
    row = OntologyComparison(
        from_ontology_id=v_from.ontology_id,
        to_ontology_id=v_to.ontology_id,
        version_from_id=v_from.id,
        version_to_id=v_to.id,
        status="failed",
        summary={"added": 99, "stale": True},
        diff_data={"stale": True},
    )
    db_session.add(row)
    await db_session.commit()

    r = await client.post(
        "/api/v1/compare/compute",
        params={"from_version_id": v_from.id, "to_version_id": v_to.id},
    )
    assert r.status_code == 202
    assert r.json() == {"status": "pending"}
    assert len(no_celery) == 1, "should re-queue when prior row was failed"

    # Verify the row was reset.
    await db_session.refresh(row)
    assert row.status == "pending"
    assert row.summary is None
    assert row.diff_data is None
