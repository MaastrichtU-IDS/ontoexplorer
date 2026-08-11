"""Shared helpers and dependencies for the admin endpoints."""
from __future__ import annotations

import asyncio

import httpx
import redis as redis_sync
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings, is_admin
from ontoexplorer.models.db import User
from ontoexplorer.modules.auth.dependencies import require_auth

_RDF_ACCEPT = (
    "application/owl+xml;q=1.0,"
    "text/turtle;q=0.9,"
    "application/rdf+xml;q=0.8,"
    "application/ld+json;q=0.7,"
    "application/n-triples;q=0.6,"
    "text/plain;q=0.5"
)


def _require_admin(user: User = Depends(require_auth)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _elk_redis() -> redis_sync.Redis:
    """Connect to Redis DB 2 where ELK stores classification results."""
    base = get_settings().redis_url.rsplit("/", 1)[0]
    return redis_sync.from_url(f"{base}/2", decode_responses=True)


def _search_redis() -> redis_sync.Redis:
    return redis_sync.from_url(get_settings().redis_url, decode_responses=True)


async def _reasoning_status(version_id: str, reasoner: str | None = None) -> str:
    """Return 'ready', 'running', or 'not_started' for a version.

    The reasoner-service caches classification per (version, reasoner) under
    `classification:{vid}:{reasoner}` (DB 2). We check that first for the
    version's current reasoner; the bare `classification:{vid}` is a legacy
    fallback, and a scan covers any reasoner as a last resort.
    """
    try:
        elk_r = await asyncio.to_thread(_elk_redis)
        if reasoner and await asyncio.to_thread(elk_r.exists, f"classification:{version_id}:{reasoner}"):
            return "ready"
        if await asyncio.to_thread(elk_r.exists, f"classification:{version_id}"):
            return "ready"
        hit = await asyncio.to_thread(
            lambda: next(elk_r.scan_iter(match=f"classification:{version_id}:*", count=50), None)
        )
        if hit is not None:
            return "ready"
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{get_settings().reasoner_service_url}/classify/{version_id}"
            )
        if resp.status_code == 200:
            return "ready"
        if resp.status_code == 409:
            body = resp.text
            return "running" if "in progress" in body.lower() else "not_started"
    except Exception:
        pass
    return "not_started"


async def _diff_status_for_pair(db: AsyncSession, from_vid: str, to_vid: str) -> dict:
    """Return the diff-pipeline status for an ordered (from, to) version pair.

    Status semantics:
      - 'missing'  — no OntologyDiff row exists for this pair
      - 'pending'  — OntologyDiff.status == 'pending'
      - 'running'  — there is a running Job(type='diff') for either version (rare;
                     compute_diff doesn't always insert a Job, so primarily we
                     trust OntologyDiff.status)
      - 'failed'   — OntologyDiff.status == 'failed'
      - 'stale'    — OntologyDiff.status == 'ready' BUT summary.inferred_status
                     shows a side != 'ready' while that side's reasoning Job is
                     now 'done' (Phase 4 stale-detection condition)
      - 'ready'    — OntologyDiff.status == 'ready' and not stale
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Job, OntologyDiff

    diff = (await db.execute(
        select(OntologyDiff).where(
            OntologyDiff.version_from_id == from_vid,
            OntologyDiff.version_to_id == to_vid,
        )
    )).scalar_one_or_none()

    if diff is None:
        return {"status": "missing", "diff_id": None, "computed_at": None}

    base = {
        "diff_id": diff.id,
        "computed_at": diff.created_at.isoformat() if diff.created_at else None,
    }

    if diff.status in ("pending", "running", "failed"):
        return {"status": diff.status, **base}

    inferred = (diff.summary or {}).get("inferred_status", {})
    for side, vid in (("from_version", from_vid), ("to_version", to_vid)):
        if inferred.get(side) != "ready":
            reason_done = (await db.execute(
                select(Job).where(
                    Job.version_id == vid,
                    Job.type == "reason",
                    Job.status == "done",
                ).limit(1)
            )).scalar_one_or_none()
            if reason_done is not None:
                return {"status": "stale", **base}

    return {"status": "ready", **base}


async def _load_version(db: AsyncSession, version_id: str):
    """Load an OntologyVersion by id or raise 404."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    v = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return v
