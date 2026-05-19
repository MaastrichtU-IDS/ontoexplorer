"""OLS4-compat property endpoints (v1 HAL).

Properties in OLS are the union of three entity types:
  object_property, data_property, annotation_property

Route registration order matters (same as terms.py):
  - Fixed-path global routes (/properties, /properties/findByIdAndIsDefiningOntology)
    must be registered BEFORE the catch-all /properties/{iri_path:path}.
  - Per-ontology hierarchy routes (/{iri}/parents, /{iri}/children, …) must be
    registered BEFORE the bare /{iri_path:path} detail route.
  - The findByIdAndIsDefiningOntology/{iri} path form must be registered BEFORE
    the bare catch-all too.

All property hierarchy endpoints use asserted-only logic (rdfs:subPropertyOf)
because ELK only classifies classes, not properties.
"""
import asyncio
import json
from collections import deque
from typing import Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._common import (
    get_latest_version_or_404,
    get_ontology_or_404,
    hal_page_params,
    page_to_offset,
)
from ontoexplorer.api.ols._envelope import hal_page
from ontoexplorer.api.ols._iri import double_decode_iri
from ontoexplorer.api.ols._shapes import entity_to_v1_term
from ontoexplorer.database import get_db
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key, _type_key
from ontoexplorer.modules.search.versions import latest_ready_versions

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROPERTY_TYPES = ("object_property", "data_property", "annotation_property")

_OWL_TOP_OP = "http://www.w3.org/2002/07/owl#topObjectProperty"
_OWL_TOP_DP = "http://www.w3.org/2002/07/owl#topDataProperty"
_OWL_EXCLUDED = {_OWL_TOP_OP, _OWL_TOP_DP}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redis_hgetall(key: str) -> dict:
    return _get_redis().hgetall(key) or {}


def _redis_scard(key: str) -> int:
    return _get_redis().scard(key)


def _redis_smembers_sorted(key: str) -> list[str]:
    return sorted(_get_redis().smembers(key))


async def _load_entity(version_id: str, iri: str) -> dict | None:
    h = await asyncio.to_thread(_redis_hgetall, _iri_key(version_id, iri))
    return h if h else None


def _all_property_iris_sorted(vid: str) -> list[str]:
    """Return a deterministically-ordered list of all property IRIs across the three types."""
    r = _get_redis()
    all_iris: set[str] = set()
    for pt in _PROPERTY_TYPES:
        all_iris.update(r.smembers(_type_key(vid, pt)))
    return sorted(all_iris)


def _total_property_count(vid: str) -> int:
    """Total count = sum of SCARD for each property type (O(1) per type)."""
    r = _get_redis()
    return sum(r.scard(_type_key(vid, pt)) for pt in _PROPERTY_TYPES)


# ---------------------------------------------------------------------------
# Asserted property-hierarchy helpers
#
# Properties use rdfs:subPropertyOf instead of rdfs:subClassOf.
# ELK does NOT classify properties, so all hierarchy endpoints are
# asserted-only (no reasoning fallback — just Redis field + SPARQL fallback).
#
# Fetcher signature: (ontology_id, vid, iri) -> list[str]
# ---------------------------------------------------------------------------

def _sparql_property_parents(ontology_id: str, vid: str, iri: str) -> list[str]:
    """SPARQL fallback: query rdfs:subPropertyOf for direct property parents."""
    try:
        from ontoexplorer.clients.oxigraph import get_store, graph_iri
        store = get_store()
        g = graph_iri(ontology_id, vid)
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?parent WHERE {{
                GRAPH <{g}> {{
                    <{iri}> rdfs:subPropertyOf ?parent .
                    FILTER(isIRI(?parent))
                    FILTER(?parent NOT IN (<{_OWL_TOP_OP}>, <{_OWL_TOP_DP}>))
                }}
            }}
        """
        return [row["parent"].value for row in store.query(q)]
    except Exception:
        return []


def _asserted_prop_parents_sync(ontology_id: str, vid: str, iri: str) -> list[str]:
    """Direct asserted property parents: Redis `parents` field first, SPARQL fallback."""
    r = _get_redis()
    raw = r.hget(_iri_key(vid, iri), "parents")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return _sparql_property_parents(ontology_id, vid, iri)


def _asserted_prop_children_sync(ontology_id: str, vid: str, iri: str) -> list[str]:
    """Direct asserted property children.

    Scans all property IRIs across the three type sets and checks each entity's
    `parents` field. Falls back to SPARQL if no entity has the field set.
    """
    r = _get_redis()
    all_prop_iris = sorted(
        set().union(*(r.smembers(_type_key(vid, pt)) for pt in _PROPERTY_TYPES))
    )

    found_any_parents_field = False
    children: list[str] = []
    for candidate in all_prop_iris:
        raw = r.hget(_iri_key(vid, candidate), "parents")
        if raw is not None:
            found_any_parents_field = True
            try:
                parents = json.loads(raw)
                if iri in parents:
                    children.append(candidate)
            except json.JSONDecodeError:
                pass

    if found_any_parents_field:
        return children

    # SPARQL fallback
    try:
        from ontoexplorer.clients.oxigraph import get_store, graph_iri
        store = get_store()
        g = graph_iri(ontology_id, vid)
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?child WHERE {{
                GRAPH <{g}> {{
                    ?child rdfs:subPropertyOf <{iri}> .
                    FILTER(isIRI(?child))
                }}
            }}
        """
        return [row["child"].value for row in store.query(q)]
    except Exception:
        return []


