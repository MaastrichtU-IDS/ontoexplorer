"""Usage statistics API."""

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Job, Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth


def _sum_bucket_bytes(bucket: str) -> int:
    from ontoexplorer.clients.minio import get_minio_client
    try:
        return sum(obj.size or 0 for obj in get_minio_client().list_objects(bucket, recursive=True))
    except Exception:
        return 0

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/public", summary="Public aggregate statistics (no auth required)")
async def get_public_stats(db: AsyncSession = Depends(get_db)):
    import json
    from ontoexplorer.modules.search.indexer import _get_redis

    total_ontologies = (await db.execute(select(func.count(Ontology.id)))).scalar_one()

    r = _get_redis()
    total_classes = 0
    total_properties = 0
    for key in r.scan_iter("search:meta:*"):
        raw = r.get(key)
        if not raw:
            continue
        try:
            meta = json.loads(raw)
            total_classes += int(meta.get("class_count", 0))
            total_properties += int(meta.get("property_count", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    return {
        "total_ontologies": total_ontologies,
        "total_classes": total_classes,
        "total_properties": total_properties,
    }


@router.get("", summary="Usage statistics for the authenticated user")
async def get_stats(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    total_ontologies = (await db.execute(
        select(func.count(Ontology.id)).where(Ontology.owner_id == user.id)
    )).scalar_one()

    total_versions = (await db.execute(
        select(func.count(OntologyVersion.id))
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .where(Ontology.owner_id == user.id)
    )).scalar_one()

    uploads_per_month = (await db.execute(
        text("""
            SELECT to_char(v.created_at, 'YYYY-MM') AS month, COUNT(*) AS count
            FROM ontology_versions v
            JOIN ontologies o ON o.id = v.ontology_id
            WHERE o.owner_id = :uid
            GROUP BY month ORDER BY month
        """),
        {"uid": user.id},
    )).all()

    job_durations = (await db.execute(
        text("""
            SELECT to_char(j.started_at, 'YYYY-MM') AS month,
                   AVG(EXTRACT(EPOCH FROM (j.finished_at - j.started_at))) AS avg_seconds
            FROM jobs j
            JOIN ontology_versions v ON v.id = j.version_id
            JOIN ontologies o ON o.id = v.ontology_id
            WHERE o.owner_id = :uid AND j.type = 'reason' AND j.status = 'done'
              AND j.started_at IS NOT NULL AND j.finished_at IS NOT NULL
            GROUP BY month ORDER BY month
        """),
        {"uid": user.id},
    )).all()

    s = get_settings()
    storage_bytes = await asyncio.to_thread(_sum_bucket_bytes, s.minio_ontologies_bucket)

    return {
        "total_ontologies": total_ontologies,
        "total_versions": total_versions,
        "storage_bytes": storage_bytes,
        "total_queries": 0,
        "uploads_per_month": [{"month": r.month, "count": r.count} for r in uploads_per_month],
        "queries_per_month": [],
        "job_durations": [{"month": r.month, "avg_seconds": round(float(r.avg_seconds or 0), 1)} for r in job_durations],
    }
