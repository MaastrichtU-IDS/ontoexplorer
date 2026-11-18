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
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.fair.fleet import FairScores, aggregate_fair_scores, scores_from_report
from ontoexplorer.modules.fair.precompute import (
    column_values,
    inputs_from_row,
    signal_query,
)
from ontoexplorer.modules.fair.score import compute_fair_report

router = APIRouter(prefix="/api/v1", tags=["fair"])
log = get_logger(__name__)

# Cap the FAIR cache rows written back during a single fleet request's self-heal,
# so a cold cache (e.g. just after the migration, before the backfill) fills
# incrementally over a few requests instead of one giant transaction. The
# aggregate still includes every row — only the write-back is bounded.
_SELFHEAL_WRITE_CAP = 400


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


def _latest_ready_subquery():
    """Latest ready version per ontology (by created_at)."""
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    join_on = (OntologyVersion.ontology_id == subq.c.ontology_id) & (
        OntologyVersion.created_at == subq.c.max_created
    )
    return subq, join_on


@router.get("/fair/fleet", summary="Fleet FAIR rollup (no auth)")
async def get_fleet_fair(db: AsyncSession = Depends(get_db)):
    subq, join_on = _latest_ready_subquery()

    # Phase 1 — read the precomputed FAIR cache (5 floats + a small JSON per row).
    cache_rows = (await db.execute(
        select(
            OntologyVersion.id,
            OntologyVersion.fair_overall, OntologyVersion.fair_f, OntologyVersion.fair_a,
            OntologyVersion.fair_i, OntologyVersion.fair_r, OntologyVersion.fair_checks,
        ).join(subq, join_on)
    )).all()

    scores: list[FairScores] = []
    missing: list[str] = []
    for r in cache_rows:
        if r.fair_overall is None:
            missing.append(r.id)
        else:
            scores.append(FairScores(
                overall=r.fair_overall, f=r.fair_f or 0.0, a=r.fair_a or 0.0,
                i=r.fair_i or 0.0, r=r.fair_r or 0.0, checks=r.fair_checks or {},
            ))

    # Phase 2 — self-heal NULL rows from the durable signals, and persist the cache
    # (best-effort: a write failure must never break the read).
    if missing:
        srows = (await db.execute(signal_query().where(OntologyVersion.id.in_(missing)))).all()
        heal: list[tuple[str, FairScores]] = []
        for sr in srows:
            sc = scores_from_report(compute_fair_report(inputs_from_row(sr)))
            scores.append(sc)
            heal.append((sr.id, sc))
        try:
            for vid, sc in heal[:_SELFHEAL_WRITE_CAP]:
                await db.execute(
                    update(OntologyVersion).where(OntologyVersion.id == vid).values(**column_values(sc))
                )
            await db.commit()
        except Exception:
            await db.rollback()
            log.warning("fair_fleet_selfheal_write_failed", n=len(heal))

    return aggregate_fair_scores(scores)
