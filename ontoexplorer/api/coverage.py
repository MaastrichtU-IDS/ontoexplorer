"""Coverage endpoints — read-only views over the Redis coverage cache."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.coverage import ENTITY_TYPES, coverage_cache_key
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["coverage"])

_AGGREGATE_FIELDS: tuple[str, ...] = ("total", "with_label", "with_definition", "multilingual")


def _empty_totals() -> dict:
    return {t: {f: 0 for f in _AGGREGATE_FIELDS} for t in ENTITY_TYPES}


@router.get("/ontologies/{ontology_id}/{version_id}/coverage", summary="Per-version coverage metrics")
async def get_version_coverage(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = r.get(coverage_cache_key(version_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Coverage not computed — reindex pending")
    return json.loads(raw)


@router.get("/coverage/public", summary="Fleet coverage rollup (no auth)")
async def get_fleet_coverage(db: AsyncSession = Depends(get_db)):
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    rows = (await db.execute(
        select(OntologyVersion.id, OntologyVersion.ontology_id, Ontology.shortname, Ontology.title)
        .join(subq,
              (OntologyVersion.ontology_id == subq.c.ontology_id)
              & (OntologyVersion.created_at == subq.c.max_created))
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
    )).all()

    r = _get_redis()
    keys = [coverage_cache_key(row.id) for row in rows]
    raws = r.mget(keys) if keys else []

    totals = _empty_totals()
    by_ontology: list[dict] = []
    for row, raw in zip(rows, raws):
        if raw is None:
            continue
        payload = json.loads(raw)
        stripped: dict[str, dict] = {}
        for t in ENTITY_TYPES:
            bucket = payload["by_type"].get(t, {})
            stripped[t] = {f: int(bucket.get(f, 0)) for f in _AGGREGATE_FIELDS}
            for f in _AGGREGATE_FIELDS:
                totals[t][f] += stripped[t][f]
        by_ontology.append({
            "ontology_id": row.ontology_id,
            "version_id":  row.id,
            "shortname":   row.shortname,
            "title":       row.title,
            "indexed_at":  payload.get("indexed_at"),
            "by_type":     stripped,
        })

    return {"totals": totals, "by_ontology": by_ontology}
