"""Cross-ontology comparison REST API."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import OntologyComparison, OntologyVersion

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/compare", tags=["compare"])


async def _get_version_or_404(db: AsyncSession, version_id: str) -> OntologyVersion:
    version = await db.scalar(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )
    if version is None:
        raise HTTPException(status_code=404, detail=f"Version {version_id} not found")
    return version


def _comparison_response(row: OntologyComparison) -> dict:
    return {
        "status": row.status,
        "summary": row.summary,
        "diff_data": row.diff_data,
        "from_ontology_id": row.from_ontology_id,
        "to_ontology_id": row.to_ontology_id,
        "version_from_id": row.version_from_id,
        "version_to_id": row.version_to_id,
    }


@router.get("", summary="Get a cross-ontology comparison result")
async def get_comparison(
    from_version_id: str = Query(..., description="Version ID for the 'from' side"),
    to_version_id: str = Query(..., description="Version ID for the 'to' side"),
    db: AsyncSession = Depends(get_db),
):
    if from_version_id == to_version_id:
        raise HTTPException(
            status_code=400,
            detail="from_version_id and to_version_id must differ",
        )
    row = await db.scalar(
        select(OntologyComparison).where(
            OntologyComparison.version_from_id == from_version_id,
            OntologyComparison.version_to_id == to_version_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Comparison not yet requested")
    if row.status == "ready":
        return _comparison_response(row)
    return JSONResponse(status_code=202, content={"status": row.status})


@router.post("/compute", summary="Trigger compute for a cross-ontology comparison")
async def trigger_compute(
    from_version_id: str = Query(...),
    to_version_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if from_version_id == to_version_id:
        raise HTTPException(
            status_code=400,
            detail="from_version_id and to_version_id must differ",
        )
    await _get_version_or_404(db, from_version_id)
    await _get_version_or_404(db, to_version_id)

    existing = await db.scalar(
        select(OntologyComparison).where(
            OntologyComparison.version_from_id == from_version_id,
            OntologyComparison.version_to_id == to_version_id,
        )
    )
    if existing and existing.status != "failed":
        # Already computed (ready) or in-flight (pending) — idempotent.
        return JSONResponse(status_code=202, content={"status": existing.status})

    if existing and existing.status == "failed":
        # Retry: reset to pending and clear stale data so the worker
        # re-runs cleanly.
        existing.status = "pending"
        existing.summary = None
        existing.diff_data = None
        await db.commit()

    elif existing is None:
        # Claim the work by inserting the pending row BEFORE dispatching, the way
        # diff.py does. Previously the row was created by the worker, so nothing
        # here was idempotent: this endpoint has no auth dependency, and N
        # concurrent requests for the same pair queued N comparison tasks onto a
        # single-concurrency worker. The unique constraint collapses the race.
        row = OntologyComparison(
            version_from_id=from_version_id,
            version_to_id=to_version_id,
            status="pending",
        )
        try:
            db.add(row)
            await db.commit()
        except Exception:
            await db.rollback()
            return JSONResponse(status_code=202, content={"status": "pending"})

    from ontoexplorer.modules.jobs.tasks import compute_ontology_comparison
    compute_ontology_comparison.delay(from_version_id, to_version_id)
    return JSONResponse(status_code=202, content={"status": "pending"})
