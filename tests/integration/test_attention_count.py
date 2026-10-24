"""GET /ontologies/attention-count — the dashboard "Needs your attention" badge
count: how many of the caller's versions are held for review (#364 Phase 2)."""
import uuid

import pytest
from sqlalchemy import select  # noqa: F401 (kept parallel with sibling tests)

from ontoexplorer.models.db import Ontology, OntologyVersion, User


async def _version(db, owner_id, status):
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 title="T", owner_id=owner_id)
    db.add(o)
    db.add(OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k",
        sha256=uuid.uuid4().hex, format="turtle", status=status, triple_count=10,
    ))
    await db.commit()
    return o


def _hdr(raw_key):
    return {"Authorization": f"Bearer {raw_key}"}


@pytest.mark.anyio
async def test_counts_only_my_needs_review(client, user_and_key, db_session):
    user, raw = user_and_key
    await _version(db_session, user.id, "needs_review")
    await _version(db_session, user.id, "needs_review")
    await _version(db_session, user.id, "ready")       # not held → excluded
    await _version(db_session, user.id, "pending")     # not held → excluded
    # A foreign user's hold exercises the ownership WHERE: the caller already owns
    # rows here, so my_ids is non-empty and the filter actually runs.
    other = User(id=str(uuid.uuid4()), email=f"other-{uuid.uuid4()}@ex.com")
    db_session.add(other)
    await db_session.commit()
    await _version(db_session, other.id, "needs_review")
    r = await client.get("/api/v1/ontologies/attention-count", headers=_hdr(raw))
    assert r.status_code == 200
    assert r.json() == {"needs_review": 2}


@pytest.mark.anyio
async def test_excludes_other_users_held_versions(client, user_and_key, db_session):
    user, raw = user_and_key
    # The caller owns a (non-held) ontology so my_ids is non-empty and the scoping
    # WHERE runs — otherwise the endpoint short-circuits and the filter is untested.
    await _version(db_session, user.id, "ready")
    other = User(id=str(uuid.uuid4()), email=f"other-{uuid.uuid4()}@ex.com")
    db_session.add(other)
    await db_session.commit()
    await _version(db_session, other.id, "needs_review")  # someone else's hold
    r = await client.get("/api/v1/ontologies/attention-count", headers=_hdr(raw))
    assert r.status_code == 200
    assert r.json() == {"needs_review": 0}


@pytest.mark.anyio
async def test_requires_auth(client):
    r = await client.get("/api/v1/ontologies/attention-count")
    assert r.status_code in (401, 403)
