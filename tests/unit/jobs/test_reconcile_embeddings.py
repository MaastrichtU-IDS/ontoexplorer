"""Self-healing embedding reconcile: re-dispatch embedding for `ready` versions
that have no term_embeddings (embeds orphaned by worker restarts), skipping any
that are already embedded or have an in-flight embedding job.
"""
import uuid

import pytest

from ontoexplorer.models.db import Job, Ontology, OntologyVersion, TermEmbedding
from ontoexplorer.modules.jobs.tasks import _reconcile_embeddings


async def _version(db, status="ready"):
    uid = uuid.uuid4().hex[:8]
    o = Ontology(id=uuid.uuid4().hex, iri=f"http://x/o-{uid}", shortname=f"o{uid}", title="O")
    db.add(o)
    await db.flush()
    v = OntologyVersion(id=uuid.uuid4().hex, ontology_id=o.id, minio_key=f"k-{uid}",
                        sha256=f"s-{uid}", format="owl", status=status)
    db.add(v)
    await db.commit()
    return v


@pytest.mark.anyio
async def test_reconcile_dispatches_only_ready_unembedded(db_session):
    v_missing = await _version(db_session, status="ready")          # → dispatch
    v_embedded = await _version(db_session, status="ready")         # has embedding → skip
    v_pending = await _version(db_session, status="ingested")       # not ready → skip
    db_session.add(TermEmbedding(version_id=v_embedded.id, entity_iri="http://x/C",
                                 entity_type="class", text_hash="h", embedding=[0.0] * 768))
    await db_session.commit()

    dispatched: list[tuple[str, str]] = []
    # High limit so this test's version is reached regardless of other rows the
    # session-scoped sqlite DB has accumulated; assert on membership, not count.
    await _reconcile_embeddings(db_session, limit=1000,
                                dispatch=lambda vid, oid: dispatched.append((vid, oid)))
    ids = [vid for vid, _ in dispatched]

    assert (v_missing.id, v_missing.ontology_id) in dispatched
    assert v_embedded.id not in ids   # already embedded
    assert v_pending.id not in ids    # not ready


@pytest.mark.anyio
async def test_reconcile_skips_versions_with_running_embed_job(db_session):
    v = await _version(db_session, status="ready")
    db_session.add(Job(id=uuid.uuid4().hex, version_id=v.id, type="embedding", status="running"))
    await db_session.commit()

    dispatched = []
    await _reconcile_embeddings(db_session, limit=1000,
                                dispatch=lambda vid, oid: dispatched.append(vid))
    # This version has an in-flight embed job → must not be re-dispatched (others
    # in the accumulated DB may be, which is fine — we assert only about `v`).
    assert v.id not in dispatched


@pytest.mark.anyio
async def test_reconcile_caps_dispatch_at_limit(db_session):
    for _ in range(4):
        await _version(db_session, status="ready")
    dispatched = []
    n = await _reconcile_embeddings(db_session, limit=2,
                                    dispatch=lambda vid, oid: dispatched.append(vid))
    assert n == 2
    assert len(dispatched) == 2
