"""OLS4-compat v2 flat surface.

Implements all /api/v2/... endpoints that mirror the v1 HAL surface but return
a flat envelope (no _links, _embedded replaced by elements).

Route registration order is critical (same caveat as terms.py and properties.py):
  - More-specific routes (/{iri}/children, /ancestors, etc.) MUST be registered
    BEFORE the bare /{iri_path:path} catch-all.
  - Global list routes (/classes, /properties, /individuals, /entities) must be
    registered BEFORE per-ontology routes that share path prefixes.

Most endpoints delegate to the same Redis fetchers as the v1 modules; the only
difference is the envelope (v2_page vs hal_page) and the shape mapper
(entity_to_v2 vs entity_to_v1_term).

TODO: factor shared helpers to _common.py if patterns crystallize further.
"""
import asyncio
import json
from typing import Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._common import (
    get_latest_version_or_404,
    get_ontology_or_404,
    hal_page_params,
    page_to_offset,
)
from ontoexplorer.api.ols._envelope import v2_page
from ontoexplorer.api.ols._iri import double_decode_iri
from ontoexplorer.api.ols._shapes import entity_to_v2, entity_to_v2_class
# TODO: factor hierarchy fetchers to _common.py if patterns crystallize
from ontoexplorer.api.ols.terms import (  # noqa: F401
    _load_entity as _load_class_entity,
    _redis_scard,
    _redis_smembers_sorted,
    _inferred_children_fetcher,
    _inferred_ancestors_fetcher,
    _inferred_descendants_fetcher,
    _hierarchical_ancestors_fetcher,
    _hierarchical_descendants_fetcher,
    _asserted_children_sync,
)
from ontoexplorer.api.ols.properties import (  # noqa: F401
    _load_entity as _load_prop_entity,
    _all_property_iris_sorted,
    _total_property_count,
    _prop_children_fetcher,
    _prop_ancestors_fetcher,
)
from ontoexplorer.api.ols.individuals import (  # noqa: F401
    _load_entity as _load_ind_entity,
)
from ontoexplorer.database import get_db
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key, _meta_key, _type_key
from ontoexplorer.modules.search.versions import latest_ready_versions

router = APIRouter()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PROPERTY_TYPES = ("object_property", "data_property", "annotation_property")


def _load_page_sync(vid: str, iris_slice: list[str]) -> list[dict]:
    r = _get_redis()
    return [h for i in iris_slice if (h := r.hgetall(_iri_key(vid, i)))]


def _fallback_entity(iri: str, etype: str = "class") -> dict:
    fragment = iri.rstrip("/")
    label = fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]
    return {
        "iri": iri,
        "primary_label": label,
        "label": label,
        "short": label,
        "type": etype,
        "source": "",
        "labels": json.dumps([{"value": label, "lang": "en"}]),
        "synonyms": "[]",
        "definitions": "[]",
    }


