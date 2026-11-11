"""Reuse-analysis endpoints — durable per-version reuse report on the version row.

The reuse report is materialized on ``versions.reuse`` at index time. These
endpoints read that row; Redis remains a hot-cache fallback for versions
re-indexed before the column was backfilled, and the per-version endpoint
self-heals by recomputing from entity_index + the store. The report used to live
only in a 30-day-TTL Redis cache, so the fleet rollup and the reuse catalogue
filter silently dropped every version indexed > 30 days ago.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.reuse.cache import reuse_cache_key
from ontoexplorer.modules.reuse.compute import compute_reuse_payload
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["reuse"])


@router.get(
    "/ontologies/{ontology_id}/{version_id}/reuse",
    summary="Per-version reuse report",
)
async def get_version_reuse(
    ontology_id: str, version_id: str, db: AsyncSession = Depends(get_db)
):
    row = (await db.execute(
        select(OntologyVersion.reuse).where(OntologyVersion.id == version_id)
    )).first()

    # 1) Durable row.
    if row is not None and isinstance(row.reuse, dict):
        return row.reuse

    # 2) Redis hot cache (re-indexed before the column was backfilled).
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, reuse_cache_key(version_id))
    if raw is not None:
        return json.loads(raw)

    # 3) Self-heal: recompute from entity_index + the store and persist. 404 only
    #    when the version is gone.
    try:
        payload = await compute_reuse_payload(db, version_id, ontology_id)
    except Exception as exc:  # noqa: BLE001 — degrade to the historical 404
        raise HTTPException(
            status_code=404, detail="Reuse report not computed — reindex pending") from exc
    if payload is None:
        raise HTTPException(
            status_code=404, detail="Reuse report not computed — reindex pending")
    try:
        await db.execute(
            update(OntologyVersion).where(OntologyVersion.id == version_id).values(
                reuse=payload))
        await db.commit()
    except Exception:
        await db.rollback()
    return payload


@router.get("/reuse/fleet", summary="Fleet reuse rollup (no auth)")
async def get_fleet_reuse(db: AsyncSession = Depends(get_db)):
    """Aggregate per-ontology reuse reports across the fleet.

    Subquery for the latest ready version per ontology, read the durable reuse
    column (Redis fallback for not-yet-backfilled rows), then compute summary
    counts.
    """
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                OntologyVersion.id,
                OntologyVersion.ontology_id,
                Ontology.shortname,
                Ontology.title,
                OntologyVersion.reuse,
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )
    ).all()

    missing = [row.id for row in rows if not isinstance(row.reuse, dict)]
    redis_fallback: dict[str, dict] = {}
    if missing:
        r = _get_redis()
        raws = await asyncio.to_thread(r.mget, [reuse_cache_key(i) for i in missing])
        redis_fallback = {i: json.loads(raw) for i, raw in zip(missing, raws) if raw is not None}

    ontologies: list[dict] = []
    totals = {
        "fleet_size": 0,
        "total_import_edges": 0,
        "total_mireot_terms": 0,
        "ontologies_with_mireot": 0,
    }
    source_prefix_uses: dict[str, int] = {}

    for row in rows:
        data = row.reuse if isinstance(row.reuse, dict) else redis_fallback.get(row.id)
        if data is None:
            continue
        totals["fleet_size"] += 1
        totals["total_import_edges"] += len(data.get("imports", []))
        mireot_count = len(data.get("mireot_terms", []))
        totals["total_mireot_terms"] += mireot_count
        if mireot_count > 0:
            totals["ontologies_with_mireot"] += 1
        for prefix in data.get("term_iri_reuse", {}):
            source_prefix_uses[prefix] = source_prefix_uses.get(prefix, 0) + 1
        ontologies.append({
            "id": row.ontology_id,
            "shortname": row.shortname,
            "title": row.title,
            "version_id": str(row.id),
            "imports_count": len(data.get("imports", [])),
            "mireot_terms_count": mireot_count,
            "term_iri_reused_count": sum(
                e["class_count"] + e["property_count"]
                for e in data.get("term_iri_reuse", {}).values()
            ),
            "mappings_count": sum(
                len(v) for v in data.get("mappings", {}).values()
            ),
            "source_prefixes": list(data.get("term_iri_reuse", {}).keys()),
        })

    top_sources = sorted(source_prefix_uses.items(), key=lambda x: -x[1])[:10]

    return {
        "ontologies": ontologies,
        "totals": totals,
        "top_reused_sources": [
            {"prefix": p, "reusers_count": n} for p, n in top_sources
        ],
    }


async def filter_ontology_ids_by_reuse(
    db: AsyncSession,
    ontology_ids: list[str],
    target_prefix: str,
) -> set[str]:
    """Subset of ontology_ids whose latest ready version reuses target_prefix."""
    if not ontology_ids:
        return set()

    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(
            OntologyVersion.ontology_id.in_(ontology_ids),
            OntologyVersion.status == "ready",
        )
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    version_rows = (
        await db.execute(
            select(
                OntologyVersion.id,
                OntologyVersion.ontology_id,
                OntologyVersion.reuse,
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
        )
    ).all()
    if not version_rows:
        return set()

    missing = [vr.id for vr in version_rows if not isinstance(vr.reuse, dict)]
    redis_fallback: dict[str, dict] = {}
    if missing:
        r = _get_redis()
        raws = await asyncio.to_thread(r.mget, [reuse_cache_key(str(i)) for i in missing])
        redis_fallback = {i: json.loads(raw) for i, raw in zip(missing, raws) if raw is not None}

    matching: set[str] = set()
    for vr in version_rows:
        data = vr.reuse if isinstance(vr.reuse, dict) else redis_fallback.get(vr.id)
        if data is None:
            continue
        if target_prefix in data.get("term_iri_reuse", {}):
            matching.add(vr.ontology_id)
        else:
            for edge in data.get("imports", []):
                if edge.get("target_prefix") == target_prefix:
                    matching.add(vr.ontology_id)
                    break
    return matching
