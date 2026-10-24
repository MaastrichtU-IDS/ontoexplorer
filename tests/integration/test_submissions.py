"""GET /ontologies/submissions[/{task_id}] — durable, owner-scoped records of a
contributor's ingest jobs, enriched with the ontology/version they produced and
any hold reasons (#364 Phase 2b). Replaces the ephemeral in-component poll."""
import uuid

import pytest

from ontoexplorer.models.db import Job, Ontology, OntologyVersion, User


async def _submission(db, user_id, *, job_status="done", ver_status=None,
                      title="T", license_compliant=True, triples=10):
    """Create an ingestion Job, optionally with the version it produced."""
    vid = None
    if ver_status is not None:
        o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                     title=title, owner_id=user_id)
        db.add(o)
        v = OntologyVersion(
            id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k",
            sha256=uuid.uuid4().hex, format="turtle", status=ver_status,
            triple_count=triples, license_compliant=license_compliant,
        )
        db.add(v)
        vid = v.id
    job = Job(id=str(uuid.uuid4()), user_id=user_id, version_id=vid,
              type="ingestion", status=job_status)
    db.add(job)
    await db.commit()
    return job


def _hdr(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.mark.anyio
async def test_lists_only_my_ingestion_jobs(client, user_and_key, db_session):
    user, raw = user_and_key
    await _submission(db_session, user.id, ver_status="ready")
    # someone else's submission
    other = User(id=str(uuid.uuid4()), email=f"o-{uuid.uuid4()}@ex.com")
    db_session.add(other)
    await db_session.commit()
    await _submission(db_session, other.id, ver_status="ready")
    # a non-ingestion job of the caller's (reasoning) — excluded
    db_session.add(Job(id=str(uuid.uuid4()), user_id=user.id, type="reason", status="done"))
    await db_session.commit()

    r = await client.get("/api/v1/ontologies/submissions", headers=_hdr(raw))
    assert r.status_code == 200
    subs = r.json()["submissions"]
    assert len(subs) == 1
    assert subs[0]["ontology"]["title"] == "T"
    assert subs[0]["version"]["status"] == "ready"


@pytest.mark.anyio
async def test_held_submission_reports_needs_review(client, user_and_key, db_session):
    user, raw = user_and_key
    job = await _submission(db_session, user.id, ver_status="needs_review",
                            title=None, license_compliant=False)
    r = await client.get(f"/api/v1/ontologies/submissions/{job.id}", headers=_hdr(raw))
    assert r.status_code == 200
    body = r.json()
    # The held status is what routes the contributor to the Phase 1 fix panel; the
    # per-reason detail lives on that panel, not on the submission record.
    assert body["version"]["status"] == "needs_review"
    assert body["ontology"] is not None


@pytest.mark.anyio
async def test_pending_submission_has_no_version(client, user_and_key, db_session):
    user, raw = user_and_key
    job = await _submission(db_session, user.id, job_status="pending", ver_status=None)
    r = await client.get(f"/api/v1/ontologies/submissions/{job.id}", headers=_hdr(raw))
    assert r.status_code == 200
    body = r.json()
    assert body["job_status"] == "pending"
    assert body["version"] is None and body["ontology"] is None


@pytest.mark.anyio
async def test_other_users_submission_is_404(client, user_and_key, db_session):
    _, raw = user_and_key
    other = User(id=str(uuid.uuid4()), email=f"o-{uuid.uuid4()}@ex.com")
    db_session.add(other)
    await db_session.commit()
    job = await _submission(db_session, other.id, ver_status="ready")
    r = await client.get(f"/api/v1/ontologies/submissions/{job.id}", headers=_hdr(raw))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_unknown_task_is_404(client, user_and_key):
    _, raw = user_and_key
    r = await client.get(f"/api/v1/ontologies/submissions/{uuid.uuid4()}", headers=_hdr(raw))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_requires_auth(client):
    r = await client.get("/api/v1/ontologies/submissions")
    assert r.status_code in (401, 403)
