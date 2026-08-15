"""HTTP client for the ELK reasoning service (v2)."""
from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import time
import httpx
import rdflib

from ontoexplorer.config import get_settings

log = logging.getLogger(__name__)


class ReasoningFailed(Exception):
    """The reasoner-service recorded a deterministic classification failure for
    this (version, reasoner) — a backend crash/OOM, an unsupported-axiom error,
    or a classification timeout. Surfaced by classify_v2 (GET /classify → 500
    'Classification failed: …') so callers can fail fast instead of retrying a
    doomed classification."""

# In-process cache for get_classification: avoids re-fetching the (often 40+ MB)
# classification JSON on every inferred-tree or MOS-search request.
# Keyed by version_id → (fetched_at, data). TTL is 10 minutes; classification
# results are immutable once computed so this is safe.
_CLASSIFICATION_CACHE: dict[str, tuple[float, dict]] = {}
_CLASSIFICATION_LOCKS: dict[str, asyncio.Lock] = {}
_CLASSIFICATION_TTL = 600.0  # seconds

# Per-IRI ELK sub/superclass results are also immutable for the lifetime of the
# version, so we cache them in Redis with a long TTL. Invalidated whenever
# `invalidate_cache(version_id)` runs (i.e. on deprecation / re-ingest).
_ELK_SUBSUP_TTL = 24 * 3600  # 24 hours


def _elk_url(path: str) -> str:
    return f"{get_settings().reasoner_service_url}{path}"


_KNOWN_REASONERS = {"rdflib", "rustdl", "konclude"}


async def list_reasoners() -> list[dict]:
    """Return the reasoner-service /reasoners payload."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_elk_url("/reasoners"))
        resp.raise_for_status()
        return resp.json()


async def available_reasoner_names() -> set[str]:
    """Names of reasoners reporting available=true. Falls back to the known set
    if the reasoner-service can't be reached (validation must not block ingest)."""
    try:
        return {r["name"] for r in await list_reasoners() if r.get("available")}
    except Exception:
        log.warning("reasoners_unreachable_fallback_to_known_names")
        return set(_KNOWN_REASONERS)


def _elk_cache_key(kind: str, version_id: str, class_iri: str, direct: bool, reasoner: str) -> str:
    h = hashlib.blake2b(class_iri.encode(), digest_size=10).hexdigest()
    return f"elk:{kind}:{version_id}:{reasoner}:{int(direct)}:{h}"


def _get_redis_client():
    # Lazy import to avoid a hard dependency cycle (indexer also imports from here).
    from ontoexplorer.modules.search.indexer import _get_redis
    return _get_redis()


async def classify_v2(
    graph: rdflib.Graph,
    version_id: str,
    reasoner: str = "rustdl",
    params: dict | None = None,
    force: bool = False,
) -> dict:
    """
    POST N-Triples to ELK service (returns 202 immediately), then poll until done.
    Max wait is reasoner_service_timeout seconds (default 3600); raises TimeoutError if exceeded.

    Re-submits the job every RESUBMIT_INTERVAL seconds if still getting 409 — this handles
    ELK service restarts that clear the in-progress set but not the Redis cache.

    ``params`` is the reasoner profile's parameter dict (e.g. rustdl
    {saturation_only, per_pair_timeout_ms, global_timeout_ms}, km {route}); each
    backend reads the keys it knows. ``force`` invalidates any cached
    classification first so changed params take effect — applied only to the
    initial submit, never the periodic re-POSTs (which would otherwise discard a
    result that completed mid-poll).
    """
    params = params or {}
    ntriples = graph.serialize(format="nt")
    RESUBMIT_INTERVAL = 120  # re-POST if job still missing after this many seconds

    async def _submit(force_now: bool) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(_elk_url("/classify"),
                                     json={"ntriples": ntriples, "version_id": version_id,
                                           "reasoner": reasoner, "params": params,
                                           "force": force_now,
                                           # deprecated alias for a rolling deploy window
                                           "saturation_only": bool(params.get("saturation_only", False))})
            resp.raise_for_status()
            return resp.json()

    posted = await _submit(force)

    # If already cached (status="done"), we're done
    if posted.get("status") == "done":
        return posted

    # Poll GET /classify/{version_id} until 200 or timeout
    max_wait = get_settings().reasoner_service_timeout
    poll_interval = 5
    elapsed = 0
    last_resubmit = 0

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        # Re-POST periodically to recover from ELK restarts that lose the in-progress state
        if elapsed - last_resubmit >= RESUBMIT_INTERVAL:
            last_resubmit = elapsed
            posted = await _submit(False)
            if posted.get("status") == "done":
                break

        async with httpx.AsyncClient(timeout=30.0) as client:
            poll = await client.get(_elk_url(f"/classify/{version_id}?reasoner={reasoner}"))
        if poll.status_code == 200:
            return poll.json()
        if poll.status_code == 500:
            # The service recorded a deterministic classification failure (crash,
            # OOM, unsupported axioms, or its own timeout). Retrying just re-runs
            # the same doomed classification, so fail fast with a distinct error.
            detail = ""
            try:
                detail = poll.json().get("detail", "")
            except Exception:
                detail = (poll.text or "")[:500]
            if "Classification failed" in detail:
                raise ReasoningFailed(detail)
        if poll.status_code != 409:
            poll.raise_for_status()

    raise TimeoutError(f"ELK classification for {version_id} did not complete within {max_wait}s")