def _asserted_prop_ancestors_sync(ontology_id: str, vid: str, iri: str) -> list[str]:
    """BFS over asserted property parents until convergence."""
    visited: set[str] = set()
    result: list[str] = []
    queue: deque[str] = deque(_asserted_prop_parents_sync(ontology_id, vid, iri))
    while queue:
        node = queue.popleft()
        if node in visited or node in _OWL_EXCLUDED:
            continue
        visited.add(node)
        result.append(node)
        queue.extend(_asserted_prop_parents_sync(ontology_id, vid, node))
    return result


def _asserted_prop_descendants_sync(ontology_id: str, vid: str, iri: str) -> list[str]:
    """BFS over asserted property children until convergence."""
    visited: set[str] = set()
    result: list[str] = []
    queue: deque[str] = deque(_asserted_prop_children_sync(ontology_id, vid, iri))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        result.append(node)
        queue.extend(_asserted_prop_children_sync(ontology_id, vid, node))
    return result


# Async wrappers for the asserted fetchers (all properties are asserted-only)
async def _prop_parents_fetcher(ontology_id: str, vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_prop_parents_sync, ontology_id, vid, iri)


async def _prop_children_fetcher(ontology_id: str, vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_prop_children_sync, ontology_id, vid, iri)


async def _prop_ancestors_fetcher(ontology_id: str, vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_prop_ancestors_sync, ontology_id, vid, iri)


async def _prop_descendants_fetcher(ontology_id: str, vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_prop_descendants_sync, ontology_id, vid, iri)


# ---------------------------------------------------------------------------
# Shared hierarchy-page helper (mirror of terms._hal_hierarchy_page)
# ---------------------------------------------------------------------------

async def _hal_hierarchy_page(
    ontology_id: str,
    iri: str,
    request: Request,
    page: int,
    size: int,
    lang: str | None,
    db: AsyncSession,
    fetcher: Callable[[str, str, str], Awaitable[list[str]]],
) -> dict:
    """Fetch related property IRIs, page, and return HAL embedded under 'properties'."""
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    all_iris = await fetcher(ontology_id, vid, iri)
    offset   = page_to_offset(page, size)
    sliced   = all_iris[offset:offset + size]

    def _load_many() -> list[tuple[str, dict]]:
        r = _get_redis()
        return [(i, r.hgetall(_iri_key(vid, i)) or {}) for i in sliced]

    entities = await asyncio.to_thread(_load_many)

    def _fallback_entity(i: str) -> dict:
        fragment = i.rstrip("/")
        label = fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]
        return {
            "iri": i,
            "primary_label": label,
            "label": label,
            "short": label,
            "type": "object_property",
            "source": "",
            "labels": json.dumps([{"value": label, "lang": "en"}]),
            "synonyms": "[]",
            "definitions": "[]",
        }

    items = [
        entity_to_v1_term(
            (e if e else _fallback_entity(i)),
            ontology,
            request=request,
            is_obsolete=False,
            is_root=False,
            has_children=False,
            lang=lang,
            resource_kind="properties",
        )
        for i, e in entities
    ]
    return hal_page(items, request, total=len(all_iris), page=page, size=size,
                    embedded_key="properties")


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/properties  (must be FIRST in scope)
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/properties")
async def list_properties_hal(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    iri: str | None = Query(None),
    short_form: str | None = Query(None),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    # Single-IRI filter
    if iri:
        entity = await _load_entity(vid, iri)
        items = (
            [entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False,
                lang=lang, resource_kind="properties",
            )]
            if entity else []
        )
        return hal_page(items, request, total=len(items), page=0, size=size,
                        embedded_key="properties")

    # short_form filter: scan all property IRIs
    if short_form:
        all_iris = await asyncio.to_thread(_all_property_iris_sorted, vid)
        matched_items = []
        for candidate_iri in all_iris:
            entity = await _load_entity(vid, candidate_iri)
            if not entity:
                continue
            if entity.get("short") != short_form:
                continue
            matched_items.append(
                entity_to_v1_term(
                    entity, ontology,
                    request=request, is_obsolete=False, is_root=False, has_children=False,
                    lang=lang, resource_kind="properties",
                )
            )
        return hal_page(matched_items, request, total=len(matched_items), page=0, size=size,
                        embedded_key="properties")

    # Paged list of all property IRIs (union of three types)
    offset = page_to_offset(page, size)
    total = await asyncio.to_thread(_total_property_count, vid)
    all_iris = await asyncio.to_thread(_all_property_iris_sorted, vid)
    page_iris = all_iris[offset:offset + size]

    def _load_page(iris_slice: list[str]) -> list[dict]:
        r = _get_redis()
        result = []
        for i in iris_slice:
            h = r.hgetall(_iri_key(vid, i))
            if h:
                result.append(h)
        return result

    entities = await asyncio.to_thread(_load_page, page_iris)
    items = [
        entity_to_v1_term(
            e, ontology,
            request=request, is_obsolete=False, is_root=False, has_children=False,
            lang=lang, resource_kind="properties",
        )
        for e in entities
    ]
    return hal_page(items, request, total=total, page=page, size=size,
                    embedded_key="properties")


