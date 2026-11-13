"""Supersede-on-re-ingest: a fresh ingest of a version_iri drops any still-held
(needs_review) draft of that SAME version_iri, so re-ingests (update polling / the
inbound webhook) don't stack duplicate held versions with an identical label.
See modules/ingestion/pipeline._supersede_stale_held_versions.
"""
import hashlib
import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.jobs import tasks
from ontoexplorer.modules.ingestion.pipeline import _supersede_stale_held_versions

pytestmark = pytest.mark.anyio

VIRI = "https://w3id.org/ontostart/pro/1.0.2"


async def _seed(db, specs):
    oid = str(uuid.uuid4())
    db.add(Ontology(id=oid, iri=f"http://ex/{uuid.uuid4()}", shortname=f"o{uuid.uuid4().hex[:8]}"))
    await db.commit()
    vids = []
    for s in specs:
        vid = str(uuid.uuid4())
        db.add(OntologyVersion(
            id=vid, ontology_id=oid, version_iri=s.get("iri", VIRI),
            minio_key=f"{oid}/{vid}.ttl", sha256=hashlib.sha256(vid.encode()).hexdigest(),
            format="ttl", status=s["status"]))
        vids.append(vid)
    await db.commit()
    return oid, vids


@pytest.fixture
def purges(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay",
                        lambda *a: calls.append(a), raising=False)
    import ontoexplorer.clients.reasoning as reasoning

    async def _noop(_vid):
        return None
    monkeypatch.setattr(reasoning, "invalidate_cache", _noop, raising=False)
    return calls


async def _ids(db, oid):
    return {str(v.id) for v in (await db.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == oid))).scalars()}


async def test_supersedes_prior_held_drafts_of_same_version_iri(db_session, purges):
    oid, (ready1, old_a, old_b, new) = await _seed(db_session, [
        {"status": "ready", "iri": "https://w3id.org/ontostart/pro/1.0.1"},
        {"status": "needs_review"},   # old held 1.0.2
        {"status": "needs_review"},   # old held 1.0.2 (the pile-up)
        {"status": "ingested"},       # the just-ingested 1.0.2
    ])
    superseded = await _supersede_stale_held_versions(db_session, oid, VIRI, new)
    assert set(superseded) == {old_a, old_b}
    assert await _ids(db_session, oid) == {ready1, new}   # held drafts gone; ready + new kept
    assert len(purges) == 2                               # one artifact-purge per superseded


async def test_never_supersedes_a_ready_version_of_same_iri(db_session, purges):
    oid, (ready_dup, new) = await _seed(db_session, [
        {"status": "ready"},       # a READY 1.0.2 is protected
        {"status": "ingested"},
    ])
    assert await _supersede_stale_held_versions(db_session, oid, VIRI, new) == []
    assert ready_dup in await _ids(db_session, oid)
    assert len(purges) == 0


async def test_noop_without_version_iri(db_session, purges):
    oid, (held, new) = await _seed(db_session, [
        {"status": "needs_review", "iri": None}, {"status": "ingested", "iri": None}])
    assert await _supersede_stale_held_versions(db_session, oid, None, new) == []
    assert len(purges) == 0


async def test_leaves_held_drafts_of_other_version_iris(db_session, purges):
    oid, (other_held, new) = await _seed(db_session, [
        {"status": "needs_review", "iri": "https://w3id.org/ontostart/pro/0.9.0"},
        {"status": "ingested"}])
    assert await _supersede_stale_held_versions(db_session, oid, VIRI, new) == []
    assert other_held in await _ids(db_session, oid)


async def test_broker_down_leaves_draft_in_place(db_session, monkeypatch):
    def _boom(*a):
        raise RuntimeError("broker down")
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay", _boom, raising=False)
    oid, (old, new) = await _seed(db_session, [
        {"status": "needs_review"}, {"status": "ingested"}])
    assert await _supersede_stale_held_versions(db_session, oid, VIRI, new) == []
    assert old in await _ids(db_session, oid)   # NOT deleted → artifacts not orphaned
