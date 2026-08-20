"""An ingestion submission must leave a queryable job row, even when it fails
before any OntologyVersion exists.

Background: loading DRON failed on the download size cap. The API had already
returned `{"task_id": ..., "status": "queued"}`, and because `jobs.version_id`
was NOT NULL with an FK to `versions`, no job row could be written for a
failure that happened before ingestion produced a version. The error existed
only in the worker log, so the submission looked like it silently stalled.

The jobs row is keyed by the Celery task id, so the id handed back by
POST /ontologies is exactly the id `GET /jobs/{id}` answers to.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ontoexplorer.models.db import Job
from ontoexplorer.modules.ingestion.pipeline import IngestionRequest
from ontoexplorer.modules.jobs import tasks, tracker


@pytest.fixture()
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _job(db, job_id: str) -> Job:
    return (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()


@pytest.mark.anyio
async def test_job_row_survives_without_a_version(db_session):
    """A version-less job row is legal — the FK column must be nullable."""
    job = await tracker.create_job(db_session, version_id=None, job_type="ingestion")
    assert job.version_id is None


@pytest.mark.anyio
async def test_start_job_is_idempotent_across_retries(db_session):
    """Celery retries re-enter the task with the same id; the row is reused."""
    await tracker.start_job(db_session, "job-retry", "ingestion")
    await tracker.mark_failed(db_session, "job-retry", "boom")
    await tracker.start_job(db_session, "job-retry", "ingestion")

    row = await _job(db_session, "job-retry")
    assert row.status == "running"
    assert row.error is None, "a fresh attempt must clear the previous attempt's error"

    rows = (await db_session.execute(select(Job).where(Job.id == "job-retry"))).scalars().all()
    assert len(rows) == 1


@pytest.mark.anyio
async def test_failed_ingestion_records_the_error(session_factory, monkeypatch):
    """The size-cap failure — pre-version — must land in the jobs table."""
    async def _boom(db, request):
        raise ValueError("Response exceeds size limit (706398355 bytes, limit 512 bytes)")

    monkeypatch.setattr(
        "ontoexplorer.modules.ingestion.pipeline.run_ingestion", _boom, raising=True
    )

    request = IngestionRequest(iri="http://purl.obolibrary.org/obo/dron.owl")
    with pytest.raises(ValueError):
        await tasks._ingest_tracked(request, "job-dron", session_factory)

    async with session_factory() as db:
        row = await _job(db, "job-dron")
    assert row.status == "failed"
    assert row.type == "ingestion"
    assert row.version_id is None
    assert "size limit" in row.error


@pytest.mark.anyio
async def test_successful_ingestion_attaches_the_version(session_factory, monkeypatch):
    class _Result:
        ontology_id = "ont-1"
        version_id = "ver-1"

    async def _ok(db, request):
        return _Result()

    monkeypatch.setattr(
        "ontoexplorer.modules.ingestion.pipeline.run_ingestion", _ok, raising=True
    )

    request = IngestionRequest(iri="http://example.org/small.owl")
    await tasks._ingest_tracked(request, "job-ok", session_factory)

    async with session_factory() as db:
        row = await _job(db, "job-ok")
    assert row.status == "done"
    assert row.version_id == "ver-1"


@pytest.mark.anyio
async def test_jobs_endpoint_reports_the_failure(client, db_session):
    """GET /jobs/{task_id} is what the UI polls — it must show the message."""
    await tracker.start_job(db_session, "job-api", "ingestion")
    await tracker.mark_failed(db_session, "job-api", "Response exceeds size limit")

    r = await client.get("/api/v1/jobs/job-api")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["version_id"] is None
    assert "size limit" in body["error"]
