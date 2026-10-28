"""Held-draft lifecycle sweep (#364 Phase 3): nudge once, then auto-deprecate.

The suite shares one un-rolled-back SQLite DB and the sweep is global, so every test
seeds a uniquely-titled ontology and asserts only on its own version (refreshed) and
on payloads filtered to that title — never on global counts.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion, User
from ontoexplorer.modules.ingestion.held_lifecycle import sweep_held_drafts


async def _held(db, *, age_days, status="needs_review", nudged=False, owner=True):
    title = f"Lifecycle-{uuid.uuid4().hex[:10]}"
    owner_id = None
    if owner:
        u = User(id=str(uuid.uuid4()), email=f"o-{uuid.uuid4()}@ex.com", display_name="Owner")
        db.add(u)
        owner_id = u.id
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title=title,
                 shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner_id)
    db.add(o)
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k", sha256=uuid.uuid4().hex,
        format="turtle", status=status, triple_count=10, created_at=created,
        held_nudged_at=created if nudged else None,
    )
    db.add(v)
    await db.commit()
    return title, v


def _for(payloads, title):
    return [p for p in payloads if p["ontology_label"] == title]


@pytest.mark.anyio
async def test_nudges_once_after_the_window(db_session):
    title, v = await _held(db_session, age_days=20)
    res = await sweep_held_drafts(db_session, nudge_days=14, retire_days=60)

    mine = _for(res["nudged"], title)
    assert len(mine) == 1
    assert mine[0]["days_held"] == 20 and mine[0]["retire_days"] == 60
    await db_session.refresh(v)
    assert v.status == "needs_review"          # nudged, not retired
    assert v.held_nudged_at is not None


@pytest.mark.anyio
async def test_does_not_renudge_an_already_nudged_draft(db_session):
    title, v = await _held(db_session, age_days=30, nudged=True)
    res = await sweep_held_drafts(db_session, nudge_days=14, retire_days=60)

    assert _for(res["nudged"], title) == []
    await db_session.refresh(v)
    assert v.status == "needs_review"


@pytest.mark.anyio
async def test_retires_past_the_retire_window(db_session):
    title, v = await _held(db_session, age_days=70)
    res = await sweep_held_drafts(db_session, nudge_days=14, retire_days=60)

    mine = _for(res["retired"], title)
    assert len(mine) == 1 and mine[0]["days_held"] == 70
    assert _for(res["nudged"], title) == []    # retire wins over nudge
    await db_session.refresh(v)
    assert v.status == "deprecated"
    assert v.held_nudged_at is not None         # held-provenance kept for reactivate


@pytest.mark.anyio
async def test_fresh_draft_is_left_alone(db_session):
    title, v = await _held(db_session, age_days=3)
    res = await sweep_held_drafts(db_session, nudge_days=14, retire_days=60)

    assert _for(res["nudged"], title) == [] and _for(res["retired"], title) == []
    await db_session.refresh(v)
    assert v.status == "needs_review" and v.held_nudged_at is None


@pytest.mark.anyio
async def test_windows_of_zero_disable_each_stage(db_session):
    title, v = await _held(db_session, age_days=90)
    res = await sweep_held_drafts(db_session, nudge_days=0, retire_days=0)

    assert _for(res["nudged"], title) == [] and _for(res["retired"], title) == []
    await db_session.refresh(v)
    assert v.status == "needs_review" and v.held_nudged_at is None


@pytest.mark.anyio
async def test_ownerless_draft_is_swept_with_no_email(db_session):
    title, v = await _held(db_session, age_days=70, owner=False)
    res = await sweep_held_drafts(db_session, nudge_days=14, retire_days=60)

    mine = _for(res["retired"], title)
    assert len(mine) == 1 and mine[0]["owner_email"] is None
    await db_session.refresh(v)
    assert v.status == "deprecated"