# ---------------------------------------------------------------------------
# Per-ontology: hierarchy endpoints
# MUST be registered BEFORE /{iri_path:path} catch-all
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/properties/{iri_path:path}/parents")
async def property_parents(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted direct parent properties (rdfs:subPropertyOf)."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _prop_parents_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/properties/{iri_path:path}/children")
async def property_children(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted direct child properties."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _prop_children_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/properties/{iri_path:path}/ancestors")
async def property_ancestors(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """All transitive asserted ancestors via rdfs:subPropertyOf+."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _prop_ancestors_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/properties/{iri_path:path}/descendants")
async def property_descendants(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """All transitive asserted descendants."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _prop_descendants_fetcher
    )


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/properties/{iri_path:path}  (catch-all LAST)
# MUST come after all hierarchy routes above
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/properties/{iri_path:path}")
async def get_property_hal(
    ontology_id: str,
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    entity = await _load_entity(vid, iri)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Property {iri} not found in {ontology_id}")

    return entity_to_v1_term(
        entity, ontology,
        request=request, is_obsolete=False, is_root=False, has_children=False,
        lang=lang, resource_kind="properties",
    )


# ---------------------------------------------------------------------------
# Global: GET /properties/findByIdAndIsDefiningOntology  (query-param form)
# MUST be registered BEFORE /properties/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/properties/findByIdAndIsDefiningOntology")
async def find_properties_by_id_defining_ontology(
    request: Request,
    iri: str = Query(...),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        source = entity.get("source", "")
        if source and source != ontology.shortname and source != str(v.ontology_id):
            continue
        items.append(
            entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False,
                lang=lang, resource_kind="properties",
            )
        )
    return hal_page(items, request, total=len(items), page=0, size=20,
                    embedded_key="properties")


# ---------------------------------------------------------------------------
# Global: GET /properties/findByIdAndIsDefiningOntology/{iri_path:path}
# Path form — must be before /properties/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/properties/findByIdAndIsDefiningOntology/{iri_path:path}")
async def find_properties_by_id_defining_ontology_path(
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    iri = double_decode_iri(iri_path)
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        source = entity.get("source", "")
        if source and source != ontology.shortname and source != str(v.ontology_id):
            continue
        items.append(
            entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False,
                lang=lang, resource_kind="properties",
            )
        )
    return hal_page(items, request, total=len(items), page=0, size=20,
                    embedded_key="properties")


# ---------------------------------------------------------------------------
# Global: GET /properties?iri=...
# MUST be registered BEFORE /properties/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/properties")
async def list_properties_global(
    request: Request,
    iri: str = Query(...),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        items.append(
            entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False,
                lang=lang, resource_kind="properties",
            )
        )
    return hal_page(items, request, total=len(items), page=0, size=20,
                    embedded_key="properties")


# ---------------------------------------------------------------------------
# Global: GET /properties/{iri_path:path}  (catch-all, LAST)
# ---------------------------------------------------------------------------

@router.get("/api/properties/{iri_path:path}")
async def get_property_global(
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    iri = double_decode_iri(iri_path)
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        items.append(
            entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False,
                lang=lang, resource_kind="properties",
            )
        )
    if not items:
        raise HTTPException(status_code=404, detail=f"Property {iri} not found in any ontology")
    return hal_page(items, request, total=len(items), page=0, size=20,
                    embedded_key="properties")
