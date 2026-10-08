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
    collect_global,
)
from ontoexplorer.api.ols._envelope import hal_page
from ontoexplorer.api.ols._iri import double_decode_iri
from ontoexplorer.api.ols._shapes import entity_to_v1_term
from ontoexplorer.database import get_db
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OWL_THING   = "http://www.w3.org/2002/07/owl#Thing"
_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
_OWL_EXCLUDED = {_OWL_THING, _OWL_NOTHING}


async def _load_entity(db, version_id: str, iri: str) -> dict | None:
    """Load the entity payload from entity_index (#242 Stage 1 PR2); None if absent."""
    from ontoexplorer.api.ols._entity_source import load_entity
    return await load_entity(db, version_id, iri)


# ---------------------------------------------------------------------------
# Asserted-hierarchy fetchers
# (read the `parents` JSON field from Redis; fall back to SPARQL when absent)
#
# Fetcher signature: (ontology_id, vid, iri) -> list[str]
# `ontology_id` is needed to construct the Oxigraph named-graph IRI.
# ---------------------------------------------------------------------------

def _sparql_parents(ontology_id: str, vid: str, iri: str) -> list[str]:
    """SPARQL fallback for direct parents when the Redis `parents` field is absent.

    Queries `?iri rdfs:subClassOf ?parent` against the named graph, filtering
    out blank nodes and owl:Thing.
    """
    try:
        from ontoexplorer.clients.oxigraph import get_store, graph_iri
        store = get_store()
        g = graph_iri(ontology_id, vid)
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>
            SELECT DISTINCT ?parent WHERE {{
                GRAPH <{g}> {{
                    <{iri}> rdfs:subClassOf ?parent .
                    FILTER(isIRI(?parent))
                    FILTER(?parent != <{_OWL_THING}>)
                }}
            }}
        """
        return [row["parent"].value for row in store.query(q)]
    except Exception:
        return []


def _sparql_children(ontology_id: str, vid: str, iri: str) -> list[str]:
    """SPARQL fallback for direct children (`?child rdfs:subClassOf <iri>`)."""
    try:
        from ontoexplorer.clients.oxigraph import get_store, graph_iri
        store = get_store()
        g = graph_iri(ontology_id, vid)
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?child WHERE {{
                GRAPH <{g}> {{
                    ?child rdfs:subClassOf <{iri}> .
                    FILTER(isIRI(?child))
                }}
            }}
        """
        return [row["child"].value for row in store.query(q)]
    except Exception:
        return []


def _sparql_bfs(ontology_id: str, vid: str, iri: str, direct) -> list[str]:
    """Transitive closure (fallback BFS) over a direct-relative SPARQL fn."""
    visited: set[str] = set()
    result: list[str] = []
    queue: deque[str] = deque(direct(ontology_id, vid, iri))
    while queue:
        node = queue.popleft()
        if node in visited or node in _OWL_EXCLUDED:
            continue
        visited.add(node)
        result.append(node)
        queue.extend(direct(ontology_id, vid, node))
    return result


async def _asserted_parents(db, ontology_id: str, vid: str, iri: str) -> list[str]:
    """Direct asserted parents from hierarchy_edge; SPARQL fallback if not materialised.

    The indexer never wrote a Redis `parents` field (every read missed → SPARQL),
    so this drops the Redis read and uses the indexed edges instead (#242 Stage 1).
    """
    from ontoexplorer.modules.hierarchy.edges import (
        CLASS_KIND, has_materialised_hierarchy, related_iris)
    if await has_materialised_hierarchy(db, vid):
        return await related_iris(db, vid, iri, CLASS_KIND, direction="up", transitive=False)
    return await asyncio.to_thread(_sparql_parents, ontology_id, vid, iri)


async def _asserted_children(db, ontology_id: str, vid: str, iri: str) -> list[str]:
    """Direct asserted children from hierarchy_edge; SPARQL fallback.

    Replaces an O(N) scan of the whole class set (smembers + per-entity hget) with
    an indexed reverse-edge lookup.
    """
    from ontoexplorer.modules.hierarchy.edges import (
        CLASS_KIND, has_materialised_hierarchy, related_iris)
    if await has_materialised_hierarchy(db, vid):
        return await related_iris(db, vid, iri, CLASS_KIND, direction="down", transitive=False)
    return await asyncio.to_thread(_sparql_children, ontology_id, vid, iri)


