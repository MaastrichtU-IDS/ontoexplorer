"""FAIR assessment endpoints.

A per-ontology FAIR report and a fleet rollup, both derived on read from the
signals already persisted on ``versions.*`` and ``ontology_meta_profiles`` — no
new ingest computation and no new storage. Scores are computed live from those
durable columns (as ``/reuse/fleet`` is), so a version aging past any cache TTL
is never dropped from the rollup.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion
from ontoexplorer.modules.fair.fleet import aggregate_fleet
from ontoexplorer.modules.fair.score import build_fair_inputs, compute_fair_report

router = APIRouter(prefix="/api/v1", tags=["fair"])

_SIGNAL_COLS = (
    OntologyVersion.id,
    OntologyVersion.ontology_id,
    OntologyVersion.version_iri,
    OntologyVersion.license,
    OntologyVersion.license_compliant,
    OntologyVersion.license_raw,
    OntologyVersion.owl_profile,
    OntologyVersion.reuse,
    OntologyVersion.coverage,
    Ontology.iri,
    Ontology.shortname,
    Ontology.groups,
    Ontology.resolvable,
    Ontology.resolve_detail,
    OntologyMetaProfile.resolved,
)


def _inputs_from_row(row):
    return build_fair_inputs(
        ontology_iri=row.iri,
        resolvable=row.resolvable,
        resolve_detail=row.resolve_detail,
        version_iri=row.version_iri,
        shortname=row.shortname,
        groups=row.groups,
        license_raw=row.license_raw,
        license_spdx=row.license,
        license_compliant=row.license_compliant,
        owl_profile=row.owl_profile,
        reuse=row.reuse,
        coverage=row.coverage,
        meta_resolved=row.resolved,
    )


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
    row = (await db.execute(
        select(*_SIGNAL_COLS)
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .outerjoin(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
        .where(OntologyVersion.id == vid)
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    report = compute_fair_report(_inputs_from_row(row))
    out = _report_to_dict(report)
    out["ontology_id"] = ontology_id
    out["version_id"] = str(vid)
    return out


@router.get("/fair/fleet", summary="Fleet FAIR rollup (no auth)")
async def get_fleet_fair(db: AsyncSession = Depends(get_db)):
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
        select(*_SIGNAL_COLS)
        .join(
            subq,
            (OntologyVersion.ontology_id == subq.c.ontology_id)
            & (OntologyVersion.created_at == subq.c.max_created),
        )
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .outerjoin(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
    )).all()
    reports = [compute_fair_report(_inputs_from_row(r)) for r in rows]
    return aggregate_fleet(reports)
