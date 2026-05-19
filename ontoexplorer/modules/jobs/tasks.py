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
    beat_schedule={
        "poll-for-updates-hourly": {
            "task": "ontoexplorer.poll_for_updates",
            "schedule": 3600.0,
        },
    },
)


@celery_app.on_after_finalize.connect
def setup_signals(sender, **kwargs):
    from celery.signals import worker_ready
    worker_ready.connect(_reset_orphaned_jobs)


def _reset_orphaned_jobs(sender=None, **kwargs):
    """Mark any jobs stuck in 'running' as failed — they were interrupted by a worker restart."""
    import asyncio
    from sqlalchemy import text
    from ontoexplorer.database import make_celery_db_session
    Session = make_celery_db_session()

    async def _reset():
        async with Session() as db:
            result = await db.execute(
                text("""
                    UPDATE jobs SET status='failed', finished_at=now(),
                        error='Interrupted: worker restarted'
                    WHERE status='running'
                    RETURNING id
                """)
            )
            ids = [r[0] for r in result.fetchall()]
            await db.commit()
            if ids:
                log.warning("orphaned_jobs_reset", count=len(ids), job_ids=ids)

    asyncio.run(_reset())


@celery_app.task(name="ontoexplorer.detect_profile")
def detect_profile(version_id: str, ontology_id: str = "") -> dict:
    """Detect annotation profile from Oxigraph, write to DB, then enqueue indexing."""
    try:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.profile.detector import run_detection

        async def _run():
            async with make_celery_db_session()() as db:
                await run_detection(db, version_id, ontology_id)

        asyncio.run(_run())
        log.info("detect_profile_done", version_id=version_id)
    except Exception as exc:
        log.error("detect_profile_failed", version_id=version_id, error=str(exc))
    finally:
        index_ontology.delay(version_id, ontology_id=ontology_id)
    return {"status": "done", "version_id": version_id}


@celery_app.task(name="ontoexplorer.detect_meta_profile")
def detect_meta_profile(version_id: str, ontology_id: str = "") -> dict:
    """Detect ontology-level metadata profile from Oxigraph and write to DB."""
    try:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.meta_profile.detector import run_meta_detection

        async def _run():
            async with make_celery_db_session()() as db:
                await run_meta_detection(db, version_id, ontology_id)

        asyncio.run(_run())
        log.info("detect_meta_profile_done", version_id=version_id)
    except Exception as exc:
        log.error("detect_meta_profile_failed", version_id=version_id, error=str(exc))
    return {"status": "done", "version_id": version_id}


@celery_app.task(name="ontoexplorer.compute_diff", time_limit=300)
def compute_diff(version_from_id: str, version_to_id: str, ontology_id: str) -> dict:
    """Compute diff between two ontology versions and store results in the DB."""
    import uuid
    from ontoexplorer.database import make_celery_db_session

    async def _run() -> None:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from ontoexplorer.models.db import OntologyDiff
        from ontoexplorer.modules.diff.compute import (
            collect_inferred_status,
            run_diff as _run_diff,
        )
        from ontoexplorer.clients.oxigraph import get_store

        async with make_celery_db_session()() as db:
            existing = await db.scalar(
                select(OntologyDiff).where(
                    OntologyDiff.version_from_id == version_from_id,
                    OntologyDiff.version_to_id == version_to_id,
                )
            )
            if existing and existing.status == "ready":
                return

            # Upsert pending row — ON CONFLICT DO NOTHING handles concurrent workers
            await db.execute(
                pg_insert(OntologyDiff)
                .values(
                    id=str(uuid.uuid4()),
                    ontology_id=ontology_id,
                    version_from_id=version_from_id,
                    version_to_id=version_to_id,
                    status="pending",
                )
                .on_conflict_do_nothing()
            )
            await db.commit()

            diff_row = await db.scalar(
                select(OntologyDiff).where(
                    OntologyDiff.version_from_id == version_from_id,
                    OntologyDiff.version_to_id == version_to_id,
                )
            )
            if diff_row is None:
                return  # should not happen, but guard

            try:
                store = get_store()
                # Pre-compute reasoning status in the async context so the
                # synchronous diff core never has to touch the DB itself.
                inferred_status = await collect_inferred_status(
                    db, version_from_id, version_to_id,
                )
                summary, diff_data = await asyncio.to_thread(
                    _run_diff, store, ontology_id, version_from_id, version_to_id,
                    inferred_status=inferred_status,
                )
                diff_row.summary = summary
                diff_row.diff_data = diff_data
                diff_row.status = "ready"
            except Exception as exc:
                diff_row.status = "failed"
                log.error("compute_diff_failed", from_vid=version_from_id,
                          to_vid=version_to_id, error=str(exc))
            await db.commit()

    try:
        asyncio.run(_run())
        log.info("compute_diff_done", from_vid=version_from_id, to_vid=version_to_id)
    except Exception as exc:
        log.error("compute_diff_task_error", error=str(exc))
        raise  # let Celery record the failure
    return {"status": "done"}


