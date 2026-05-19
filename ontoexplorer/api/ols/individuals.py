"""OLS4-compat individuals endpoints (v1 HAL).

Individuals are OWL named individuals — instances of classes.  They do NOT
have a class hierarchy (no parents/children endpoints), but DO have a /types
endpoint returning the classes the individual is rdf:type of.

Route registration order matters:
  - Per-ontology fixed-path routes (/individuals) before catch-all /{iri_path:path}.
  - The /types suffix route MUST be registered BEFORE the bare /{iri_path:path}
    catch-all, otherwise the literal '/types' gets consumed as part of the IRI.
  - Global fixed routes (/individuals with ?iri= query param) before global
    catch-all (/individuals/{iri_path:path}).

For /types, the implementation reads a ``types`` JSON field from the individual's
Redis hash (a list of class IRIs written by the test fixture and, when the
indexer is extended, by the production indexer).  If that field is absent it
falls back to a SPARQL query against Oxigraph.
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

_OWL_NAMED_INDIVIDUAL = "http://www.w3.org/2002/07/owl#NamedIndividual"


def _redis_hgetall(key: str) -> dict:
    return _get_redis().hgetall(key) or {}


def _redis_scard(key: str) -> int:
    return _get_redis().scard(key)


def _redis_smembers_sorted(key: str) -> list[str]:
    return sorted(_get_redis().smembers(key))


async def _load_entity(version_id: str, iri: str) -> dict | None:
    h = await asyncio.to_thread(_redis_hgetall, _iri_key(version_id, iri))
    return h if h else None


# ---------------------------------------------------------------------------
# /types helper: resolve rdf:type classes for an individual
# ---------------------------------------------------------------------------

def _individual_types_sync(ontology_id: str, vid: str, iri: str, entity: dict) -> list[str]:
    """Return the class IRIs that ``iri`` is rdf:type of.

    Primary path: read the ``types`` JSON field from the Redis entity hash.
    This field is written by the test fixture; the production indexer does not
    yet write it, so we fall through to SPARQL.

    SPARQL fallback: query Oxigraph for ``?iri rdf:type ?cls`` in the named
    graph, filtering out blank nodes and owl:NamedIndividual.
    """
    raw = entity.get("types")
    if raw:
        try:
            iris = json.loads(raw)
            if isinstance(iris, list) and iris:
                return [i for i in iris if i != _OWL_NAMED_INDIVIDUAL]
        except json.JSONDecodeError:
            pass

    # SPARQL fallback
    try:
        from ontoexplorer.clients.oxigraph import get_store, graph_iri
        store = get_store()
        g = graph_iri(ontology_id, vid)
        q = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT DISTINCT ?cls WHERE {{
                GRAPH <{g}> {{
                    <{iri}> rdf:type ?cls .
                    FILTER(isIRI(?cls))
                    FILTER(?cls != <{_OWL_NAMED_INDIVIDUAL}>)
                }}
            }}
        """
        return [row["cls"].value for row in store.query(q)]
    except Exception:
        return []


def _fallback_class_entity(iri: str) -> dict:
    """Minimal class entity dict for a class IRI not found in Redis."""
    fragment = iri.rstrip("/")
    label = fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]
    return {
        "iri": iri,
        "primary_label": label,
        "label": label,
        "short": label,
        "type": "class",
        "source": "",
        "labels": json.dumps([{"value": label, "lang": "en"}]),
        "synonyms": "[]",
        "definitions": "[]",
    }


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/individuals   (paged list, first in scope)
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/individuals")
async def list_individuals_hal(
    ontology_id: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    iri: str | None = Query(None),
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
                lang=lang, resource_kind="individuals",
            )]
            if entity else []
        )
        return hal_page(items, request, total=len(items), page=0, size=size,
                        embedded_key="individuals")

    # Paged list of all individual IRIs
    offset = page_to_offset(page, size)
    total  = await asyncio.to_thread(_redis_scard, _type_key(vid, "individual"))
    all_iris = await asyncio.to_thread(_redis_smembers_sorted, _type_key(vid, "individual"))
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
            lang=lang, resource_kind="individuals",
        )
        for e in entities
    ]
    return hal_page(items, request, total=total, page=page, size=size,
                    embedded_key="individuals")


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/individuals/{iri_path:path}/types
# MUST be registered BEFORE the bare /{iri_path:path} catch-all
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/individuals/{iri_path:path}/types")
async def individual_types(
    ontology_id: str,
    iri_path: str,
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return the classes this individual is rdf:type of, as a HAL page of terms."""
    page, size = page_size
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version  = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    entity = await _load_entity(vid, iri)
    if not entity:
        raise HTTPException(status_code=404,
                            detail=f"Individual {iri} not found in {ontology_id}")

    type_iris = await asyncio.to_thread(
        _individual_types_sync, ontology_id, vid, iri, entity
    )

    offset  = page_to_offset(page, size)
    sliced  = type_iris[offset:offset + size]

    def _load_classes() -> list[tuple[str, dict]]:
        r = _get_redis()
        return [(ci, r.hgetall(_iri_key(vid, ci)) or {}) for ci in sliced]

    class_entities = await asyncio.to_thread(_load_classes)

    items = [
        entity_to_v1_term(
            (e if e else _fallback_class_entity(ci)),
            ontology,
            request=request, is_obsolete=False, is_root=False, has_children=False,
            lang=lang, resource_kind="terms",
        )
        for ci, e in class_entities
    ]
    return hal_page(items, request, total=len(type_iris), page=page, size=size,
                    embedded_key="terms")


# ---------------------------------------------------------------------------
# Per-ontology: GET /ontologies/{onto}/individuals/{iri_path:path}  (catch-all LAST)
# MUST come after /types route above
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/individuals/{iri_path:path}")
async def get_individual_hal(
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
        raise HTTPException(status_code=404,
                            detail=f"Individual {iri} not found in {ontology_id}")

    return entity_to_v1_term(
        entity, ontology,
        request=request, is_obsolete=False, is_root=False, has_children=False,
        lang=lang, resource_kind="individuals",
    )


# ---------------------------------------------------------------------------
# Global: GET /individuals?iri=...
# MUST be registered BEFORE /individuals/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/individuals")
async def list_individuals_global(
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
                lang=lang, resource_kind="individuals",
            )
        )
    return hal_page(items, request, total=len(items), page=0, size=20,
                    embedded_key="individuals")


# ---------------------------------------------------------------------------
# Global: GET /individuals/{iri_path:path}  (catch-all, last)
# ---------------------------------------------------------------------------

@router.get("/api/individuals/{iri_path:path}")
async def get_individual_global(
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
                lang=lang, resource_kind="individuals",
            )
        )
    if not items:
        raise HTTPException(status_code=404,
                            detail=f"Individual {iri} not found in any ontology")
    return hal_page(items, request, total=len(items), page=0, size=20,
                    embedded_key="individuals")