async def _asserted_ancestors(db, ontology_id: str, vid: str, iri: str) -> list[str]:
    """Transitive asserted parents from hierarchy_edge; SPARQL-BFS fallback."""
    from ontoexplorer.modules.hierarchy.edges import (
        CLASS_KIND, has_materialised_hierarchy, related_iris)
    if await has_materialised_hierarchy(db, vid):
        return await related_iris(db, vid, iri, CLASS_KIND, direction="up", transitive=True)
    return await asyncio.to_thread(_sparql_bfs, ontology_id, vid, iri, _sparql_parents)


async def _asserted_descendants(db, ontology_id: str, vid: str, iri: str) -> list[str]:
    """Transitive asserted children from hierarchy_edge; SPARQL-BFS fallback."""
    from ontoexplorer.modules.hierarchy.edges import (
        CLASS_KIND, has_materialised_hierarchy, related_iris)
    if await has_materialised_hierarchy(db, vid):
        return await related_iris(db, vid, iri, CLASS_KIND, direction="down", transitive=True)
    return await asyncio.to_thread(_sparql_bfs, ontology_id, vid, iri, _sparql_children)


# (#283) The sync Redis-first jstree/graph helpers (_asserted_parents_sync,
# _asserted_children_sync) were removed: the widget builders are async now and use
# the indexed hierarchy_edge path like every other hierarchy reader.


# ---------------------------------------------------------------------------
# Inferred-hierarchy fetchers  (fall back to asserted on any error)
#
# Fetcher signature: (ontology_id, vid, iri) -> list[str]
# ---------------------------------------------------------------------------

async def _inferred_parents_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    """Direct inferred parents via targeted superclasses(direct=True); fallback: asserted.

    #282: per-IRI call, not the full classification blob (OOM on large ontologies).
    """
    try:
        from ontoexplorer.clients.reasoning import superclasses as _reasoner_superclasses
        data = await _reasoner_superclasses(vid, iri, direct=True, reasoner=reasoner)
        parents = [p for p in data.get("superclasses", []) if p not in _OWL_EXCLUDED]
        if parents:
            return parents
        # Fall through to asserted if empty (term may not be in the classification)
    except Exception:
        pass
    return await _asserted_parents(db, ontology_id, vid, iri)


# These fetch ONE class's inferred edges via targeted per-IRI reasoner calls
# (#282), NOT get_classification() — that returned the whole classification blob,
# whose transitive maps on a large ontology (CHEBI, 218k classes) parse into
# multi-GB of Python dicts and OOM-killed the api pod just to read one class's
# children. Same pattern the MOS evaluator moved to in #280. The reasoner serves
# each from the same maps, cached per-IRI; a raise (not-ready / not-found) falls
# back to the asserted edges exactly as before.

async def _inferred_children_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    """Direct inferred children via targeted subclasses(direct=True); fallback: asserted."""
    try:
        from ontoexplorer.clients.reasoning import subclasses as _reasoner_subclasses
        data = await _reasoner_subclasses(vid, iri, direct=True, reasoner=reasoner)
        children = [c for c in data.get("subclasses", []) if c not in _OWL_EXCLUDED]
        if children:
            return children
    except Exception:
        pass
    return await _asserted_children(db, ontology_id, vid, iri)


async def _inferred_ancestors_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    """All inferred ancestors via targeted superclasses(direct=False); fallback: asserted-BFS."""
    try:
        from ontoexplorer.clients.reasoning import superclasses as _reasoner_superclasses
        data = await _reasoner_superclasses(vid, iri, direct=False, reasoner=reasoner)
        ancestors = [a for a in data.get("superclasses", []) if a not in _OWL_EXCLUDED]
        if ancestors:
            return ancestors
    except Exception:
        pass
    return await _asserted_ancestors(db, ontology_id, vid, iri)


async def _inferred_descendants_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    """All inferred descendants via targeted subclasses(direct=False); fallback: asserted-BFS."""
    try:
        from ontoexplorer.clients.reasoning import subclasses as _reasoner_subclasses
        data = await _reasoner_subclasses(vid, iri, direct=False, reasoner=reasoner)
        descendants = [d for d in data.get("subclasses", []) if d not in _OWL_EXCLUDED]
        if descendants:
            return descendants
    except Exception:
        pass
    return await _asserted_descendants(db, ontology_id, vid, iri)


# ---------------------------------------------------------------------------
# Asserted-only fetchers (hierarchical* variants)
# ---------------------------------------------------------------------------