@celery_app.task(name="ontoexplorer.compute_ontology_comparison", time_limit=600)
def compute_ontology_comparison(version_from_id: str, version_to_id: str) -> dict:
    """Compute a cross-ontology comparison between two version IDs.

    Resolves each version's ontology_id from the DB, runs run_comparison,
    and persists results to the ontology_comparisons table.
    """
    import uuid
    from ontoexplorer.database import make_celery_db_session

    async def _run() -> None:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from ontoexplorer.clients.oxigraph import get_store
        from ontoexplorer.models.db import OntologyComparison, OntologyVersion
        from ontoexplorer.modules.compare.compute import run_comparison as _run_comparison

        async with make_celery_db_session()() as db:
            from_ver = await db.scalar(
                select(OntologyVersion).where(OntologyVersion.id == version_from_id)
            )
            to_ver = await db.scalar(
                select(OntologyVersion).where(OntologyVersion.id == version_to_id)
            )
            if from_ver is None or to_ver is None:
                log.error(
                    "compute_ontology_comparison_missing_version",
                    from_vid=version_from_id, to_vid=version_to_id,
                )
                return

            existing = await db.scalar(
                select(OntologyComparison).where(
                    OntologyComparison.version_from_id == version_from_id,
                    OntologyComparison.version_to_id == version_to_id,
                )
            )
            if existing and existing.status == "ready":
                return

            await db.execute(
                pg_insert(OntologyComparison)
                .values(
                    id=str(uuid.uuid4()),
                    from_ontology_id=from_ver.ontology_id,
                    to_ontology_id=to_ver.ontology_id,
                    version_from_id=version_from_id,
                    version_to_id=version_to_id,
                    status="pending",
                )
                .on_conflict_do_nothing()
            )
            await db.commit()

            row = await db.scalar(
                select(OntologyComparison).where(
                    OntologyComparison.version_from_id == version_from_id,
                    OntologyComparison.version_to_id == version_to_id,
                )
            )
            if row is None:
                return  # should not happen, but guard

            try:
                store = get_store()
                summary, diff_data = await asyncio.to_thread(
                    _run_comparison,
                    store,
                    str(from_ver.ontology_id), version_from_id,
                    str(to_ver.ontology_id),   version_to_id,
                )
                row.summary = summary
                row.diff_data = diff_data
                row.status = "ready"
            except Exception as exc:
                row.status = "failed"
                log.error(
                    "compute_ontology_comparison_failed",
                    from_vid=version_from_id, to_vid=version_to_id, error=str(exc),
                )
            await db.commit()

    try:
        asyncio.run(_run())
        log.info(
            "compute_ontology_comparison_done",
            from_vid=version_from_id, to_vid=version_to_id,
        )
    except Exception as exc:
        log.error("compute_ontology_comparison_task_error", error=str(exc))
        raise
    return {"status": "done"}


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
    groups: list[str] | None = None,
) -> dict:
    """Celery task: run the full ingestion pipeline for one ontology submission."""
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion

    raw_bytes = bytes.fromhex(raw_bytes_hex) if raw_bytes_hex else None
    request = IngestionRequest(
        iri=iri, url=url, raw_bytes=raw_bytes,
        filename=filename, content_type=content_type, owner_id=owner_id, groups=groups or [],
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


@celery_app.task(name="ontoexplorer.load_imports", bind=True, max_retries=1)
def load_imports(self, version_id: str, ontology_id: str) -> dict:
    """
    Load all resolved owl:imports for a version into Oxigraph (backfill task).

    Safe to re-run: appends triples without clearing the named graph, so it is
    idempotent if the same triples are already present (Oxigraph deduplicates).
    """
    async def _run():
        from sqlalchemy import select
        from ontoexplorer.clients.oxigraph import append_bytes_to_graph
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.models.db import OntologyImport
        from ontoexplorer.modules.storage.minio_client import get_import_bytes

        loaded = 0
        async with make_celery_db_session()() as db:
            result = await db.execute(
                select(OntologyImport).where(OntologyImport.version_id == version_id)
            )
            imports = result.scalars().all()

        for imp in imports:
            if not imp.resolved_minio_key:
                continue
            try:
                data, ext = get_import_bytes(imp.resolved_minio_key)
                append_bytes_to_graph(ontology_id, version_id, data, ext)
                loaded += 1
                log.info("import_loaded", version_id=version_id, iri=imp.import_iri)
            except Exception as exc:
                log.warning("import_load_failed", version_id=version_id,
                            iri=imp.import_iri, error=str(exc))

        return {"version_id": version_id, "imports_loaded": loaded}

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("load_imports_failed", version_id=version_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(name="ontoexplorer.index_ontology", bind=True, max_retries=2)
def index_ontology(self, version_id: str, ontology_id: str = "") -> dict:
    """Build the Redis entity search index for a version and mark it ready."""
    log.info("index_ontology_start", version_id=version_id)
    try:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.profile.detector import load_profile

        async def _fetch_profile():
            async with make_celery_db_session()() as db:
                return await load_profile(db, version_id)

        profile = asyncio.run(_fetch_profile())
        from ontoexplorer.modules.search.indexer import build_index
        stats = build_index(version_id, ontology_id, profile=profile)

        from sqlalchemy import update as _sa_update
        from ontoexplorer.models.db import OntologyVersion as _OV

        async def _mark_ready():
            async with make_celery_db_session()() as db:
                await db.execute(
                    _sa_update(_OV)
                    .where(_OV.id == version_id, _OV.status != "deprecated")
                    .values(status="ready")
                )
                await db.commit()

        asyncio.run(_mark_ready())
        embed_ontology.delay(version_id, ontology_id=ontology_id)
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


async def _run_poll(db) -> None:
    """Async body of poll_for_updates: check each auto_sync ontology for changes."""
    import hashlib
    import httpx as _httpx

    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion

    result = await db.execute(
        select(Ontology).where(Ontology.auto_sync.is_(True))
    )
    ontologies = result.scalars().all()

    for ont in ontologies:
        ver_result = await db.execute(
            select(OntologyVersion)
            .where(OntologyVersion.ontology_id == ont.id)
            .where(OntologyVersion.status != "deprecated")
            .where(OntologyVersion.source_url.is_not(None))
            .order_by(OntologyVersion.created_at.desc())
            .limit(1)
        )
        version = ver_result.scalar_one_or_none()
        if not version:
            continue

        try:
            with _httpx.Client(timeout=_httpx.Timeout(60.0), follow_redirects=True) as client:
                resp = client.get(version.source_url)
                resp.raise_for_status()
                new_sha256 = hashlib.sha256(resp.content).hexdigest()
        except Exception as exc:
            log.warning("poll_fetch_failed", ontology_id=ont.id,
                        source_url=version.source_url, error=str(exc))
            continue

        if new_sha256 == version.sha256:
            log.info("poll_no_change", ontology_id=ont.id, source_url=version.source_url)
            continue

        log.info("poll_change_detected", ontology_id=ont.id,
                 source_url=version.source_url, old_sha256=version.sha256, new_sha256=new_sha256)
        ingest_ontology.delay(url=version.source_url, owner_id=ont.owner_id, groups=list(ont.groups or []))


@celery_app.task(name="ontoexplorer.poll_for_updates")
def poll_for_updates() -> None:
    """Periodic task: re-fetch all auto_sync ontologies and queue re-ingestion if changed."""
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
            await _run_poll(db)

    asyncio.run(_run())


@celery_app.task(name="ontoexplorer.embed_ontology")
def embed_ontology(version_id: str, ontology_id: str = "") -> dict:
    """Compute pgvector embeddings for all indexed entities in a version."""
    log.info("embed_ontology_start", version_id=version_id)
    try:
        import uuid as _uuid_mod
        from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
        from ontoexplorer.modules.search.indexer import _get_redis, _iri_key, _type_key
        from ontoexplorer.modules.search.embedder import build_entity_text, text_hash, embed_texts
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.models.db import TermEmbedding
        from ontoexplorer.modules.jobs import tracker
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        r = _get_redis()
        named_graph = graph_iri(ontology_id, version_id)

        all_entities: dict[str, str] = {}
        for etype in ["class", "object_property", "data_property", "annotation_property", "individual"]:
            for iri in r.smembers(_type_key(version_id, etype)):
                all_entities[iri] = etype

        if not all_entities:
            log.info("embed_ontology_skip_empty", version_id=version_id)
            return {"status": "skip", "version_id": version_id}

        _SKIP_IRIS = {
            "http://www.w3.org/2002/07/owl#Thing",
            "http://www.w3.org/2002/07/owl#topObjectProperty",
            "http://www.w3.org/2002/07/owl#topDataProperty",
        }
        parents_by_iri: dict[str, list[str]] = {iri: [] for iri in all_entities}
        children_by_iri: dict[str, list[str]] = {iri: [] for iri in all_entities}

        try:
            for sol in sparql_query(f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?entity ?parent WHERE {{
                    GRAPH <{named_graph}> {{
                        ?entity rdfs:subClassOf ?parent .
                        FILTER(isIRI(?entity) && isIRI(?parent))
                    }}
                }}
            """):
                iri = sol["entity"].value
                parent = sol["parent"].value
                if iri in parents_by_iri and parent not in _SKIP_IRIS:
                    parents_by_iri[iri].append(parent)
            for sol in sparql_query(f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?child ?entity WHERE {{
                    GRAPH <{named_graph}> {{
                        ?child rdfs:subClassOf ?entity .
                        FILTER(isIRI(?child) && isIRI(?entity))
                    }}
                }}
            """):
                iri = sol["entity"].value
                child = sol["child"].value
                if iri in children_by_iri:
                    children_by_iri[iri].append(child)
        except Exception as exc:
            log.warning("embed_ontology_sparql_warn", version_id=version_id, error=str(exc))

        def _label(iri: str) -> str:
            v = r.hget(_iri_key(version_id, iri), "primary_label")
            return v or iri.split("/")[-1].split("#")[-1]

        records: list[tuple[str, str, str, str]] = []
        for iri, etype in all_entities.items():
            entity = r.hgetall(_iri_key(version_id, iri))
            if not entity:
                continue
            p_labels = [_label(p) for p in parents_by_iri.get(iri, [])[:5]]
            c_labels = [_label(c) for c in children_by_iri.get(iri, [])[:10]]
            t = build_entity_text(entity, p_labels, c_labels)
            records.append((iri, etype, t, text_hash(t)))

        if not records:
            return {"status": "skip", "version_id": version_id}

        BATCH = 32
        total = len(records)

        async def _embed_and_store() -> None:
            async with make_celery_db_session()() as db:
                job = await tracker.create_job(db, version_id=version_id, job_type="embedding")
                await tracker.mark_running(db, job.id)
                try:
                    for i in range(0, total, BATCH):
                        batch = records[i : i + BATCH]
                        embeddings = embed_texts([rec[2] for rec in batch])
                        for (iri, etype, _, h), emb in zip(batch, embeddings):
                            stmt = pg_insert(TermEmbedding).values(
                                id=str(_uuid_mod.uuid4()),
                                version_id=version_id,
                                entity_iri=iri,
                                entity_type=etype,
                                text_hash=h,
                                embedding=emb,
                            ).on_conflict_do_update(
                                index_elements=["version_id", "entity_iri"],
                                set_={"entity_type": etype, "text_hash": h, "embedding": emb},
                                where=(TermEmbedding.text_hash != h),
                            )
                            await db.execute(stmt)
                        await db.commit()
                        done = min(i + BATCH, total)
                        if done % 1000 < BATCH or done == total:
                            log.info("embed_ontology_progress", version_id=version_id,
                                     done=done, total=total)
                    await tracker.mark_done(db, job.id)
                except Exception as exc:
                    await tracker.mark_failed(db, job.id, str(exc))
                    raise

        asyncio.run(_embed_and_store())
        log.info("embed_ontology_done", version_id=version_id, total=total)
        return {"status": "done", "version_id": version_id, "total": total}
    except Exception as exc:
        log.error("embed_ontology_failed", version_id=version_id, error=str(exc))
        return {"status": "failed", "version_id": version_id, "error": str(exc)}