# ── Incremental EL++ reasoning sessions (km) — thin proxies to the reasoner-service ──

async def incremental_create(version_id: str, reasoner: str) -> dict:
    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(_elk_url("/incremental"),
                                 json={"version_id": version_id, "reasoner": reasoner})
        resp.raise_for_status()
        return resp.json()


async def incremental_subsumed(session_id: str, sub: str, sup: str) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(_elk_url(f"/incremental/{session_id}/subsumed"),
                                 json={"sub": sub, "sup": sup})
        resp.raise_for_status()
        return resp.json()


async def incremental_assert(session_id: str, sub: str, sup: str) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(_elk_url(f"/incremental/{session_id}/assert"),
                                 json={"sub": sub, "sup": sup})
        resp.raise_for_status()
        return resp.json()


async def incremental_close(session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(_elk_url(f"/incremental/{session_id}"))
        resp.raise_for_status()
        return resp.json()


async def superclasses(version_id: str, class_iri: str, direct: bool = False, reasoner: str = "rustdl") -> dict:
    """Return all (or direct-only) inferred superclasses of class_iri.

    Cached in Redis under `elk:super:{version_id}:…` with a 24-hour TTL.
    Per-IRI inferred sets are immutable for the lifetime of a version, so any
    repeat lookup within a browsing session is served from cache.
    """
    r = _get_redis_client()
    key = _elk_cache_key("super", version_id, class_iri, direct, reasoner)
    cached = await asyncio.to_thread(r.get, key)
    if cached:
        return _json.loads(cached)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _elk_url(f"/classify/{version_id}/superclasses"),
            params={"cls": class_iri, "direct": str(direct).lower(), "reasoner": reasoner},
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        if resp.status_code == 404:
            raise ClassNotFoundError(class_iri)
        resp.raise_for_status()
    data = resp.json()
    await asyncio.to_thread(r.set, key, _json.dumps(data), _ELK_SUBSUP_TTL)
    return data


async def subclasses(version_id: str, class_iri: str, direct: bool = False, reasoner: str = "rustdl") -> dict:
    """Return all (or direct-only) inferred subclasses of class_iri.

    Cached identically to `superclasses` — see that docstring.
    """
    r = _get_redis_client()
    key = _elk_cache_key("sub", version_id, class_iri, direct, reasoner)
    cached = await asyncio.to_thread(r.get, key)
    if cached:
        return _json.loads(cached)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _elk_url(f"/classify/{version_id}/subclasses"),
            params={"cls": class_iri, "direct": str(direct).lower(), "reasoner": reasoner},
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        if resp.status_code == 404:
            raise ClassNotFoundError(class_iri)
        resp.raise_for_status()
    data = resp.json()
    await asyncio.to_thread(r.set, key, _json.dumps(data), _ELK_SUBSUP_TTL)
    return data


async def consistency(version_id: str, reasoner: str = "rustdl") -> dict:
    """Return consistency check result including unsatisfiable classes."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_elk_url(f"/classify/{version_id}/consistency?reasoner={reasoner}"))
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
    return resp.json()


async def request_justification(
    version_id: str,
    sub: str,
    sup: str | None,
    max_justifications: int = 1,
    reasoner: str = "rustdl",
    cache_only: bool = False,
) -> dict:
    """
    Request justification computation from the reasoner service.

    With ``cache_only`` the service returns the cached result if present, or a
    ``{"cached": False}`` miss marker without computing — cheap enough to call
    from a live HTTP handler. Without it the call is long-running and must be
    driven from a Celery task, never an HTTP handler.
    """
    body: dict = {"sub": sub, "max_justifications": max_justifications, "reasoner": reasoner}
    if sup:
        body["sup"] = sup
    else:
        body["type"] = "unsatisfiable"
    if cache_only:
        body["cache_only"] = True

    # A cache peek is a fast Redis read; the full compute needs the long buffer.
    timeout = 10 if cache_only else get_settings().reasoner_service_timeout + 60
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            _elk_url(f"/classify/{version_id}/justification"),
            json=body,
        )
        if resp.status_code == 422:
            detail = resp.json().get("detail", "reasoner does not support justifications")
            return {"justifications": [], "reasoning_available": False, "reason": detail}
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
    return resp.json()


async def invalidate_cache(version_id: str) -> None:
    """Invalidate ELK in-process cache, Redis sub/super cache, and ELK-side cache."""
    _CLASSIFICATION_CACHE.pop(version_id, None)
    _CLASSIFICATION_LOCKS.pop(version_id, None)

    # Drop the per-IRI sub/super Redis cache for this version.
    def _drop_elk_keys() -> None:
        r = _get_redis_client()
        for kind in ("sub", "super"):
            for k in r.scan_iter(f"elk:{kind}:{version_id}:*", count=500):
                r.delete(k)

    await asyncio.to_thread(_drop_elk_keys)

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.delete(_elk_url(f"/classify/{version_id}"))


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_elk_url("/health"))
            return resp.status_code == 200 and resp.json().get("redis") == "ok"
    except Exception:
        return False


async def get_classification(version_id: str, reasoner: str = "rustdl") -> dict:
    """Fetch the full ClassificationResult JSON from the ELK service cache.

    Returns the raw dict with keys: superclasses, subclasses, direct_superclasses,
    direct_subclasses, unsatisfiable, class_count, proof_traces, etc.

    Results are cached in-process for _CLASSIFICATION_TTL seconds to avoid
    repeatedly fetching large (40+ MB) payloads on every tree or search request.
    The cache is keyed by version_id alone (not reasoner) since a version's
    reasoner is immutable, so version_id -> reasoner is a 1:1 mapping.

    Raises ReasoningNotReadyError if the version has not been classified yet.
    """
    now = time.monotonic()
    cached = _CLASSIFICATION_CACHE.get(version_id)
    if cached and (now - cached[0]) < _CLASSIFICATION_TTL:
        return cached[1]

    # Per-version lock prevents a thundering herd when multiple requests arrive
    # simultaneously for the same uncached version.
    if version_id not in _CLASSIFICATION_LOCKS:
        _CLASSIFICATION_LOCKS[version_id] = asyncio.Lock()
    async with _CLASSIFICATION_LOCKS[version_id]:
        # Re-check under lock in case another coroutine just populated it.
        cached = _CLASSIFICATION_CACHE.get(version_id)
        if cached and (now - cached[0]) < _CLASSIFICATION_TTL:
            return cached[1]

        url = f"{_elk_url('')}/classify/{version_id}?reasoner={reasoner}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
        if resp.status_code in (404, 409):
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
        data = resp.json()
        _CLASSIFICATION_CACHE[version_id] = (time.monotonic(), data)
        return data


class ReasoningNotReadyError(Exception):
    def __init__(self, version_id: str):
        super().__init__(f"Reasoning not yet completed for version {version_id}")
        self.version_id = version_id


class ClassNotFoundError(Exception):
    def __init__(self, class_iri: str):
        super().__init__(f"Class {class_iri} not found in classification index")
        self.class_iri = class_iri
