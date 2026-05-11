"""Celery application and task definitions."""

import asyncio
import logging

from celery import Celery

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "ontoexplorer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # re-queue on worker crash
    worker_prefetch_multiplier=1, # one task at a time per worker thread
)


@celery_app.task(bind=True, name="ontoexplorer.ingest_ontology", max_retries=3)
def ingest_ontology(
    self,
    *,
    iri: str | None = None,
    url: str | None = None,
    raw_bytes_hex: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    owner_id: str | None = None,
) -> dict:
    """
    Celery task: run the full ingestion pipeline for one ontology submission.

    raw_bytes are passed as hex string (JSON-serialisable).
    Returns a dict with ontology_id, version_id, sha256, triple_count, is_duplicate.
    """
    from ontoexplorer.database import AsyncSessionLocal
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion

    raw_bytes = bytes.fromhex(raw_bytes_hex) if raw_bytes_hex else None

    request = IngestionRequest(
        iri=iri,
        url=url,
        raw_bytes=raw_bytes,
        filename=filename,
        content_type=content_type,
        owner_id=owner_id,
    )

    async def _run():
        async with AsyncSessionLocal() as db:
            return await run_ingestion(db, request)

    try:
        result = asyncio.run(_run())
        return {
            "ontology_id": result.ontology_id,
            "version_id": result.version_id,
            "sha256": result.sha256,
            "format": result.format.value,
            "triple_count": result.triple_count,
            "is_duplicate": result.is_duplicate,
            "warnings": result.warnings,
        }
    except Exception as exc:
        logger.exception("Ingestion failed: %s", exc)
        raise self.retry(exc=exc, countdown=60) from exc


@celery_app.task(name="ontoexplorer.reason_ontology")
def reason_ontology(version_id: str) -> dict:
    """Stub: trigger OWL-EL reasoning for a version. Implemented in Phase 6."""
    logger.info("reason_ontology stub called for version %s", version_id)
    return {"status": "stub", "version_id": version_id}


@celery_app.task(name="ontoexplorer.index_ontology")
def index_ontology(version_id: str) -> dict:
    """Stub: trigger NL search indexing for a version. Implemented in Phase 3."""
    logger.info("index_ontology stub called for version %s", version_id)
    return {"status": "stub", "version_id": version_id}
