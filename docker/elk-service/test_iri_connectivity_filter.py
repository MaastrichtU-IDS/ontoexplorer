"""Tests for the IRI-connectivity pre-filter that reduces the greedy walk's
candidate set before justification computation.

Correctness property: the filter must NEVER drop an axiom that's load-bearing
for sub ⊑ sup. Practically: the chain axioms (those that DIRECTLY mention
sub, sup, or any IRI on a path between them) must survive.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
_pywhelk = pytest.importorskip("pywhelk")
_pyhornedowl = pytest.importorskip("pyhornedowl")

from pyhornedowl import model
from justification import _filter_iri_connected


def _cls(iri: str):
    """Construct a Class object directly (without going through an ontology)."""
    onto = _pyhornedowl.PyIndexedOntology()
    return onto.class_(iri)


def test_filter_keeps_chain_drops_unrelated():
    """A⊑B + B⊑C chain plus 20 unrelated SubClassOfs: filter keeps just the 2 chain axioms."""
    A = _cls("http://example.org/A")
    B = _cls("http://example.org/B")
    C = _cls("http://example.org/C")
    chain = [model.SubClassOf(A, B), model.SubClassOf(B, C)]
    unrelated = [
        model.SubClassOf(_cls(f"http://example.org/X{i}"), _cls(f"http://example.org/Y{i}"))
        for i in range(20)
    ]
    filtered = _filter_iri_connected(chain + unrelated,
                                     "http://example.org/A", "http://example.org/C")
    assert len(filtered) == 2, f"expected 2 (the chain), got {len(filtered)}"


def test_filter_keeps_axiom_with_intermediate_iri():
    """An axiom that connects to the chain via a shared IRI (not sub or sup)
    must be retained. A⊑B, B⊑C, D⊑B — D⊑B shares B with the chain, keep it."""
    A = _cls("http://example.org/A")
    B = _cls("http://example.org/B")
    C = _cls("http://example.org/C")
    D = _cls("http://example.org/D")
    axes = [
        model.SubClassOf(A, B),  # chain
        model.SubClassOf(B, C),  # chain
        model.SubClassOf(D, B),  # connected via B
        model.SubClassOf(_cls("http://example.org/X"), _cls("http://example.org/Y")),  # unrelated
    ]
    filtered = _filter_iri_connected(axes, "http://example.org/A", "http://example.org/C")
    # D⊑B should be kept; X⊑Y dropped.
    assert len(filtered) == 3


def test_filter_keeps_empty_seed_with_no_matches():
    """No axiom mentions sub or sup → filter returns empty."""
    A = _cls("http://example.org/A")
    B = _cls("http://example.org/B")
    axes = [model.SubClassOf(A, B)]
    filtered = _filter_iri_connected(axes,
                                     "http://example.org/totally-unrelated-sub",
                                     "http://example.org/totally-unrelated-sup")
    assert filtered == []
