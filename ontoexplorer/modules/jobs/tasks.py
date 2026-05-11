"""Celery application and task definitions."""

import asyncio

import pyoxigraph
import rdflib
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
    task_ignore_result=True,  # use Postgres jobs table for status; avoid blocking on Redis result backend
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
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion

    raw_bytes = bytes.fromhex(raw_bytes_hex) if raw_bytes_hex else None
    request = IngestionRequest(
        iri=iri, url=url, raw_bytes=raw_bytes,
        filename=filename, content_type=content_type, owner_id=owner_id,
    )

    async def _run():
        async with make_celery_db_session()() as db:
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
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
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
    named_node = pyoxigraph.NamedNode(asserted_iri)
    for quad in store.quads_for_pattern(None, None, None, named_node):
        # subject
        if isinstance(quad.subject, pyoxigraph.NamedNode):
            s = rdflib.URIRef(quad.subject.value)
        else:
            s = rdflib.BNode(quad.subject.value)
        # predicate (always a NamedNode in valid RDF)
        p = rdflib.URIRef(quad.predicate.value)
        # object
        o_raw = quad.object
        if isinstance(o_raw, pyoxigraph.NamedNode):
            o = rdflib.URIRef(o_raw.value)
        elif isinstance(o_raw, pyoxigraph.Literal):
            if o_raw.language:
                o = rdflib.Literal(o_raw.value, lang=o_raw.language)
            else:
                dt = rdflib.URIRef(o_raw.datatype.value) if o_raw.datatype else None
                o = rdflib.Literal(o_raw.value, datatype=dt)
        else:
            o = rdflib.BNode(o_raw.value)
        asserted_graph.add((s, p, o))

    if len(asserted_graph) == 0:
        log.warning("reasoning_empty_graph", version_id=version_id, graph=asserted_iri)

    # Call ELK service — classify_v2 POSTs to /classify and caches in Redis
    import httpx as _httpx
    from ontoexplorer.config import get_settings as _get_settings
    await reasoning_client.classify_v2(asserted_graph, version_id)

    # Fetch the full inferred graph from ELK classification result for Oxigraph persistence
    async with _httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{_get_settings().elk_service_url}/classify/{version_id}")
        resp.raise_for_status()
    classification = resp.json()

    # Build inferred N-Triples from superclasses index
    inferred_nt_lines = []
    for sub, supers in classification.get("superclasses", {}).items():
        for sup in supers:
            inferred_nt_lines.append(
                f"<{sub}> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{sup}> ."
            )
    inferred_nt = "\n".join(inferred_nt_lines).encode()
    inferred_count = len(inferred_nt_lines)

    # Load inferred triples into Oxigraph under :inferred named graph
    inferred_iri = graph_iri(ontology_id, version_id, inferred=True)
    if inferred_nt.strip():
        import io as _io
        inferred_named = pyoxigraph.NamedNode(inferred_iri)
        store.remove_graph(inferred_named)
        store.add_graph(inferred_named)
        store.bulk_load(
            _io.BytesIO(inferred_nt),
            "application/n-triples",
            to_graph=inferred_named,
        )

    # Update job status
    await tracker.mark_done(db, job.id)

    # Fire webhook
    await broadcast_event(db, "reasoning.completed", {
        "version_id": version_id,
        "ontology_id": ontology_id,
        "inferred_axiom_count": inferred_count,
    })

    return {"version_id": version_id, "inferred_count": inferred_count}


@celery_app.task(name="ontoexplorer.index_ontology", bind=True, max_retries=2)
def index_ontology(self, version_id: str, ontology_id: str = "") -> dict:
    """Build the Redis entity search index for a version."""
    log.info("index_ontology_start", version_id=version_id)
    try:
        from ontoexplorer.modules.search.indexer import build_index
        stats = build_index(version_id, ontology_id)
        log.info("index_ontology_done", version_id=version_id,
                 class_count=stats.class_count, property_count=stats.property_count)
        return {"status": "done", "version_id": version_id,
                "class_count": stats.class_count, "property_count": stats.property_count}
    except Exception as exc:
        log.error("index_ontology_failed", version_id=version_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, name="ontoexplorer.compute_justification", max_retries=1,
                 time_limit=660)  # 11 min hard limit (matches ELK 300s + buffer)
def compute_justification(
    self,
    *,
    version_id: str,
    ontology_id: str,
    sub: str,
    sup: str | None,
    max_justifications: int = 1,
) -> dict:
    """
    Compute justification(s) for a subclass inference or unsatisfiability.

    Calls ELK service synchronously (ELK does the work), stores the result,
    updates job status, and fires justification.completed / justification.failed.
    """

    async def _run():
        from ontoexplorer.clients import reasoning as reasoning_client
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.jobs import tracker
        from ontoexplorer.modules.webhooks.delivery import broadcast_event

        async with make_celery_db_session()() as db:
            job = await tracker.create_job(db, version_id=version_id, job_type="justification")
            await tracker.mark_running(db, job.id)
            try:
                result = await reasoning_client.request_justification(
                    version_id, sub, sup, max_justifications
                )
                await tracker.mark_done(db, job.id)
                await broadcast_event(db, "justification.completed", {
                    "version_id": version_id,
                    "ontology_id": ontology_id,
                    "sub": sub,
                    "sup": sup,
                    "justifications_found": result.get("justifications_found", 0),
                })
                return result
            except Exception as exc:
                await tracker.mark_failed(db, job.id, str(exc))
                await broadcast_event(db, "justification.failed", {
                    "version_id": version_id,
                    "ontology_id": ontology_id,
                    "sub": sub,
                    "sup": sup,
                    "error": str(exc),
                })
                raise

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("justification_task_failed", version_id=version_id, sub=sub, error=str(exc))
        raise self.retry(exc=exc, countdown=30) from exc
