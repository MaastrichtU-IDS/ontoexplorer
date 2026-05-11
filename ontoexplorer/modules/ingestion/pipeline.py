"""
Ingestion pipeline — orchestrates all 10 steps for a submitted ontology.

Steps:
  0. Resolve source (IRI / URL / bytes)
  1. Detect format
  2. Parse to rdflib Graph
  3. Resolve owl:imports closure (cache in MinIO)
  4. Deduplicate (SHA-256 content hash)
  5. Store artifact in MinIO
  6. Load asserted triples into Oxigraph
  7. (Phase 3) Extract FAIR metadata → QLever
  8. Queue reasoning job (stub)
  9. Queue search indexing (stub)
  10. Deliver webhooks (stub)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import rdflib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings

from ontoexplorer.clients.oxigraph import load_graph
from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
from ontoexplorer.modules.metadata.dcat import build_dcat_record
from ontoexplorer.modules.metadata.prov import build_ingestion_activity
from ontoexplorer.modules.metadata.qlever_writer import write_version_metadata
from ontoexplorer.modules.metadata.void import compute_void_stats
from ontoexplorer.modules.storage.minio_client import ontology_download_url
from ontoexplorer.modules.ingestion.deduplicator import compute_sha256
from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, detect_format
from ontoexplorer.modules.ingestion.import_resolver import resolve_imports
from ontoexplorer.modules.ingestion.parser import parse_ontology
from ontoexplorer.modules.ingestion.source_resolver import (
    ResolvedSource,
    resolve_bytes,
    resolve_iri,
    resolve_url,
)
from ontoexplorer.modules.storage.minio_client import store_ontology
from ontoexplorer.logging_config import get_logger
from ontoexplorer import metrics

log = get_logger(__name__)


@dataclass
class IngestionRequest:
    """One of iri, url, or raw_bytes must be provided."""
    iri: str | None = None
    url: str | None = None
    raw_bytes: bytes | None = None
    filename: str | None = None
    content_type: str | None = None
    owner_id: str | None = None


@dataclass
class IngestionResult:
    ontology_id: str
    version_id: str
    sha256: str
    format: OntologyFormat
    triple_count: int
    is_duplicate: bool
    import_results: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


async def run_ingestion(db: AsyncSession, request: IngestionRequest) -> IngestionResult:
    """Run the full ingestion pipeline. Returns IngestionResult."""
    _t0 = time.monotonic()

    # ── Step 0: Resolve source ────────────────────────────────────────────────
    source: ResolvedSource
    if request.iri:
        log.info("resolving_iri", iri=request.iri)
        source = resolve_iri(request.iri)
    elif request.url:
        log.info("resolving_url", url=request.url)
        source = resolve_url(request.url)
    elif request.raw_bytes is not None:
        source = resolve_bytes(request.raw_bytes, request.content_type)
    else:
        raise ValueError("IngestionRequest must specify iri, url, or raw_bytes")

    # ── Step 1: Detect format ─────────────────────────────────────────────────
    fmt = detect_format(
        source.data,
        filename=request.filename,
        content_type=source.content_type or request.content_type,
    )
    log.info("format_detected", format=fmt.value)

    # ── Step 2: Parse ─────────────────────────────────────────────────────────
    graph = parse_ontology(source.data, fmt)
    log.info("parsed_triples", count=len(graph))

    # ── Step 3: Resolve owl:imports ───────────────────────────────────────────
    import_results = resolve_imports(graph)
    warnings = [f"Failed to fetch import: {iri}" for iri, key in import_results.items() if not key]

    # ── Step 4: Deduplicate ───────────────────────────────────────────────────
    sha256 = compute_sha256(graph)
    existing = await db.execute(select(OntologyVersion).where(OntologyVersion.sha256 == sha256))
    existing_version = existing.scalar_one_or_none()
    if existing_version:
        log.info("duplicate_detected", sha256=sha256, existing_version_id=existing_version.id)
        metrics.ontologies_ingested_total.labels(format=fmt.value, duplicate="true").inc()
        return IngestionResult(
            ontology_id=existing_version.ontology_id,
            version_id=existing_version.id,
            sha256=sha256,
            format=fmt,
            triple_count=len(graph),
            is_duplicate=True,
            import_results=import_results,
        )

    # ── Step 5: Store artifact in MinIO ───────────────────────────────────────
    ontology_id = await _ensure_ontology(db, graph, request)
    version_id = str(uuid.uuid4())
    minio_key = store_ontology(ontology_id, version_id, sha256, fmt.value, source.data)

    # ── Persist version record ────────────────────────────────────────────────
    version_iri = _extract_version_iri(graph)
    version = OntologyVersion(
        id=version_id,
        ontology_id=ontology_id,
        version_iri=version_iri,
        minio_key=minio_key,
        sha256=sha256,
        format=fmt.value,
        status="ingested",
    )
    db.add(version)

    # Persist import records
    for import_iri, import_key in import_results.items():
        db.add(OntologyImport(
            version_id=version_id,
            import_iri=import_iri,
            resolved_minio_key=import_key or None,
        ))

    await db.commit()

    # ── Step 6: Load into Oxigraph ────────────────────────────────────────────
    triple_count = load_graph(ontology_id, version_id, graph)

    # ── Step 7: Extract FAIR metadata → QLever ────────────────────────────────
    await _write_fair_metadata(
        ontology_id=ontology_id,
        version_id=version_id,
        graph=graph,
        version=version,
        source=source,
        triple_count=triple_count,
    )

    # ── Step 8: Queue reasoning job ───────────────────────────────────────────
    from ontoexplorer.modules.jobs.tasks import reason_ontology
    reason_ontology.delay(version_id)

    # ── Step 9: Queue search indexing ─────────────────────────────────────────
    from ontoexplorer.modules.jobs.tasks import index_ontology
    index_ontology.delay(version_id)

    elapsed = time.monotonic() - _t0
    metrics.ontologies_ingested_total.labels(format=fmt.value, duplicate="false").inc()
    metrics.ingestion_duration_seconds.labels(format=fmt.value).observe(elapsed)
    metrics.ingestion_triples.observe(triple_count)
    log.info("ingestion_complete", ontology_id=ontology_id, version_id=version_id,
             triple_count=triple_count, duration_s=round(elapsed, 2))

    return IngestionResult(
        ontology_id=ontology_id,
        version_id=version_id,
        sha256=sha256,
        format=fmt,
        triple_count=triple_count,
        is_duplicate=False,
        import_results=import_results,
        warnings=warnings,
    )


async def _ensure_ontology(db: AsyncSession, graph, request: IngestionRequest) -> str:
    """Get or create the Ontology record, using the ontology IRI from the graph."""
    ontology_iri = _extract_ontology_iri(graph) or request.iri or request.url or f"urn:uuid:{uuid.uuid4()}"

    result = await db.execute(select(Ontology).where(Ontology.iri == ontology_iri))
    existing = result.scalar_one_or_none()
    if existing:
        return existing.id

    ontology = Ontology(
        id=str(uuid.uuid4()),
        iri=ontology_iri,
        owner_id=request.owner_id,
    )
    db.add(ontology)
    await db.flush()
    return ontology.id


async def _write_fair_metadata(
    *,
    ontology_id: str,
    version_id: str,
    graph: rdflib.Graph,
    version: OntologyVersion,
    source: ResolvedSource,
    triple_count: int,
) -> None:
    """Compute VoID stats, build DCAT + PROV-O graphs, write to QLever."""
    try:
        settings = get_settings()
        void_stats = compute_void_stats(graph)
        download_url = ontology_download_url(version.minio_key)

        dcat_graph = build_dcat_record(
            ontology_id=ontology_id,
            version_id=version_id,
            ontology_iri=version.ontology.iri if version.ontology else ontology_id,
            version_iri=version.version_iri,
            minio_download_url=download_url,
            format_ext=version.format,
            void_stats=void_stats,
            app_base_url=str(settings.app_url),
        )

        prov_graph = build_ingestion_activity(
            version_id=version_id,
            ontology_iri=version.ontology.iri if version.ontology else ontology_id,
            source_url=source.final_url,
            mode=source.mode.value,
            sha256=version.sha256,
            triple_count=triple_count,
            app_base_url=str(settings.app_url),
        )

        await write_version_metadata(ontology_id, version_id, dcat_graph, prov_graph)
    except Exception as exc:
        log.warning("fair_metadata_failed", error=str(exc))


def _extract_ontology_iri(graph) -> str | None:
    from rdflib.namespace import OWL, RDF
    for s in graph.subjects(RDF.type, OWL.Ontology):
        if str(s).startswith("http"):
            return str(s)
    return None


def _extract_version_iri(graph) -> str | None:
    from rdflib.namespace import OWL
    for _, _, o in graph.triples((None, OWL.versionIRI, None)):
        return str(o)
    return None
