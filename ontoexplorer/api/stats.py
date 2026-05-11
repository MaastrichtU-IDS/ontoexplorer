"""Usage statistics API."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Job, Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


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

    return {
        "total_ontologies": total_ontologies,
        "total_versions": total_versions,
        "storage_bytes": 0,
        "total_queries": 0,
        "uploads_per_month": [{"month": r.month, "count": r.count} for r in uploads_per_month],
        "queries_per_month": [],
        "job_durations": [{"month": r.month, "avg_seconds": round(float(r.avg_seconds or 0), 1)} for r in job_durations],
    }
