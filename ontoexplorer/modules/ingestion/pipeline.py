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

import asyncio
import io
import re
import time
import uuid
from dataclasses import dataclass, field

import pyoxigraph
import rdflib
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings

from ontoexplorer.clients.oxigraph import bulk_load_bytes, load_graph
from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
from ontoexplorer.modules.metadata.dcat import build_dcat_record
from ontoexplorer.modules.metadata.prov import build_ingestion_activity
from ontoexplorer.modules.metadata.qlever_writer import write_version_metadata
from ontoexplorer.modules.metadata.void import compute_void_stats_sparql
from ontoexplorer.modules.storage.minio_client import ontology_download_url
from ontoexplorer.modules.ingestion.deduplicator import compute_sha256_bytes
from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, detect_format
from ontoexplorer.modules.ingestion.import_resolver import resolve_imports, resolve_imports_sparql
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

# Formats that Oxigraph can bulk-load natively — no rdflib parse needed.
# OWL/XML (.owl) is almost always RDF/XML serialization, accepted as application/rdf+xml.
_DIRECT_MIME: dict[OntologyFormat, str] = {
    OntologyFormat.OWL_XML:   "application/rdf+xml",
    OntologyFormat.RDF_XML:   "application/rdf+xml",
    OntologyFormat.TURTLE:    "text/turtle",
    OntologyFormat.N_TRIPLES: "application/n-triples",
    OntologyFormat.N_QUADS:   "application/n-quads",
    OntologyFormat.JSON_LD:   "application/ld+json",
    OntologyFormat.TRIG:      "application/trig",
}

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
    groups: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.groups is None:
            self.groups = []


