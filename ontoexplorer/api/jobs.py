"""Job tracking API — GET /jobs and GET /jobs/{id}."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Job

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs", summary="List recent jobs")
async def list_jobs(
    type: str | None = Query(None, description="Filter by job type: reasoning | indexing"),
    status: str | None = Query(None, description="Filter by status: pending | running | done | failed"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if type:
        stmt = stmt.where(Job.type == type)
    if status:
        stmt = stmt.where(Job.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {"jobs": [_job_to_dict(j) for j in jobs]}


@router.get("/jobs/{job_id}", summary="Get job status")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "version_id": job.version_id,
        "type": job.type,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
    }
