"""Unit tests for KoncludeBackend's transitive-closure helper.

Konclude's `classification -o out.owx` output only carries the direct
(told + direct-inferred) subClassOf taxonomy, not the full transitive
closure — unlike whelk (`inferred_axioms()`) and rustdl
(`superclasses_of()`), which both return the closure natively.
`_transitive_superclasses` reconstructs that closure from the direct
child->parents map Konclude gives us. This module is pure Python (no
Konclude binary, no pyhornedowl) so it can run on any host, including
this macOS dev machine where the Konclude binary itself is unavailable
and test_konclude_backend.py skips.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from konclude_backend import _transitive_superclasses


def test_chain_transitive_closure():
    # A subClassOf B, B subClassOf C -- both edges are asserted (told), so
    # Konclude's direct-edges-only output is identical to `parents` here.
    # superclasses[A] must include the transitive ancestor C (inferred,
    # not asserted); superclasses[B] must be omitted since B's only
    # ancestor (C) is asserted, leaving nothing inferred.
    parents = {"A": {"B"}, "B": {"C"}}
    asserted = {("A", "B"), ("B", "C")}

    result = _transitive_superclasses(parents, asserted)

    assert result.get("A") == ["C"]
    assert "B" not in result


def test_diamond_transitive_closure():
    # A -> B -> D, A -> C -> D (diamond), all edges told/asserted. A's raw
    # ancestor set is {B, C, D}, but (A,B) and (A,C) are asserted so only
    # the transitive ancestor D is inferred and non-asserted.
    parents = {"A": {"B", "C"}, "B": {"D"}, "C": {"D"}}
    asserted = {("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")}

    result = _transitive_superclasses(parents, asserted)

    assert result["A"] == ["D"]
    assert "B" not in result
    assert "C" not in result


def test_equivalent_class_cycle_does_not_recurse_forever():
    # A and B are owl:equivalentClass -- Konclude emits mutual subClassOf
    # edges (A subClassOf B, B subClassOf A). The caller marks both
    # directions as asserted, so the cycle must terminate and the mutual
    # edge must be filtered out of `superclasses` entirely (it belongs in
    # direct_superclasses instead).
    parents = {"A": {"B"}, "B": {"A"}}
    asserted = {("A", "B"), ("B", "A")}

    result = _transitive_superclasses(parents, asserted)

    assert result == {}


def test_no_asserted_pairs_means_everything_is_inferred():
    # Edge case exercised by live Konclude output: if Konclude infers an
    # edge that was NOT told (e.g. via an equivalent-class chain collapsing
    # two named classes), it should surface as inferred.
    parents = {"A": {"B"}, "B": {"C"}}
    asserted: set[tuple[str, str]] = set()

    result = _transitive_superclasses(parents, asserted)

    assert result["A"] == ["B", "C"]
    assert result["B"] == ["C"]