async def _v2_hierarchy_page(
    ontology_id: str,
    iri: str,
    request: Request,
    page: int,
    size: int,
    lang: str | None,
    db: AsyncSession,
    fetcher: Callable[[str, str, str], Awaitable[list[str]]],
    entity_type: str = "class",
) -> dict:
    """Fetch related IRIs, page, load entities, wrap in v2_page."""
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
    items = [
        entity_to_v2(
            e if e else _fallback_entity(i, entity_type),
            ontology,
            request=request,
            lang=lang,
        )
        for i, e in entities
    ]
    return v2_page(items, request, total=len(all_iris), page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/stats
# ---------------------------------------------------------------------------

@router.get("/api/v2/stats")
async def v2_stats(db: AsyncSession = Depends(get_db)):
    """Aggregate counts across all ready ontology versions."""
    versions = await latest_ready_versions(db)

    def _get_all_metas() -> list[dict]:
        r = _get_redis()
        return [r.hgetall(_meta_key(str(v.id))) or {} for v in versions]

    meta_blobs = await asyncio.to_thread(_get_all_metas)

    return {
        "numberOfOntologies":  len(versions),
        "numberOfClasses":     sum(int(m.get("class_count", 0))      for m in meta_blobs),
        "numberOfProperties":  sum(int(m.get("property_count", 0))   for m in meta_blobs),
        "numberOfIndividuals": sum(int(m.get("individual_count", 0)) for m in meta_blobs),
    }


# ---------------------------------------------------------------------------
# /v2/defined-fields  (static, no DB call)
# ---------------------------------------------------------------------------

_DEFINED_FIELDS = [
    "iri", "label", "short_form", "obo_id", "ontology_name", "ontology_prefix",
    "ontology_iri", "is_defining_ontology", "description", "synonyms", "annotation",
    "is_obsolete", "term_replaced_by", "is_root", "has_children", "in_subset",
    "is_preferred_root", "lang", "obo_xref", "obo_definition_citation", "obo_synonym",
    "type",
]


@router.get("/api/v2/defined-fields")
async def v2_defined_fields():
    """Return the static list of field names recognised by this API."""
    return _DEFINED_FIELDS


# ---------------------------------------------------------------------------
# Global /v2/classes  (paged across all ontologies)
# Must be registered BEFORE /v2/ontologies/{onto}/classes to avoid prefix collision.
# ---------------------------------------------------------------------------

@router.get("/api/v2/classes")
async def v2_list_classes_global(
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    search: str | None = Query(None),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Global paged class list, optional substring label filter."""
    page, size = page_size
    offset = page_to_offset(page, size)
    versions = await latest_ready_versions(db)

    items: list[dict] = []
    total = 0
    for v in versions:
        vid = str(v.id)
        all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "class"))
        if search:
            s_lower = search.lower()
            all_iris = [i for i in all_iris if s_lower in i.lower()]
        total += len(all_iris)
        if len(items) < offset + size:
            for i in all_iris:
                entity = await asyncio.to_thread(
                    lambda _i=i: _get_redis().hgetall(_iri_key(vid, _i)) or {}
                )
                if not entity:
                    continue
                if search and search.lower() not in entity.get("primary_label", "").lower():
                    continue
                ontology = await get_ontology_or_404(db, str(v.ontology_id))
                items.append(entity_to_v2_class(entity, ontology, request=request, lang=lang))

    page_items = items[offset:offset + size]
    return v2_page(page_items, request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# Global /v2/classes/{iri_path:path} detail
# NOTE: registered AFTER per-ontology routes to avoid path conflict; but since
# the prefix differs (/v2/classes vs /v2/ontologies) there is no conflict.
# ---------------------------------------------------------------------------

@router.get("/api/v2/classes/{iri_path:path}")
async def v2_get_class_global(
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Global class detail — returns a v2_page over all ontologies containing this IRI."""
    iri = double_decode_iri(iri_path)
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_class_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        items.append(entity_to_v2_class(entity, ontology, request=request, lang=lang))
    if not items:
        raise HTTPException(status_code=404, detail=f"Class {iri} not found in any ontology")
    return v2_page(items, request, total=len(items), page=0, size=20)


# ---------------------------------------------------------------------------
# Global /v2/properties
# ---------------------------------------------------------------------------

@router.get("/api/v2/properties")
async def v2_list_properties_global(
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)
    versions = await latest_ready_versions(db)

    all_items: list[dict] = []
    total = 0
    for v in versions:
        vid = str(v.id)
        all_iris = await asyncio.to_thread(_all_property_iris_sorted, vid)
        total += len(all_iris)
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        for i in all_iris:
            entity = await _load_prop_entity(vid, i)
            if entity:
                all_items.append(entity_to_v2(entity, ontology, request=request, lang=lang))

    return v2_page(all_items[offset:offset + size], request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# Global /v2/properties/{iri_path:path} detail
# ---------------------------------------------------------------------------

@router.get("/api/v2/properties/{iri_path:path}")
async def v2_get_property_global(
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    iri = double_decode_iri(iri_path)
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_prop_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        items.append(entity_to_v2(entity, ontology, request=request, lang=lang))
    if not items:
        raise HTTPException(status_code=404, detail=f"Property {iri} not found in any ontology")
    return v2_page(items, request, total=len(items), page=0, size=20)


# ---------------------------------------------------------------------------
# Global /v2/individuals
# ---------------------------------------------------------------------------

@router.get("/api/v2/individuals")
async def v2_list_individuals_global(
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)
    versions = await latest_ready_versions(db)

    all_items: list[dict] = []
    total = 0
    for v in versions:
        vid = str(v.id)
        all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "individual"))
        total += len(all_iris)
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        for i in all_iris:
            entity = await _load_ind_entity(vid, i)
            if entity:
                all_items.append(entity_to_v2(entity, ontology, request=request, lang=lang))

    return v2_page(all_items[offset:offset + size], request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# Global /v2/individuals/{iri_path:path} detail
# ---------------------------------------------------------------------------

@router.get("/api/v2/individuals/{iri_path:path}")
async def v2_get_individual_global(
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    iri = double_decode_iri(iri_path)
    versions = await latest_ready_versions(db)
    items: list[dict] = []
    for v in versions:
        entity = await _load_ind_entity(str(v.id), iri)
        if not entity:
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        items.append(entity_to_v2(entity, ontology, request=request, lang=lang))
    if not items:
        raise HTTPException(status_code=404, detail=f"Individual {iri} not found in any ontology")
    return v2_page(items, request, total=len(items), page=0, size=20)


# ---------------------------------------------------------------------------
# /v2/entities  (global union, optional ?type= filter)
# Must be before /v2/ontologies/{onto}/... to avoid prefix collision.
# ---------------------------------------------------------------------------

@router.get("/api/v2/entities")
async def v2_list_entities_global(
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    type: str | None = Query(None, description="class | property | individual"),
    search: str | None = Query(None),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Union of classes + properties + individuals across all ontologies."""
    page, size = page_size
    offset = page_to_offset(page, size)
    versions = await latest_ready_versions(db)

    all_items: list[dict] = []
    for v in versions:
        vid = str(v.id)
        ontology = await get_ontology_or_404(db, str(v.ontology_id))

        if not type or type == "class":
            for i in await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "class")):
                e = await _load_class_entity(vid, i)
                if e:
                    all_items.append(entity_to_v2(e, ontology, request=request, lang=lang))

        if not type or type == "property":
            for i in await asyncio.to_thread(_all_property_iris_sorted, vid):
                e = await _load_prop_entity(vid, i)
                if e:
                    all_items.append(entity_to_v2(e, ontology, request=request, lang=lang))

        if not type or type == "individual":
            for i in await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "individual")):
                e = await _load_ind_entity(vid, i)
                if e:
                    all_items.append(entity_to_v2(e, ontology, request=request, lang=lang))

    # Optional label search filter
    if search:
        s_lower = search.lower()
        all_items = [it for it in all_items if s_lower in it.get("label", "").lower()]

    total = len(all_items)
    return v2_page(all_items[offset:offset + size], request, total=total, page=page, size=size)


# ===========================================================================
# Per-ontology routes
# ===========================================================================

# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/classes  — paged list
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/classes")
async def v2_list_classes(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    total = await asyncio.to_thread(_redis_scard, _type_key(vid, "class"))
    all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "class"))
    page_iris = all_iris[offset:offset + size]

    entities = await asyncio.to_thread(_load_page_sync, vid, page_iris)
    items = [entity_to_v2_class(e, ontology, request=request, lang=lang) for e in entities]
    return v2_page(items, request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/classes/{iri}/children  — MUST be before catch-all
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/children")
async def v2_class_children(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Reasoner-inferred direct children; fallback to asserted."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _inferred_children_fetcher)


@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/ancestors")
async def v2_class_ancestors(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Reasoner-inferred transitive ancestors; fallback to asserted BFS."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _inferred_ancestors_fetcher)


@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/descendants")
async def v2_class_descendants(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Reasoner-inferred transitive descendants; fallback to asserted BFS."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _inferred_descendants_fetcher)


@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/hierarchicalChildren")
async def v2_class_hierarchical_children(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted direct children only (rdfs:subClassOf, no reasoner)."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    await get_latest_version_or_404(db, ontology_id)

    async def _hierarchical_children_fetcher(ontology_id: str, vid: str, iri: str) -> list[str]:
        return await asyncio.to_thread(_asserted_children_sync, ontology_id, vid, iri)

    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _hierarchical_children_fetcher)


@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/hierarchicalAncestors")
async def v2_class_hierarchical_ancestors(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted transitive ancestors only."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _hierarchical_ancestors_fetcher)


@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/hierarchicalDescendants")
async def v2_class_hierarchical_descendants(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted transitive descendants only."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _hierarchical_descendants_fetcher)


@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}/individuals")
async def v2_class_individuals(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Individuals that are rdf:type of this class."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    all_ind_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "individual"))

    def _filter_by_type() -> list[str]:
        r = _get_redis()
        result = []
        for ind_i in all_ind_iris:
            raw = r.hget(_iri_key(vid, ind_i), "types")
            if raw:
                try:
                    types = json.loads(raw)
                    if iri in types:
                        result.append(ind_i)
                except json.JSONDecodeError:
                    pass
        return result

    typed_iris = await asyncio.to_thread(_filter_by_type)

    # SPARQL fallback when no 'types' field is present
    if not typed_iris:
        try:
            from ontoexplorer.clients.oxigraph import get_store, graph_iri
            def _sparql_ind() -> list[str]:
                store = get_store()
                g = graph_iri(ontology_id, vid)
                q = f"""
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    SELECT DISTINCT ?ind WHERE {{
                        GRAPH <{g}> {{
                            ?ind rdf:type <{iri}> .
                            FILTER(isIRI(?ind))
                        }}
                    }}
                """
                return [row["ind"].value for row in store.query(q)]
            typed_iris = await asyncio.to_thread(_sparql_ind)
        except Exception:
            pass

    offset = page_to_offset(page, size)
    sliced = typed_iris[offset:offset + size]

    def _load_many() -> list[tuple[str, dict]]:
        r = _get_redis()
        return [(i, r.hgetall(_iri_key(vid, i)) or {}) for i in sliced]

    entities = await asyncio.to_thread(_load_many)
    items = [
        entity_to_v2(
            e if e else _fallback_entity(i, "individual"),
            ontology,
            request=request,
            lang=lang,
        )
        for i, e in entities
    ]
    return v2_page(items, request, total=len(typed_iris), page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/classes/{iri_path:path}  — detail (catch-all LAST)
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/classes/{iri_path:path}")
async def v2_get_class(
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

    entity = await _load_class_entity(vid, iri)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Class {iri} not found in {ontology_id}")
    return entity_to_v2_class(entity, ontology, request=request, lang=lang)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/properties  — paged list
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/properties")
async def v2_list_properties(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    total    = await asyncio.to_thread(_total_property_count, vid)
    all_iris = await asyncio.to_thread(_all_property_iris_sorted, vid)
    page_iris = all_iris[offset:offset + size]

    entities = await asyncio.to_thread(_load_page_sync, vid, page_iris)
    items = [entity_to_v2(e, ontology, request=request, lang=lang) for e in entities]
    return v2_page(items, request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/properties hierarchy — BEFORE catch-all
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/properties/{iri_path:path}/children")
async def v2_property_children(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _prop_children_fetcher, entity_type="object_property")


@router.get("/api/v2/ontologies/{ontology_id}/properties/{iri_path:path}/ancestors")
async def v2_property_ancestors(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _v2_hierarchy_page(ontology_id, iri, request, page, size, lang, db,
                                    _prop_ancestors_fetcher, entity_type="object_property")


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/properties/{iri_path:path}  — detail (catch-all LAST)
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/properties/{iri_path:path}")
async def v2_get_property(
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

    entity = await _load_prop_entity(vid, iri)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Property {iri} not found in {ontology_id}")
    return entity_to_v2(entity, ontology, request=request, lang=lang)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/individuals  — paged list
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/individuals")
async def v2_list_individuals(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    total    = await asyncio.to_thread(_redis_scard, _type_key(vid, "individual"))
    all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "individual"))
    page_iris = all_iris[offset:offset + size]

    entities = await asyncio.to_thread(_load_page_sync, vid, page_iris)
    items = [entity_to_v2(e, ontology, request=request, lang=lang) for e in entities]
    return v2_page(items, request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/individuals/{iri_path:path}  — detail (catch-all)
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/individuals/{iri_path:path}")
async def v2_get_individual(
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

    entity = await _load_ind_entity(vid, iri)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Individual {iri} not found in {ontology_id}")
    return entity_to_v2(entity, ontology, request=request, lang=lang)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/entities  — scoped union
# Must come BEFORE /v2/ontologies/{onto}/entities/{iri}/relatedFrom to avoid
# /entities being consumed as an IRI path segment
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/entities")
async def v2_list_entities(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    type: str | None = Query(None, description="class | property | individual"),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Union of classes + properties + individuals within one ontology."""
    page, size = page_size
    offset = page_to_offset(page, size)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    all_items: list[dict] = []

    if not type or type == "class":
        all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "class"))
        for i in all_iris:
            e = await _load_class_entity(vid, i)
            if e:
                all_items.append(entity_to_v2(e, ontology, request=request, lang=lang))

    if not type or type == "property":
        all_iris = await asyncio.to_thread(_all_property_iris_sorted, vid)
        for i in all_iris:
            e = await _load_prop_entity(vid, i)
            if e:
                all_items.append(entity_to_v2(e, ontology, request=request, lang=lang))

    if not type or type == "individual":
        all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "individual"))
        for i in all_iris:
            e = await _load_ind_entity(vid, i)
            if e:
                all_items.append(entity_to_v2(e, ontology, request=request, lang=lang))

    total = len(all_items)
    return v2_page(all_items[offset:offset + size], request, total=total, page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/entities/{iri_path}/relatedFrom  — empty stub
# relatedFrom requires a reverse-index we do not have; return empty page.
# Registered BEFORE the bare entities/{iri} detail to prevent suffix collision.
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/entities/{iri_path:path}/relatedFrom")
async def v2_entity_related_from(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    db: AsyncSession = Depends(get_db),
):
    """Return an empty v2 page.

    A full implementation of relatedFrom requires a reverse-index of entity
    references, which is not available in this version of the search index.
    The route is wired so clients do not receive 404.
    """
    page, size = page_size
    return v2_page([], request, total=0, page=page, size=size)


# ---------------------------------------------------------------------------
# /v2/ontologies/{onto}/entities/{iri_path:path}  — scoped detail (catch-all LAST)
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/entities/{iri_path:path}")
async def v2_get_entity(
    ontology_id: str,
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return first matching entity (class, property, or individual) in the ontology."""
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    for loader in (_load_class_entity, _load_prop_entity, _load_ind_entity):
        entity = await loader(vid, iri)
        if entity:
            return entity_to_v2(entity, ontology, request=request, lang=lang)

    raise HTTPException(status_code=404, detail=f"Entity {iri} not found in {ontology_id}")
