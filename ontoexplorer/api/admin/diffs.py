"""Admin diff queue endpoints — single-pair and per-ontology recompute-all."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import User

from ._common import _require_admin

router = APIRouter()


class _DiffQueueBody(BaseModel):
    from_version_id: str
    to_version_id: str


@router.post(
    "/diffs/queue",
    summary="Queue compute_diff for a specific (from, to) version pair",
)
async def admin_queue_diff(
    body: _DiffQueueBody,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Both versions must belong to the same ontology."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs.tasks import compute_diff

    v_from = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == body.from_version_id)
    )).scalar_one_or_none()
    v_to = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == body.to_version_id)
    )).scalar_one_or_none()
    if v_from is None or v_to is None:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    if v_from.ontology_id != v_to.ontology_id:
        raise HTTPException(
            status_code=422,
            detail="Versions belong to different ontologies — use the /compare endpoint",
        )

    task = compute_diff.delay(v_from.id, v_to.id, v_from.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/ontologies/{ontology_id}/diffs/recompute-all",
    summary="Queue compute_diff for every consecutive version pair of an ontology",
)
async def admin_recompute_all_diffs(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.jobs.tasks import compute_diff

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    versions = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .order_by(OntologyVersion.created_at.asc())
    )).scalars().all()

    queued = 0
    for prev, curr in zip(versions, versions[1:]):
        compute_diff.delay(prev.id, curr.id, ontology_id)
        queued += 1

    return {"queued": queued}
