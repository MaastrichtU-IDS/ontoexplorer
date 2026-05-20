"""Unit tests for OWL 2 RL forbidden-pattern detection."""
from __future__ import annotations

import pyoxigraph
from pyoxigraph import RdfFormat

from ontoexplorer.modules.owl_profile.patterns import RL_PATTERNS, make_rl_patterns, run_pattern_count


def _store_from_turtle(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), RdfFormat.TURTLE)
    return s


# ---------------------------------------------------------------------------
# Test 1: hasSelf is detected
# ---------------------------------------------------------------------------

def test_rl_has_self_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty .
    :SelfClass a owl:Class ;
        owl:equivalentClass [ a owl:Restriction ;
            owl:onProperty :p ;
            owl:hasSelf true ] .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:hasSelf")
    count, samples = run_pattern_count(store, None, p)
    assert count == 1


# ---------------------------------------------------------------------------
# Test 2: pure SubClassOf ontology — no RL violations
# ---------------------------------------------------------------------------

def test_rl_pure_subclass_no_violations():
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
    for pat in RL_PATTERNS:
        count, _ = run_pattern_count(store, None, pat)
        assert count == 0, f"RL pattern '{pat.axiom_type}' should not fire on pure SubClassOf ontology"


# ---------------------------------------------------------------------------
# Test 3: maxCardinality > 1 detected, but maxCardinality = 1 is NOT
# ---------------------------------------------------------------------------

def test_rl_max_cardinality_2_detected_but_max_1_not():
    ttl_gt1 = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :R a owl:ObjectProperty .
    :A rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty :R ;
        owl:maxCardinality "2"^^xsd:nonNegativeInteger ] .
    """
    ttl_eq1 = """
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
    # Get the cardinality-gt-1 pattern
    card_gt1_pat = next(
        pat for pat in RL_PATTERNS if pat.axiom_type == "owl:cardinality-restriction-gt1"
    )

    # Value "2" should be detected
    store_gt1 = _store_from_turtle(ttl_gt1)
    count_gt1, _ = run_pattern_count(store_gt1, None, card_gt1_pat)
    assert count_gt1 == 1, "maxCardinality 2 should be flagged as RL violation"

    # Value "1" should NOT be detected by the gt-1 pattern
    store_eq1 = _store_from_turtle(ttl_eq1)
    count_eq1, _ = run_pattern_count(store_eq1, None, card_gt1_pat)
    assert count_eq1 == 0, "maxCardinality 1 should NOT be flagged by the gt-1 cardinality pattern"


# ---------------------------------------------------------------------------
# Test 4: minCardinality (any value) is always forbidden in RL
# ---------------------------------------------------------------------------

def test_rl_min_cardinality_any_value_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :R a owl:ObjectProperty .
    :A rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty :R ;
        owl:minCardinality "1"^^xsd:nonNegativeInteger ] .
    """
    store = _store_from_turtle(ttl)
    min_card_pat = next(
        pat for pat in RL_PATTERNS if pat.axiom_type == "owl:min-cardinality-restriction"
    )
    count, _ = run_pattern_count(store, None, min_card_pat)
    assert count == 1, "minCardinality (any value) should be flagged as RL violation"


# ---------------------------------------------------------------------------
# Test 5: complementOf detected
# ---------------------------------------------------------------------------

def test_rl_complement_of_on_lhs_detected():
    """RL forbids complementOf on subClassExpression position (LHS of subClassOf
    or inside another complementOf). On RHS it's allowed."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class .
    # Complement of :A used as LHS of subClassOf — forbidden in RL
    [ owl:complementOf :A ] rdfs:subClassOf :B .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:complementOf-on-subClass")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1


# ---------------------------------------------------------------------------
# Positional patterns: RL §5.2 distinguishes LHS vs RHS of SubClassOf
# ---------------------------------------------------------------------------

def test_rl_someValuesFrom_on_rhs_detected():
    """ObjectSomeValuesFrom on RHS of subClassOf is forbidden in RL (§5.2).
    On LHS it is allowed."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class .
    :p a owl:ObjectProperty .
    # SubClassOf(:A ObjectSomeValuesFrom(:p :B)) — forbidden in RL
    :A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ; owl:someValuesFrom :B ] .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:someValuesFrom-on-superClass")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1


def test_rl_someValuesFrom_on_lhs_is_allowed():
    """ObjectSomeValuesFrom on LHS of subClassOf is allowed in RL."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class .
    :p a owl:ObjectProperty .
    # SubClassOf(ObjectSomeValuesFrom(:p :A) :B) — allowed on LHS
    [ a owl:Restriction ; owl:onProperty :p ; owl:someValuesFrom :A ] rdfs:subClassOf :B .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:someValuesFrom-on-superClass")
    count, _ = run_pattern_count(store, None, p)
    assert count == 0


def test_rl_allValuesFrom_on_lhs_detected():
    """ObjectAllValuesFrom on LHS of subClassOf is forbidden in RL."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class .
    :p a owl:ObjectProperty .
    [ a owl:Restriction ; owl:onProperty :p ; owl:allValuesFrom :A ] rdfs:subClassOf :B .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:allValuesFrom-on-subClass")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1


def test_rl_allValuesFrom_on_rhs_is_allowed():
    """ObjectAllValuesFrom on RHS of subClassOf is allowed in RL."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :B a owl:Class .
    :p a owl:ObjectProperty .
    :A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ; owl:allValuesFrom :B ] .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:allValuesFrom-on-subClass")
    count, _ = run_pattern_count(store, None, p)
    assert count == 0


def test_rl_reflexive_property_detected():
    """RL forbids ObjectReflexiveProperty (§5.2 property characteristics)."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ReflexiveProperty .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in RL_PATTERNS if pat.axiom_type == "owl:ReflexiveProperty")
    count, _ = run_pattern_count(store, None, p)
    assert count == 1


def test_rl_transitive_property_is_allowed():
    """RL allows TransitiveObjectProperty (unlike QL)."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:TransitiveProperty .
    """
    store = _store_from_turtle(ttl)
    for p in RL_PATTERNS:
        count, _ = run_pattern_count(store, None, p)
        assert count == 0, f"TransitiveProperty is RL-allowed; pattern {p.axiom_type} matched"
