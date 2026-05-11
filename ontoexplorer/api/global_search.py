"""Global cross-ontology entity search — GET /api/v1/search?q=<query>."""
import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.search.indexer import entity_lookup

router = APIRouter(prefix="/api/v1/search", tags=["global-search"])


@router.get("", summary="Cross-ontology entity prefix search")
async def global_search(
    q: str = Query(..., min_length=1, description="Entity label prefix"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    # Gather all version IDs that are not deprecated
    result = await db.execute(
        select(OntologyVersion.id, OntologyVersion.ontology_id, OntologyVersion.status)
        .where(OntologyVersion.status != "deprecated")
    )
    versions = result.fetchall()

    if not versions:
        return {"results": [], "count": 0, "truncated": False}

    per_version = max(5, limit // max(len(versions), 1))

    async def search_version(vid: str, oid: str) -> list[dict]:
        rows = await asyncio.to_thread(entity_lookup, vid, q, None, per_version)
        for r in rows:
            r["version_id"] = vid
            r["ontology_id"] = oid
        return rows

    nested = await asyncio.gather(
        *[search_version(str(v.id), str(v.ontology_id)) for v in versions]
    )

    seen_iris: set[str] = set()
    merged: list[dict] = []
    for rows in nested:
        for row in rows:
            if row["iri"] not in seen_iris:
                seen_iris.add(row["iri"])
                merged.append(row)
            if len(merged) >= limit:
                break
        if len(merged) >= limit:
            break

    return {"results": merged, "count": len(merged), "truncated": len(merged) >= limit}
