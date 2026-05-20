"""Reuse-analysis endpoints — read-only views over the Redis reuse cache."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.reuse.cache import reuse_cache_key
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["reuse"])


@router.get(
    "/ontologies/{ontology_id}/{version_id}/reuse",
    summary="Per-version reuse report",
)
async def get_version_reuse(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, reuse_cache_key(version_id))
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Reuse report not computed — reindex pending",
        )
    return json.loads(raw)


@router.get("/reuse/fleet", summary="Fleet reuse rollup (no auth)")
async def get_fleet_reuse(db: AsyncSession = Depends(get_db)):
    """Aggregate per-ontology reuse reports across the fleet.

    Mirrors the `/owl-profile/public` fleet rollup pattern: subquery for the
    latest ready version per ontology, mget the reuse cache payloads, then
    compute summary counts.
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
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )
    ).all()

    r = _get_redis()
    keys = [reuse_cache_key(str(row.id)) for row in rows]
    payloads = await asyncio.to_thread(r.mget, keys) if keys else []

    ontologies: list[dict] = []
    totals = {
        "fleet_size": 0,
        "total_import_edges": 0,
        "total_mireot_terms": 0,
        "ontologies_with_mireot": 0,
    }
    source_prefix_uses: dict[str, int] = {}

    for row, raw in zip(rows, payloads):
        if not raw:
            continue
        data = json.loads(raw)
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
            select(OntologyVersion.id, OntologyVersion.ontology_id)
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
        )
    ).all()
    if not version_rows:
        return set()

    r = _get_redis()
    keys = [reuse_cache_key(str(vr.id)) for vr in version_rows]
    raws = await asyncio.to_thread(r.mget, keys)

    matching: set[str] = set()
    for vr, raw in zip(version_rows, raws):
        if not raw:
            continue
        data = json.loads(raw)
        if target_prefix in data.get("term_iri_reuse", {}):
            matching.add(vr.ontology_id)
        else:
            for edge in data.get("imports", []):
                if edge.get("target_prefix") == target_prefix:
                    matching.add(vr.ontology_id)
                    break
    return matching
