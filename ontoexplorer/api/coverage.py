"""Coverage endpoints — durable per-version coverage on the version row.

Coverage is materialized on ``versions.coverage`` at index time (recomputed from
entity_index). These endpoints read that row; Redis remains a hot-cache fallback,
and a version with neither self-heals by recomputing from entity_index. Coverage
used to live only in a 30-day-TTL Redis cache, so the rollup silently dropped
every version indexed > 30 days ago.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.coverage import (
    ENTITY_TYPES,
    compute_coverage_from_index,
    coverage_cache_key,
)
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["coverage"])

_AGGREGATE_FIELDS: tuple[str, ...] = ("total", "with_label", "with_definition", "multilingual")


def _empty_totals() -> dict:
    return {t: {f: 0 for f in _AGGREGATE_FIELDS} for t in ENTITY_TYPES}


@router.get("/ontologies/{ontology_id}/{version_id}/coverage", summary="Per-version coverage metrics")
async def get_version_coverage(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(OntologyVersion.coverage, OntologyVersion.indexed_at).where(
            OntologyVersion.id == version_id,
            OntologyVersion.ontology_id == ontology_id,
        )
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")

    # 1) Durable row.
    if isinstance(row.coverage, dict):
        return row.coverage

    # 2) Redis hot cache (a version re-indexed before the column was backfilled).
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, coverage_cache_key(version_id))
    if raw is not None:
        return json.loads(raw)

    # 3) Self-heal: recompute from entity_index and persist. 404 only when the
    #    version has no indexed entities at all (nothing to cover yet).
    try:
        indexed_at = row.indexed_at.isoformat() if row.indexed_at is not None else None
        payload = await compute_coverage_from_index(db, version_id, indexed_at)
    except Exception as exc:  # noqa: BLE001 — degrade to the historical 404
        raise HTTPException(
            status_code=404, detail="Coverage not computed — reindex pending") from exc
    if not any(payload["by_type"][t]["total"] for t in ENTITY_TYPES):
        raise HTTPException(status_code=404, detail="Coverage not computed — reindex pending")
    try:
        await db.execute(
            update(OntologyVersion).where(OntologyVersion.id == version_id).values(coverage=payload))
        await db.commit()
    except Exception:
        await db.rollback()
    return payload


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
        select(
            OntologyVersion.id, OntologyVersion.ontology_id,
            Ontology.shortname, Ontology.title, OntologyVersion.coverage,
        )
        .join(subq,
              (OntologyVersion.ontology_id == subq.c.ontology_id)
              & (OntologyVersion.created_at == subq.c.max_created))
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
    )).all()

    # Durable source = the row's coverage column. Redis is a fallback only for
    # versions not yet backfilled (indexed before the column existed).
    missing = [row.id for row in rows if not isinstance(row.coverage, dict)]
    redis_fallback: dict[str, dict] = {}
    if missing:
        r = _get_redis()
        raws = await asyncio.to_thread(r.mget, [coverage_cache_key(i) for i in missing])
        redis_fallback = {i: json.loads(raw) for i, raw in zip(missing, raws) if raw is not None}

    totals = _empty_totals()
    by_ontology: list[dict] = []
    for row in rows:
        payload = row.coverage if isinstance(row.coverage, dict) else redis_fallback.get(row.id)
        if payload is None:
            continue
        by_type = payload.get("by_type", {})
        stripped: dict[str, dict] = {}
        for t in ENTITY_TYPES:
            bucket = by_type.get(t, {})
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
