"""Admin trigger for the gated MOD-API harvest.

A thin endpoint: validate the body and enqueue ``harvest_peer``. All gating
(``harvest_enabled``, politeness, admission) lives in the task/runner. Dry-run by
default so an operator can see what *would* be ingested before enabling a live run.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ontoexplorer.models.db import User

from ._common import _require_admin

router = APIRouter()

MAX_HARVEST_LIMIT = 500


class HarvestRequest(BaseModel):
    peer_id: str | None = None
    limit: int | None = Field(default=None, gt=0, le=MAX_HARVEST_LIMIT)
    dry_run: bool = True


@router.post("/harvest")
async def trigger_harvest(body: HarvestRequest, _: User = Depends(_require_admin)) -> dict:
    from ontoexplorer.modules.jobs.tasks import harvest_peer

    result = harvest_peer.delay(peer_id=body.peer_id, limit=body.limit, dry_run=body.dry_run)
    return {"task_id": result.id, "dry_run": body.dry_run, "peer_id": body.peer_id}
