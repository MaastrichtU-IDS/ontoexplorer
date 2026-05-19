"""Service health checks and the aggregated admin overview endpoint."""
from __future__ import annotations

import asyncio

import httpx
import redis as redis_sync
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import User

from ._common import _reasoning_status, _require_admin, _search_redis

router = APIRouter()


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


@router.get("/overview", summary="Admin system overview")
async def admin_overview(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    postgres_status, redis_status, minio_status, elk_status = await asyncio.gather(
        _check_postgres(db),
        asyncio.to_thread(_check_redis),
        _check_minio(),
        _check_elk(),
    )
    queue_depth = await asyncio.to_thread(_celery_queue_depth)

    rows = (await db.execute(
        text("""
            SELECT o.id, o.iri, o.shortname, o.title AS ont_title,
                   v.id AS version_id, v.version_iri, v.triple_count,
                   v.status AS ingestion_status,
                   v.created_at AS version_created_at, v.source_url,
                   mp.resolved AS meta_resolved,
                   (SELECT COUNT(*) FROM versions WHERE ontology_id = o.id) AS version_count
            FROM ontologies o
            JOIN versions v ON v.id = (
                SELECT id FROM versions WHERE ontology_id = o.id
                ORDER BY created_at DESC LIMIT 1
            )
            LEFT JOIN ontology_meta_profiles mp ON mp.version_id = v.id
            ORDER BY o.shortname NULLS LAST, o.iri
        """)
    )).mappings().all()

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
        profile_computed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"owl_profile:{vid}"))
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
            "version_iri": row["version_iri"],
            "version_count": int(row["version_count"]),
            "triple_count": row["triple_count"],
            "ingestion_status": row["ingestion_status"],
            "indexed": indexed,
            "profile_computed": profile_computed,
            "embed_count": embed_counts.get(vid, 0),
            "reasoning_status": reasoning,
            "version_created_at": created.isoformat() if created else None,
        }

    ontologies = await asyncio.gather(*[_onto_entry(r) for r in rows])

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