async def _hierarchical_parents_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    return await _asserted_parents(db, ontology_id, vid, iri)


async def _hierarchical_ancestors_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    return await _asserted_ancestors(db, ontology_id, vid, iri)


async def _hierarchical_descendants_fetcher(db, ontology_id: str, vid: str, iri: str, reasoner: str = "rustdl") -> list[str]:
    return await _asserted_descendants(db, ontology_id, vid, iri)


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
    fetcher: Callable[..., Awaitable[list[str]]],
) -> dict:
    """Fetch related IRIs via `fetcher(db, ontology_id, vid, iri, reasoner)`, page them, and return HAL."""
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    all_iris = await fetcher(db, ontology_id, vid, iri, version.reasoner)
    offset   = page_to_offset(page, size)
    sliced   = all_iris[offset:offset + size]

    # Render from entity_index, not the Redis :iri: hash (#242 Stage 1 PR 2).
    from ontoexplorer.api.ols._entity_source import load_entities
    ent_map = await load_entities(db, vid, sliced)
    entities = [(i, ent_map.get(i) or {}) for i in sliced]

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
        entity = await _load_entity(db, vid, iri)
        items = (
            [entity_to_v1_term(
                entity, ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
            )]
            if entity else []
        )
        return hal_page(items, request, total=len(items), page=0, size=size, embedded_key="terms")

    # short_form / obo_id filters → a direct entity_index `short` lookup (#242
    # Workstream B — was a full Redis class type-set scan + per-IRI load). obo_id
    # (PREFIX:NNN) reverses to the stored short (PREFIX_NNN).
    if short_form or obo_id:
        from sqlalchemy import select as _select
        from ontoexplorer.models.db import EntityIndex as _EI
        from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict as _adapt
        _short = short_form if short_form else obo_id.replace(":", "_", 1)
        rows = (await db.execute(
            _select(_EI).where(
                _EI.version_id == vid, _EI.type == "class", _EI.short == _short)
        )).scalars().all()
        matched_items = [
            entity_to_v1_term(
                _adapt(r), ontology,
                request=request, is_obsolete=False, is_root=False, has_children=False, lang=lang,
            )
            for r in rows
        ]
        return hal_page(matched_items, request, total=len(matched_items), page=0, size=size, embedded_key="terms")

    # Paged list of all classes — enumerate + load from entity_index (#242 PR2).
    from ontoexplorer.api.ols._entity_source import count_entities, list_entities
    offset = page_to_offset(page, size)
    total = await count_entities(db, vid, ["class"])
    entities = await list_entities(db, vid, ["class"], limit=size, offset=offset)
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

        # Prefetch the root entities from entity_index (#242 Workstream B — was a
        # per-root Redis hgetall) so synonyms/definitions/source/non-en labels
        # survive once the Redis :iri: hash stops being written.
        from ontoexplorer.api.ols._entity_source import load_entities
        _ent_map = await load_entities(db, vid, [t["iri"] for t in page_terms])

        def _enrich(row_terms: list[dict]) -> list[dict]:
            result = []
            for t in row_terms:
                term_iri = t["iri"]
                entity = _ent_map.get(term_iri)
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


@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/hierarchicalChildren")
async def term_hierarchical_children(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Direct inferred subclasses via ELK direct_subclasses (asserted fallback).

    Symmetric to hierarchicalParents but for direct subclasses; matches the
    OLS4 EBI convention of returning the reasoner's direct subclass set here.
    """
    page, size = page_size
    iri = double_decode_iri(iri_path)
    return await _hal_hierarchy_page(
        ontology_id, iri, request, page, size, lang, db, _inferred_children_fetcher,
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

    entity = await _load_entity(db, vid, iri)
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
    items = await collect_global(
        db, iri,
        lambda e, o: entity_to_v1_term(
            e, o, request=request, is_obsolete=False, is_root=False,
            has_children=False, lang=lang),
        defining_only=True,
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
    items = await collect_global(
        db, iri,
        lambda e, o: entity_to_v1_term(
            e, o, request=request, is_obsolete=False, is_root=False,
            has_children=False, lang=lang),
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
    items = await collect_global(
        db, iri,
        lambda e, o: entity_to_v1_term(
            e, o, request=request, is_obsolete=False, is_root=False,
            has_children=False, lang=lang),
    )
    if not items:
        raise HTTPException(status_code=404, detail=f"Term {iri} not found in any ontology")
    return hal_page(items, request, total=len(items), page=0, size=20, embedded_key="terms")
