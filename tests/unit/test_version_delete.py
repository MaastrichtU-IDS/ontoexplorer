"""Per-version delete: hard delete (purge=true) and soft deprecate (default).

`DELETE /ontologies/{oid}/{vid}` soft-deprecates; `?purge=true` hard-deletes,
reusing the ontology-delete machinery: it queues purge_version_artifacts (503 if
the broker is down — nothing removed), drops the row (cascade), and re-points the
pinned default to the predecessor. Deleting the only version is refused (409).
"""
import hashlib
import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.config import get_settings
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.jobs import tasks

pytestmark = pytest.mark.anyio


async def _seed(db_session, owner_id, specs):
    """Create an ontology owned by owner_id + one version per spec
    {version_iri, status?}. Returns (ontology_id, [version_id, ...])."""
    oid = str(uuid.uuid4())
    db_session.add(Ontology(id=oid, iri=f"http://ex/{uuid.uuid4()}",
                            shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner_id))
    await db_session.commit()
    vids = []
    for spec in specs:
        vid = str(uuid.uuid4())
        db_session.add(OntologyVersion(
            id=vid, ontology_id=oid, version_iri=spec["version_iri"],
            minio_key=f"{oid}/{vid}.ttl", sha256=hashlib.sha256(vid.encode()).hexdigest(),
            format="ttl", status=spec.get("status", "ready")))
        vids.append(vid)
    await db_session.commit()
    return oid, vids


@pytest.fixture(autouse=True)
def _no_broker_or_cache(monkeypatch):
    """Default: dispatch + cache-invalidation succeed as no-ops (overridable)."""
    monkeypatch.setattr(get_settings(), "auth_bypass", False, raising=False)
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay", lambda *a: None, raising=False)
    import ontoexplorer.clients.reasoning as reasoning

    async def _noop(_vid):
        return None
    monkeypatch.setattr(reasoning, "invalidate_cache", _noop, raising=False)


async def test_hard_delete_removes_version_and_queues_purge(client, db_session, user_and_key, monkeypatch):
    owner, key = user_and_key
    oid, (v1, v2) = await _seed(db_session, owner.id,
                                [{"version_iri": "http://ex/o/1.0"}, {"version_iri": "http://ex/o/2.0"}])
    calls: list[tuple] = []
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay",
                        lambda *a: calls.append(a), raising=False)

    r = await client.delete(f"/api/v1/ontologies/{oid}/{v1}?purge=true",
                            headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 204, r.text

    remaining = (await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == oid))).scalars().all()
    assert [v.id for v in remaining] == [v2], "only the deleted version should be gone"
    assert calls and calls[0][:2] == (oid, v1), "purge_version_artifacts must be dispatched"


async def test_hard_delete_refuses_when_broker_down(client, db_session, user_and_key, monkeypatch):
    owner, key = user_and_key
    oid, (v1, _v2) = await _seed(db_session, owner.id,
                                 [{"version_iri": "http://ex/o/1.0"}, {"version_iri": "http://ex/o/2.0"}])

    def _down(*_a):
        raise RuntimeError("broker unreachable")
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay", _down, raising=False)

    r = await client.delete(f"/api/v1/ontologies/{oid}/{v1}?purge=true",
                            headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 503
    still = await db_session.scalar(select(OntologyVersion).where(OntologyVersion.id == v1))
    assert still is not None, "nothing should be removed when the purge can't be queued"


async def test_hard_delete_only_version_refused(client, db_session, user_and_key):
    owner, key = user_and_key
    oid, (v1,) = await _seed(db_session, owner.id, [{"version_iri": "http://ex/o/1.0"}])

    r = await client.delete(f"/api/v1/ontologies/{oid}/{v1}?purge=true",
                            headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 409
    still = await db_session.scalar(select(OntologyVersion).where(OntologyVersion.id == v1))
    assert still is not None


async def test_hard_delete_repoints_pinned_default_to_predecessor(client, db_session, user_and_key):
    owner, key = user_and_key
    oid, (v1, v2) = await _seed(db_session, owner.id,
                                [{"version_iri": "http://ex/o/1.0"}, {"version_iri": "http://ex/o/2.0"}])
    ont = await db_session.get(Ontology, oid)
    ont.current_version_id = v2  # pin the version we're about to delete
    await db_session.commit()

    r = await client.delete(f"/api/v1/ontologies/{oid}/{v2}?purge=true",
                            headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 204, r.text
    await db_session.refresh(ont)
    assert ont.current_version_id == v1, "pin should move to the predecessor, not dangle/null"


async def test_soft_deprecate_is_default(client, db_session, user_and_key):
    owner, key = user_and_key
    oid, (v1, v2) = await _seed(db_session, owner.id,
                                [{"version_iri": "http://ex/o/1.0"}, {"version_iri": "http://ex/o/2.0"}])

    r = await client.delete(f"/api/v1/ontologies/{oid}/{v1}",  # no ?purge
                            headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    v = await db_session.scalar(select(OntologyVersion).where(OntologyVersion.id == v1))
    assert v is not None and v.status == "deprecated", "soft deprecate keeps the row"
