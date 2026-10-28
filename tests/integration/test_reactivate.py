"""Owner reactivation of an auto-retired held draft (#364 Phase 3 lifecycle).

The lifecycle sweep auto-deprecates a version held too long (keeping held_nudged_at
as the held-provenance marker). The owner can reactivate that set-aside draft back to
needs_review — but only such a draft: an ordinary deprecate (no held provenance) and a
still-held version are both 409, so this never silently resurrects the wrong thing.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology, OntologyVersion, User


async def _version(db, owner_id, *, status, nudged):
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title="T", owner_id=owner_id)
    db.add(o)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k", sha256=uuid.uuid4().hex,
        format="turtle", status=status, triple_count=10,
        held_nudged_at=datetime.now(timezone.utc) if nudged else None,
    )
    db.add(v)
    await db.commit()
    return o, v


def _hdr(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.mark.anyio
async def test_reactivate_auto_retired_draft(client, user_and_key, db_session):
    user, raw = user_and_key
    o, v = await _version(db_session, user.id, status="deprecated", nudged=True)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reactivate", headers=_hdr(raw))
    assert r.status_code == 200
    assert r.json()["status"] == "needs_review"
    row = (await db_session.execute(select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.status == "needs_review"
    assert row.held_nudged_at is None   # eligible for a fresh nudge if it stalls again


@pytest.mark.anyio
async def test_ordinary_deprecate_cannot_be_reactivated(client, user_and_key, db_session):
    # Deprecated but never in the held lifecycle (held_nudged_at NULL) → 409.
    user, raw = user_and_key
    o, v = await _version(db_session, user.id, status="deprecated", nudged=False)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reactivate", headers=_hdr(raw))
    assert r.status_code == 409
    row = (await db_session.execute(select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.status == "deprecated"


@pytest.mark.anyio
async def test_a_still_held_version_is_not_reactivatable(client, user_and_key, db_session):
    user, raw = user_and_key
    o, v = await _version(db_session, user.id, status="needs_review", nudged=True)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reactivate", headers=_hdr(raw))
    assert r.status_code == 409


@pytest.mark.anyio
async def test_non_owner_cannot_reactivate(client, user_and_key, db_session):
    _, raw = user_and_key
    other = User(id=str(uuid.uuid4()), email=f"x-{uuid.uuid4()}@ex.com")
    db_session.add(other)
    await db_session.commit()
    o, v = await _version(db_session, other.id, status="deprecated", nudged=True)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reactivate", headers=_hdr(raw))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_reactivate_requires_auth(client, user_and_key, db_session):
    user, _ = user_and_key
    o, v = await _version(db_session, user.id, status="deprecated", nudged=True)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reactivate")
    assert r.status_code == 401
