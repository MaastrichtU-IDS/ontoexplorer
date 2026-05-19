"""Celery worker introspection and task revocation."""
from __future__ import annotations

import asyncio

import redis as redis_sync
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import User

from ._common import _require_admin

router = APIRouter()


@router.get("/workers", summary="List active, reserved, and pending Celery tasks")
async def admin_workers(_: User = Depends(_require_admin)):
    """Return all tasks: actively running, prefetched by a worker, or waiting in the Redis queue.

    Uses a 2-second inspect timeout for the worker side.
    Pending tasks are read directly from Redis so they appear even before a worker picks them up.
    """
    import base64
    import json as _json
    from ontoexplorer.modules.jobs.tasks import celery_app

    def _inspect():
        inspector = celery_app.control.inspect(timeout=2.0)
        return inspector.active() or {}, inspector.reserved() or {}

    def _read_queue() -> list[dict]:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        raw_messages = r.lrange("celery", 0, -1)
        result = []
        for msg_str in raw_messages:
            try:
                msg = _json.loads(msg_str)
                body = _json.loads(base64.b64decode(msg["body"]).decode("utf-8"))
                args = body[0] if len(body) > 0 else []
                kwargs = body[1] if len(body) > 1 else {}
                # Promote positional version_id (args[0]) into kwargs so the
                # frontend versionMap lookup works regardless of dispatch style.
                if "version_id" not in kwargs and args:
                    kwargs = dict(kwargs, version_id=args[0])
                headers = msg.get("headers", {})
                task_id = headers.get("id") or msg.get("properties", {}).get("correlation_id", "")
                task_name = headers.get("task", "")
                result.append({
                    "id": task_id,
                    "name": task_name,
                    "state": "pending",
                    "kwargs": kwargs,
                    "time_start": None,
                    "worker": "queue",
                })
            except Exception:
                continue
        return result

    (active, reserved), pending = await asyncio.gather(
        asyncio.to_thread(_inspect),
        asyncio.to_thread(_read_queue),
    )

    seen_ids: set[str] = set()
    tasks = []

    for worker, task_list in active.items():
        for t in (task_list or []):
            seen_ids.add(t["id"])
            tasks.append({
                "id": t["id"],
                "name": t["name"],
                "state": "active",
                "kwargs": t.get("kwargs", {}),
                "time_start": t.get("time_start"),
                "worker": worker,
            })
    for worker, task_list in reserved.items():
        for t in (task_list or []):
            seen_ids.add(t["id"])
            tasks.append({
                "id": t["id"],
                "name": t["name"],
                "state": "reserved",
                "kwargs": t.get("kwargs", {}),
                "time_start": None,
                "worker": worker,
            })
    for t in pending:
        if t["id"] not in seen_ids:
            tasks.append(t)

    return {"tasks": tasks}


@router.delete("/workers/{task_id}", summary="Revoke (cancel) a Celery task")
async def admin_revoke_worker(
    task_id: str,
    version_id: str | None = None,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a Celery task and mark its DB job record as cancelled.

    ``version_id`` is optional but should be passed when known so the running
    job record is cleaned up immediately (SIGTERM kills the process before its
    own except-block can call mark_failed).
    """
    from datetime import datetime, timezone
    from ontoexplorer.modules.jobs.tasks import celery_app

    await asyncio.to_thread(
        lambda: celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
    )

    if version_id:
        await db.execute(
            text("""
                UPDATE jobs
                SET status = 'failed', finished_at = :now, error = 'Cancelled by admin'
                WHERE version_id = :vid AND status = 'running'
            """),
            {"vid": version_id, "now": datetime.now(timezone.utc)},
        )
        await db.commit()

    return {"status": "revoked", "task_id": task_id}
