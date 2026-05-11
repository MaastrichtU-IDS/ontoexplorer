"""Job status CRUD in Postgres."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Job


async def create_job(db: AsyncSession, version_id: str, job_type: str) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        version_id=version_id,
        type=job_type,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def mark_running(db: AsyncSession, job_id: str) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="running", started_at=datetime.now(UTC))
    )
    await db.commit()


async def mark_done(db: AsyncSession, job_id: str) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="done", finished_at=datetime.now(UTC))
    )
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
