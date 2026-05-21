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


async def _check_fuseki() -> str:
    """Ping the Jena Fuseki SPARQL endpoint.

    Fuseki's /$/ping lives at the server root, so we strip any dataset path
    (e.g. /fuseki) from the configured endpoint before pinging.
    """
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(get_settings().fuseki_endpoint)
    root = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{root}/$/ping")
        return "ok" if resp.status_code == 200 else f"error: HTTP {resp.status_code}"
    except Exception as exc:
        return f"error: {exc}"


def _check_oxigraph() -> str:
    """Open the singleton Oxigraph store (read-only inside the API) and assert it is readable."""
    try:
        from ontoexplorer.clients.oxigraph import get_store
        store = get_store()
        len(store)  # forces a RocksDB read; raises if the store is unusable
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _check_beat() -> str:
    """Return 'ok' if Celery Beat wrote a heartbeat to Redis in the last 120 s, else 'error: …'."""
    from datetime import UTC, datetime
    try:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        raw = r.get("beat:heartbeat")
        if not raw:
            return "error: no heartbeat"
        last = datetime.fromisoformat(raw)
        age = (datetime.now(UTC) - last).total_seconds()
        if age > 120:
            return f"error: stale ({int(age)}s)"
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _check_workers() -> str:
    """Return 'ok' when at least one worker responds to celery ping; 'error: …' otherwise."""
    try:
        from ontoexplorer.modules.jobs.tasks import celery_app
        pongs = celery_app.control.ping(timeout=2.0) or []
        return "ok" if pongs else "error: no workers"
    except Exception as exc:
        return f"error: {exc}"


def _celery_queue_depth() -> int:
    try:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        return r.llen("celery")
    except Exception:
        return -1


async def _check_entity_index(db: AsyncSession) -> tuple[str, dict]:
    """Return (status, stats) for the Postgres entity_index.

    Status is 'ok' when row count for ready versions matches the per-type sums in
    Redis to within 5%, 'warn: drift' when they diverge, 'error: …' when the query
    fails. Stats include the total row count and the version drift list.
    """
    try:
        pg_row = (await db.execute(
            text("SELECT COUNT(*) AS n FROM entity_index")
        )).first()
        pg_total = int(pg_row.n) if pg_row else 0

        # Per-version row count in entity_index, only for ready non-deprecated versions
        per_version_rows = (await db.execute(
            text("""
                SELECT ei.version_id, COUNT(*) AS n
                FROM entity_index ei
                JOIN versions v ON v.id = ei.version_id
                WHERE v.status NOT IN ('pending','failed','deprecated')
                GROUP BY ei.version_id
            """)
        )).all()
        pg_by_vid = {r.version_id: int(r.n) for r in per_version_rows}

        # Compare against Redis per-version type-set sums (best-effort)
        from ontoexplorer.modules.search.indexer import _get_redis, _type_key
        r = _get_redis()
        types = ("class", "object_property", "data_property", "annotation_property", "individual")
        drift: list[dict] = []
        for vid, pg_n in pg_by_vid.items():
            redis_n = sum(r.scard(_type_key(vid, t)) for t in types)
            if redis_n == 0:
                continue  # Redis missing this version; not our problem here
            if abs(redis_n - pg_n) / max(redis_n, 1) > 0.05:
                drift.append({"version_id": vid, "redis": redis_n, "pg": pg_n})

        status = "ok" if not drift else f"warn: {len(drift)} version(s) drift"
        return status, {"total_rows": pg_total, "drift": drift[:10]}
    except Exception as exc:
        return f"error: {exc}", {"total_rows": 0, "drift": []}


@router.get("/overview", summary="Admin system overview")
async def admin_overview(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    (
        postgres_status,
        redis_status,
        minio_status,
        elk_status,
        fuseki_status,
        oxigraph_status,
        workers_status,
        beat_status,
        entity_index_result,
    ) = await asyncio.gather(
        _check_postgres(db),
        asyncio.to_thread(_check_redis),
        _check_minio(),
        _check_elk(),
        _check_fuseki(),
        asyncio.to_thread(_check_oxigraph),
        asyncio.to_thread(_check_workers),
        asyncio.to_thread(_check_beat),
        _check_entity_index(db),
    )
    entity_index_status, entity_index_stats = entity_index_result
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
            "fuseki": fuseki_status,
            "oxigraph": oxigraph_status,
            "workers": workers_status,
            "beat": beat_status,
            "entity_index": entity_index_status,
            "entity_index_rows": entity_index_stats["total_rows"],
            "entity_index_drift": entity_index_stats["drift"],
            "celery_queue_depth": queue_depth,
        },
        "ontologies": list(ontologies),
        "jobs": jobs,
    }
