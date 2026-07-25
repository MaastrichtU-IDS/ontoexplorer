"""Flush Redis usage counters into usage_daily, and export usage_daily to MinIO.

Absolute-count UPSERT: the flush writes the current Redis totals (not deltas),
so re-running it is idempotent and a worker crash loses nothing — the anti
double-count design. Monthly/weekly/yearly are derived on read from the daily
rows; nothing here aggregates beyond the day grain.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology, UsageDaily


def read_usage_counts(redis_client, day: str) -> dict[tuple[str, str], dict[str, int]]:
    """Parse the `usage:counts:{day}` hash into {(kind, ontology_id): {unique,total}}.

    Fields are `"{kind}:{ontology_id}:{metric}"`; kind and the UUID ontology_id
    contain no ':' so a 3-way split is unambiguous.
    """
    raw = redis_client.hgetall(f"usage:counts:{day}") or {}
    agg: dict[tuple[str, str], dict[str, int]] = {}
    for field, val in raw.items():
        parts = field.split(":")
        if len(parts) != 3:
            continue
        kind, onto, metric = parts
        if metric not in ("unique", "total"):
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        agg.setdefault((kind, onto), {"unique": 0, "total": 0})[metric] = n
    return agg


async def flush_day(db: AsyncSession, redis_client, day: str) -> int:
    """Upsert one UTC day's counts (absolute) into usage_daily. Returns rows written."""
    agg = read_usage_counts(redis_client, day)
    if not agg:
        return 0
    onto_ids = {onto for (_kind, onto) in agg}
    existing = set((await db.execute(
        select(Ontology.id).where(Ontology.id.in_(onto_ids))
    )).scalars().all())

    day_date = datetime.strptime(day, "%Y%m%d").date()
    written = 0
    for (kind, onto), counts in agg.items():
        if onto not in existing:  # ontology deleted since the hit — skip (FK)
            continue
        stmt = pg_insert(UsageDaily).values(
            id=str(uuid.uuid4()),
            ontology_id=onto,
            kind=kind,
            day=day_date,
            unique_count=counts["unique"],
            total_count=counts["total"],
        ).on_conflict_do_update(
            constraint="uq_usage_daily",
            set_={
                "unique_count": counts["unique"],
                "total_count": counts["total"],
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
        written += 1
    await db.commit()
    return written


async def export_usage_daily(db: AsyncSession) -> bytes:
    """Serialize the whole usage_daily table to JSON bytes for a MinIO snapshot."""
    rows = (await db.execute(select(UsageDaily))).scalars().all()
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "count": len(rows),
        "rows": [
            {
                "ontology_id": r.ontology_id,
                "kind": r.kind,
                "day": r.day.isoformat(),
                "unique_count": r.unique_count,
                "total_count": r.total_count,
            }
            for r in rows
        ],
    }
    return json.dumps(payload).encode()
