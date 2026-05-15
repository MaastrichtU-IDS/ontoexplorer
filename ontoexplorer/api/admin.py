"""Admin overview endpoint — aggregates service health, pipeline state, and recent jobs."""
from __future__ import annotations

import asyncio

import httpx
import redis as redis_sync
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings, is_admin
from ontoexplorer.database import get_db
from ontoexplorer.models.db import User
from ontoexplorer.modules.auth.dependencies import require_auth

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _require_admin(user: User = Depends(require_auth)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Service health checks ─────────────────────────────────────────────────────

async def _check_postgres(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _check_redis() -> str:
    try:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        r.ping()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_minio() -> str:
    s = get_settings()
    scheme = "https" if s.minio_secure else "http"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{scheme}://{s.minio_endpoint}/minio/health/live")
        return "ok" if resp.status_code == 200 else f"error: HTTP {resp.status_code}"
    except Exception as exc:
        return f"error: {exc}"


async def _check_elk() -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{get_settings().elk_service_url}/health")
        return "ok" if resp.status_code == 200 else f"error: HTTP {resp.status_code}"
    except Exception as exc:
        return f"error: {exc}"


def _celery_queue_depth() -> int:
    try:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        return r.llen("celery")
    except Exception:
        return -1


# ── Ontology pipeline status ──────────────────────────────────────────────────

def _elk_redis() -> redis_sync.Redis:
    """Connect to Redis DB 2 where ELK stores classification results."""
    base = get_settings().redis_url.rsplit("/", 1)[0]
    return redis_sync.from_url(f"{base}/2", decode_responses=True)


def _search_redis() -> redis_sync.Redis:
    return redis_sync.from_url(get_settings().redis_url, decode_responses=True)


async def _reasoning_status(version_id: str) -> str:
    """Return 'ready', 'running', or 'not_started' for a version."""
    # Fast path: check ELK Redis cache (DB 2)
    try:
        elk_r = await asyncio.to_thread(_elk_redis)
        if await asyncio.to_thread(elk_r.exists, f"classification:{version_id}"):
            return "ready"
    except Exception:
        pass

    # Slow path: call ELK service for non-ready versions
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{get_settings().elk_service_url}/classify/{version_id}"
            )
        if resp.status_code == 200:
            return "ready"
        if resp.status_code == 409:
            body = resp.text
            return "running" if "in progress" in body.lower() else "not_started"
    except Exception:
        pass
    return "not_started"


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.get("/overview", summary="Admin system overview")
async def admin_overview(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    # 1. Service health (concurrent)
    postgres_status, redis_status, minio_status, elk_status = await asyncio.gather(
        _check_postgres(db),
        asyncio.to_thread(_check_redis),
        _check_minio(),
        _check_elk(),
    )
    queue_depth = await asyncio.to_thread(_celery_queue_depth)

    # 2. Ontology pipeline — latest version per ontology
    rows = (await db.execute(
        text("""
            SELECT o.id, o.iri, o.shortname,
                   v.id AS version_id, v.triple_count, v.status AS ingestion_status,
                   v.created_at AS version_created_at,
                   mp.resolved AS meta_resolved
            FROM ontologies o
            JOIN versions v ON v.id = (
                SELECT id FROM versions WHERE ontology_id = o.id
                ORDER BY created_at DESC LIMIT 1
            )
            LEFT JOIN ontology_meta_profiles mp ON mp.version_id = v.id
            ORDER BY o.shortname NULLS LAST, o.iri
        """)
    )).mappings().all()

    search_r = await asyncio.to_thread(_search_redis)

    async def _onto_entry(row) -> dict:
        vid = row["version_id"]
        indexed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"search:meta:{vid}"))
        )
        reasoning = await _reasoning_status(vid)
        created = row["version_created_at"]
        meta_resolved = row["meta_resolved"] or {}
        label = meta_resolved.get("title") or None
        return {
            "id": row["id"],
            "iri": row["iri"],
            "shortname": row["shortname"],
            "label": label,
            "version_id": vid,
            "triple_count": row["triple_count"],
            "ingestion_status": row["ingestion_status"],
            "indexed": indexed,
            "reasoning_status": reasoning,
            "version_created_at": created.isoformat() if created else None,
        }

    ontologies = await asyncio.gather(*[_onto_entry(r) for r in rows])

    # 3. Recent jobs (last 50, with ontology shortname via join)
    job_rows = (await db.execute(
        text("""
            SELECT j.id, j.type, j.version_id, j.status,
                   j.started_at, j.finished_at, j.error, j.created_at,
                   o.shortname AS ontology_shortname, o.iri AS ontology_iri
            FROM jobs j
            JOIN versions v ON v.id = j.version_id
            JOIN ontologies o ON o.id = v.ontology_id
            ORDER BY j.created_at DESC
            LIMIT 50
        """)
    )).mappings().all()

    def _fmt(dt) -> str | None:
        return dt.isoformat() if dt else None

    jobs = [
        {
            "id": r["id"],
            "type": r["type"],
            "version_id": r["version_id"],
            "ontology_shortname": r["ontology_shortname"],
            "ontology_iri": r["ontology_iri"],
            "status": r["status"],
            "started_at": _fmt(r["started_at"]),
            "finished_at": _fmt(r["finished_at"]),
            "error": r["error"],
        }
        for r in job_rows
    ]

    return {
        "services": {
            "postgres": postgres_status,
            "redis": redis_status,
            "minio": minio_status,
            "elk": elk_status,
            "celery_queue_depth": queue_depth,
        },
        "ontologies": list(ontologies),
        "jobs": jobs,
    }


@router.post("/reindex", summary="Queue search re-index for all ingested versions")
async def admin_reindex(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue index_ontology tasks for every ingested version. Safe to run multiple times."""
    from ontoexplorer.modules.jobs.tasks import index_ontology
    from sqlalchemy.orm import joinedload
    from ontoexplorer.models.db import OntologyVersion

    result = await db.execute(
        text("""
            SELECT v.id AS version_id, v.ontology_id
            FROM versions v
            WHERE v.status = 'ingested'
            ORDER BY v.created_at DESC
        """)
    )
    rows = result.mappings().all()
    queued = 0
    for row in rows:
        index_ontology.delay(str(row["version_id"]), str(row["ontology_id"]))
        queued += 1
    return {"queued": queued, "message": f"Queued {queued} index_ontology tasks"}
