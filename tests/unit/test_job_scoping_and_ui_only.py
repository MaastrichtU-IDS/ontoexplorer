"""Jobs belong to whoever submitted them; justification backs the UI only."""

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from ontoexplorer.models.db import ApiKey, Job, User


@pytest.fixture(autouse=True)
def _identity_is_real(monkeypatch):
    from ontoexplorer.config import get_settings
    monkeypatch.setattr(get_settings(), "auth_bypass", False, raising=False)


async def _user_with_key(db, scopes=("read", "write")) -> tuple[User, str]:
    raw = f"oe_test_{uuid.uuid4().hex}"
    u = User(id=str(uuid.uuid4()), email=f"u-{uuid.uuid4()}@example.com", display_name="Somebody")
    db.add(u)
    db.add(ApiKey(id=str(uuid.uuid4()), user_id=u.id, name="k",
                  key_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=list(scopes)))
    await db.commit()
    return u, raw


async def _job(db, *, owner: User | None, jid: str | None = None) -> Job:
    j = Job(id=jid or str(uuid.uuid4()), version_id=None, type="ingestion",
            status="done", created_at=datetime.now(UTC),
            user_id=owner.id if owner else None)
    db.add(j)
    await db.commit()
    return j


def _auth(k): return {"Authorization": f"Bearer {k}"}


@pytest.mark.anyio
async def test_listing_hides_another_users_jobs(client, db_session):
    mine_user, mine_key = await _user_with_key(db_session)
    other, _ = await _user_with_key(db_session)
    await _job(db_session, owner=mine_user)
    await _job(db_session, owner=other)

    r = await client.get("/api/v1/jobs?limit=100", headers=_auth(mine_key))
    assert r.status_code == 200
    owners = {j["id"] for j in r.json()["jobs"]}
    mine = {j["id"] for j in r.json()["jobs"]}
    assert mine == owners  # sanity
    # every returned row must be mine
    from sqlalchemy import select
    rows = (await db_session.execute(select(Job).where(Job.id.in_(owners)))).scalars().all()
    assert all(row.user_id == mine_user.id for row in rows)


@pytest.mark.anyio
async def test_system_jobs_are_not_public(client, db_session):
    """A NULL submitter means beat started it. Unknown owner is not public."""
    _u, key = await _user_with_key(db_session)
    orphan = await _job(db_session, owner=None)

    r = await client.get("/api/v1/jobs?limit=100", headers=_auth(key))
    assert orphan.id not in {j["id"] for j in r.json()["jobs"]}


@pytest.mark.anyio
async def test_fetching_another_users_job_by_id_is_a_404_not_a_403(client, db_session):
    """403 would confirm the id exists, and these are Celery task ids."""
    _mine, mine_key = await _user_with_key(db_session)
    other, _ = await _user_with_key(db_session)
    theirs = await _job(db_session, owner=other)

    r = await client.get(f"/api/v1/jobs/{theirs.id}", headers=_auth(mine_key))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_submitter_can_still_poll_their_own_job(client, db_session):
    """The UI polls GET /jobs/{task_id} after an ingest; that must keep working."""
    mine_user, mine_key = await _user_with_key(db_session)
    j = await _job(db_session, owner=mine_user)

    r = await client.get(f"/api/v1/jobs/{j.id}", headers=_auth(mine_key))
    assert r.status_code == 200
    assert r.json()["status"] == "done"


@pytest.mark.anyio
async def test_anonymous_listing_is_empty_rather_than_everything(client, db_session):
    await _job(db_session, owner=None)
    r = await client.get("/api/v1/jobs?limit=100")
    assert r.status_code == 200
    assert r.json()["jobs"] == []


@pytest.mark.anyio
async def test_api_keys_cannot_reach_justification(client, db_session):
    """It queues work on a single-concurrency worker and exists to serve the UI."""
    _u, key = await _user_with_key(db_session)
    r = await client.get(
        "/api/v1/ontologies/00000000-0000-0000-0000-000000000000/"
        "11111111-1111-1111-1111-111111111111/justification?sub=http://a&sup=http://b",
        headers=_auth(key),
    )
    assert r.status_code == 403
    assert "web interface" in r.json()["detail"]


@pytest.mark.anyio
async def test_the_incremental_api_is_no_longer_served(client):
    r = await client.post(
        "/api/v1/ontologies/00000000-0000-0000-0000-000000000000/"
        "11111111-1111-1111-1111-111111111111/incremental"
    )
    assert r.status_code == 404
