"""OLS4-compat term endpoints (v1 HAL).

Route registration order matters:
  - Fixed-path routes (/terms, /roots, /findByIdAndIsDefiningOntology) must be
    registered *before* the catch-all /{iri_path:path} route, otherwise FastAPI
    will match the fixed names as part of the IRI path.
"""
import asyncio
import json

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
# Per-ontology: GET /ontologies/{onto}/terms/{iri_path:path}   (catch-all last)
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
