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

# Bounded so one triggered run finishes within harvest_peer's 900s time_limit:
# discover() does all page + per-artefact distribution fetches (each spaced by the
# politeness floor, default 1s) BEFORE any enqueue, so an over-large limit would be
# killed mid-discovery having ingested nothing. 200 fetches stay well under 900s;
# the default run (harvest_max_candidates=50) is ~1 min. Raise the floor/interval
# together if this ceiling ever needs to grow.
MAX_HARVEST_LIMIT = 200


class HarvestRequest(BaseModel):
    peer_id: str | None = None
    limit: int | None = Field(default=None, gt=0, le=MAX_HARVEST_LIMIT)
    dry_run: bool = True


@router.post("/harvest")
async def trigger_harvest(body: HarvestRequest, _: User = Depends(_require_admin)) -> dict:
    from ontoexplorer.modules.jobs.tasks import harvest_peer

    result = harvest_peer.delay(peer_id=body.peer_id, limit=body.limit, dry_run=body.dry_run)
    return {"task_id": result.id, "dry_run": body.dry_run, "peer_id": body.peer_id}
