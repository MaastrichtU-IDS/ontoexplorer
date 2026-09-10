"""Cross-repository entity listing - GET /api/v1/entities."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.modules.search.pg_search import (
    _LISTABLE_TYPES,
    count_entities_by_type,
    decode_entity_cursor,
    list_entities_by_type,
    pg_entity_search,
)

router = APIRouter(prefix="/api/v1", tags=["entities"])

_COUNT_TTL = 300  # seconds


async def _approx_total(db: AsyncSession, entity_type: str, collapse: bool) -> int:
    """Cached count per (type, collapse); direct count when Redis is unavailable."""
    key = f"entities_count:{entity_type}:{int(collapse)}"
    r = None
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        r = _get_redis()
        cached = r.get(key)
        if cached is not None:
            return int(cached)
    except Exception:
        r = None
    total = await count_entities_by_type(db, entity_type, collapse)
    try:
        if r is not None:
            r.setex(key, _COUNT_TTL, total)
    except Exception:
        pass
    return total


def _wrap_search_hit(hit: dict) -> dict:
    """Map a pg_entity_search result to the /entities entity shape."""
    return {
        "iri": hit["iri"], "label": hit["label"], "short": hit["short"],
        "type": hit["type"], "source": hit.get("source") or "",
        "ontologies": [{"ontology_id": hit["ontology_id"], "version_id": hit["version_id"]}],
    }


@router.get("/entities", summary="Cross-repository entity listing / search by type")
async def list_entities(
    type: str = Query(..., description="class | object_property | data_property | annotation_property | individual"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="Opaque pagination cursor from a previous response's `next`"),
    q: str | None = Query(None, description="Search text: exact-match ranked first, then prefix, then fuzzy word-match. Replaces the paged listing."),
    collapse: bool = Query(False, description="Collapse each IRI to one row, aggregating the ontologies that use it."),
    db: AsyncSession = Depends(get_db),
):
    if type not in _LISTABLE_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown entity type: {type}")

    query = (q or "").strip()
    if query:
        # Ranked exact/prefix/fuzzy search (deduped by IRI). Not keyset-paged:
        # returns the top `limit` matches as a single page.
        hits = await pg_entity_search(db, query, limit, types=[type])
        entities = [_wrap_search_hit(h) for h in hits]
        return {"entities": entities, "next": None, "approx_total": len(entities), "limit": limit, "query": query}

    after = None
    if cursor:
        after = decode_entity_cursor(cursor)
        if after is None:
            raise HTTPException(status_code=422, detail="invalid cursor")
    entities, next_cursor = await list_entities_by_type(db, type, limit, after, collapse)
    approx_total = await _approx_total(db, type, collapse)
    return {"entities": entities, "next": next_cursor, "approx_total": approx_total, "limit": limit}
