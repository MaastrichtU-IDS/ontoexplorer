import asyncio
import json
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion
from ontoexplorer.modules.mod.builder import (
    build_artefact_graph,
    build_artefacts_list_graph,
    build_catalogue_graph,
    build_distribution_graph,
    build_distributions_list_graph,
    build_labels_graph,
    build_record_graph,
    build_records_list_graph,
    build_resource_list_graph,
    build_resources_summary_graph,
    build_search_results_graph,
)
from ontoexplorer.modules.mod.ratelimit import mod_rate_limit
from ontoexplorer.modules.mod.response import RDFResponse

router = APIRouter(tags=["mod"])

_FORMAT_PARAM = Query(None, description="Response format: jsonld, ttl, rdfxml, html")
_PAGE_PARAM = Query(1, ge=1, description="Page number")
_PAGE_SIZE_PARAM = Query(20, ge=1, le=200, description="Items per page")


def _base_url(request: Request) -> str:
    s = get_settings()
    return str(s.app_url).rstrip("/")


def _get_stats(version_id: str) -> dict:
    try:
        from ontoexplorer.modules.search.indexer import _get_redis, _stats_cache_key
        raw = _get_redis().get(_stats_cache_key(version_id))
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


async def _fetch_stats(version_id: str) -> dict:
    return await asyncio.to_thread(_get_stats, version_id)


