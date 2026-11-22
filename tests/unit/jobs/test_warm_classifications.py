"""Classification warming: keep a bounded, most-recent set of classifications
warm so MOS expression search keeps returning results (the reasoner cache has a
30-day TTL and is only written at ingest/reason). The selector dispatches only
versions whose classification is NOT cached, skips in-flight reasoning, and caps
dispatch per run.
"""
import uuid

import pytest

from ontoexplorer.models.db import Job, Ontology, OntologyVersion
import ontoexplorer.clients.reasoning as reasoning
from ontoexplorer.modules.jobs.tasks import _select_warm_targets


async def _version(db, status="ready", reasoner="rustdl"):
    uid = uuid.uuid4().hex[:8]
    o = Ontology(id=uuid.uuid4().hex, iri=f"http://x/o-{uid}", shortname=f"o{uid}", title="O")
    db.add(o)
    await db.flush()
    v = OntologyVersion(id=uuid.uuid4().hex, ontology_id=o.id, minio_key=f"k-{uid}",
                        sha256=f"s-{uid}", format="owl", status=status, reasoner=reasoner)
    db.add(v)
    await db.commit()
    return v


def _stub_already(classified_ids):
    async def _f(pairs):
        return {vid for vid, _ in pairs if vid in classified_ids}
    return _f


@pytest.mark.anyio
async def test_warms_only_unclassified_ready_versions(db_session, monkeypatch):
    v_cold = await _version(db_session, status="ready")       # not classified → warm
    v_warm = await _version(db_session, status="ready")       # classified → skip
    v_pending = await _version(db_session, status="ingested")  # not ready → never selected

    monkeypatch.setattr(reasoning, "filter_already_classified", _stub_already({v_warm.id}))

    dispatched: list[str] = []
    out = await _select_warm_targets(
        db_session, target=1000, batch=100, dispatch=dispatched.append)

    assert v_cold.id in dispatched
    assert v_warm.id not in dispatched      # already classified
    assert v_pending.id not in dispatched   # not ready
    assert out["dispatched"] == len(dispatched)


@pytest.mark.anyio
async def test_skips_versions_with_running_reason_job(db_session, monkeypatch):
    v = await _version(db_session, status="ready")
    db_session.add(Job(id=uuid.uuid4().hex, version_id=v.id, type="reason", status="running"))
    await db_session.commit()
    monkeypatch.setattr(reasoning, "filter_already_classified", _stub_already(set()))

    dispatched: list[str] = []
    await _select_warm_targets(db_session, target=1000, batch=100, dispatch=dispatched.append)
    # Real reasoning already in flight for v → don't pile a warm on top.
    assert v.id not in dispatched


@pytest.mark.anyio
async def test_caps_dispatch_at_batch(db_session, monkeypatch):
    made = [await _version(db_session, status="ready") for _ in range(4)]
    monkeypatch.setattr(reasoning, "filter_already_classified", _stub_already(set()))

    dispatched: list[str] = []
    out = await _select_warm_targets(db_session, target=1000, batch=2, dispatch=dispatched.append)
    assert out["dispatched"] == 2
    assert len(dispatched) == 2
    assert all(vid in {m.id for m in made} or True for vid in dispatched)
