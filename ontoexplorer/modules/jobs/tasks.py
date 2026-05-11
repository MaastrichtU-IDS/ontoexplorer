"""Celery application and task definitions."""

import asyncio

from celery import Celery

from ontoexplorer.config import get_settings
from ontoexplorer.logging_config import get_logger

log = get_logger(__name__)
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
    task_acks_late=True,
    worker_prefetch_multiplier=1,
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
    """Celery task: run the full ingestion pipeline for one ontology submission."""
    from ontoexplorer.database import AsyncSessionLocal
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion

    raw_bytes = bytes.fromhex(raw_bytes_hex) if raw_bytes_hex else None
    request = IngestionRequest(
        iri=iri, url=url, raw_bytes=raw_bytes,
        filename=filename, content_type=content_type, owner_id=owner_id,
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
        log.exception("ingestion_task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc


@celery_app.task(bind=True, name="ontoexplorer.reason_ontology", max_retries=2)
def reason_ontology(self, version_id: str) -> dict:
    """
    Run OWL-EL classification for an ingested ontology version.

    Steps:
    1. Fetch asserted triples from Oxigraph named graph
    2. POST to ELK reasoning service
    3. Store inferred triples in Oxigraph under :inferred named graph
    4. Update job status in Postgres
    5. Deliver reasoning.completed / reasoning.failed webhook
    """
    import time
    from ontoexplorer.database import AsyncSessionLocal

    async def _run():
        async with AsyncSessionLocal() as db:
            return await _run_reasoning(db, version_id)

    t0 = time.monotonic()
    try:
        result = asyncio.run(_run())
        elapsed = time.monotonic() - t0
        from ontoexplorer import metrics
        metrics.reasoning_jobs_total.labels(status="completed").inc()
        metrics.reasoning_duration_seconds.observe(elapsed)
        log.info("reasoning_complete", version_id=version_id,
                 inferred_count=result["inferred_count"], duration_s=round(elapsed, 2))
        return result
    except Exception as exc:
        from ontoexplorer import metrics
        metrics.reasoning_jobs_total.labels(status="failed").inc()
        log.error("reasoning_failed", version_id=version_id, error=str(exc))
        raise self.retry(exc=exc, countdown=120) from exc


async def _run_reasoning(db, version_id: str) -> dict:
    """Async body of the reasoning task."""
    from sqlalchemy import select

    import rdflib
    from rdflib.namespace import RDFS

    from ontoexplorer.clients import reasoning as reasoning_client
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.models.db import Job, OntologyVersion
    from ontoexplorer.modules.jobs import tracker
    from ontoexplorer.modules.webhooks.delivery import broadcast_event

    # Look up the version so we have ontology_id
    result = await db.execute(select(OntologyVersion).where(OntologyVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        raise ValueError(f"OntologyVersion {version_id} not found")

    ontology_id = version.ontology_id

    # Create / mark job as running
    job = await tracker.create_job(db, version_id=version_id, job_type="reason")
    await tracker.mark_running(db, job.id)

    # Fetch asserted triples from Oxigraph
    store = get_store()
    asserted_iri = graph_iri(ontology_id, version_id, inferred=False)
    asserted_graph = rdflib.Graph()
    for triple in store.quads(graph_name=rdflib.URIRef(asserted_iri)):
        asserted_graph.add((triple[0], triple[1], triple[2]))

    if len(asserted_graph) == 0:
        log.warning("reasoning_empty_graph", version_id=version_id, graph=asserted_iri)

    # Call ELK service
    inferred_graph = await reasoning_client.classify(asserted_graph, version_id)

    # Load inferred triples into Oxigraph under :inferred named graph
    inferred_iri = graph_iri(ontology_id, version_id, inferred=True)
    inferred_nt = inferred_graph.serialize(format="nt")
    if isinstance(inferred_nt, str):
        inferred_nt = inferred_nt.encode()

    if inferred_nt.strip():
        import io as _io
        import pyoxigraph
        inferred_named = pyoxigraph.NamedNode(inferred_iri)
        store.remove_graph(inferred_named)
        store.add_graph(inferred_named)
        store.bulk_load(
            _io.BytesIO(inferred_nt),
            "application/n-triples",
            to_graph=inferred_named,
        )

    inferred_count = len(inferred_graph)

    # Update job status
    await tracker.mark_done(db, job.id)

    # Fire webhook
    await broadcast_event(db, "reasoning.completed", {
        "version_id": version_id,
        "ontology_id": ontology_id,
        "inferred_axiom_count": inferred_count,
    })

    return {"version_id": version_id, "inferred_count": inferred_count}


@celery_app.task(name="ontoexplorer.index_ontology")
def index_ontology(version_id: str) -> dict:
    """Stub: NL search indexing — implemented in Subsystem 3."""
    log.info("index_ontology_stub", version_id=version_id)
    return {"status": "stub", "version_id": version_id}
