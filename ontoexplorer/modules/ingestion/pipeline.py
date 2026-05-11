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

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.oxigraph import load_graph
from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
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

logger = logging.getLogger(__name__)


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

    # ── Step 0: Resolve source ────────────────────────────────────────────────
    source: ResolvedSource
    if request.iri:
        logger.info("Resolving IRI: %s", request.iri)
        source = resolve_iri(request.iri)
    elif request.url:
        logger.info("Resolving URL: %s", request.url)
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
    logger.info("Detected format: %s", fmt)

    # ── Step 2: Parse ─────────────────────────────────────────────────────────
    graph = parse_ontology(source.data, fmt)
    logger.info("Parsed %d triples", len(graph))

    # ── Step 3: Resolve owl:imports ───────────────────────────────────────────
    import_results = resolve_imports(graph)
    warnings = [f"Failed to fetch import: {iri}" for iri, key in import_results.items() if not key]

    # ── Step 4: Deduplicate ───────────────────────────────────────────────────
    sha256 = compute_sha256(graph)
    existing = await db.execute(select(OntologyVersion).where(OntologyVersion.sha256 == sha256))
    existing_version = existing.scalar_one_or_none()
    if existing_version:
        logger.info("Duplicate detected (sha256=%s), returning existing version", sha256)
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

    # ── Steps 7-10: Stubs (implemented in later phases) ──────────────────────
    # Phase 3: extract_fair_metadata(version_id)
    # Phase 3: queue reasoning job
    # Phase 3: queue search indexing
    # Phase 4: deliver_webhooks("ontology.ingested", version_id)

    logger.info(
        "Ingestion complete: ontology=%s version=%s triples=%d",
        ontology_id, version_id, triple_count,
    )

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
