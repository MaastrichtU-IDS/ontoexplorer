"""OLS4-compat term endpoints (v1 HAL).

Route registration order matters:
  - Fixed-path routes (/terms, /roots, /findByIdAndIsDefiningOntology) must be
    registered *before* the catch-all /{iri_path:path} route, otherwise FastAPI
    will match the fixed names as part of the IRI path.
  - Hierarchy routes (/{iri}/parents, /{iri}/children, …) MUST be registered
    before the bare /{iri_path:path} detail route for the same reason.
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
# Internal helpers
# ---------------------------------------------------------------------------

_OWL_THING   = "http://www.w3.org/2002/07/owl#Thing"
_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
_OWL_EXCLUDED = {_OWL_THING, _OWL_NOTHING}


def _redis_hgetall(key: str) -> dict:
    """Sync helper: returns hash as dict, or empty dict."""
    return _get_redis().hgetall(key) or {}


def _redis_smembers_sorted(key: str) -> list[str]:
    """Sync helper: returns sorted set members."""
    return sorted(_get_redis().smembers(key))


def _redis_scard(key: str) -> int:
    """Sync helper: returns cardinality of a set."""
    return _get_redis().scard(key)


async def _load_entity(version_id: str, iri: str) -> dict | None:
    """Load entity hash from Redis; return None if missing."""
    h = await asyncio.to_thread(_redis_hgetall, _iri_key(version_id, iri))
    return h if h else None


# ---------------------------------------------------------------------------
# Asserted-hierarchy fetchers
# (read the `parents` JSON field seeded by the indexer or the test fixture)
# ---------------------------------------------------------------------------

def _asserted_parents_sync(vid: str, iri: str) -> list[str]:
    """Return direct asserted parents of `iri` from the Redis hash `parents` field."""
    r = _get_redis()
    raw = r.hget(_iri_key(vid, iri), "parents")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return []


def _asserted_children_sync(vid: str, iri: str) -> list[str]:
    """Return direct asserted children of `iri` by scanning the class type set.

    Reads the `parents` field from each entity hash. This is O(N) in the number
    of classes indexed for the version — acceptable for v1; a `children` index
    field should be added to the indexer in a follow-up task.
    """
    r = _get_redis()
    all_iris = sorted(r.smembers(_type_key(vid, "class")))
    children: list[str] = []
    for candidate in all_iris:
        raw = r.hget(_iri_key(vid, candidate), "parents")
        if raw:
            try:
                parents = json.loads(raw)
                if iri in parents:
                    children.append(candidate)
            except json.JSONDecodeError:
                pass
    return children


def _asserted_ancestors_sync(vid: str, iri: str) -> list[str]:
    """BFS over asserted parents until convergence."""
    visited: set[str] = set()
    result: list[str] = []
    queue: deque[str] = deque(_asserted_parents_sync(vid, iri))
    while queue:
        node = queue.popleft()
        if node in visited or node in _OWL_EXCLUDED:
            continue
        visited.add(node)
        result.append(node)
        queue.extend(_asserted_parents_sync(vid, node))
    return result


def _asserted_descendants_sync(vid: str, iri: str) -> list[str]:
    """BFS over asserted children until convergence."""
    visited: set[str] = set()
    result: list[str] = []
    queue: deque[str] = deque(_asserted_children_sync(vid, iri))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        result.append(node)
        queue.extend(_asserted_children_sync(vid, node))
    return result


# ---------------------------------------------------------------------------
# Inferred-hierarchy fetchers  (fall back to asserted on any error)
# ---------------------------------------------------------------------------

async def _inferred_parents_fetcher(vid: str, iri: str) -> list[str]:
    """Direct inferred parents via ELK `direct_superclasses`; fallback: asserted."""
    try:
        from ontoexplorer.clients.reasoning import get_classification, ReasoningNotReadyError
        classification = await get_classification(vid)
        direct = classification.get("direct_superclasses", {})
        parents = [p for p in direct.get(iri, []) if p not in _OWL_EXCLUDED]
        if parents:
            return parents
        # Fall through to asserted if empty (term may not be in the classification)
    except Exception:
        pass
    return await asyncio.to_thread(_asserted_parents_sync, vid, iri)


async def _inferred_children_fetcher(vid: str, iri: str) -> list[str]:
    """Direct inferred children via ELK `direct_subclasses`; fallback: asserted."""
    try:
        from ontoexplorer.clients.reasoning import get_classification, ReasoningNotReadyError
        classification = await get_classification(vid)
        direct = classification.get("direct_subclasses", {})
        children = [c for c in direct.get(iri, []) if c not in _OWL_EXCLUDED]
        if children:
            return children
    except Exception:
        pass
    return await asyncio.to_thread(_asserted_children_sync, vid, iri)


async def _inferred_ancestors_fetcher(vid: str, iri: str) -> list[str]:
    """All inferred ancestors via ELK `superclasses`; fallback: asserted-BFS."""
    try:
        from ontoexplorer.clients.reasoning import get_classification, ReasoningNotReadyError
        classification = await get_classification(vid)
        all_sup = classification.get("superclasses", {})
        ancestors = [a for a in all_sup.get(iri, []) if a not in _OWL_EXCLUDED]
        if ancestors:
            return ancestors
    except Exception:
        pass
    return await asyncio.to_thread(_asserted_ancestors_sync, vid, iri)


async def _inferred_descendants_fetcher(vid: str, iri: str) -> list[str]:
    """All inferred descendants via ELK `subclasses`; fallback: asserted-BFS."""
    try:
        from ontoexplorer.clients.reasoning import get_classification, ReasoningNotReadyError
        classification = await get_classification(vid)
        all_sub = classification.get("subclasses", {})
        descendants = [d for d in all_sub.get(iri, []) if d not in _OWL_EXCLUDED]
        if descendants:
            return descendants
    except Exception:
        pass
    return await asyncio.to_thread(_asserted_descendants_sync, vid, iri)


# ---------------------------------------------------------------------------
# Asserted-only fetchers (hierarchical* variants)
# ---------------------------------------------------------------------------

async def _hierarchical_parents_fetcher(vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_parents_sync, vid, iri)


async def _hierarchical_ancestors_fetcher(vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_ancestors_sync, vid, iri)


async def _hierarchical_descendants_fetcher(vid: str, iri: str) -> list[str]:
    return await asyncio.to_thread(_asserted_descendants_sync, vid, iri)


# ---------------------------------------------------------------------------
# Shared hierarchy-page helper
# ---------------------------------------------------------------------------

async def _hal_hierarchy_page(
    ontology_id: str,
    iri: str,
    request: Request,
    page: int,
    size: int,
    lang: str | None,
    db: AsyncSession,
    fetcher: Callable[[str, str], Awaitable[list[str]]],
) -> dict:
    """Fetch related IRIs via `fetcher`, page them, and return an HAL envelope."""
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    all_iris = await fetcher(vid, iri)
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
            "type": "class",
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
        )
        for i, e in entities
    ]
    return hal_page(items, request, total=len(all_iris), page=page, size=size, embedded_key="terms")


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/terms   (must be first in its scope)
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/terms")
async def list_terms_hal(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    iri: str | None = Query(None),
    short_form: str | None = Query(None),
    obo_id: str | None = Query(None),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    ontology = await get_ontology_or_404(db, ontology_id)
    version = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    # Single-IRI filter
    if iri:
        entity = await _load_entity(vid, iri)
        items = (
            [entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
            )]
            if entity else []
        )
        return hal_page(items, request, total=len(items), page=0, size=size, embedded_key="terms")

    # short_form / obo_id filters: scan the entire type set and match
    if short_form or obo_id:
        all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "class"))
        matched_items = []
        for candidate_iri in all_iris:
            entity = await _load_entity(vid, candidate_iri)
            if not entity:
                continue
            if short_form and entity.get("short") != short_form:
                continue
            if obo_id:
                from ontoexplorer.api.ols._shapes import derive_obo_id
                if derive_obo_id(entity.get("short", "")) != obo_id:
                    continue
            matched_items.append(
                entity_to_v1_term(
                    entity, ontology,
                    request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
                )
            )
        return hal_page(matched_items, request, total=len(matched_items), page=0, size=size, embedded_key="terms")

    # Paged list of all class IRIs
    offset = page_to_offset(page, size)
    total = await asyncio.to_thread(_redis_scard, _type_key(vid, "class"))
    iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "class"))
    page_iris = iris[offset:offset + size]

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
            request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
        )
        for e in entities
    ]
    return hal_page(items, request, total=total, page=page, size=size, embedded_key="terms")


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/terms/roots
# MUST be registered before /{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/terms/roots")
async def list_terms_roots_hal(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    ontology = await get_ontology_or_404(db, ontology_id)
    version = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    # Try the pre-built root cache from _build_tree_cache (keyed by limit=100)
    _DEFAULT_LIMIT = 100
    roots_cache_key = f"terms_root:{vid}:class:{_DEFAULT_LIMIT}"

    def _get_roots_cached() -> list[dict] | None:
        raw = _get_redis().get(roots_cache_key)
        if raw:
            data = json.loads(raw)
            return data.get("terms", [])
        return None

    cached_terms = await asyncio.to_thread(_get_roots_cached)

    if cached_terms is not None:
        # Apply paging to the cached list
        offset = page_to_offset(page, size)
        total = len(cached_terms)
        page_terms = cached_terms[offset:offset + size]

        def _enrich(row_terms: list[dict]) -> list[dict]:
            r = _get_redis()
            result = []
            for t in row_terms:
                term_iri = t["iri"]
                entity = r.hgetall(_iri_key(vid, term_iri))
                if not entity:
                    # Fallback: construct a minimal entity from the cached row
                    entity = {
                        "iri": term_iri,
                        "primary_label": t.get("label") or term_iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1],
                        "label": t.get("label") or "",
                        "short": term_iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1],
                        "type": "class",
                        "source": "",
                        "labels": json.dumps([{"value": t.get("label") or "", "lang": "en"}]),
                        "synonyms": "[]",
                        "definitions": "[]",
                    }
                result.append(
                    entity_to_v1_term(
                        entity, ontology,
                        request=request, is_obsolete=False,
                        is_root=True,
                        has_children=bool(t.get("has_children", False)),
                        lang=lang,
                    )
                )
            return result

        items = await asyncio.to_thread(_enrich, page_terms)
        return hal_page(items, request, total=total, page=page, size=size, embedded_key="terms")

    # No cache — return empty paged response (Oxigraph unavailable in tests)
    return hal_page([], request, total=0, page=page, size=size, embedded_key="terms")


# ---------------------------------------------------------------------------
# Per-ontology: hierarchy endpoints
# MUST be registered before /{iri_path:path} catch-all
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/parents")
async def term_parents(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Inferred parents (direct superclasses); falls back to asserted on reasoning unavailability."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _inferred_parents_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/children")
async def term_children(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Inferred direct children; falls back to asserted on reasoning unavailability."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _inferred_children_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/ancestors")
async def term_ancestors(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """All inferred ancestors (transitive superclasses); falls back to asserted-BFS."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _inferred_ancestors_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/descendants")
async def term_descendants(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """All inferred descendants (transitive subclasses); falls back to asserted-BFS."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _inferred_descendants_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/hierarchicalParents")
async def term_hierarchical_parents(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted-only direct parents (strict rdfs:subClassOf, no reasoner)."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _hierarchical_parents_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/hierarchicalAncestors")
async def term_hierarchical_ancestors(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted-only transitive ancestors (strict rdfs:subClassOf+, no reasoner)."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _hierarchical_ancestors_fetcher
    )


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/hierarchicalDescendants")
async def term_hierarchical_descendants(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Asserted-only transitive descendants (strict rdfs:subClassOf+, no reasoner)."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _hierarchical_descendants_fetcher
    )


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/terms/{iri_path:path}   (catch-all LAST)
# MUST come after all hierarchy routes above
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}")
async def get_term_hal(
    ontology_id: str,
    iri_path: str,
    request: Request,
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    entity = await _load_entity(vid, iri)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Term {iri} not found in {ontology_id}")

    # has_children: check if this IRI has an entry in the type set with children
    # (no search:tree: key exists; use False as safe default)
    has_children = False

    return entity_to_v1_term(
        entity, ontology,
        request=request, is_obsolete=False, is_root=False, has_children=has_children, lang=lang,
    )


# ---------------------------------------------------------------------------
# Global: GET /terms/findByIdAndIsDefiningOntology
# MUST be registered before /terms/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/terms/findByIdAndIsDefiningOntology")
async def find_terms_by_id_defining_ontology(
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
        # Include only if source matches the ontology (i.e. this is the defining ontology)
        source = entity.get("source", "")
        if source and source != str(v.ontology_id):
            continue
        ontology = await get_ontology_or_404(db, str(v.ontology_id))
        items.append(
            entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
            )
        )
    return hal_page(items, request, total=len(items), page=0, size=20, embedded_key="terms")


# ---------------------------------------------------------------------------
# Global: GET /terms?iri=...
# MUST be registered before /terms/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/terms")
async def list_terms_global(
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
                request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
            )
        )
    return hal_page(items, request, total=len(items), page=0, size=20, embedded_key="terms")


# ---------------------------------------------------------------------------
# Global: GET /terms/{iri_path:path}  (catch-all, last)
# ---------------------------------------------------------------------------

@router.get("/api/terms/{iri_path:path}")
async def get_term_global(
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
                request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
            )
        )
    if not items:
        raise HTTPException(status_code=404, detail=f"Term {iri} not found in any ontology")
    return hal_page(items, request, total=len(items), page=0, size=20, embedded_key="terms")
