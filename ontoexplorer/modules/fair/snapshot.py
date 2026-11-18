"""Daily fleet-wide FAIR snapshot — the data behind fairness-over-time.

``capture_fair_snapshot`` runs once per UTC day from the beat task, computing the
same aggregate ``/fair/fleet`` serves and upserting one ``fair_snapshots`` row.
``fair_history`` reads the series back for the trend chart.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import FairSnapshot
from ontoexplorer.modules.fair.fleet import aggregate_fair_scores
from ontoexplorer.modules.fair.precompute import load_fleet_scores

# Aggregate keys kept in the snapshot's JSON (the scalars are columns).
_DATA_KEYS = ("principle_means", "principle_stddevs", "overall_histogram", "check_pass_rate")


async def capture_fair_snapshot(db: AsyncSession) -> dict:
    """Compute today's fleet FAIR aggregate and upsert one row for the UTC day.
    Idempotent: a second run on the same day overwrites that day's row."""
    agg = aggregate_fair_scores(await load_fleet_scores(db))
    day = datetime.now(timezone.utc).date()
    data = {k: agg[k] for k in _DATA_KEYS}
    row = (await db.execute(select(FairSnapshot).where(FairSnapshot.day == day))).scalar_one_or_none()
    if row is None:
        db.add(FairSnapshot(
            day=day, n=agg["n"], overall_mean=agg["overall_mean"],
            overall_stddev=agg["overall_stddev"], data=data,
        ))
    else:
        row.n = agg["n"]
        row.overall_mean = agg["overall_mean"]
        row.overall_stddev = agg["overall_stddev"]
        row.data = data
    await db.commit()
    return {
        "day": day.isoformat(), "n": agg["n"],
        "overall_mean": agg["overall_mean"], "overall_stddev": agg["overall_stddev"],
    }


async def fair_history(db: AsyncSession, days: int = 365) -> list[dict]:
    """The fairness-over-time series (oldest first) over the last ``days`` days."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    rows = (await db.execute(
        select(FairSnapshot).where(FairSnapshot.day >= cutoff).order_by(FairSnapshot.day.asc())
    )).scalars().all()
    series = []
    for s in rows:
        d = s.data or {}
        series.append({
            "day": s.day.isoformat(),
            "n": s.n,
            "overall_mean": s.overall_mean,
            "overall_stddev": s.overall_stddev,
            "principle_means": d.get("principle_means", {}),
            "principle_stddevs": d.get("principle_stddevs", {}),
        })
    return series
