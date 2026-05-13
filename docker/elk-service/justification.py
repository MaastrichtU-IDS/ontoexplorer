"""
Justification computation for OWL-EL inferences.

Algorithm:
1. Find all input axioms (N-Triple strings) that are used anywhere in
   the proof trace for the target inference.
2. Greedily shrink the set (remove axioms that are not load-bearing)
   by re-running classification on the reduced graph.
3. For multiple justifications, use the hitting-set approach:
   after finding one justification J, add a blocking constraint
   (exclude at least one axiom from J) and search again.
"""
from __future__ import annotations

import io
import itertools
from typing import Sequence

import rdflib

from classifier import ClassificationResult, classify


def compute_justifications(
    graph: rdflib.Graph,
    result: ClassificationResult,
    sub: str,
    sup: str,
    max_justifications: int = 1,
) -> list[list[str]]:
    """
    Return a list of minimal justifications for the inference sub ⊑ sup.

    Each justification is a list of N-Triple strings (original axioms).
    max_justifications=0 means find all (may be expensive).
    Returns [] if the inference is not present in result.
    """
    # Verify inference is present
    if sup == str(rdflib.OWL.Nothing):
        if sub not in result.unsatisfiable:
            return []
    else:
        if sup not in result.superclasses.get(sub, []) and sup not in result.direct_superclasses.get(sub, []):
            return []

    all_axioms = _extract_all_axioms(graph)
    if not all_axioms:
        return []

    justifications: list[list[str]] = []
    excluded: list[frozenset[str]] = []  # hitting sets to block

    limit = max_justifications if max_justifications > 0 else 999

    while len(justifications) < limit:
        candidate = _find_one_justification(all_axioms, sub, sup, excluded)
        if candidate is None:
            break
        justifications.append(candidate)
        excluded.append(frozenset(candidate))

    return justifications


def _find_one_justification(
    all_axioms: list[str],
    sub: str,
    sup: str,
    excluded: list[frozenset[str]],
) -> list[str] | None:
    """Find one minimal justification not blocked by any set in excluded."""
    # Start with all axioms and greedily remove non-load-bearing ones
    candidate = list(all_axioms)

    # Apply exclusion: must contain at least one axiom NOT in each excluded set.
    # Remove one axiom from each excluded justification to force a different path.
    for ex_set in excluded:
        for ax in list(ex_set):
            if ax in candidate:
                candidate = [a for a in candidate if a != ax]
                break

    if not _entails(candidate, sub, sup):
        return None

    # Greedy minimisation: try removing each axiom
    minimal = list(candidate)
    for ax in list(candidate):
        reduced = [a for a in minimal if a != ax]
        if _entails(reduced, sub, sup):
            minimal = reduced

    return minimal if minimal else None


def _entails(axioms: list[str], sub: str, sup: str) -> bool:
    """Return True if the given axiom set entails sub ⊑ sup."""
    g = rdflib.Graph()
    try:
        g.parse(data="\n".join(axioms), format="nt")
    except Exception:
        for ax in axioms:
            try:
                g.parse(data=ax, format="nt")
            except Exception:
                pass
    if len(g) == 0:
        return False
    try:
        r = classify(g, "_check")
    except Exception:
        return False
    if sup == str(rdflib.OWL.Nothing):
        return sub in r.unsatisfiable
    return (sup in r.superclasses.get(sub, []) or
            sup in r.direct_superclasses.get(sub, []))


def _extract_all_axioms(graph: rdflib.Graph) -> list[str]:
    """Serialise graph as N-Triples, one line per axiom, preserving blank node IDs."""
    nt_text = graph.serialize(format="nt")
    return [line.strip() for line in nt_text.splitlines() if line.strip()]
