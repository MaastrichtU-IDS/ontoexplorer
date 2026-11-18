"""Pure fleet-level aggregation of per-version FAIR scores.

I/O-free so it is unit-testable. The endpoint loads the precomputed
``versions.fair_*`` cache (self-healing any NULL rows from the durable signal
columns) and hands the scores here, which produce the overall-score histogram,
per-principle mean + standard deviation, the overall mean + standard deviation,
and per-check pass rates. Aggregating the cached scores (not ~1,900 live
``compute_fair_report`` calls) is what makes the fleet rollup fast, and the same
function powers the fairness-over-time snapshots.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

_BUCKETS = ("<50", "50-69", "70-84", "85-100")


def _bucket(pct: float) -> str:
    if pct < 50:
        return "<50"
    if pct < 70:
        return "50-69"
    if pct < 85:
        return "70-84"
    return "85-100"


@dataclass
class FairScores:
    """One version's cached FAIR scores: the four principle sub-scores + overall
    (each a 0..1 fraction) and ``checks`` = {check_id: score} for the 19 checks."""
    overall: float
    f: float
    a: float
    i: float
    r: float
    checks: dict[str, float] = field(default_factory=dict)


def scores_from_report(report) -> FairScores:
    """Extract the cacheable scores from a freshly computed FairReport."""
    sub = {p.principle: p.score for p in report.principles}
    checks = {c.id: c.score for p in report.principles for c in p.checks}
    return FairScores(
        overall=report.overall,
        f=sub.get("F", 0.0), a=sub.get("A", 0.0),
        i=sub.get("I", 0.0), r=sub.get("R", 0.0),
        checks=checks,
    )


@lru_cache(maxsize=1)
def _check_meta() -> dict[str, tuple[str, str]]:
    """{check_id: (principle, name)} for the 19 checks, derived once from an
    empty report so the names stay defined only in score.py."""
    from ontoexplorer.modules.fair.score import FairInputs, compute_fair_report
    rep = compute_fair_report(FairInputs())
    return {c.id: (c.principle, c.name) for p in rep.principles for c in p.checks}


def _mean_std(vals: list[float], denom: int) -> tuple[float, float]:
    mean = sum(vals) / denom
    var = sum((v - mean) ** 2 for v in vals) / denom  # population variance
    return round(mean, 4), round(math.sqrt(var), 4)


def aggregate_fair_scores(scores: list[FairScores]) -> dict:
    """Overall histogram, per-principle + overall mean/stddev, per-check pass rate."""
    n = len(scores)
    denom = n or 1

    hist = {b: 0 for b in _BUCKETS}
    for s in scores:
        hist[_bucket(s.overall * 100)] += 1

    overalls = [s.overall for s in scores]
    overall_mean, overall_std = _mean_std(overalls, denom)
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for key, attr in (("F", "f"), ("A", "a"), ("I", "i"), ("R", "r")):
        means[key], stds[key] = _mean_std([getattr(s, attr) for s in scores], denom)

    meta = _check_meta()
    csum: dict[str, float] = {}
    for s in scores:
        for cid, score in (s.checks or {}).items():
            csum[cid] = csum.get(cid, 0.0) + score

    return {
        "n": n,
        "overall_mean": overall_mean,
        "overall_stddev": overall_std,
        "overall_histogram": [{"bucket": b, "count": hist[b]} for b in _BUCKETS],
        "principle_means": means,
        "principle_stddevs": stds,
        "check_pass_rate": [
            {"id": cid, "principle": meta.get(cid, ("", ""))[0],
             "name": meta.get(cid, ("", ""))[1], "rate": round(csum[cid] / denom, 4)}
            for cid in sorted(csum)
        ],
    }
