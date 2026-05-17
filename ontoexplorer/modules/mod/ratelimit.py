import asyncio
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status

from ontoexplorer.config import get_settings
from ontoexplorer.modules.auth.dependencies import get_current_user


def _get_redis():
    from ontoexplorer.modules.search.indexer import _get_redis as _base_get_redis
    return _base_get_redis()


def _increment_and_check(key: str, limit: int) -> int:
    r = _get_redis()
    count = r.incr(key)
    if count == 1:
        now = datetime.now(UTC)
        seconds_until_midnight = (24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second)
        r.expire(key, max(seconds_until_midnight, 1))
    return count


async def mod_rate_limit(
    request: Request,
    user=Depends(get_current_user),
) -> None:
    settings = get_settings()
    if user is not None:
        key = f"ratelimit:mod:key:{user.id}"
        limit = settings.mod_rate_limit_auth
    else:
        ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:mod:ip:{ip}"
        limit = settings.mod_rate_limit_anon

    count = await asyncio.to_thread(_increment_and_check, key, limit)

    if count > limit:
        now = datetime.now(UTC)
        retry_after = (24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Use an API key for higher limits.",
            headers={"Retry-After": str(retry_after)},
        )
