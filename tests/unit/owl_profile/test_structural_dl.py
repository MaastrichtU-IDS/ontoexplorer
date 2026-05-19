"""Unit tests for OWL 2 DL structural checks (Task 5).

Covers:
1. Punning detection (forbidden co-typing pairs)
2. Punning allowed case (owl:Class + owl:NamedIndividual is permitted)
3. Transitive property in a role hierarchy cycle
4. Literal with unsupported datatype (xsd:duration)
5. Known-good datatypes produce no violations
6. el-only.ttl fixture produces zero DL violations
"""
from __future__ import annotations

from pathlib import Path

import pyoxigraph
from pyoxigraph import RdfFormat, NamedNode

from ontoexplorer.modules.owl_profile.structural import (
    detect_dl_violations,
    _detect_punning,
    _detect_transitive_cycles,
    _detect_bad_datatypes,
    _detect_reserved_vocab,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "owl_profile"


def _store_from_turtle(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), RdfFormat.TURTLE)
    return s


def _store_from_fixture(name: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    path = FIXTURES_DIR / name
    with open(path, "rb") as f:
        s.load(f.read(), RdfFormat.TURTLE)
    return s


# ---------------------------------------------------------------------------
# Test 1: punning — ObjectProperty + AnnotationProperty on same IRI is detected
# ---------------------------------------------------------------------------

def test_punning_detected():
    """Fixture has :p typed as both owl:ObjectProperty and owl:AnnotationProperty."""
    store = _store_from_fixture("punning.ttl")
    violations = _detect_punning(store, None)
    assert len(violations) == 1, f"Expected 1 punning violation, got {violations}"
    v = violations[0]
    assert v.profile == "dl"
    assert v.axiom_type == "punning"
    assert v.subject_iri == "http://example.org/punning#p"


# ---------------------------------------------------------------------------
# Test 2: class-individual punning is ALLOWED (no violation)
# ---------------------------------------------------------------------------

def test_class_individual_punning_allowed():
    """owl:Class + owl:NamedIndividual on the same IRI is legal in OWL 2."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :x a owl:Class, owl:NamedIndividual .
    """
    store = _store_from_turtle(ttl)
    violations = _detect_punning(store, None)
    assert violations == [], f"Class-individual punning should be allowed, got {violations}"


# ---------------------------------------------------------------------------
# Test 3: transitive property in a self sub-property cycle is detected
# ---------------------------------------------------------------------------

def test_transitive_cycle_detected():
    """Fixture has :p a owl:TransitiveProperty ; rdfs:subPropertyOf :p."""
    store = _store_from_fixture("role-hierarchy-cycle.ttl")
    violations = _detect_transitive_cycles(store, None)
    assert len(violations) == 1, f"Expected 1 cycle violation, got {violations}"
    v = violations[0]
    assert v.profile == "dl"
    assert v.axiom_type == "role-hierarchy-cycle"
    assert v.subject_iri == "http://example.org/rolecycle#p"


# ---------------------------------------------------------------------------
# Test 4: literal with xsd:duration (not in OWL 2 map) is detected
# ---------------------------------------------------------------------------

def test_bad_datatype_detected():
    """Fixture uses xsd:duration which is not in the OWL 2 datatype map."""
    store = _store_from_fixture("bad-datatype.ttl")
    violations = _detect_bad_datatypes(store, None)
    assert len(violations) >= 1, f"Expected at least 1 datatype violation, got {violations}"
    violating_types = {v.subject_iri for v in violations}
    assert "http://www.w3.org/2001/XMLSchema#duration" in violating_types


# ---------------------------------------------------------------------------
# Test 5: literals with xsd:string and xsd:integer produce no datatype violations
# ---------------------------------------------------------------------------

def test_known_datatypes_pass():
    """xsd:string and xsd:integer are in the OWL 2 datatype map — no violations."""
    ttl = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix :     <http://example.org/> .
    :A a owl:Class .
    :a1 a :A ;
        rdfs:label "hello"^^xsd:string ;
        :count "42"^^xsd:integer .
    """
    store = _store_from_turtle(ttl)
    violations = _detect_bad_datatypes(store, None)
    assert violations == [], f"Known OWL 2 datatypes should not trigger violations, got {violations}"


# ---------------------------------------------------------------------------
# Test 6: el-only.ttl produces zero DL violations (full aggregator)
# ---------------------------------------------------------------------------

def test_pure_dl_fixture_passes():
    """el-only.ttl is a conformant OWL 2 DL ontology — no structural DL violations."""
    store = _store_from_fixture("el-only.ttl")
    violations = detect_dl_violations(store, None)
    assert violations == [], (
        f"el-only.ttl should produce zero DL violations, got:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test 7: DatatypeProperty + ObjectProperty punning detected
# ---------------------------------------------------------------------------

def test_punning_datatype_object_property_detected():
    """IRI typed as both owl:DatatypeProperty and owl:ObjectProperty is forbidden."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :dp a owl:DatatypeProperty, owl:ObjectProperty .
    """
    store = _store_from_turtle(ttl)
    violations = _detect_punning(store, None)
    assert len(violations) == 1, f"Expected 1 punning violation, got {violations}"
    assert violations[0].subject_iri == "http://example.org/dp"


# ---------------------------------------------------------------------------
# Test 8: named-graph wrapping works for detect_dl_violations
# ---------------------------------------------------------------------------

def test_dl_named_graph_wrapping():
    """DL checks query inside the named graph when graph_iri is provided."""
    ttl = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty, owl:AnnotationProperty .
    """
    graph_iri = "urn:test-dl-graph"
    store = pyoxigraph.Store()
    graph_node = NamedNode(graph_iri)
    store.add_graph(graph_node)
    store.load(ttl.encode("utf-8"), RdfFormat.TURTLE, to_graph=graph_node)

    # Querying the named graph should detect the violation
    violations_named = detect_dl_violations(store, graph_iri)
    punning = [v for v in violations_named if v.axiom_type == "punning"]
    assert len(punning) == 1, f"Named-graph punning check should detect violation, got {violations_named}"

    # Default-graph query should find nothing
    violations_default = detect_dl_violations(store, None)
    punning_default = [v for v in violations_default if v.axiom_type == "punning"]
    assert punning_default == [], "Default-graph check should not see named-graph triples"
