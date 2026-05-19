"""Unit tests for OWL 2 QL forbidden-pattern detection."""
from __future__ import annotations

import pyoxigraph
from pyoxigraph import RdfFormat

from ontoexplorer.modules.owl_profile.patterns import QL_PATTERNS, make_ql_patterns, run_pattern_count


def _store_from_turtle(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), RdfFormat.TURTLE)
    return s


# ---------------------------------------------------------------------------
# Test 1: TransitiveProperty is detected
# ---------------------------------------------------------------------------

def test_ql_transitive_property_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty, owl:TransitiveProperty .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in QL_PATTERNS if pat.axiom_type == "owl:TransitiveProperty")
    count, samples = run_pattern_count(store, None, p)
    assert count == 1
    assert samples and samples[0]["subject_iri"] == "http://example.org/p"


# ---------------------------------------------------------------------------
# Test 2: pure SubClassOf ontology — no QL violations
# ---------------------------------------------------------------------------

def test_ql_pure_subclass_no_violations():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class ; rdfs:subClassOf :A .
    :C a owl:Class ; rdfs:subClassOf :B .
    :p a owl:ObjectProperty .
    """
    store = _store_from_turtle(ttl)
    for pat in QL_PATTERNS:
        count, _ = run_pattern_count(store, None, pat)
        assert count == 0, f"QL pattern '{pat.axiom_type}' should not fire on pure SubClassOf ontology"


# ---------------------------------------------------------------------------
# Test 3: pairwise disjointness between named classes is allowed in QL
# (W3C OWL 2 Profiles §6.2). Regression for prior over-flagging behavior.
# ---------------------------------------------------------------------------

def test_ql_pairwise_disjoint_named_classes_is_allowed():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :A a owl:Class ; owl:disjointWith :B .
    :B a owl:Class .
    [] a owl:AllDisjointClasses ; owl:members ( :A :B ) .
    """
    store = _store_from_turtle(ttl)
    for p in QL_PATTERNS:
        count, _ = run_pattern_count(store, None, p)
        assert count == 0, (
            f"Pairwise disjointness between named classes should not be flagged "
            f"as QL violation; pattern {p.axiom_type} matched"
        )


# ---------------------------------------------------------------------------
# Test 4: any cardinality restriction (including ≤ 1) is forbidden in QL
# ---------------------------------------------------------------------------

def test_ql_cardinality_1_detected():
    """QL forbids ALL cardinality restrictions, even maxCardinality 1."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :R a owl:ObjectProperty .
    :A rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty :R ;
        owl:maxCardinality "1"^^xsd:nonNegativeInteger ] .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in QL_PATTERNS if pat.axiom_type == "owl:cardinality-restriction")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1, "QL forbids ALL cardinality restrictions, including maxCardinality 1"


# ---------------------------------------------------------------------------
# Test 5: FunctionalProperty detected
# ---------------------------------------------------------------------------

def test_ql_functional_property_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty, owl:FunctionalProperty .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in QL_PATTERNS if pat.axiom_type == "owl:FunctionalProperty")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1


# ---------------------------------------------------------------------------
# Test 6: unionOf detected
# ---------------------------------------------------------------------------

def test_ql_union_of_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class .
    :AorB a owl:Class ; owl:equivalentClass [ owl:unionOf ( :A :B ) ] .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in QL_PATTERNS if pat.axiom_type == "owl:unionOf")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1