async def _resolve_artefact(
    artefact_id: str, db: AsyncSession
) -> tuple[Ontology, OntologyVersion]:
    decoded = unquote(artefact_id)
    stmt = (
        select(Ontology, OntologyVersion)
        .join(OntologyVersion, OntologyVersion.ontology_id == Ontology.id)
        .where(
            (Ontology.shortname == decoded) | (Ontology.iri == decoded),
            OntologyVersion.status == "ready",
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Artefact not found")
    return row.Ontology, row.OntologyVersion


async def _fetch_meta(version_id: str, db: AsyncSession) -> dict:
    result = await db.execute(
        select(OntologyMetaProfile.resolved).where(OntologyMetaProfile.version_id == version_id)
    )
    row = result.scalar_one_or_none()
    return row or {}


async def _ready_ontologies_with_latest(
    db: AsyncSession, q: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[tuple[Ontology, OntologyVersion]], int]:
    subq = (
        select(OntologyVersion.ontology_id, func.max(OntologyVersion.created_at).label("max_created"))
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    base_stmt = (
        select(Ontology, OntologyVersion)
        .join(subq, Ontology.id == subq.c.ontology_id)
        .join(
            OntologyVersion,
            (OntologyVersion.ontology_id == subq.c.ontology_id)
            & (OntologyVersion.created_at == subq.c.max_created),
        )
    )
    if q:
        q_lower = f"%{q.lower()}%"
        base_stmt = base_stmt.where(
            (func.lower(Ontology.title).like(q_lower))
            | (func.lower(Ontology.shortname).like(q_lower))
        )
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(base_stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return [(row.Ontology, row.OntologyVersion) for row in rows], total


@router.get("/mod/", dependencies=[Depends(mod_rate_limit)])
async def get_catalogue(
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    base = _base_url(request)
    total = (await db.execute(
        select(func.count(Ontology.id)).where(
            Ontology.id.in_(
                select(OntologyVersion.ontology_id).where(OntologyVersion.status == "ready")
            )
        )
    )).scalar_one()
    graph = build_catalogue_graph(
        base_url=base,
        title=settings.mod_catalogue_title,
        description=settings.mod_catalogue_description,
        artefact_count=total,
        sparql_endpoint=f"{base}/api/v1/sparql/content",
    )
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/records", dependencies=[Depends(mod_rate_limit)])
async def list_records(
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    pairs, total = await _ready_ontologies_with_latest(db, page=page, page_size=page_size)
    graph = build_records_list_graph(records=pairs, total=total, page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/records/{artefact_id}", dependencies=[Depends(mod_rate_limit)])
async def get_record(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph = build_record_graph(ontology=ontology, version=version, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts", dependencies=[Depends(mod_rate_limit)])
async def list_artefacts(
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    q: str | None = Query(None, description="Filter by title or acronym"),
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    pairs, total = await _ready_ontologies_with_latest(db, q=q, page=page, page_size=page_size)
    artefacts = []
    for ontology, version in pairs:
        meta = await _fetch_meta(version.id, db)
        stats = await _fetch_stats(version.id)
        artefacts.append((ontology, version, meta, stats))
    graph = build_artefacts_list_graph(artefacts=artefacts, total=total, page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/record", dependencies=[Depends(mod_rate_limit)])
async def get_artefact_record(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph = build_record_graph(ontology=ontology, version=version, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/distributions/latest", dependencies=[Depends(mod_rate_limit)])
async def get_latest_distribution(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph = build_distribution_graph(ontology=ontology, version=version, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/distributions/{distribution_id}", dependencies=[Depends(mod_rate_limit)])
async def get_distribution(
    artefact_id: str,
    distribution_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    decoded = unquote(artefact_id)
    stmt = (
        select(Ontology, OntologyVersion)
        .join(OntologyVersion, OntologyVersion.ontology_id == Ontology.id)
        .where(
            (Ontology.shortname == decoded) | (Ontology.iri == decoded),
            OntologyVersion.id == distribution_id,
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Distribution not found")
    graph = build_distribution_graph(ontology=row.Ontology, version=row.OntologyVersion, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/distributions", dependencies=[Depends(mod_rate_limit)])
async def list_distributions(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    decoded = unquote(artefact_id)
    ont_result = await db.execute(
        select(Ontology).where((Ontology.shortname == decoded) | (Ontology.iri == decoded))
    )
    ontology = ont_result.scalar_one_or_none()
    if not ontology:
        raise HTTPException(status_code=404, detail="Artefact not found")
    versions_result = await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology.id)
        .order_by(OntologyVersion.created_at.desc())
    )
    versions = list(versions_result.scalars().all())
    graph = build_distributions_list_graph(ontology=ontology, versions=versions, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}", dependencies=[Depends(mod_rate_limit)])
async def get_artefact(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    meta = await _fetch_meta(version.id, db)
    stats = await _fetch_stats(version.id)
    graph = build_artefact_graph(ontology=ontology, version=version, meta=meta, stats=stats, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


async def _sparql_terms(ontology_id: str, version_id: str, entity_type: str, limit: int, offset: int) -> list[dict]:
    TYPE_SPARQL = {
        "class": "owl:Class",
        "property": "rdf:Property",
        "individual": "owl:NamedIndividual",
        "concept": "skos:Concept",
        "scheme": "skos:ConceptScheme",
        "collection": "skos:Collection",
    }
    rdf_type = TYPE_SPARQL.get(entity_type, "owl:Class")
    graph_iri = f"urn:ontology:{ontology_id}:{version_id}"
    sparql = f"""
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?uri ?label WHERE {{
  GRAPH <{graph_iri}> {{
    ?uri a {rdf_type} .
    OPTIONAL {{ ?uri rdfs:label ?label FILTER(langMatches(lang(?label), "en") || lang(?label) = "") }}
  }}
}} ORDER BY ?uri LIMIT {limit} OFFSET {offset}
"""

    def _run() -> list[dict]:
        from ontoexplorer.clients.oxigraph import get_store
        store = get_store()
        results = store.query(sparql)
        terms = []
        for row in results:
            terms.append({
                "iri": str(row["uri"]),
                "label": str(row["label"]) if row.get("label") else None,
            })
        return terms

    return await asyncio.to_thread(_run)


async def _sparql_term_count(ontology_id: str, version_id: str, entity_type: str) -> int:
    TYPE_SPARQL = {
        "class": "owl:Class",
        "property": "rdf:Property",
        "individual": "owl:NamedIndividual",
        "concept": "skos:Concept",
        "scheme": "skos:ConceptScheme",
        "collection": "skos:Collection",
    }
    rdf_type = TYPE_SPARQL.get(entity_type, "owl:Class")
    graph_iri = f"urn:ontology:{ontology_id}:{version_id}"
    sparql = f"""
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT (COUNT(DISTINCT ?uri) AS ?count) WHERE {{
  GRAPH <{graph_iri}> {{ ?uri a {rdf_type} . }}
}}
"""

    def _run() -> int:
        from ontoexplorer.clients.oxigraph import get_store
        store = get_store()
        results = list(store.query(sparql))
        if results:
            return int(str(results[0]["count"]))
        return 0

    return await asyncio.to_thread(_run)


@router.get("/mod/artefacts/{artefact_id}/resources", dependencies=[Depends(mod_rate_limit)])
async def get_resources_summary(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    stats = await _fetch_stats(version.id)
    graph = build_resources_summary_graph(ontology=ontology, version=version, stats=stats, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


async def _resource_endpoint(
    artefact_id: str, entity_type: str, request: Request,
    fmt: str | None, page: int, page_size: int, db: AsyncSession,
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    base = _base_url(request)
    offset = (page - 1) * page_size
    terms, total = await asyncio.gather(
        _sparql_terms(ontology.id, version.id, entity_type, page_size, offset),
        _sparql_term_count(ontology.id, version.id, entity_type),
    )
    graph = build_resource_list_graph(
        ontology=ontology, version=version, terms=terms,
        entity_type=entity_type, total=total, page=page, page_size=page_size, base_url=base,
    )
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/resources/classes", dependencies=[Depends(mod_rate_limit)])
async def get_classes(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "class", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/properties", dependencies=[Depends(mod_rate_limit)])
async def get_properties(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "property", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/individuals", dependencies=[Depends(mod_rate_limit)])
async def get_individuals(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "individual", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/concepts", dependencies=[Depends(mod_rate_limit)])
async def get_concepts(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "concept", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/schemes", dependencies=[Depends(mod_rate_limit)])
async def get_schemes(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "scheme", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/collections", dependencies=[Depends(mod_rate_limit)])
async def get_collections(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "collection", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/labels", dependencies=[Depends(mod_rate_limit)])
async def get_labels(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph_iri_str = f"urn:ontology:{ontology.id}:{version.id}"
    offset = (page - 1) * page_size
    sparql = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?uri ?label WHERE {{
  GRAPH <{graph_iri_str}> {{ ?uri rdfs:label ?label }}
}} ORDER BY ?uri LIMIT {page_size} OFFSET {offset}
"""

    def _run() -> list[dict]:
        from ontoexplorer.clients.oxigraph import get_store
        results = get_store().query(sparql)
        return [
            {"iri": str(r["uri"]), "label": str(r["label"]), "lang": r["label"].language or None}
            for r in results
        ]

    terms = await asyncio.to_thread(_run)
    graph = build_labels_graph(ontology=ontology, version=version, terms=terms, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


async def _mod_search(q: str, db: AsyncSession, content_only: bool = False, metadata_only: bool = False) -> list[dict]:
    results: list[dict] = []
    if not metadata_only:
        from ontoexplorer.api.global_search import _latest_ingested_versions, _entity_search
        versions = await _latest_ingested_versions(db)
        for version in versions[:10]:
            try:
                hits = await _entity_search(version, q, lang=None, limit=5)
                for hit in hits:
                    results.append({
                        "iri": hit.get("iri", ""),
                        "label": hit.get("label", ""),
                        "ontology_id": version.ontology_id,
                    })
            except Exception:
                pass
    if not content_only:
        rows = await db.execute(
            select(Ontology).where(
                (func.lower(Ontology.title).like(f"%{q.lower()}%"))
                | (func.lower(Ontology.shortname).like(f"%{q.lower()}%"))
            ).limit(20)
        )
        for ont in rows.scalars():
            results.append({"iri": ont.iri, "label": ont.title or ont.shortname or "", "ontology_id": ont.id})
    return results


@router.get("/mod/search", dependencies=[Depends(mod_rate_limit)])
async def mod_search(
    request: Request,
    q: str = Query(..., min_length=1),
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    results = await _mod_search(q, db)
    graph = build_search_results_graph(results=results, q=q, total=len(results), page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/search/content", dependencies=[Depends(mod_rate_limit)])
async def mod_search_content(
    request: Request,
    q: str = Query(..., min_length=1),
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    results = await _mod_search(q, db, content_only=True)
    graph = build_search_results_graph(results=results, q=q, total=len(results), page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/search/metadata", dependencies=[Depends(mod_rate_limit)])
async def mod_search_metadata(
    request: Request,
    q: str = Query(..., min_length=1),
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    results = await _mod_search(q, db, metadata_only=True)
    graph = build_search_results_graph(results=results, q=q, total=len(results), page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))
