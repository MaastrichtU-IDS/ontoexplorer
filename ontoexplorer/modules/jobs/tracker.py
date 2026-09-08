"""Job status CRUD in Postgres."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Job


async def create_job(db: AsyncSession, version_id: str | None, job_type: str,
                     user_id: str | None = None) -> Job:
    """`user_id` is who asked for this. None means the system did (beat), and the
    jobs listing treats that as admin-only rather than public."""
    job = Job(
        id=str(uuid.uuid4()),
        version_id=version_id,
        type=job_type,
        status="pending",
        user_id=user_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def start_job(db: AsyncSession, job_id: str, job_type: str,
                    user_id: str | None = None) -> None:
    """Insert-or-reset a running job row under a caller-supplied id.

    Ingestion keys its job row on the Celery task id — the same id the submit
    endpoint hands back — so the caller cannot let the DB pick one. Idempotent
    because a Celery retry re-enters the task with the same id; a fresh attempt
    clears the previous attempt's error rather than leaving it to look current.
    """
    now = datetime.now(UTC)
    existing = await db.execute(select(Job.id).where(Job.id == job_id))
    if existing.scalar_one_or_none() is None:
        db.add(Job(id=job_id, version_id=None, type=job_type,
                   status="running", started_at=now, user_id=user_id))
    else:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status="running", started_at=now, finished_at=None, error=None)
        )
    await db.commit()


async def mark_running(db: AsyncSession, job_id: str) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="running", started_at=datetime.now(UTC))
    )
    await db.commit()


async def mark_done(db: AsyncSession, job_id: str, version_id: str | None = None) -> None:
    values: dict = {"status": "done", "finished_at": datetime.now(UTC)}
    if version_id is not None:
        # Ingestion jobs start version-less; the version only exists once the
        # pipeline has produced it.
        values["version_id"] = version_id
    await db.execute(update(Job).where(Job.id == job_id).values(**values))
    await db.commit()


async def mark_failed(db: AsyncSession, job_id: str, error: str) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="failed", finished_at=datetime.now(UTC), error=error)
    )
    await db.commit()


async def get_job(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()
