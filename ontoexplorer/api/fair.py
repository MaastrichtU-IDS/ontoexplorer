"""FAIR assessment endpoints.

A per-ontology FAIR report and a fleet rollup. Per-version scores are a derived
cache on ``versions.fair_*`` (filled at index time from the durable signals, and
self-healed here on read when NULL), so the fleet rollup aggregates column reads
instead of recomputing ~1,900 reports per request. The signals themselves
(owl_profile/reuse/coverage/license*/meta profile) remain the source of truth, so
a version aging past any cache TTL is never dropped.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.fair.fleet import aggregate_fair_scores
from ontoexplorer.modules.fair.precompute import inputs_from_row, load_fleet_scores, signal_query
from ontoexplorer.modules.fair.score import compute_fair_report

router = APIRouter(prefix="/api/v1", tags=["fair"])


def _report_to_dict(report) -> dict:
    d = asdict(report)
    d["overall_pct"] = round(report.overall * 100)
    for p in d["principles"]:
        p["score_pct"] = round(p["score"] * 100)
        for c in p["checks"]:
            c["score_pct"] = round(c["score"] * 100)
    return d


async def _resolve_version_id(db: AsyncSession, ontology_id: str, version_id: str | None) -> str | None:
    if version_id:
        return version_id
    vid = await db.scalar(
        select(OntologyVersion.id)
        .where(OntologyVersion.ontology_id == ontology_id, OntologyVersion.status == "ready")
        .order_by(OntologyVersion.created_at.desc()).limit(1)
    )
    if vid:
        return vid
    vid = await db.scalar(select(Ontology.current_version_id).where(Ontology.id == ontology_id))
    if vid:
        return vid
    return await db.scalar(
        select(OntologyVersion.id)
        .where(OntologyVersion.ontology_id == ontology_id)
        .order_by(OntologyVersion.created_at.desc()).limit(1)
    )


@router.get("/ontologies/{ontology_id}/fair", summary="Per-ontology FAIR report")
async def get_fair_report(
    ontology_id: str,
    version_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    vid = await _resolve_version_id(db, ontology_id, version_id)
    if not vid:
        raise HTTPException(status_code=404, detail="No version to assess")
    row = (await db.execute(signal_query().where(OntologyVersion.id == vid))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    report = compute_fair_report(inputs_from_row(row))
    out = _report_to_dict(report)
    out["ontology_id"] = ontology_id
    out["version_id"] = str(vid)
    return out


@router.get("/fair/fleet", summary="Fleet FAIR rollup (no auth)")
async def get_fleet_fair(db: AsyncSession = Depends(get_db)):
    return aggregate_fair_scores(await load_fleet_scores(db))


@router.get("/fair/fleet/history", summary="Fleet FAIR over time (no auth)")
async def get_fleet_fair_history(
    days: int = Query(365, ge=1, le=1825, description="How many days of history"),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.fair.snapshot import fair_history
    return {"series": await fair_history(db, days)}
