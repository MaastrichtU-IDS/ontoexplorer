"""Pure fleet-level aggregation of per-version FAIR reports.

Kept I/O-free so it is unit-testable; the endpoint loads the durable
``versions.*`` columns, scores each version with :func:`compute_fair_report`,
and hands the list here. Computed live from durable columns (like
``/reuse/fleet``) so aged versions are never silently dropped.
"""
from __future__ import annotations

from ontoexplorer.modules.fair.score import FairReport

_BUCKETS = ("<50", "50-69", "70-84", "85-100")


def _bucket(pct: float) -> str:
    if pct < 50:
        return "<50"
    if pct < 70:
        return "50-69"
    if pct < 85:
        return "70-84"
    return "85-100"


def aggregate_fleet(reports: list[FairReport]) -> dict:
    """Overall-score histogram, per-principle means, and per-check pass rate."""
    n = len(reports)
    hist = {b: 0 for b in _BUCKETS}
    psum = {"F": 0.0, "A": 0.0, "I": 0.0, "R": 0.0}
    csum: dict[str, float] = {}
    cname: dict[str, str] = {}
    cprin: dict[str, str] = {}

    for r in reports:
        hist[_bucket(r.overall * 100)] += 1
        for p in r.principles:
            psum[p.principle] += p.score
            for c in p.checks:
                csum[c.id] = csum.get(c.id, 0.0) + c.score
                cname[c.id] = c.name
                cprin[c.id] = c.principle

    denom = n or 1
    return {
        "n": n,
        "overall_histogram": [{"bucket": b, "count": hist[b]} for b in _BUCKETS],
        "principle_means": {k: round(v / denom, 4) for k, v in psum.items()},
        "check_pass_rate": [
            {"id": cid, "principle": cprin[cid], "name": cname[cid],
             "rate": round(csum[cid] / denom, 4)}
            for cid in sorted(csum)
        ],
    }
