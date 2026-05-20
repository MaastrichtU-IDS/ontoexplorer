"""Unit tests for OWL 2 EL forbidden-pattern detection."""
from __future__ import annotations

import pyoxigraph
from pyoxigraph import RdfFormat, NamedNode

from ontoexplorer.modules.owl_profile.patterns import EL_PATTERNS, make_el_patterns, run_pattern_count


def _store_from_turtle(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), RdfFormat.TURTLE)
    return s


# ---------------------------------------------------------------------------
# Test 1: owl:inverseOf is detected (a still-forbidden EL construct)
# ---------------------------------------------------------------------------

def test_el_inverse_of_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty ; owl:inverseOf :q .
    :q a owl:ObjectProperty .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in EL_PATTERNS if pat.axiom_type == "owl:inverseOf")
    count, samples = run_pattern_count(store, None, p)
    assert count == 1
    assert samples and samples[0]["subject_iri"] == "http://example.org/p"


# ---------------------------------------------------------------------------
# Test 2: pure EL ontology has no violations across all patterns
# ---------------------------------------------------------------------------

def test_el_pure_subclass_no_violations():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class ; rdfs:subClassOf :A .
    :C a owl:Class ; rdfs:subClassOf :A .
    :p a owl:ObjectProperty .
    """
    store = _store_from_turtle(ttl)
    for p in EL_PATTERNS:
        count, _ = run_pattern_count(store, None, p)
        assert count == 0, f"{p.axiom_type} should not match on pure EL ontology"


# ---------------------------------------------------------------------------
# Test 3: cardinality restriction is detected
# ---------------------------------------------------------------------------

def test_el_cardinality_restriction_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :R a owl:ObjectProperty .
    :A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :R ; owl:maxCardinality "1"^^xsd:nonNegativeInteger ] .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in EL_PATTERNS if pat.axiom_type == "owl:cardinality-restriction")
    count, samples = run_pattern_count(store, None, p)
    assert count == 1
    assert len(samples) == 1  # blank node subject found


# ---------------------------------------------------------------------------
# Test 4: named-graph wrapping — detection against named graph, not default
# ---------------------------------------------------------------------------

def test_el_named_graph_wrapping():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty ; owl:inverseOf :q .
    :q a owl:ObjectProperty .
    """
    graph_iri = "urn:test-graph"
    store = pyoxigraph.Store()
    graph_node = NamedNode(graph_iri)
    store.add_graph(graph_node)
    store.load(ttl.encode("utf-8"), RdfFormat.TURTLE, to_graph=graph_node)

    # Named-graph patterns should detect the violation
    named_patterns = make_el_patterns(graph_iri)
    p_named = next(pat for pat in named_patterns if pat.axiom_type == "owl:inverseOf")
    count_named, _ = run_pattern_count(store, graph_iri, p_named)
    assert count_named == 1, "named-graph pattern should detect inverseOf"

    # Default-graph patterns should find nothing (triples only in named graph)
    p_default = next(pat for pat in EL_PATTERNS if pat.axiom_type == "owl:inverseOf")
    count_default, _ = run_pattern_count(store, None, p_default)
    assert count_default == 0, "default-graph pattern should not see named-graph triples"


# ---------------------------------------------------------------------------
# Test 5: unionOf class expression is detected
# ---------------------------------------------------------------------------

def test_el_union_of_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :A a owl:Class ; owl:equivalentClass [ a owl:Class ; owl:unionOf ( :B :C ) ] .
    :B a owl:Class .
    :C a owl:Class .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in EL_PATTERNS if pat.axiom_type == "owl:unionOf")
    count, samples = run_pattern_count(store, None, p)
    assert count == 1
    assert len(samples) == 1


# ---------------------------------------------------------------------------
# Regression: pairwise disjointness between named classes is allowed in EL
# (W3C OWL 2 Profiles §4.2). Previously over-flagged; now correctly accepted.
# ---------------------------------------------------------------------------

def test_el_has_value_is_allowed():
    """ObjectHasValue and DataHasValue ARE allowed in OWL 2 EL (W3C §4.2.1):
    ∃R.{a} reduces to ObjectSomeValuesFrom over a singleton ObjectOneOf,
    which is in the EL grammar. Regression for prior over-flagging that
    produced false-positive EL=OUT verdicts on ontologies like ORDO that
    use hundreds/thousands of hasValue restrictions."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :hasName a owl:DatatypeProperty .
    :p a owl:ObjectProperty .
    :A a owl:Class ; rdfs:subClassOf
        [ a owl:Restriction ; owl:onProperty :p ; owl:hasValue :B ] ,
        [ a owl:Restriction ; owl:onProperty :hasName ; owl:hasValue "Alice" ] .
    :B a owl:NamedIndividual .
    """
    store = _store_from_turtle(ttl)
    for p in EL_PATTERNS:
        count, _ = run_pattern_count(store, None, p)
        assert count == 0, f"owl:hasValue is EL-allowed; pattern {p.axiom_type} matched"


def test_el_pairwise_disjoint_named_classes_is_allowed():
    """OWL 2 EL allows pairwise DisjointClasses between EL-conformant classes.
    Named classes are trivially EL-conformant, so this should NOT be flagged."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :A a owl:Class ; owl:disjointWith :B .
    :B a owl:Class .
    [] a owl:AllDisjointClasses ; owl:members ( :A :B ) .
    """
    store = _store_from_turtle(ttl)
    for p in EL_PATTERNS:
        count, _ = run_pattern_count(store, None, p)
        assert count == 0, (
            f"Pairwise disjointness between named classes should not be flagged "
            f"as EL violation; pattern {p.axiom_type} matched"
        )
