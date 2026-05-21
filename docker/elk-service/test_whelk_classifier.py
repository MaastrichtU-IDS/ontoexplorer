"""Unit tests for the whelk-rs-backed classifier.

These cover the same `ClassificationResult` contract the legacy backend's
tests cover, minus the proof-trace assertion (whelk emits no traces).
Tests are skipped when py-whelk isn't importable so the test suite still
runs on environments without the Rust extension wheel.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import io
import pytest
import rdflib

EX = "http://example.org/"
OWL_THING = "http://www.w3.org/2002/07/owl#Thing"


def _g(ttl: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(io.StringIO(ttl), format="turtle")
    return graph


_pywhelk = pytest.importorskip("pywhelk")
_pyhornedowl = pytest.importorskip("pyhornedowl")
from whelk_classifier import classify  # noqa: E402  — must import after skip


def test_transitive_inference_present_in_superclasses():
    """A ⊑ B, B ⊑ C → A's `superclasses` (inferred only) includes C, not B."""
    result = classify(_g(f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <{EX}> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """), "v-test")
    sups = result.superclasses.get(f"{EX}A", [])
    assert f"{EX}C" in sups, f"Expected transitive C in {sups!r}"
    # B is asserted, must NOT appear in `superclasses` per the legacy contract
    assert f"{EX}B" not in sups


def test_direct_superclasses_contain_only_asserted():
    """direct_superclasses == the asserted set, exactly as the legacy backend reports."""
    result = classify(_g(f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <{EX}> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """), "v-test")
    direct_a = result.direct_superclasses.get(f"{EX}A", [])
    assert direct_a == [f"{EX}B"], f"expected one-hop only, got {direct_a!r}"


def test_unsatisfiable_class_is_reported():
    """A ⊑ B, A ⊑ C, B disjointWith C → A unsatisfiable."""
    result = classify(_g(f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <{EX}> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """), "v-test")
    assert f"{EX}A" in result.unsatisfiable, (
        f"A should be unsatisfiable, got {result.unsatisfiable!r}"
    )


def test_existential_propagation_through_role_hierarchy():
    """r ⊑ s, A ⊑ ∃r.B, ∃s.B ⊑ C → A ⊑ C. The CR5 case the legacy backend tests."""
    result = classify(_g(f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <{EX}> .
    ex:r a owl:ObjectProperty ; rdfs:subPropertyOf ex:s .
    ex:s a owl:ObjectProperty .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:r ; owl:someValuesFrom ex:B ] .
    [ a owl:Restriction ; owl:onProperty ex:s ; owl:someValuesFrom ex:B ] rdfs:subClassOf ex:C .
    """), "v-test")
    sups = result.superclasses.get(f"{EX}A", [])
    assert f"{EX}C" in sups, f"Expected C via CR5 in {sups!r}"


def test_proof_traces_are_empty_by_design():
    """Whelk doesn't expose proof traces; we emit {} so callers know to
    treat the justification feature as degraded for this backend."""
    result = classify(_g(f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <{EX}> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class .
    """), "v-test")
    assert result.proof_traces == {}
