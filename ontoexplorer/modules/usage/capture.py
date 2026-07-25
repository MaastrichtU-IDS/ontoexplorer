"""Privacy-preserving capture of ontology view/download usage.

Design (see the usage-stats plan): Redis is the intra-day source of truth and
does dedup + counting; a Celery task flushes absolute counts to `usage_daily`.
NO raw IP/UA and NO per-visitor rows ever reach Postgres — the only per-visitor
artifact is an ephemeral Redis key (~48h TTL). Dedup uses a rotating daily salt
so hashes are correlatable only within one UTC day and only inside Redis.

Redis keys (all UTC-day scoped):
  usage:seen:{kind}:{ontology_id}:{yyyymmdd}:{visitor_hash}  -> "1"  (SET NX EX 48h)
  usage:counts:{yyyymmdd}  (hash) field "{kind}:{ontology_id}:{total|unique}"

record_usage is fire-and-forget: any error (Redis down, bad header) is swallowed
so it can never break a download or page load.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

import redis.asyncio as aioredis

from ontoexplorer.config import get_settings
from ontoexplorer.logging_config import get_logger

log = get_logger(__name__)

KIND_VIEW = "view"
KIND_DOWNLOAD = "download"

_SEEN_TTL_SECONDS = 172_800  # 48h — survives the UTC midnight boundary + flush lag

# Substrings that mark a non-human user agent. Case-insensitive.
_BOT_UA = (
    "bot", "crawl", "spider", "slurp", "headless", "python-requests",
    "curl", "wget", "httpx", "scrapy", "facebookexternalhit", "bingpreview",
    "monitor", "uptime", "pingdom", "gptbot",
)

_redis: aioredis.Redis | None = None


def _client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def _is_bot(ua: str) -> bool:
    ua = ua.lower()
    return not ua or any(sig in ua for sig in _BOT_UA)


def _do_not_track(request) -> bool:
    return request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1"


def _client_ip(request) -> str:
    # Behind the cluster ingress/egress proxy the peer is the proxy; the real
    # client chain is in X-Forwarded-For (first hop). Used only to compute an
    # ephemeral salted hash — never stored.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _visitor_hash(ip: str, ua: str, ontology_id: str, day: str) -> str:
    s = get_settings()
    secret = (s.usage_hash_salt or s.jwt_secret_key).encode()
    daily_salt = hmac.new(secret, day.encode(), hashlib.sha256).digest()
    msg = f"{ip}|{ua}|{ontology_id}|{day}".encode()
    return hmac.new(daily_salt, msg, hashlib.sha256).hexdigest()


async def record_usage(request, ontology_id: str, kind: str) -> None:
    """Record one view/download. Deduped per visitor per UTC day. Never raises."""
    try:
        if _do_not_track(request):
            return
        ua = request.headers.get("user-agent", "")
        if _is_bot(ua):
            return

        day = datetime.now(UTC).strftime("%Y%m%d")
        vhash = _visitor_hash(_client_ip(request), ua, ontology_id, day)

        r = _client()
        counts_key = f"usage:counts:{day}"
        # First hit of the day for this (visitor, kind, ontology)?
        is_new = await r.set(
            f"usage:seen:{kind}:{ontology_id}:{day}:{vhash}", "1",
            nx=True, ex=_SEEN_TTL_SECONDS,
        )
        pipe = r.pipeline(transaction=False)
        pipe.hincrby(counts_key, f"{kind}:{ontology_id}:total", 1)
        if is_new:
            pipe.hincrby(counts_key, f"{kind}:{ontology_id}:unique", 1)
        # Keep the day hash alive well past its UTC day so the flush always sees
        # final counts; it is overwritten idempotently, not deleted.
        pipe.expire(counts_key, _SEEN_TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # never let stats break the request
        log.debug("record_usage skipped (%s): %s", kind, exc)
