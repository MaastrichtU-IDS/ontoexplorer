"""Celery application and task definitions."""

import asyncio

import pyoxigraph
import rdflib
from celery import Celery
from celery.schedules import crontab

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
    # Redis broker redelivers any task still unacked after visibility_timeout,
    # assuming the worker died. With acks_late=True a task is acked only on
    # completion, so the default (3600s) causes long jobs — reasoning, or
    # embedding a 200k-term ontology — to be redelivered and run as a duplicate
    # every hour. Raise it well above the longest expected task.
    broker_transport_options={"visibility_timeout": 86400},  # 24h
    result_backend_transport_options={"visibility_timeout": 86400},
    task_ignore_result=True,  # use Postgres jobs table for status; avoid blocking on Redis result backend
    task_default_queue="light",
    # Workers split by Oxigraph ACCESS MODE, not by "heavy/light" — see
    # docker-compose.yml. The embedded pyoxigraph (RocksDB) store allows only ONE
    # read-write opener but any number of read-only ones. Route every task that
    # WRITES triples to a dedicated "write" queue drained by a single-concurrency
    # worker, so there is exactly one read-write opener and no LOCK contention.
    # ingest/reason/load_imports are the only writers; everything else reads the
    # store read-only (OXIGRAPH_READ_ONLY=true on the "light" worker) and runs in
    # parallel. Unrouted tasks fall back to `light` via task_default_queue.
    task_routes={
        "ontoexplorer.ingest_ontology": {"queue": "write"},
        "ontoexplorer.reason_ontology": {"queue": "write"},
        "ontoexplorer.load_imports": {"queue": "write"},
        "ontoexplorer.purge_version_artifacts": {"queue": "write"},
    },
    beat_schedule={
        "poll-for-updates-hourly": {
            "task": "ontoexplorer.poll_for_updates",
            "schedule": 3600.0,
        },
        "refresh-stale-inferred-diffs-15min": {
            "task": "ontoexplorer.refresh_stale_inferred_diffs",
            "schedule": 900.0,
        },
        "beat-heartbeat-60s": {
            "task": "ontoexplorer.beat_heartbeat",
            "schedule": 60.0,
        },
        # Flush Redis view/download counters into usage_daily (absolute upsert).
        "rollup-usage-15min": {
            "task": "ontoexplorer.rollup_usage",
            "schedule": 900.0,
        },
        # Weekly snapshot of the processed aggregates to MinIO (durability).
        "backup-usage-weekly": {
            "task": "ontoexplorer.backup_usage_daily",
            "schedule": crontab(hour=3, minute=30, day_of_week="sun"),
        },
    },
)


@celery_app.task(name="ontoexplorer.beat_heartbeat")
def beat_heartbeat() -> None:
    """Write the current UTC timestamp to Redis so the admin health check can detect a dead beat."""
    from datetime import UTC, datetime
    import redis as redis_sync
    r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
    r.set("beat:heartbeat", datetime.now(UTC).isoformat(), ex=300)


