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
    try:
        elk_r = await asyncio.to_thread(_elk_redis)
        if await asyncio.to_thread(elk_r.exists, f"classification:{version_id}"):
            return "ready"
    except Exception:
        pass

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


# ── Overview ──────────────────────────────────────────────────────────────────

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
            SELECT o.id, o.iri, o.shortname, o.title AS ont_title,
                   v.id AS version_id, v.triple_count, v.status AS ingestion_status,
                   v.created_at AS version_created_at, v.source_url,
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

    # Embedding counts per version in one query
    version_ids = [str(r["version_id"]) for r in rows]
    embed_counts: dict[str, int] = {}
    if version_ids:
        count_rows = (await db.execute(
            text("""
                SELECT version_id, COUNT(*) AS cnt
                FROM term_embeddings
                WHERE version_id = ANY(:ids)
                GROUP BY version_id
            """),
            {"ids": version_ids},
        )).all()
        embed_counts = {str(r.version_id): int(r.cnt) for r in count_rows}

    search_r = await asyncio.to_thread(_search_redis)

    async def _onto_entry(row) -> dict:
        vid = str(row["version_id"])
        indexed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"search:meta:{vid}"))
        )
        reasoning = await _reasoning_status(vid)
        created = row["version_created_at"]
        meta_resolved = row["meta_resolved"] or {}
        label = row["ont_title"] or meta_resolved.get("title") or None
        return {
            "id": row["id"],
            "iri": row["iri"],
            "shortname": row["shortname"],
            "label": label,
            "source_url": row["source_url"],
            "version_id": vid,
            "triple_count": row["triple_count"],
            "ingestion_status": row["ingestion_status"],
            "indexed": indexed,
            "embed_count": embed_counts.get(vid, 0),
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


# ── Workers ───────────────────────────────────────────────────────────────────

@router.get("/workers", summary="List active, reserved, and pending Celery tasks")
async def admin_workers(_: User = Depends(_require_admin)):
    """Return all tasks: actively running, prefetched by a worker, or waiting in the Redis queue.

    Uses a 2-second inspect timeout for the worker side.
    Pending tasks are read directly from Redis so they appear even before a worker picks them up.
    """
    import base64
    import json as _json
    from ontoexplorer.modules.jobs.tasks import celery_app

    def _inspect():
        inspector = celery_app.control.inspect(timeout=2.0)
        return inspector.active() or {}, inspector.reserved() or {}

    def _read_queue() -> list[dict]:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        raw_messages = r.lrange("celery", 0, -1)
        result = []
        for msg_str in raw_messages:
            try:
                msg = _json.loads(msg_str)
                body = _json.loads(base64.b64decode(msg["body"]).decode("utf-8"))
                kwargs = body[1] if len(body) > 1 else {}
                headers = msg.get("headers", {})
                task_id = headers.get("id") or msg.get("properties", {}).get("correlation_id", "")
                task_name = headers.get("task", "")
                result.append({
                    "id": task_id,
                    "name": task_name,
                    "state": "pending",
                    "kwargs": kwargs,
                    "time_start": None,
                    "worker": "queue",
                })
            except Exception:
                continue
        return result

    (active, reserved), pending = await asyncio.gather(
        asyncio.to_thread(_inspect),
        asyncio.to_thread(_read_queue),
    )

    seen_ids: set[str] = set()
    tasks = []

    for worker, task_list in active.items():
        for t in (task_list or []):
            seen_ids.add(t["id"])
            tasks.append({
                "id": t["id"],
                "name": t["name"],
                "state": "active",
                "kwargs": t.get("kwargs", {}),
                "time_start": t.get("time_start"),
                "worker": worker,
            })
    for worker, task_list in reserved.items():
        for t in (task_list or []):
            seen_ids.add(t["id"])
            tasks.append({
                "id": t["id"],
                "name": t["name"],
                "state": "reserved",
                "kwargs": t.get("kwargs", {}),
                "time_start": None,
                "worker": worker,
            })
    for t in pending:
        if t["id"] not in seen_ids:
            tasks.append(t)

    return {"tasks": tasks}


@router.delete("/workers/{task_id}", summary="Revoke (cancel) a Celery task")
async def admin_revoke_worker(
    task_id: str,
    version_id: str | None = None,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a Celery task and mark its DB job record as cancelled.

    ``version_id`` is optional but should be passed when known so the running
    job record is cleaned up immediately (SIGTERM kills the process before its
    own except-block can call mark_failed).
    """
    from datetime import datetime, timezone
    from ontoexplorer.modules.jobs.tasks import celery_app

    await asyncio.to_thread(
        lambda: celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
    )

    if version_id:
        await db.execute(
            text("""
                UPDATE jobs
                SET status = 'failed', finished_at = :now, error = 'Cancelled by admin'
                WHERE version_id = :vid AND status = 'running'
            """),
            {"vid": version_id, "now": datetime.now(timezone.utc)},
        )
        await db.commit()

    return {"status": "revoked", "task_id": task_id}


# ── Check for ontology update ─────────────────────────────────────────────────

@router.post("/ontologies/{ontology_id}/check-update", summary="Check if a remote ontology has changed")
async def admin_check_update(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the latest version and compare SHA-256.

    Falls back to the ontology IRI (with RDF content negotiation) when no
    source_url is stored (e.g. the version was uploaded as a file).
    """
    import hashlib
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="No version found for this ontology")

    ont = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one()

    fetch_url = version.source_url
    use_iri_negotiation = False
    if not fetch_url:
        if not ont.iri:
            return {"status": "no_source_url"}
        fetch_url = ont.iri
        use_iri_negotiation = True

    headers = {"Accept": _RDF_ACCEPT} if use_iri_negotiation else {}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), follow_redirects=True) as client:
            async with client.stream("GET", fetch_url, headers=headers) as resp:
                resp.raise_for_status()
                h = hashlib.sha256()
                async for chunk in resp.aiter_bytes(65536):
                    h.update(chunk)
                new_sha256 = h.hexdigest()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Source returned HTTP {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch source: {exc}")

    if new_sha256 == version.sha256:
        return {"status": "up_to_date"}

    from ontoexplorer.modules.jobs.tasks import ingest_ontology
    task = ingest_ontology.delay(
        iri=fetch_url if use_iri_negotiation else None,
        url=fetch_url if not use_iri_negotiation else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "update_queued", "task_id": task.id}


# ── Force re-ingest ───────────────────────────────────────────────────────────

@router.post("/ontologies/{ontology_id}/ingest", summary="Queue re-ingestion of an ontology")
async def admin_queue_ingest(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Directly queue re-ingestion using source_url (URL) or IRI (content negotiation).

    No SHA-256 comparison — always queues a new ingest job.
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    ont = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one()

    fetch_url = version.source_url if version else None
    use_iri = False
    if not fetch_url:
        if not ont.iri:
            raise HTTPException(status_code=422, detail="No source URL or IRI available for this ontology")
        fetch_url = ont.iri
        use_iri = True

    task = ingest_ontology.delay(
        iri=fetch_url if use_iri else None,
        url=fetch_url if not use_iri else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "queued", "task_id": task.id, "method": "iri" if use_iri else "url"}


# ── Reindex ───────────────────────────────────────────────────────────────────

@router.post("/reindex", summary="Queue search re-index for all ingested versions")
async def admin_reindex(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue index_ontology for every ingested version and detect_meta_profile for all versions.

    Safe to run multiple times.
    """
    from ontoexplorer.modules.jobs.tasks import detect_meta_profile, index_ontology

    all_rows = (await db.execute(
        text("""
            SELECT v.id AS version_id, v.ontology_id, v.status
            FROM versions v
            ORDER BY v.created_at DESC
        """)
    )).mappings().all()

    meta_queued = 0
    index_queued = 0
    for row in all_rows:
        vid = str(row["version_id"])
        oid = str(row["ontology_id"])
        detect_meta_profile.delay(vid, ontology_id=oid)
        meta_queued += 1
        if row["status"] == "ingested":
            index_ontology.delay(vid, ontology_id=oid)
            index_queued += 1

    return {
        "meta_detection_queued": meta_queued,
        "index_queued": index_queued,
        "message": (
            f"Queued {meta_queued} detect_meta_profile tasks "
            f"and {index_queued} index_ontology tasks"
        ),
    }
