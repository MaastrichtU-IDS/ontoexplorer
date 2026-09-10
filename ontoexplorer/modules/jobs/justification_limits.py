"""Per-user rate limits for justification requests.

Justification is session-only (require_auth + reject_api_key_auth) but one cheap
POST dispatches an OWL justification job bounded at an 11-minute hard time_limit
on the reasoner pool. Without a limit, a single user can queue many at once and
starve reasoning for everyone. Two limits, checked in this order:

  1. In-flight cap — how many of this user's justification jobs are pending or
     running right now. This is the one that matters: the scarce resource is
     simultaneous long jobs, and a daily count does nothing against a burst
     launched in one second. It self-heals — a crashed job is bounded by the
     task's time_limit and the worker-restart sweep that marks orphaned running
     jobs failed — so the count cannot leak slots indefinitely.
  2. Daily ceiling — a Redis counter that resets at midnight UTC, as a backstop
     against slow-drip sustained abuse that never trips the in-flight cap.

Both raise 429 with a Retry-After. The in-flight check runs first so a rejected
burst does not consume the daily budget.
"""

import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import Job, User

logger = get_logger(__name__)

_JOB_TYPE = "justification"
_ACTIVE = ("pending", "running")


async def _inflight_count(db: AsyncSession, user_id: str) -> int:
    stmt = (
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user_id, Job.type == _JOB_TYPE, Job.status.in_(_ACTIVE))
    )
    return int((await db.execute(stmt)).scalar_one())


def _seconds_until_midnight() -> int:
    now = datetime.now(UTC)
    return max((24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second), 1)


def _incr_daily(user_id: str) -> int:
    """Increment today's per-user counter, expiring it at midnight UTC."""
    from ontoexplorer.modules.search.indexer import _get_redis

    r = _get_redis()
    key = f"ratelimit:justify:{user_id}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, _seconds_until_midnight())
    return count


async def enforce_justification_limits(db: AsyncSession, user: User) -> None:
    """Raise 429 if `user` is over the in-flight cap or the daily ceiling."""
    settings = get_settings()

    inflight = await _inflight_count(db, user.id)
    if inflight >= settings.justification_max_inflight:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You already have {inflight} justification job(s) in progress "
                f"(limit {settings.justification_max_inflight}); wait for one to finish."
            ),
            headers={"Retry-After": "30"},
        )

    # The daily ceiling is a backstop; the in-flight cap above is the real
    # protection and needs no Redis. So if Redis is unavailable, fail open on the
    # ceiling rather than 500 the endpoint — a rate-limit outage must not take
    # justification down with it.
    try:
        count = await asyncio.to_thread(_incr_daily, user.id)
    except Exception:
        logger.warning("justification daily-limit check skipped: redis unavailable")
        return
    if count > settings.justification_daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily justification limit ({settings.justification_daily_limit}) reached.",
            headers={"Retry-After": str(_seconds_until_midnight())},
        )
