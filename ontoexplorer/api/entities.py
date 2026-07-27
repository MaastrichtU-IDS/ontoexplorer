"""Cross-repository entity listing - GET /api/v1/entities."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.modules.search.pg_search import (
    _LISTABLE_TYPES,
    count_entities_by_type,
    decode_entity_cursor,
    list_entities_by_type,
)

router = APIRouter(prefix="/api/v1", tags=["entities"])

_COUNT_TTL = 300  # seconds


async def _approx_total(db: AsyncSession, entity_type: str) -> int:
    """Cached COUNT(*) per type; direct count when Redis is unavailable."""
    key = f"entities_count:{entity_type}"
    r = None
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        r = _get_redis()
        cached = r.get(key)
        if cached is not None:
            return int(cached)
    except Exception:
        r = None
    total = await count_entities_by_type(db, entity_type)
    try:
        if r is not None:
            r.setex(key, _COUNT_TTL, total)
    except Exception:
        pass
    return total


@router.get("/entities", summary="Cross-repository keyset-paginated entity listing by type")
async def list_entities(
    type: str = Query(..., description="class | object_property | data_property | annotation_property | individual"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="Opaque pagination cursor from a previous response's `next`"),
    db: AsyncSession = Depends(get_db),
):
    if type not in _LISTABLE_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown entity type: {type}")
    after = None
    if cursor:
        after = decode_entity_cursor(cursor)
        if after is None:
            raise HTTPException(status_code=422, detail="invalid cursor")
    entities, next_cursor = await list_entities_by_type(db, type, limit, after)
    approx_total = await _approx_total(db, type)
    return {"entities": entities, "next": next_cursor, "approx_total": approx_total, "limit": limit}
