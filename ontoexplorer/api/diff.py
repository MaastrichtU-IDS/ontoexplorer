"""Ontology version diff REST API."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import OntologyDiff, OntologyVersion

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/ontologies", tags=["diff"])


async def _get_version_or_404(
    db: AsyncSession, ontology_id: str, version_id: str
) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(
            OntologyVersion.id == version_id,
            OntologyVersion.ontology_id == ontology_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _diff_response(diff: OntologyDiff) -> dict:
    return {
        "status": diff.status,
        "summary": diff.summary,
        "diff_data": diff.diff_data,
        "narrative": diff.narrative,
    }


async def _get_or_enqueue(
    db: AsyncSession,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
) -> dict | JSONResponse:
    existing = await db.scalar(
        select(OntologyDiff).where(
            OntologyDiff.version_from_id == from_vid,
            OntologyDiff.version_to_id == to_vid,
        )
    )
    if existing:
        if existing.status == "ready":
            return _diff_response(existing)
        return JSONResponse(status_code=202, content={"status": existing.status})

    diff_row = OntologyDiff(
        ontology_id=ontology_id,
        version_from_id=from_vid,
        version_to_id=to_vid,
        status="pending",
    )
    try:
        db.add(diff_row)
        await db.commit()
    except Exception:
        await db.rollback()
        existing = await db.scalar(
            select(OntologyDiff).where(
                OntologyDiff.version_from_id == from_vid,
                OntologyDiff.version_to_id == to_vid,
            )
        )
        return JSONResponse(
            status_code=202,
            content={"status": existing.status if existing else "pending"},
        )

    from ontoexplorer.modules.jobs.tasks import compute_diff as _compute_diff_task
    _compute_diff_task.delay(from_vid, to_vid, ontology_id)
    return JSONResponse(status_code=202, content={"status": "pending"})


@router.get("/{ontology_id}/{version_id}/diff",
            summary="Diff between this version and its predecessor")
async def get_consecutive_diff(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    version = await _get_version_or_404(db, ontology_id, version_id)
    prev = await db.scalar(
        select(OntologyVersion)
        .where(
            OntologyVersion.ontology_id == ontology_id,
            OntologyVersion.id != version_id,
            OntologyVersion.status != "deprecated",
            OntologyVersion.created_at < version.created_at,
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    if not prev:
        raise HTTPException(status_code=404, detail="No previous version found")
    return await _get_or_enqueue(db, ontology_id, str(prev.id), version_id)


@router.get("/{ontology_id}/diff", summary="Diff between any two versions of an ontology")
async def get_arbitrary_diff(
    ontology_id: str,
    from_vid: str = Query(..., alias="from"),
    to_vid: str = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
):
    if from_vid == to_vid:
        raise HTTPException(status_code=400, detail="from and to must be different versions")
    await _get_version_or_404(db, ontology_id, from_vid)
    await _get_version_or_404(db, ontology_id, to_vid)
    return await _get_or_enqueue(db, ontology_id, from_vid, to_vid)


@router.post("/{ontology_id}/diff/compute",
             summary="Trigger async diff computation for an arbitrary version pair")
async def trigger_diff_compute(
    ontology_id: str,
    from_vid: str = Query(..., alias="from"),
    to_vid: str = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
):
    if from_vid == to_vid:
        raise HTTPException(status_code=400, detail="from and to must be different versions")
    await _get_version_or_404(db, ontology_id, from_vid)
    await _get_version_or_404(db, ontology_id, to_vid)
    return await _get_or_enqueue(db, ontology_id, from_vid, to_vid)
