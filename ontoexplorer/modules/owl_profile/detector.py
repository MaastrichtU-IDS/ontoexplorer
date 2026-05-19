"""OWL 2 profile detector aggregator.

Runs all four OWL 2 profile checks (EL, RL, QL, DL) against a Pyoxigraph store
and returns the cache payload ready for Redis serialisation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pyoxigraph

from ontoexplorer.modules.owl_profile.patterns import (
    make_el_patterns,
    make_rl_patterns,
    make_ql_patterns,
    run_pattern_count,
)
from ontoexplorer.modules.owl_profile.structural import detect_dl_violations

_SAMPLE_CAP = 50


def _run_profile_patterns(
    store: pyoxigraph.Store,
    graph_iri: str | None,
    patterns,
) -> dict:
    """Run a list of patterns and aggregate into the profile result dict."""
    violations_by_axiom_type: dict[str, int] = {}
    sample_violations: list[dict] = []
    total_violations = 0

    for pat in patterns:
        count, samples = run_pattern_count(store, graph_iri, pat)
        if count > 0:
            violations_by_axiom_type[pat.axiom_type] = (
                violations_by_axiom_type.get(pat.axiom_type, 0) + count
            )
            total_violations += count
            for s in samples:
                sample_violations.append({
                    "axiom_type": pat.axiom_type,
                    "subject_iri": s["subject_iri"],
                })

    # Cap samples at 50 across all patterns
    sample_violations = sample_violations[:_SAMPLE_CAP]

    return {
        "in_profile": total_violations == 0,
        "total_violations": total_violations,
        "violations_by_axiom_type": violations_by_axiom_type,
        "sample_violations": sample_violations,
    }


def _run_dl_checks(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> dict:
    """Run DL structural checks and return the profile result dict."""
    violations = detect_dl_violations(store, graph_iri)

    violations_by_axiom_type: dict[str, int] = defaultdict(int)
    sample_violations: list[dict] = []

    for v in violations:
        violations_by_axiom_type[v.axiom_type] += 1
        if len(sample_violations) < _SAMPLE_CAP:
            sample_violations.append({
                "axiom_type": v.axiom_type,
                "subject_iri": v.subject_iri,
                "details": v.details,
            })

    total_violations = sum(violations_by_axiom_type.values())

    return {
        "in_profile": total_violations == 0,
        "total_violations": total_violations,
        "violations_by_axiom_type": dict(violations_by_axiom_type),
        "sample_violations": sample_violations,
    }


def detect_profiles(
    store: pyoxigraph.Store,
    graph_iri: str | None,
    ontology_id: str,
    version_id: str,
) -> dict:
    """Run all OWL 2 profile checks. Returns the cache payload.

    The graph_iri parameter is used by the pattern factories to wrap queries
    in a GRAPH clause when the data lives in a named graph (production); pass
    None to query the default graph (unit tests).
    """
    el_result = _run_profile_patterns(store, graph_iri, make_el_patterns(graph_iri))
    rl_result = _run_profile_patterns(store, graph_iri, make_rl_patterns(graph_iri))
    ql_result = _run_profile_patterns(store, graph_iri, make_ql_patterns(graph_iri))
    dl_result = _run_dl_checks(store, graph_iri)

    return {
        "el": el_result,
        "rl": rl_result,
        "ql": ql_result,
        "dl": dl_result,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
