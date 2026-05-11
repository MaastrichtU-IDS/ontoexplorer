"""Redis-backed classification result cache."""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import asdict

import redis

from classifier import ClassificationResult

_CLASSIFICATION_TTL = int(os.getenv("CLASSIFICATION_TTL_SECONDS", str(30 * 24 * 3600)))
_JUSTIFICATION_TTL  = int(os.getenv("JUSTIFICATION_TTL_SECONDS",  str(7  * 24 * 3600)))
_REDIS_URL          = os.getenv("REDIS_URL", "redis://localhost:6379/2")

_redis: redis.Redis = redis.from_url(_REDIS_URL, decode_responses=False)


def _classification_key(version_id: str) -> str:
    return f"classification:{version_id}"


def _justification_key(version_id: str, sub: str, sup: str | None, max_j: int) -> str:
    import hashlib
    raw = f"{sub}|{sup}|{max_j}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"justification:{version_id}:{h}"


def store_classification(result: ClassificationResult) -> None:
    key = _classification_key(result.version_id)
    data = json.dumps(asdict(result)).encode()
    compressed = gzip.compress(data)
    _redis.setex(key, _CLASSIFICATION_TTL, compressed)


def load_classification(version_id: str) -> ClassificationResult | None:
    key = _classification_key(version_id)
    raw = _redis.get(key)
    if raw is None:
        return None
    data = json.loads(gzip.decompress(raw))
    return ClassificationResult(**data)


def store_justification(version_id: str, sub: str, sup: str | None, max_j: int, result: dict) -> None:
    key = _justification_key(version_id, sub, sup, max_j)
    _redis.setex(key, _JUSTIFICATION_TTL, json.dumps(result).encode())


def load_justification(version_id: str, sub: str, sup: str | None, max_j: int) -> dict | None:
    key = _justification_key(version_id, sub, sup, max_j)
    raw = _redis.get(key)
    return json.loads(raw) if raw else None


def invalidate_version(version_id: str) -> None:
    """Remove all cache entries for a version (called on deprecation)."""
    pattern = f"*:{version_id}:*"
    keys = list(_redis.scan_iter(pattern))
    keys.append(_classification_key(version_id).encode())
    if keys:
        _redis.delete(*keys)
