import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.jobs.tasks import _retryable_resolvability_ids


async def _o(db, *, resolvable, detail, checked_minutes_ago=10):
    o = Ontology(
        id=uuid.uuid4().hex, iri=f"http://x/{uuid.uuid4().hex}", shortname=uuid.uuid4().hex[:8],
        title="O", resolvable=resolvable, resolve_detail=detail,
        resolve_checked_at=datetime.now(timezone.utc) - timedelta(minutes=checked_minutes_ago),
    )
    db.add(o)
    await db.commit()
    return o


@pytest.mark.anyio
async def test_retryable_selects_transient_failures(db_session):
    rate = await _o(db_session, resolvable=False, detail={"http_status": "429"})
    err = await _o(db_session, resolvable=False, detail={"http_status": None, "error": "timeout"})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert rate.id in ids and err.id in ids


@pytest.mark.anyio
async def test_retryable_excludes_permanent(db_session):
    dead = await _o(db_session, resolvable=False, detail={"http_status": "404"})
    html = await _o(db_session, resolvable=False, detail={"http_status": "200"})
    ok = await _o(db_session, resolvable=True, detail={"http_status": "200"})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert dead.id not in ids and html.id not in ids and ok.id not in ids


@pytest.mark.anyio
async def test_retryable_skips_cooldown(db_session):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    cooling = await _o(db_session, resolvable=False,
                       detail={"http_status": "503", "retry_after": future})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert cooling.id not in ids


@pytest.mark.anyio
async def test_retryable_includes_elapsed_cooldown(db_session):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    ready = await _o(db_session, resolvable=False,
                     detail={"http_status": "429", "retry_after": past})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert ready.id in ids