@celery_app.task(name="ontoexplorer.rollup_usage")
def rollup_usage() -> dict:
    """Flush today's + yesterday's Redis usage counters into usage_daily.

    Both days each run: yesterday is re-flushed to capture any hits recorded
    just before the UTC boundary. Upserts are absolute counts → idempotent.
    """
    try:
        from datetime import UTC, datetime, timedelta

        import redis as redis_sync

        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.usage.rollup import flush_day

        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        now = datetime.now(UTC)
        days = [now.strftime("%Y%m%d"), (now - timedelta(days=1)).strftime("%Y%m%d")]

        async def _run() -> int:
            written = 0
            async with make_celery_db_session()() as db:
                for d in days:
                    written += await flush_day(db, r, d)
            return written

        n = asyncio.run(_run())
        log.info("rollup_usage_done", rows=n)
        return {"status": "done", "rows": n}
    except Exception as exc:
        log.error("rollup_usage_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


@celery_app.task(name="ontoexplorer.backup_usage_daily")
def backup_usage_daily() -> dict:
    """Snapshot the whole usage_daily table to MinIO as JSON (durability)."""
    try:
        from datetime import UTC, datetime

        from ontoexplorer.clients.minio import ensure_bucket, upload_bytes
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.usage.rollup import export_usage_daily

        async def _run() -> bytes:
            async with make_celery_db_session()() as db:
                return await export_usage_daily(db)

        blob = asyncio.run(_run())
        bucket = get_settings().minio_backups_bucket
        ensure_bucket(bucket)
        key = f"usage-backups/usage_daily_{datetime.now(UTC).strftime('%Y-%m-%d')}.json"
        upload_bytes(bucket, key, blob, content_type="application/json")
        log.info("backup_usage_daily_done", key=key, bytes=len(blob))
        return {"status": "done", "key": key, "bytes": len(blob)}
    except Exception as exc:
        log.error("backup_usage_daily_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


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



@celery_app.task(name="ontoexplorer.purge_version_artifacts", time_limit=600)
def purge_version_artifacts(ontology_id: str, version_id: str, minio_key: str | None = None) -> dict:
    """Erase one version's artifacts from every store outside Postgres.

    Deleting an ontology used to remove only its Postgres rows. The triples
    stayed in Oxigraph and remained anonymously queryable through
    /api/v1/sparql/content, the DCAT and PROV records stayed in Fuseki's shared
    catalogue graphs, and the uploaded file stayed in MinIO — so a "deleted"
    ontology was still fully readable, and a withdrawal request could not
    actually be honoured. `clients.oxigraph.delete_graph` existed the whole time
    and had no callers.

    Runs on the write queue because the API opens Oxigraph read-only; only
    worker-heavy holds the read-write handle.

    Best-effort per store: one unreachable backend must not strand the rest, so
    each step is attempted and failures are collected rather than raised.
    """
    import asyncio

    removed: dict[str, str] = {}

    def _step(name, fn):
        try:
            fn()
            removed[name] = "ok"
        except Exception as exc:
            removed[name] = f"failed: {exc}"
            log.warning("purge_step_failed", step=name, version_id=version_id, error=str(exc))

    from ontoexplorer.clients.oxigraph import delete_graph as _drop_content_graph

    _step("oxigraph_asserted", lambda: _drop_content_graph(ontology_id, version_id, inferred=False))
    _step("oxigraph_inferred", lambda: _drop_content_graph(ontology_id, version_id, inferred=True))

    def _drop_fuseki():
        from ontoexplorer.modules.metadata.fuseki_writer import delete_version_metadata
        asyncio.run(delete_version_metadata(ontology_id, version_id))

    _step("fuseki_metadata", _drop_fuseki)

    if minio_key:
        def _drop_object():
            from ontoexplorer.clients.minio import remove_object
            from ontoexplorer.config import get_settings as _gs
            remove_object(_gs().minio_ontologies_bucket, minio_key)

        _step("minio_object", _drop_object)

    def _drop_redis():
        from ontoexplorer.modules.search.indexer import _get_redis
        r = _get_redis()
        for key in r.scan_iter(match=f"*{version_id}*"):
            r.delete(key)

    _step("redis_index", _drop_redis)

    log.info("purged_version_artifacts", version_id=version_id, result=removed)
    return removed

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
                from ontoexplorer.modules.diff.compute import collect_inferred_status
                inferred_status = await collect_inferred_status(
                    db, version_from_id, version_to_id,
                )
                summary, diff_data = await asyncio.to_thread(
                    _run_comparison,
                    store,
                    str(from_ver.ontology_id), version_from_id,
                    str(to_ver.ontology_id),   version_to_id,
                    inferred_status=inferred_status,
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


async def _ingest_tracked(request, job_id: str | None, session_factory):
    """Run the ingestion pipeline, mirroring its progress into the jobs table.

    The row is keyed by the Celery task id, so the `task_id` POST /ontologies
    hands back is exactly the id GET /jobs/{id} answers to. Without this, a
    submission that fails before the pipeline produces an OntologyVersion —
    unreachable IRI, source over the download cap, unparseable file — left no
    trace outside the worker log, and the caller saw a queued submission that
    simply never appeared.

    Each jobs update runs in its own session so it is unaffected by the state
    of the (possibly failed) ingestion transaction, and a tracking failure is
    logged rather than allowed to mask the real outcome.
    """
    from ontoexplorer.modules.ingestion.pipeline import run_ingestion
    from ontoexplorer.modules.jobs import tracker

    async def _track(fn) -> None:
        if not job_id:
            return
        try:
            async with session_factory() as db:
                await fn(db)
        except Exception:
            log.exception("ingest_job_tracking_failed", job_id=job_id)

    await _track(lambda db: tracker.start_job(db, job_id, "ingestion"))
    try:
        async with session_factory() as db:
            result = await run_ingestion(db, request)
    except Exception as exc:
        # Bind the text now: Python unbinds `exc` at the end of the except block,
        # so a lambda closing over it would be reading a name about to vanish.
        message = str(exc)[:1000]
        await _track(lambda db: tracker.mark_failed(db, job_id, message))
        raise
    await _track(lambda db: tracker.mark_done(db, job_id, version_id=result.version_id))
    return result


@celery_app.task(bind=True, name="ontoexplorer.ingest_ontology", max_retries=3)
def ingest_ontology(
    self,
    *,
    iri: str | None = None,
    url: str | None = None,
    raw_bytes_hex: str | None = None,
    upload_key: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    format: str | None = None,
    owner_id: str | None = None,
    groups: list[str] | None = None,
    reasoner: str = "rustdl",
    reasoner_profile_id: str | None = None,
) -> dict:
    """Celery task: run the full ingestion pipeline for one ontology submission."""
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.modules.ingestion.format_detect import parse_format
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest

    # File uploads are staged in MinIO and referenced by key (see submit_ontology),
    # so the bytes never travel through the broker. Fall back to the legacy
    # inline-hex path for backward compatibility.
    if upload_key:
        from ontoexplorer.modules.storage.minio_client import fetch_staged_upload
        raw_bytes = fetch_staged_upload(upload_key)
    else:
        raw_bytes = bytes.fromhex(raw_bytes_hex) if raw_bytes_hex else None
    # Celery args are JSON, so the format arrives as a string; the API has
    # already validated it, and re-parsing here keeps the task callable directly.
    request = IngestionRequest(
        iri=iri, url=url, raw_bytes=raw_bytes,
        filename=filename, content_type=content_type, format=parse_format(format),
        owner_id=owner_id, groups=groups or [],
        reasoner=reasoner, reasoner_profile_id=reasoner_profile_id,
    )

    session_factory = make_celery_db_session()

    async def _run():
        return await _ingest_tracked(request, self.request.id, session_factory)

    try:
        result = asyncio.run(_run())
        if upload_key:
            # Ingestion stored the file under the ontologies bucket; drop the
            # staging copy. Only on success — retries re-fetch the same key.
            from ontoexplorer.modules.storage.minio_client import delete_staged_upload
            delete_staged_upload(upload_key)
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
        # Deterministic failures shouldn't retry — retrying just re-runs the same
        # doomed classification. TimeoutError = the ontology is too large/hard for
        # this reasoner within reasoner_service_timeout; ReasoningFailed = the
        # reasoner-service recorded a backend crash/OOM/unsupported-axiom/timeout
        # error. Both fail fast (the job row is already marked failed by
        # _run_reasoning). Other errors may be transient (worker/service blip) and
        # still retry.
        from ontoexplorer.clients.reasoning import ReasoningFailed
        if isinstance(exc, (TimeoutError, ReasoningFailed)):
            raise
        raise self.retry(exc=exc, countdown=120) from exc


async def _run_reasoning(db, version_id: str) -> dict:
    """Async body of the reasoning task."""
    from sqlalchemy import select

    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs import tracker

    # Look up the version so we have ontology_id
    result = await db.execute(select(OntologyVersion).where(OntologyVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        raise ValueError(f"OntologyVersion {version_id} not found")

    ontology_id = version.ontology_id

    # Create / mark job as running
    job = await tracker.create_job(db, version_id=version_id, job_type="reason")
    await tracker.mark_running(db, job.id)

    try:
        return await _reason_and_persist(db, version, version_id, ontology_id, job.id)
    except Exception as exc:
        # Mark this attempt failed so a crash/timeout doesn't leave a zombie
        # 'running' row (e.g. classify_v2 TimeoutError on very large ontologies
        # such as GO). The outer task may still retry; each attempt then ends
        # 'failed' rather than lingering forever as 'running'.
        try:
            await tracker.mark_failed(db, job.id, str(exc)[:1000])
        except Exception:
            log.exception("reason_mark_failed_failed", version_id=version_id)
        raise


def _version_is_el_profile(version_id: str) -> bool:
    """True if the version's cached OWL 2 profile report marks it in the EL profile.

    The report is computed during indexing and cached in Redis by owl_profile.
    Returns False if it's missing or unreadable (safe default: full DL path).
    """
    import json
    try:
        from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
        from ontoexplorer.modules.search.indexer import _get_redis
        raw = _get_redis().get(owl_profile_cache_key(version_id))
        if not raw:
            return False
        return bool(json.loads(raw).get("el", {}).get("in_profile"))
    except Exception:
        log.exception("el_profile_lookup_failed", version_id=version_id)
        return False


def _named_classes_in_store(ontology_id: str, version_id: str) -> set[str]:
    """Every named class declared in a version's asserted graph.

    Read from Oxigraph rather than the Redis search index so the inferred
    hierarchy does not depend on indexing having already run. Blank nodes are
    excluded: anonymous class expressions are not navigable tree nodes.
    """
    from ontoexplorer.clients.oxigraph import graph_iri, sparql_query

    g = graph_iri(ontology_id, version_id)
    try:
        solutions = sparql_query(f"""
            SELECT DISTINCT ?c FROM <{g}> WHERE {{
                {{ ?c a <http://www.w3.org/2002/07/owl#Class> }}
                UNION {{ ?c a <http://www.w3.org/2000/01/rdf-schema#Class> }}
                FILTER(isIRI(?c))
            }}
        """)
        return {row["c"].value for row in solutions}
    except Exception as exc:
        # Best-effort: the Redis union below still covers the common case.
        log.warning("named_class_lookup_failed", version_id=version_id, error=str(exc))
        return set()


async def _reason_and_persist(db, version, version_id: str, ontology_id: str, job_id: str) -> dict:
    """Classify the asserted graph, persist inferred triples, and mark the job done.

    Split out from _run_reasoning so its caller can mark the job 'failed' on any
    exception instead of leaving it 'running'.
    """
    from ontoexplorer.clients import reasoning as reasoning_client
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.jobs import tracker
    from ontoexplorer.modules.webhooks.delivery import broadcast_event

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

    # Resolve the version's reasoner profile (reference-binding) into the effective
    # parameter dict passed to the reasoner. A profile's params win; when it's
    # silent we still auto-enable rustdl EL-saturation for EL-profile ontologies
    # (rustdl's SROIQ tableau is O(n²) and blows up on large EL ontologies like GO).
    from sqlalchemy import select as _select
    from ontoexplorer.models.db import Job, ReasonerProfile
    params: dict = {}
    if version.reasoner_profile_id:
        prof = (await db.execute(
            _select(ReasonerProfile).where(ReasonerProfile.id == version.reasoner_profile_id)
        )).scalar_one_or_none()
        if prof:
            params = dict(prof.params or {})
    if version.reasoner == "rustdl" and "saturation_only" not in params and _version_is_el_profile(version_id):
        params["saturation_only"] = True

    # Record the effective run on the job for provenance (reference-binding
    # resolves params at run time, so snapshot what was actually used).
    from sqlalchemy import update as _update
    await db.execute(_update(Job).where(Job.id == job_id).values(
        meta={"reasoner": version.reasoner, "params": params,
              "profile_id": version.reasoner_profile_id}))
    await db.commit()
    log.info("reasoning_params", version_id=version_id, reasoner=version.reasoner,
             params=params, profile_id=version.reasoner_profile_id)

    import httpx as _httpx
    from ontoexplorer.config import get_settings as _get_settings
    await reasoning_client.classify_v2(
        asserted_graph, version_id, reasoner=version.reasoner, params=params, force=True
    )

    # Fetch the full inferred graph from ELK classification result for Oxigraph persistence
    async with _httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{_get_settings().reasoner_service_url}/classify/{version_id}?reasoner={version.reasoner}"
        )
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

    # Materialise the inferred hierarchy for the navigation tree. Deriving it
    # per request meant fetching and parsing the whole classification (12 s on
    # DRON) and reducing 771,507 classes to direct parents (1 s) to return two
    # terms. Best-effort: /inferred-children falls back for versions with no
    # inferred edges. Scoped to the 'inferred' kind so it cannot clear the
    # asserted edges, which indexing writes concurrently on another queue.
    try:
        import time as _t
        from ontoexplorer.clients.reasoning import get_classification
        from ontoexplorer.modules.hierarchy.edges import (
            INFERRED_KIND,
            reduce_direct_inferred,
            replace_edges,
            replace_inferred_roots,
        )
        from ontoexplorer.modules.search.indexer import _get_redis, _type_key

        _t0 = _t.monotonic()
        _c = await get_classification(version_id, reasoner=version.reasoner)
        # Union in every named class: EL reasoners omit classes with no
        # non-trivial subsumptions, and those are exactly the top-level classes
        # that must still appear as inferred roots.
        _all = set(_c.get("direct_superclasses", {})) | set(_c.get("superclasses", {}))
        for _parents in _c.get("direct_superclasses", {}).values():
            _all.update(_parents)
        for _parents in _c.get("superclasses", {}).values():
            _all.update(_parents)
        # The named classes come from the RDF store, not from the Redis type
        # set alone. Redis is written by indexing, which the pipeline queues
        # *after* reasoning (step 9 vs step 8) and on a different queue, so
        # reasoning routinely wins the race and reads an empty set. When that
        # happened, `_all` held only the classes the reasoner mentioned, and
        # every class with no non-trivial subsumption silently vanished from
        # the inferred tree -- e.g. SKOS lost skos:Concept and
        # skos:ConceptScheme, keeping only skos:Collection.
        #
        # Redis stays in the union: it is authoritative once built, and covers
        # anything indexing derives that a plain type assertion does not.
        _all |= _named_classes_in_store(str(version.ontology_id), version_id)
        _all |= {
            m.decode() if isinstance(m, bytes) else m
            for m in _get_redis().smembers(_type_key(version_id, "class"))
        }
        _edges, _roots = reduce_direct_inferred(
            _c.get("direct_superclasses", {}), _c.get("superclasses", {}),
            _c.get("unsatisfiable", []), _all,
        )
        await replace_edges(db, version_id, _edges, kinds=(INFERRED_KIND,))
        await replace_inferred_roots(db, version_id, _roots)
        log.info("inferred_hierarchy_materialised", version_id=version_id,
                 edges=len(_edges), roots=len(_roots),
                 duration_s=round(_t.monotonic() - _t0, 2))
    except Exception as exc:
        log.warning("inferred_hierarchy_failed", version_id=version_id, error=str(exc))

    # Update job status
    await tracker.mark_done(db, job_id)

    # Fire webhook
    await broadcast_event(db, "reasoning.completed", {
        "version_id": version_id,
        "ontology_id": ontology_id,
        "inferred_axiom_count": inferred_count,
    })

    # Re-queue any diffs whose inferred half is stale for this version.
    try:
        await _requeue_stale_diffs_for_version(db, version_id)
    except Exception:
        log.exception("requeue_stale_diffs_failed", version_id=version_id)
        # Don't fail the reasoning task — the beat safety net will catch missed
        # re-queues.

    return {"version_id": version_id, "inferred_count": inferred_count}


async def _requeue_stale_diffs_for_version(db, version_id: str) -> None:
    """Re-queue compute_diff / compute_ontology_comparison for any row whose
    stored inferred_status for this version isn't 'ready'.

    Covers both OntologyDiff (intra-ontology version diff) and OntologyComparison
    (cross-ontology comparison; includes same-ontology version comparisons from /compare).
    """
    from sqlalchemy import or_, select
    from ontoexplorer.models.db import OntologyComparison, OntologyDiff

    diffs = (await db.execute(
        select(OntologyDiff).where(
            or_(
                OntologyDiff.version_from_id == version_id,
                OntologyDiff.version_to_id == version_id,
            ),
            OntologyDiff.status == "ready",
        )
    )).scalars().all()
    for row in diffs:
        inferred_status = (row.summary or {}).get("inferred_status", {})
        side = "from_version" if row.version_from_id == version_id else "to_version"
        if inferred_status.get(side) == "ready":
            continue
        log.info(
            "requeuing_stale_diff",
            diff_id=row.id,
            version_id=version_id,
            side=side,
            current_status=inferred_status.get(side),
        )
        compute_diff.delay(row.version_from_id, row.version_to_id, row.ontology_id)

    comparisons = (await db.execute(
        select(OntologyComparison).where(
            or_(
                OntologyComparison.version_from_id == version_id,
                OntologyComparison.version_to_id == version_id,
            ),
            OntologyComparison.status == "ready",
        )
    )).scalars().all()
    for row in comparisons:
        inferred_status = (row.summary or {}).get("inferred_status", {})
        side = "from_version" if row.version_from_id == version_id else "to_version"
        if inferred_status.get(side) == "ready":
            continue
        log.info(
            "requeuing_stale_comparison",
            comparison_id=row.id,
            version_id=version_id,
            side=side,
            current_status=inferred_status.get(side),
        )
        compute_ontology_comparison.delay(row.version_from_id, row.version_to_id)


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

        # Mirror the asserted hierarchy so the navigation tree is served from
        # SQL rather than re-deriving roots from the whole graph on every cache
        # miss. Runs before entity_index so the child set can be written there
        # as is_root. Best-effort: list_terms falls back to SPARQL for any
        # version with no edge rows.
        _non_roots: set[str] | None = None
        try:
            import time as _t
            from ontoexplorer.clients.oxigraph import get_store, graph_iri
            from ontoexplorer.database import make_celery_db_session as _mk
            from ontoexplorer.modules.hierarchy.edges import (
                extract_edges,
                non_root_iris,
                replace_edges,
            )

            _t0 = _t.monotonic()
            _edges = extract_edges(get_store(), graph_iri(ontology_id, version_id))
            _non_roots = non_root_iris(_edges)

            async def _store_edges():
                async with _mk()() as _db:
                    return await replace_edges(_db, version_id, _edges)

            _n = asyncio.run(_store_edges())
            _edges_ready = _n > 0
            log.info("hierarchy_edges_populated", version_id=version_id, edges=_n,
                     duration_s=round(_t.monotonic() - _t0, 2))
        except Exception as exc:
            _edges_ready = False
            log.warning("hierarchy_edges_failed", version_id=version_id, error=str(exc))

        # Mirror the Redis index into Postgres `entity_index` for the SQL-backed
        # /search path. Best-effort: keyword search falls back to Redis if this fails.
        try:
            from ontoexplorer.modules.search.pg_indexer import populate_entity_index_sync
            pg_rows = populate_entity_index_sync(version_id, ontology_id, _non_roots)
            log.info("entity_index_populated", version_id=version_id, rows=pg_rows)
        except Exception as exc:
            log.warning("entity_index_populate_failed", version_id=version_id, error=str(exc))

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
        # The Celery worker invalidates only its own in-process cache; the API
        # process picks up the new version on its own 30s TTL expiry. That's
        # acceptable — ingest is not a low-latency path.
        try:
            from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache
            invalidate_latest_ready_versions_cache()
        except Exception:
            pass
        # Drop the shared cross-process /search, /autocomplete, /terms response
        # caches so newly-indexed entities show up immediately rather than waiting on TTL.
        try:
            from ontoexplorer.modules.search.indexer import _get_redis
            _r = _get_redis()
            for _pattern in ("search:result:*", "search:autocomplete:*", "search:term:*"):
                for _k in _r.scan_iter(_pattern, count=500):
                    _r.delete(_k)
        except Exception:
            pass
        # Precompute the navigation tree's root level. Root detection compares
        # the whole entity set against the whole child set, which on a
        # DRON-sized ontology (~800k classes) takes ~13 s — the indexing worker
        # pays it once here so no visitor does. Also drops the pre-index cached
        # variants, which the long TTL would otherwise preserve.
        try:
            import time as _time
            from ontoexplorer.modules.search.indexer import _get_redis
            _t0 = _time.monotonic()
            if _edges_ready:
                # Cheap path: the edges were just written, so reuse them rather
                # than re-deriving roots from the whole graph (~0.7 s vs ~17 s).
                from ontoexplorer.database import make_celery_db_session as _mk2
                from ontoexplorer.modules.hierarchy.edges import warm_root_cache_sql

                async def _warm():
                    async with _mk2()() as _db:
                        return await warm_root_cache_sql(_db, _get_redis(), version_id)

                _n = asyncio.run(_warm())
                _via = "sql"
            else:
                from ontoexplorer.clients.oxigraph import get_store, graph_iri
                from ontoexplorer.modules.hierarchy.roots import warm_root_cache
                _n = warm_root_cache(
                    get_store(), _get_redis(), version_id,
                    graph_iri(ontology_id, version_id),
                    deprecated_filter=(
                        'FILTER NOT EXISTS { ?class owl:deprecated ?_d . '
                        'FILTER(str(?_d) = "true") }'
                    ),
                )
                _via = "sparql"
            log.info("root_cache_warmed", version_id=version_id, roots=_n, via=_via,
                     duration_s=round(_time.monotonic() - _t0, 2))
        except Exception as exc:
            # Non-fatal: the endpoint still computes on demand.
            log.warning("root_cache_warm_failed", version_id=version_id, error=str(exc))
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
        from sqlalchemy import select

        from ontoexplorer.clients import reasoning as reasoning_client
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.models.db import OntologyVersion
        from ontoexplorer.modules.jobs import tracker
        from ontoexplorer.modules.webhooks.delivery import broadcast_event

        async with make_celery_db_session()() as db:
            job = await tracker.create_job(db, version_id=version_id, job_type="justification")
            await tracker.mark_running(db, job.id)
            try:
                version_result = await db.execute(
                    select(OntologyVersion).where(OntologyVersion.id == version_id)
                )
                version = version_result.scalar_one_or_none()
                reasoner = version.reasoner if version else "rustdl"
                result = await reasoning_client.request_justification(
                    version_id, sub, sup, max_justifications, reasoner=reasoner
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

        # Larger batches amortize ONNX call overhead and cut DB-commit frequency.
        # embed_texts feeds these to passage_embed in sub-batches of 128.
        BATCH = 256
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


@celery_app.task(name="ontoexplorer.refresh_owl_profile", time_limit=300)
def refresh_owl_profile(version_id: str, ontology_id: str) -> dict:
    """Rebuild ONLY the owl_profile:{version_id} Redis cache.

    Cheaper alternative to a full index_ontology when the only thing that
    needs updating is the OWL profile classification (e.g. after fixing a
    detector bug). Does NOT touch the search index or queue embeddings.
    """
    import json as _json
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.owl_profile.detector import detect_profiles
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    from ontoexplorer.modules.search.indexer import _get_redis, _SEARCH_TTL

    g = graph_iri(ontology_id, version_id)
    payload = detect_profiles(get_store(), graph_iri=g,
                              ontology_id=ontology_id, version_id=version_id)
    _get_redis().setex(owl_profile_cache_key(version_id), _SEARCH_TTL, _json.dumps(payload))
    log.info("owl_profile_refresh_done", version_id=version_id)
    return {"status": "done", "version_id": version_id,
            "verdicts": {p: payload[p]["in_profile"] for p in ("el", "rl", "ql", "dl")}}


@celery_app.task(name="ontoexplorer.refresh_stale_inferred_diffs")
def refresh_stale_inferred_diffs() -> dict:
    """Safety net: catch diffs whose inferred half is stale because the
    inline re-queue hook in reason_ontology failed (e.g. worker crash).

    For each OntologyDiff with status='ready', if either side's
    inferred_status is not 'ready' AND that side's reasoning job is now
    'done', re-queue compute_diff.
    """
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
            await _refresh_stale_inferred_diffs_body(db)

    try:
        asyncio.run(_run())
        return {"status": "done"}
    except Exception as exc:
        log.exception("refresh_stale_inferred_diffs_failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


async def _refresh_stale_inferred_diffs_body(db) -> int:
    """Returns the count of diffs/comparisons re-queued."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyComparison, OntologyDiff
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version

    requeued = 0

    diffs = (await db.execute(
        select(OntologyDiff).where(OntologyDiff.status == "ready")
    )).scalars().all()
    for row in diffs:
        inferred_status = (row.summary or {}).get("inferred_status", {})
        for side, vid in (
            ("from_version", row.version_from_id),
            ("to_version", row.version_to_id),
        ):
            if inferred_status.get(side) != "ready":
                current = await _reasoning_status_for_version(db, vid)
                if current == "ready":
                    log.info(
                        "beat_requeue_stale_diff",
                        diff_id=row.id,
                        version_id=vid,
                        side=side,
                    )
                    compute_diff.delay(
                        row.version_from_id, row.version_to_id, row.ontology_id
                    )
                    requeued += 1
                    break

    comparisons = (await db.execute(
        select(OntologyComparison).where(OntologyComparison.status == "ready")
    )).scalars().all()
    for row in comparisons:
        inferred_status = (row.summary or {}).get("inferred_status", {})
        for side, vid in (
            ("from_version", row.version_from_id),
            ("to_version", row.version_to_id),
        ):
            if inferred_status.get(side) != "ready":
                current = await _reasoning_status_for_version(db, vid)
                if current == "ready":
                    log.info(
                        "beat_requeue_stale_comparison",
                        comparison_id=row.id,
                        version_id=vid,
                        side=side,
                    )
                    compute_ontology_comparison.delay(
                        row.version_from_id, row.version_to_id
                    )
                    requeued += 1
                    break
                    break  # one re-queue per row is enough
    return requeued


@celery_app.task(name="ontoexplorer.refresh_reuse", time_limit=300)
def refresh_reuse(version_id: str, ontology_id: str) -> dict:
    """Rebuild ONLY the reuse:{version_id} Redis cache.

    Cheaper alternative to a full index_ontology when only the reuse report
    needs updating (e.g. after a detector bug fix). Does NOT touch the
    search index, OWL profile cache, or queue embeddings.
    """
    import json as _json
    from dataclasses import asdict as _asdict

    from sqlalchemy import select

    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.models.db import Ontology, OntologyImport
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    from ontoexplorer.modules.reuse.detector import detect_reuse
    from ontoexplorer.modules.search.indexer import (
        _get_redis,
        _SEARCH_TTL,
        _type_key,
    )

    async def _gather():
        async with make_celery_db_session()() as db:
            ont = (await db.execute(
                select(Ontology).where(Ontology.id == ontology_id)
            )).scalar_one_or_none()
            imp_rows = (await db.execute(
                select(OntologyImport).where(OntologyImport.version_id == version_id)
            )).scalars().all()
            db_imports = [
                {"import_iri": row.import_iri, "depth": 1} for row in imp_rows
            ]
            return ont.iri if ont else "", db_imports

    host_iri, db_imports = asyncio.run(_gather())
    host_namespaces = [host_iri + sep for sep in ("#", "/")] if host_iri else []

    # Re-collect entities from the existing search index in Redis
    r = _get_redis()
    entities: list[tuple[str, str]] = []
    for etype in ("class", "object_property", "data_property",
                  "annotation_property", "individual"):
        for iri in r.smembers(_type_key(version_id, etype)):
            entities.append((iri, etype))

    g = graph_iri(ontology_id, version_id)
    report = detect_reuse(
        get_store(),
        graph_iri=g,
        version_id=version_id,
        host_iri=host_iri,
        host_namespaces=host_namespaces,
        db_imports=db_imports,
        entities=entities,
    )
    r.setex(reuse_cache_key(version_id), _SEARCH_TTL,
            _json.dumps(_asdict(report)))
    log.info("reuse_refresh_done", version_id=version_id)
    return {
        "status": "done",
        "version_id": version_id,
        "imports_count": len(report.imports),
        "mireot_terms_count": len(report.mireot_terms),
        "sources_reused": len(report.term_iri_reuse),
    }


