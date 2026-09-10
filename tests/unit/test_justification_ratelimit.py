"""Per-user rate limits on justification requests.

Justification dispatches an OWL job bounded at an 11-minute time_limit on the
reasoner pool; one user could otherwise queue many at once and starve reasoning
for everyone. These pin both limits and their order.
"""
import uuid

import pytest
from fastapi import HTTPException

from ontoexplorer.models.db import Job, User
from ontoexplorer.modules.jobs import justification_limits
from ontoexplorer.modules.jobs.justification_limits import enforce_justification_limits


def _user():
    return User(id=str(uuid.uuid4()), email=f"u-{uuid.uuid4()}@ex.org", display_name="U")


async def _add_jobs(db, user_id, *, jtype="justification", status="running", n=1):
    for _ in range(n):
        db.add(Job(id=str(uuid.uuid4()), version_id=str(uuid.uuid4()),
                   type=jtype, status=status, user_id=user_id))
    await db.commit()


@pytest.fixture(autouse=True)
def _no_daily_limit(monkeypatch):
    """Default: daily counter well under the ceiling, and no real Redis."""
    monkeypatch.setattr(justification_limits, "_incr_daily", lambda uid: 1)


@pytest.mark.anyio
async def test_under_both_limits_passes(db_session):
    user = _user(); db_session.add(user); await db_session.commit()
    await _add_jobs(db_session, user.id, n=1)          # 1 in-flight, cap is 2
    await enforce_justification_limits(db_session, user)  # no raise


@pytest.mark.anyio
async def test_inflight_cap_blocks_at_limit(db_session, monkeypatch):
    monkeypatch.setattr(justification_limits.get_settings(), "justification_max_inflight", 2, raising=False)
    user = _user(); db_session.add(user); await db_session.commit()
    await _add_jobs(db_session, user.id, status="running", n=1)
    await _add_jobs(db_session, user.id, status="pending", n=1)   # 2 active => at cap
    with pytest.raises(HTTPException) as ei:
        await enforce_justification_limits(db_session, user)
    assert ei.value.status_code == 429
    assert "in progress" in ei.value.detail


@pytest.mark.anyio
async def test_inflight_ignores_other_users_types_and_finished(db_session):
    user = _user(); other = _user()
    db_session.add_all([user, other]); await db_session.commit()
    await _add_jobs(db_session, other.id, n=5)                         # another user
    await _add_jobs(db_session, user.id, jtype="reasoning", n=5)       # different type
    await _add_jobs(db_session, user.id, status="done", n=5)           # finished
    await _add_jobs(db_session, user.id, status="failed", n=5)         # finished
    await enforce_justification_limits(db_session, user)               # none count => passes


@pytest.mark.anyio
async def test_daily_ceiling_blocks_when_exceeded(db_session, monkeypatch):
    monkeypatch.setattr(justification_limits, "_incr_daily",
                        lambda uid: 201)   # over default 200
    user = _user(); db_session.add(user); await db_session.commit()
    with pytest.raises(HTTPException) as ei:
        await enforce_justification_limits(db_session, user)
    assert ei.value.status_code == 429
    assert "Daily" in ei.value.detail


@pytest.mark.anyio
async def test_inflight_checked_before_daily(db_session, monkeypatch):
    """A burst rejected by the in-flight cap must not consume the daily budget."""
    monkeypatch.setattr(justification_limits.get_settings(), "justification_max_inflight", 1, raising=False)
    called = {"daily": False}
    def _spy(uid):
        called["daily"] = True
        return 1
    monkeypatch.setattr(justification_limits, "_incr_daily", _spy)
    user = _user(); db_session.add(user); await db_session.commit()
    await _add_jobs(db_session, user.id, n=1)   # at cap of 1
    with pytest.raises(HTTPException):
        await enforce_justification_limits(db_session, user)
    assert called["daily"] is False, "daily counter incremented despite in-flight rejection"


@pytest.mark.anyio
async def test_daily_check_fails_open_when_redis_down(db_session, monkeypatch):
    """A Redis outage must not 500 the endpoint — the in-flight cap still holds."""
    def _boom(uid):
        raise ConnectionError("redis down")
    monkeypatch.setattr(justification_limits, "_incr_daily", _boom)
    user = _user(); db_session.add(user); await db_session.commit()
    await enforce_justification_limits(db_session, user)   # no raise, no in-flight jobs
