"""Job tracking API — GET /jobs and GET /jobs/{id}."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import is_admin
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Job, User
from ontoexplorer.modules.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs", summary="List recent jobs")
async def list_jobs(
    type: str | None = Query(None, description="Filter by job type: reasoning | indexing"),
    status: str | None = Query(None, description="Filter by status: pending | running | done | failed"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    # Scoped: this listed every row to any caller, so one user could read
    # another's job history. Jobs with no submitter are system-initiated (beat)
    # and stay admin-only — the safe reading of an unknown owner.
    if user is None:
        return {"jobs": []}
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if not is_admin(user):
        stmt = stmt.where(Job.user_id == user.id)
    if type:
        stmt = stmt.where(Job.type == type)
    if status:
        stmt = stmt.where(Job.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {"jobs": [_job_to_dict(j, include_error=user is not None) for j in jobs]}


@router.get("/jobs/{job_id}", summary="Get job status")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # 404 rather than 403 for someone else's job: a 403 would confirm the id
    # exists, and these ids are Celery task ids handed to the submitter.
    if job.user_id is not None and (user is None or (job.user_id != user.id and not is_admin(user))):
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job, include_error=user is not None)


def _job_to_dict(job: Job, *, include_error: bool) -> dict:
    """Job status. `error` carries a raw exception string, so it is withheld from
    anonymous callers.

    The ingest pipeline stores `str(exc)[:1000]`, which for a failed fetch is the
    full connection error including the target host — that turns an unauthenticated
    read of this endpoint into an oracle for probing internal addresses through the
    ingest URL, and leaks internal hostnames and paths besides. Status itself stays
    public so the UI can poll without a session.
    """
    return {
        "id": job.id,
        "version_id": job.version_id,
        "type": job.type,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error if include_error else (None if job.error is None else "hidden"),
        "created_at": job.created_at.isoformat(),
    }