@dataclass
class IngestionResult:
    ontology_id: str
    version_id: str
    sha256: str
    format: OntologyFormat
    triple_count: int
    is_duplicate: bool
    import_results: dict = field(default_factory=dict)  # iri → ResolvedImport
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

    # ── Step 4: Deduplicate (fast hash on raw bytes) ───────────────────────────
    sha256 = compute_sha256_bytes(source.data)
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
            triple_count=existing_version.triple_count or 0,
            is_duplicate=True,
        )

    # ── Step 5: Store artifact in MinIO ───────────────────────────────────────
    # Determine provisional ontology IRI before creating the DB record.
    provisional_iri = (
        _extract_ontology_iri_fast(source.data, fmt)
        or request.iri
        or request.url
        or f"urn:uuid:{uuid.uuid4()}"
    )
    ontology_id = await _ensure_ontology(db, provisional_iri, request)
    version_id = str(uuid.uuid4())
    minio_key = store_ontology(ontology_id, version_id, sha256, fmt.value, source.data)

    # ── Step 2+6: Load into Oxigraph (streaming or via rdflib) ────────────────
    if fmt in _DIRECT_MIME:
        # Fast path: stream bytes directly into Oxigraph, skip rdflib parse entirely
        mime = _DIRECT_MIME[fmt]
        triple_count = bulk_load_bytes(ontology_id, version_id, source.data, mime)
        log.info("bulk_loaded_bytes", fmt=fmt.value, mime=mime, triples=triple_count)
        graph = None
    else:
        # Slow path: OBO / Manchester need rdflib first
        graph = parse_ontology(source.data, fmt)
        log.info("parsed_triples", count=len(graph))
        triple_count = load_graph(ontology_id, version_id, graph)

    # ── Step 3: Resolve owl:imports and load into Oxigraph ───────────────────
    if graph is not None:
        import_results = resolve_imports(graph)
    else:
        import_results = resolve_imports_sparql(ontology_id, version_id)
    warnings = [f"Failed to fetch import: {iri}" for iri, r in import_results.items() if not r.key]

    # Load each resolved import's triples into the same named graph so the indexer
    # and reasoner see the full import closure, not just the main ontology's axioms.
    from ontoexplorer.clients.oxigraph import append_bytes_to_graph
    for imp_iri, imp in import_results.items():
        if imp.data:
            try:
                append_bytes_to_graph(ontology_id, version_id, imp.data, imp.ext)
                log.info("loaded_import_triples", iri=imp_iri, ext=imp.ext)
            except Exception as exc:
                log.warning("failed_to_load_import_triples", iri=imp_iri, error=str(exc))
                warnings.append(f"Could not load import triples: {imp_iri}")

    # ── Refine ontology IRI from loaded triples (safety net) ──────────────────
    # _extract_ontology_iri_fast already runs an in-memory parse before any DB
    # writes, so this normally agrees with provisional_iri. The SPARQL re-check
    # runs against the persisted store (which now also contains import closure
    # triples) and catches the rare case where the eager parse missed.
    canonical_iri = _extract_ontology_iri_sparql(ontology_id, version_id)
    if canonical_iri and canonical_iri != provisional_iri:
        ontology_id = await _reconcile_ontology_iri(
            db, bogus_ontology_id=ontology_id, canonical_iri=canonical_iri, version_id=version_id
        )

    # ── Persist version record ────────────────────────────────────────────────
    effective_iri = canonical_iri or provisional_iri
    version_iri = (
        _extract_version_iri(graph, ontology_iri=effective_iri) if graph is not None
        else _extract_version_iri_sparql(ontology_id, version_id, ontology_iri=effective_iri)
    )
    version = OntologyVersion(
        id=version_id,
        ontology_id=ontology_id,
        version_iri=version_iri,
        minio_key=minio_key,
        sha256=sha256,
        format=fmt.value,
        status="ingested",
        triple_count=triple_count,
        source_url=source.final_url or request.url or request.iri,
    )
    db.add(version)

    for imp_iri, imp in import_results.items():
        db.add(OntologyImport(
            version_id=version_id,
            import_iri=imp_iri,
            resolved_minio_key=imp.key or None,
        ))

    await db.commit()

    # ── Step 7: Extract FAIR metadata → QLever ────────────────────────────────
    ontology_iri = canonical_iri or provisional_iri
    await _write_fair_metadata(
        ontology_id=ontology_id,
        version_id=version_id,
        ontology_iri=ontology_iri,
        version=version,
        source=source,
        triple_count=triple_count,
    )

    # ── Step 8: Queue reasoning job ───────────────────────────────────────────
    from ontoexplorer.modules.jobs.tasks import reason_ontology
    reason_ontology.delay(version_id)

    # ── Step 9: Queue profile detection (chains to indexing on completion) ────
    from ontoexplorer.modules.jobs.tasks import detect_profile, detect_meta_profile
    detect_profile.delay(version_id, ontology_id=ontology_id)
    detect_meta_profile.delay(version_id, ontology_id=ontology_id)

    # ── Step 10: Queue diff computation against previous version ─────────────
    prev_result = await db.execute(
        select(OntologyVersion)
        .where(
            OntologyVersion.ontology_id == ontology_id,
            OntologyVersion.id != version_id,
            OntologyVersion.status != "deprecated",
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    prev_version = prev_result.scalar_one_or_none()
    if prev_version:
        from ontoexplorer.modules.jobs.tasks import compute_diff as _compute_diff_task
        _compute_diff_task.delay(str(prev_version.id), version_id, ontology_id)

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


async def _ensure_ontology(db: AsyncSession, ontology_iri: str, request: IngestionRequest) -> str:
    """Get or create the Ontology record for the given IRI."""
    result = await db.execute(select(Ontology).where(Ontology.iri == ontology_iri))
    existing = result.scalar_one_or_none()
    if existing:
        return existing.id
    ontology = Ontology(id=str(uuid.uuid4()), iri=ontology_iri, owner_id=request.owner_id, groups=request.groups)
    db.add(ontology)
    await db.flush()
    return ontology.id


async def _reconcile_ontology_iri(
    db: AsyncSession,
    bogus_ontology_id: str,
    canonical_iri: str,
    version_id: str,
) -> str:
    """Reconcile a post-load canonical IRI against the provisional Ontology row.

    Three outcomes:
      1. No row with `canonical_iri` exists → update the provisional row's IRI in place.
      2. Some other row already has `canonical_iri` → MERGE: move the just-loaded
         named graph in Oxigraph to the canonical row's id, reassign this version,
         drop the orphan row. Returns the canonical row's id.
      3. The canonical row IS this row → no-op.

    Replaces the previous handler that silently kept the wrong IRI on conflict.
    """
    existing = (await db.execute(
        select(Ontology).where(Ontology.iri == canonical_iri)
    )).scalar_one_or_none()

    if existing is None:
        await db.execute(
            update(Ontology).where(Ontology.id == bogus_ontology_id).values(iri=canonical_iri)
        )
        log.info("ontology_iri_updated", ontology_id=bogus_ontology_id, canonical_iri=canonical_iri)
        return bogus_ontology_id

    if existing.id == bogus_ontology_id:
        return bogus_ontology_id

    await _move_named_graph(bogus_ontology_id, existing.id, version_id)

    # Drop the bogus row only if no other versions point to it (the current
    # version hasn't been added to the session yet, so a brand-new bogus row
    # from this ingestion will have zero versions and is safe to delete).
    other_version = (await db.execute(
        select(OntologyVersion.id)
        .where(OntologyVersion.ontology_id == bogus_ontology_id)
        .limit(1)
    )).scalar_one_or_none()
    if other_version is None:
        await db.execute(delete(Ontology).where(Ontology.id == bogus_ontology_id))

    log.info(
        "ontology_iri_conflict_merged",
        from_id=bogus_ontology_id,
        into_id=existing.id,
        canonical_iri=canonical_iri,
        orphan_deleted=other_version is None,
    )
    return existing.id


async def _move_named_graph(old_ontology_id: str, new_ontology_id: str, version_id: str) -> None:
    """Copy quads from the old named graph to the new one and drop the old."""
    from ontoexplorer.clients.oxigraph import get_store, graph_iri

    def _do_move() -> None:
        store = get_store()
        old_named = pyoxigraph.NamedNode(graph_iri(old_ontology_id, version_id))
        new_named = pyoxigraph.NamedNode(graph_iri(new_ontology_id, version_id))
        store.add_graph(new_named)
        for q in store.quads_for_pattern(None, None, None, old_named):
            store.add(pyoxigraph.Quad(q.subject, q.predicate, q.object, new_named))
        store.remove_graph(old_named)

    await asyncio.to_thread(_do_move)


async def _write_fair_metadata(
    *,
    ontology_id: str,
    version_id: str,
    ontology_iri: str,
    version: OntologyVersion,
    source: ResolvedSource,
    triple_count: int,
) -> None:
    """Compute VoID stats via SPARQL, build DCAT + PROV-O graphs, write to QLever."""
    try:
        settings = get_settings()
        void_stats = compute_void_stats_sparql(ontology_id, version_id)
        download_url = ontology_download_url(version.minio_key)

        dcat_graph = build_dcat_record(
            ontology_id=ontology_id,
            version_id=version_id,
            ontology_iri=ontology_iri,
            version_iri=version.version_iri,
            minio_download_url=download_url,
            format_ext=version.format,
            void_stats=void_stats,
            app_base_url=str(settings.app_url),
        )

        prov_graph = build_ingestion_activity(
            version_id=version_id,
            ontology_iri=ontology_iri,
            source_url=source.final_url,
            mode=source.mode.value,
            sha256=version.sha256,
            triple_count=triple_count,
            app_base_url=str(settings.app_url),
        )

        await write_version_metadata(ontology_id, version_id, dcat_graph, prov_graph)
    except Exception as exc:
        log.warning("fair_metadata_failed", error=str(exc))


def _extract_ontology_iri_fast(data: bytes, fmt: OntologyFormat) -> str | None:
    """Find the owl:Ontology declaration.

    Tries a regex over the first 32 KB first (cheap), then falls back to a full
    in-memory parse via pyoxigraph for bulk-loadable formats. Returns None when
    no `?iri a owl:Ontology` triple is present (caller falls back to URL/IRI).

    The previous "any rdf:about that looks like a URL" fallback was removed —
    it grabbed class IRIs from files where the `<owl:Ontology>` element is
    declared after the first class block, producing bogus ontology rows.
    """
    snippet = data[:32768].decode("utf-8", errors="replace")
    if fmt in (OntologyFormat.OWL_XML, OntologyFormat.RDF_XML):
        m = re.search(r'<[^>]*\bOntology\b[^>]+rdf:about="([^"]+)"', snippet)
        if m:
            return m.group(1)
    elif fmt == OntologyFormat.TURTLE:
        m = re.search(r'<([^>]+)>\s+(?:rdf:type|a)\s+(?:owl:Ontology|<http://www\.w3\.org/2002/07/owl#Ontology>)', snippet)
        if m:
            return m.group(1)
    return _extract_ontology_iri_by_parsing(data, fmt)


def _extract_ontology_iri_by_parsing(data: bytes, fmt: OntologyFormat) -> str | None:
    """Authoritative IRI extraction via in-memory pyoxigraph parse.

    Used when the fast regex misses (e.g. `<owl:Ontology>` declared deep in the
    file, or unusual XML/Turtle syntax). Costs an extra parse pass but happens
    before any DB write, so failures are non-destructive.
    """
    mime = _DIRECT_MIME.get(fmt)
    if not mime:
        return None  # OBO/Manchester are parsed by rdflib later; can't do it cheaply here
    try:
        tmp = pyoxigraph.Store()
        tmp.bulk_load(io.BytesIO(data), mime)
        results = tmp.query(
            "SELECT ?iri WHERE { ?iri a <http://www.w3.org/2002/07/owl#Ontology> . FILTER(isIRI(?iri)) } LIMIT 1"
        )
        for row in results:
            val = row["iri"].value if hasattr(row["iri"], "value") else str(row["iri"])
            if val.startswith("http"):
                return val
    except Exception as exc:
        log.warning("eager_iri_parse_failed", error=str(exc), fmt=fmt.value)
    return None


def _extract_ontology_iri_sparql(ontology_id: str, version_id: str) -> str | None:
    """Query Oxigraph for the ontology IRI of the loaded graph."""
    from ontoexplorer.clients.oxigraph import sparql_query, graph_iri
    g = graph_iri(ontology_id, version_id)
    results = sparql_query(f"""
        SELECT ?iri FROM <{g}> WHERE {{
            ?iri a <http://www.w3.org/2002/07/owl#Ontology> .
            FILTER(isIRI(?iri))
        }} LIMIT 1
    """)
    for row in results:
        val = str(row["iri"])
        if val.startswith("http"):
            return val
    return None


def _extract_version_iri(graph: rdflib.Graph, ontology_iri: str | None = None) -> str | None:
    """Return owl:versionIRI scoped to the given ontology IRI when provided.

    Without scoping, an arbitrary owl:versionIRI triple from a merged import
    closure can be returned (e.g. the imported pro ontology's version IRI
    showing up as the pizza ontology's version IRI).
    """
    from rdflib.namespace import OWL
    subject = rdflib.URIRef(ontology_iri) if ontology_iri else None
    for _, _, o in graph.triples((subject, OWL.versionIRI, None)):
        return str(o)
    return None


def _extract_version_iri_sparql(ontology_id: str, version_id: str, ontology_iri: str | None = None) -> str | None:
    """Query Oxigraph for the owl:versionIRI of this ontology in the named graph.

    Scoped to `<ontology_iri>` to avoid grabbing an import's version IRI from
    the merged closure. Falls back to unscoped query only if no ontology IRI
    is known (rare — provisional URI always exists).
    """
    from ontoexplorer.clients.oxigraph import sparql_query, graph_iri
    g = graph_iri(ontology_id, version_id)
    if ontology_iri:
        query = f"""
            SELECT ?v FROM <{g}> WHERE {{
                <{ontology_iri}> <http://www.w3.org/2002/07/owl#versionIRI> ?v .
            }} LIMIT 1
        """
    else:
        query = f"""
            SELECT ?v FROM <{g}> WHERE {{
                ?ont <http://www.w3.org/2002/07/owl#versionIRI> ?v .
            }} LIMIT 1
        """
    results = sparql_query(query)
    for row in results:
        v = row["v"]
        return v.value if hasattr(v, "value") else str(v)
    return None
