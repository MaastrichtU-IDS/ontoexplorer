"""OWL 2 profile detector aggregator.

Runs all four OWL 2 profile checks (EL, RL, QL, DL) against a Pyoxigraph store
and returns the cache payload ready for Redis serialisation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pyoxigraph as ox

from ontoexplorer.modules.owl_profile.patterns import (
    make_el_patterns,
    make_rl_patterns,
    make_ql_patterns,
    run_pattern_count,
)
from ontoexplorer.modules.owl_profile.structural import detect_dl_violations_with_terms
from ontoexplorer.modules.diff.manchester import (
    render_axiom,
    render_class_expression,
    _known_iris,
)

_SAMPLE_CAP = 50

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_OWL = "http://www.w3.org/2002/07/owl#"


def _build_render_context(
    store: ox.Store,
    graph_iri: str | None,
) -> tuple[ox.NamedNode | None, frozenset[str], dict[str, str]]:
    """Build graph node, known_iris, and labels for Manchester rendering.

    Returns (graph_node, known_iris, labels).
    graph_node is None when graph_iri is None (default graph); in this case
    rendering is still attempted using ox.DefaultGraph().
    """
    if graph_iri:
        graph_node: ox.NamedNode | None = ox.NamedNode(graph_iri)
    else:
        graph_node = None
    # _known_iris requires a NamedNode or DefaultGraph — use DefaultGraph for default graph
    effective_graph = graph_node if graph_node is not None else ox.DefaultGraph()
    known = _known_iris(store, effective_graph)
    labels: dict[str, str] = {}
    return graph_node, known, labels


def _render_sample(
    store: ox.Store,
    graph_node: ox.NamedNode | None,
    known_iris: frozenset[str],
    labels: dict[str, str],
    subject_iri: str,
    predicate_iri: str | None,
    object_term: ox.Term | None,
) -> list[dict] | None:
    """Render a violation sample to Manchester tokens (plain dicts).

    Returns a list of token dicts (JSON-serializable), or None on failure.
    """
    effective_graph = graph_node if graph_node is not None else ox.DefaultGraph()
    try:
        tokens = None
        is_bnode = not (subject_iri.startswith("http") or subject_iri.startswith("urn:"))

        if predicate_iri is not None and object_term is not None:
            # Try axiom rendering first (works for class/property axioms like DisjointWith, etc.)
            tokens = render_axiom(
                store, effective_graph, subject_iri, predicate_iri, object_term,
                labels=labels, known_iris=known_iris,
            )
            # If render_axiom returned None (predicate not in _CLASS_AXIOMS), try as
            # individual property assertion (Facts:) — covers custom data properties
            # used in unsupported-datatype violations.
            if tokens is None and not is_bnode:
                tokens = render_axiom(
                    store, effective_graph, subject_iri, predicate_iri, object_term,
                    labels=labels, known_iris=known_iris,
                    entity_type="individual",
                )
            # If still None and subject is a bnode (cardinality/restriction patterns),
            # render the restriction bnode as a class expression.
            if tokens is None and is_bnode:
                subj_bnode = ox.BlankNode(subject_iri)
                tok_list = render_class_expression(
                    store, effective_graph, subj_bnode,
                    labels=labels, known_iris=known_iris,
                )
                tokens = tok_list if tok_list else None

        if tokens is None:
            # Type-based pattern or no triple available.
            if not is_bnode:
                # Named IRI subject — try rdf:type rendering first (for Characteristics: keyword)
                subj_nn = ox.NamedNode(subject_iri)
                type_pred = ox.NamedNode(_RDF_TYPE)
                for q in store.quads_for_pattern(subj_nn, type_pred, None, effective_graph):
                    if isinstance(q.object, ox.NamedNode):
                        tok = render_axiom(
                            store, effective_graph, subject_iri, _RDF_TYPE, q.object,
                            labels=labels, known_iris=known_iris,
                        )
                        if tok is not None:
                            tokens = tok
                            break
                if tokens is None:
                    tok_list = render_class_expression(
                        store, effective_graph, subj_nn,
                        labels=labels, known_iris=known_iris,
                    )
                    tokens = tok_list if tok_list else None
            else:
                # Blank node subject
                subj_bnode = ox.BlankNode(subject_iri)
                tok_list = render_class_expression(
                    store, effective_graph, subj_bnode,
                    labels=labels, known_iris=known_iris,
                )
                tokens = tok_list if tok_list else None

        if tokens is None:
            return None
        return [dict(t) for t in tokens]
    except Exception:
        return None


def _run_profile_patterns(
    store: ox.Store,
    graph_iri: str | None,
    patterns,
    graph_node: ox.NamedNode | None,
    known_iris: frozenset[str],
    labels: dict[str, str],
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
                manchester = _render_sample(
                    store, graph_node, known_iris, labels,
                    subject_iri=s["subject_iri"],
                    predicate_iri=s.get("predicate_iri"),
                    object_term=s.get("object_term"),
                )
                entry: dict = {
                    "axiom_type": pat.axiom_type,
                    "subject_iri": s["subject_iri"],
                    "manchester": manchester,
                }
                sample_violations.append(entry)

    # Cap samples at 50 across all patterns
    sample_violations = sample_violations[:_SAMPLE_CAP]

    return {
        "in_profile": total_violations == 0,
        "total_violations": total_violations,
        "violations_by_axiom_type": violations_by_axiom_type,
        "sample_violations": sample_violations,
    }


def _run_dl_checks(
    store: ox.Store,
    graph_iri: str | None,
    graph_node: ox.NamedNode | None,
    known_iris: frozenset[str],
    labels: dict[str, str],
) -> dict:
    """Run DL structural checks and return the profile result dict."""
    violation_tuples = detect_dl_violations_with_terms(store, graph_iri)

    violations_by_axiom_type: dict[str, int] = defaultdict(int)
    sample_violations: list[dict] = []

    for v, predicate_iri, object_term in violation_tuples:
        violations_by_axiom_type[v.axiom_type] += 1
        if len(sample_violations) < _SAMPLE_CAP:
            manchester = _render_sample(
                store, graph_node, known_iris, labels,
                subject_iri=v.subject_iri or "",
                predicate_iri=predicate_iri,
                object_term=object_term,
            )
            sample_violations.append({
                "axiom_type": v.axiom_type,
                "subject_iri": v.subject_iri,
                "details": v.details,
                "manchester": manchester,
            })

    total_violations = sum(violations_by_axiom_type.values())

    return {
        "in_profile": total_violations == 0,
        "total_violations": total_violations,
        "violations_by_axiom_type": dict(violations_by_axiom_type),
        "sample_violations": sample_violations,
    }


def detect_profiles(
    store: ox.Store,
    graph_iri: str | None,
    ontology_id: str,
    version_id: str,
) -> dict:
    """Run all OWL 2 profile checks. Returns the cache payload.

    The graph_iri parameter is used by the pattern factories to wrap queries
    in a GRAPH clause when the data lives in a named graph (production); pass
    None to query the default graph (unit tests).
    """
    # Build the Manchester rendering context once — shared across all profiles
    # to avoid recomputing known_iris (O(n) over the graph) four times.
    graph_node, known, labels = _build_render_context(store, graph_iri)

    el_result = _run_profile_patterns(store, graph_iri, make_el_patterns(graph_iri), graph_node, known, labels)
    rl_result = _run_profile_patterns(store, graph_iri, make_rl_patterns(graph_iri), graph_node, known, labels)
    ql_result = _run_profile_patterns(store, graph_iri, make_ql_patterns(graph_iri), graph_node, known, labels)
    dl_result = _run_dl_checks(store, graph_iri, graph_node, known, labels)

    # OWL 2 EL, RL, and QL are strict subsets of OWL 2 DL. An ontology that
    # violates DL cannot be in any of them, regardless of whether the profile-
    # specific patterns matched. Propagate DL=OUT to the sub-profile verdicts
    # (leave per-profile violation lists untouched — the user reads the DL tab
    # for the reason; the sub-profile tab correctly shows zero EL/RL/QL-
    # specific violations alongside in_profile=false).
    if not dl_result["in_profile"]:
        for sub in (el_result, rl_result, ql_result):
            sub["in_profile"] = False

    return {
        "el": el_result,
        "rl": rl_result,
        "ql": ql_result,
        "dl": dl_result,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
