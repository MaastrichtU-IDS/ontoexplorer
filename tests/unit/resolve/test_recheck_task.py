import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.jobs.tasks import _recheck_batch


async def _clear(db):
    # The unit-test sqlite DB is session-scoped and accumulates rows across
    # tests; clear it so count/no-op assertions here are deterministic.
    await db.execute(text("DELETE FROM ontologies"))
    await db.commit()


async def _o(db, host):
    o = Ontology(
        id=uuid.uuid4().hex, iri=f"https://{host}/{uuid.uuid4().hex}", shortname=uuid.uuid4().hex[:8],
        title="O", resolvable=False, resolve_detail={"http_status": "429"},
        resolve_checked_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.add(o)
    await db.commit()
    return o


def _logical_clock():
    """A deterministic clock/sleep pair sharing one logical 'now', so tests don't
    depend on wall-clock jitter. sleep(s) advances the clock by s."""
    t = [0.0]
    slept = []

    def clock():
        return t[0]

    def sleep(s):
        slept.append(s)
        t[0] += s

    return clock, sleep, slept


@pytest.mark.anyio
async def test_recheck_spaces_same_host(db_session):
    await _clear(db_session)
    await _o(db_session, "w3id.org")
    await _o(db_session, "w3id.org")
    clock, sleep, slept = _logical_clock()
    applied = []

    async def _apply(db, oid, **k):
        applied.append(oid)

    n = await _recheck_batch(db_session, limit=100, min_host_interval_s=2.0,
                             sleep=sleep, apply=_apply, clock=clock)
    assert n == 2
    assert len(applied) == 2
    # the two same-host checks are spaced by >= the min interval
    assert any(s >= 2.0 for s in slept)


@pytest.mark.anyio
async def test_recheck_spaces_only_same_host(db_session):
    await _clear(db_session)
    await _o(db_session, "w3id.org")
    await _o(db_session, "purl.obolibrary.org")
    clock, sleep, slept = _logical_clock()

    async def _apply(db, oid, **k):
        pass

    n = await _recheck_batch(db_session, limit=100, min_host_interval_s=2.0,
                             sleep=sleep, apply=_apply, clock=clock)
    assert n == 2
    # different hosts → no spacing sleep required
    assert slept == []


@pytest.mark.anyio
async def test_recheck_noop_when_none(db_session):
    await _clear(db_session)
    clock, sleep, slept = _logical_clock()
    n = await _recheck_batch(db_session, limit=100, min_host_interval_s=2.0,
                             sleep=sleep, apply=None, clock=clock)
    assert n == 0 and slept == []
