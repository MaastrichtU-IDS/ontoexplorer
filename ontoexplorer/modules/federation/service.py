"""Federation service: concurrent fan-out to peers, cached, partial-failure safe.

``federated_artefacts`` queries every configured peer in parallel under an
overall time budget. A peer that is slow, unauthorised or broken never fails
the request: it becomes a :class:`CatalogueStatus` (``timeout`` / ``error``)
and contributes zero rows. Peer responses are cached in Redis (best-effort:
any Redis problem is treated as a cache miss / skipped write).

Remote rows whose IRI is already in the local catalogue are dropped (local is
authoritative); the rest are appended grouped by peer in the given peer order,
preserving each peer's own ranking and capped at ``limit`` per peer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from ontoexplorer.config import get_settings
from ontoexplorer.modules.federation import client
from ontoexplorer.modules.federation.client import FederationFetchError
from ontoexplorer.modules.federation.config import Peer, get_federation_peers
from ontoexplorer.modules.federation.models import ArtefactRow, CatalogueStatus

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "federation"


def _redis():
    from ontoexplorer.modules.search.indexer import _get_redis

    return _get_redis()


def _cache_key(peer_id: str, q: str) -> str:
    digest = hashlib.sha256(q.strip().lower().encode("utf-8")).hexdigest()
    return f"{_CACHE_PREFIX}:{peer_id}:{digest}"


def _cache_get(key: str) -> list[ArtefactRow] | None:
    try:
        raw = _redis().get(key)
        if not raw:
            return None
        return [ArtefactRow.model_validate(d) for d in json.loads(raw)]
    except Exception as exc:  # best-effort: any cache problem is a miss
        logger.debug("federation cache read failed for %s: %s", key, exc)
        return None


def _cache_set(key: str, rows: list[ArtefactRow], ttl: int) -> None:
    try:
        payload = json.dumps([r.model_dump(mode="json") for r in rows])
        _redis().setex(key, ttl, payload)
    except Exception as exc:  # best-effort
        logger.debug("federation cache write failed for %s: %s", key, exc)


async def _one_peer(peer: Peer, q: str, limit: int) -> list[ArtefactRow]:
    """Cache-then-live fetch for one peer. Raises on live-fetch failure."""
    key = _cache_key(peer.id, q)
    cached = await asyncio.to_thread(_cache_get, key)
    if cached is not None:
        return cached
    rows = await client.search_artefacts(peer, q, limit)
    await asyncio.to_thread(_cache_set, key, rows, get_settings().federation_cache_ttl_s)
    return rows


async def _timed(peer: Peer, q: str, limit: int) -> tuple[list[ArtefactRow], int]:
    t0 = time.monotonic()
    rows = await _one_peer(peer, q, limit)
    return rows, int((time.monotonic() - t0) * 1000)


async def federated_artefacts(
    q: str,
    local_iris: set[str],
    peers: list[Peer] | None = None,
    limit: int | None = None,
) -> tuple[list[ArtefactRow], list[CatalogueStatus]]:
    """Query all peers for ``q``; return ``(remote_only_rows, per_peer_statuses)``.

    Never raises because of a peer. Statuses are in peer order, one per peer.
    ``CatalogueStatus.count`` is the number of rows actually returned after
    local-dedup and the per-peer cap; ``status`` reflects the peer's own
    outcome (``empty`` = peer answered with zero rows).
    """
    settings = get_settings()
    if peers is None:
        peers = get_federation_peers()
    if limit is None:
        limit = settings.federation_max_results_per_peer
    if not peers:
        return [], []

    budget_s = settings.federation_fanout_timeout_ms / 1000.0
    started = time.monotonic()
    tasks = [asyncio.ensure_future(_timed(p, q, limit)) for p in peers]
    try:
        # Backstop: peers still running at the overall budget are cancelled and
        # reported as "timeout"; completed peers keep their results.
        _done, pending = await asyncio.wait(tasks, timeout=budget_s)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise

    rows: list[ArtefactRow] = []
    statuses: list[CatalogueStatus] = []
    overall_ms = int((time.monotonic() - started) * 1000)
    for peer, task in zip(peers, tasks):
        if task.cancelled():
            statuses.append(
                CatalogueStatus(id=peer.id, label=peer.label, status="timeout", took_ms=overall_ms)
            )
            continue
        exc = task.exception()
        if exc is not None:
            is_timeout = isinstance(exc, FederationFetchError) and exc.reason == "timeout"
            if not is_timeout:
                logger.warning("federation: peer %s failed: %r", peer.id, exc)
            statuses.append(
                CatalogueStatus(
                    id=peer.id,
                    label=peer.label,
                    status="timeout" if is_timeout else "error",
                    took_ms=overall_ms,
                )
            )
            continue
        fetched, took_ms = task.result()
        kept = [r for r in fetched if r.iri not in local_iris][:limit]
        rows.extend(kept)
        statuses.append(
            CatalogueStatus(
                id=peer.id,
                label=peer.label,
                status="ok" if fetched else "empty",
                count=len(kept),
                took_ms=took_ms,
            )
        )
    return rows, statuses
