"""Unit tests for Manchester rendering in OWL profile violation samples.

TDD: these tests are written BEFORE the implementation.
They verify that:
1. run_pattern_count returns predicate_iri and object_term in samples
2. detect_profiles includes a `manchester` field in sample_violations
3. _detect_bad_datatypes returns usage triples (s, p, o) rather than just dt IRI
4. The rendered Manchester string is human-readable (not a bnode ID)
"""
from __future__ import annotations

import pyoxigraph
from pyoxigraph import RdfFormat

from ontoexplorer.modules.owl_profile.patterns import (
    EL_PATTERNS,
    run_pattern_count,
)
from ontoexplorer.modules.owl_profile.detector import detect_profiles
from ontoexplorer.modules.owl_profile.structural import _detect_bad_datatypes


def _store_from_ttl(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), RdfFormat.TURTLE)
    return s


# ---------------------------------------------------------------------------
# Test 1: run_pattern_count returns predicate_iri and object_term in samples
# ---------------------------------------------------------------------------

def test_run_pattern_count_returns_predicate_and_object():
    """Predicate-based patterns return predicate_iri and object_term in samples."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty ; owl:inverseOf :q .
    :q a owl:ObjectProperty .
    """
    store = _store_from_ttl(ttl)
    pat = next(p for p in EL_PATTERNS if p.axiom_type == "owl:inverseOf")
    count, samples = run_pattern_count(store, None, pat)
    assert count == 1
    assert len(samples) == 1
    s = samples[0]
    assert s["subject_iri"] == "http://example.org/p"
    assert s.get("predicate_iri") == "http://www.w3.org/2002/07/owl#inverseOf"
    assert s.get("object_term") is not None


def test_run_pattern_count_type_pattern_has_no_predicate():
    """Type-based patterns (owl:FunctionalProperty) still work; predicate_iri may be absent."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:FunctionalProperty .
    """
    store = _store_from_ttl(ttl)
    pat = next(p for p in EL_PATTERNS if p.axiom_type == "owl:FunctionalProperty")
    count, samples = run_pattern_count(store, None, pat)
    assert count == 1
    assert len(samples) == 1
    s = samples[0]
    assert s["subject_iri"] == "http://example.org/p"


def test_run_pattern_count_cardinality_returns_card_predicate():
    """Cardinality patterns return the specific cardinality predicate in samples."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :R a owl:ObjectProperty .
    :A rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty :R ;
        owl:maxCardinality "1"^^xsd:nonNegativeInteger
    ] .
    """
    store = _store_from_ttl(ttl)
    pat = next(p for p in EL_PATTERNS if p.axiom_type == "owl:cardinality-restriction")
    count, samples = run_pattern_count(store, None, pat)
    assert count == 1
    assert len(samples) == 1
    s = samples[0]
    assert s.get("predicate_iri") == "http://www.w3.org/2002/07/owl#maxCardinality"
    assert s.get("object_term") is not None


# ---------------------------------------------------------------------------
# Test 2: detect_profiles includes `manchester` field in sample_violations
# ---------------------------------------------------------------------------

def test_detect_profiles_sample_has_manchester_for_named_property_inverseof():
    """inverseOf between named properties: manchester should be non-empty."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty ; rdfs:label "P" ; owl:inverseOf :q .
    :q a owl:ObjectProperty ; rdfs:label "Q" .
    """
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    el_samples = result["el"]["sample_violations"]
    samples = [s for s in el_samples if s["axiom_type"] == "owl:inverseOf"]
    assert len(samples) > 0, "Should have inverseOf samples"
    sample = samples[0]
    assert "manchester" in sample, f"manchester key missing from sample: {sample}"
    assert sample["manchester"] is not None, "manchester should not be None"
    assert len(sample["manchester"]) > 0, "manchester tokens should be non-empty"
    text = "".join(
        t["v"] if t["t"] == "text" else t.get("label", t.get("iri", ""))
        for t in sample["manchester"]
    )
    assert "InverseOf" in text, f"Expected 'InverseOf' in Manchester text: {text!r}"


def test_detect_profiles_bnode_violation_renders_manchester():
    """A bnode-subject violation (owl:unionOf class expression) renders Manchester."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :A a owl:Class ; owl:equivalentClass [ a owl:Class ; owl:unionOf ( :B :C ) ] .
    :B a owl:Class .
    :C a owl:Class .
    """
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    el_samples = result["el"]["sample_violations"]
    union_samples = [s for s in el_samples if s["axiom_type"] == "owl:unionOf"]
    assert len(union_samples) > 0
    sample = union_samples[0]
    # The sample has a manchester field (may be bnode fallback or None for type-based)
    assert "manchester" in sample


def test_detect_profiles_cardinality_bnode_manchester():
    """Cardinality restriction (bnode subject): manchester renders 'R max 1' style."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class .
    :R a owl:ObjectProperty ; rdfs:label "myProp" .
    :A rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty :R ;
        owl:maxCardinality "1"^^xsd:nonNegativeInteger
    ] .
    """
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    el_samples = result["el"]["sample_violations"]
    card_samples = [s for s in el_samples if s["axiom_type"] == "owl:cardinality-restriction"]
    assert len(card_samples) > 0
    sample = card_samples[0]
    assert "manchester" in sample
    if sample["manchester"]:
        text = "".join(
            t["v"] if t["t"] == "text" else t.get("label", "")
            for t in sample["manchester"]
        )
        # Should contain "max" and "1" at minimum
        assert "max" in text.lower() or "1" in text, f"Unexpected Manchester for cardinality: {text!r}"


def test_detect_profiles_functional_property_manchester():
    """FunctionalProperty (type-based): manchester renders 'Characteristics: Functional'."""
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:FunctionalProperty .
    """
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    el_samples = result["el"]["sample_violations"]
    fp_samples = [s for s in el_samples if s["axiom_type"] == "owl:FunctionalProperty"]
    assert len(fp_samples) > 0
    sample = fp_samples[0]
    assert "manchester" in sample
    # FunctionalProperty is type-based — render_axiom(rdf:type, owl:FunctionalProperty)
    # should return "Characteristics: Functional"
    if sample["manchester"]:
        text = "".join(
            t["v"] if t["t"] == "text" else t.get("label", "")
            for t in sample["manchester"]
        )
        assert "Functional" in text, f"Expected 'Functional' in Manchester: {text!r}"


# ---------------------------------------------------------------------------
# Test 3: _detect_bad_datatypes returns usage triples (s, p, o) for subject_iri
# ---------------------------------------------------------------------------

def test_bad_datatype_returns_usage_triple_not_dt_iri():
    """
    After fix: the subject_iri should be the SUBJECT of the triple using the bad datatype,
    not the datatype IRI itself. Also a manchester field should be present.
    """
    ttl = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix :     <http://example.org/> .
    :A a owl:Class .
    :a1 a :A ;
        :hasIdentifier "xyz"^^xsd:ID .
    """
    store = _store_from_ttl(ttl)
    violations = _detect_bad_datatypes(store, None)
    # Should have at least one violation
    assert len(violations) >= 1
    # The subject_iri should be the individual (:a1), NOT the datatype xsd:ID
    subject_iris = {v.subject_iri for v in violations}
    assert "http://www.w3.org/2001/XMLSchema#ID" not in subject_iris, (
        "subject_iri should NOT be the datatype IRI — it should be the axiom subject"
    )
    # Check that one of the subjects is the individual
    assert any("a1" in (s or "") for s in subject_iris), (
        f"Expected :a1 in subjects, got {subject_iris}"
    )
    # Details should still mention the bad datatype
    details = {v.details for v in violations}
    assert any("ID" in (d or "") for d in details), (
        f"Expected 'ID' in details, got {details}"
    )


def test_bad_datatype_violation_has_manchester():
    """_detect_bad_datatypes produces violations with manchester field."""
    ttl = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix :     <http://example.org/> .
    :A a owl:Class .
    :a1 a :A ;
        :hasIdentifier "xyz"^^xsd:ID .
    """
    store = _store_from_ttl(ttl)
    # Use detect_profiles so we go through the Manchester rendering step
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    dl_samples = result["dl"]["sample_violations"]
    dt_samples = [s for s in dl_samples if s["axiom_type"] == "unsupported-datatype"]
    assert len(dt_samples) > 0
    sample = dt_samples[0]
    assert "manchester" in sample
    # The manchester content should be useful (not just the datatype IRI)
    if sample["manchester"]:
        text = "".join(
            t["v"] if t["t"] == "text" else t.get("label", t.get("iri", ""))
            for t in sample["manchester"]
        )
        # Should contain the predicate or value in some recognizable form
        assert len(text) > 0, "Manchester text should be non-empty"


# ---------------------------------------------------------------------------
# Test 4: manchester tokens are JSON-serializable dicts (not TypedDicts)
# ---------------------------------------------------------------------------

def test_manchester_tokens_are_json_serializable():
    """Tokens in sample_violations must be plain dicts that can round-trip through JSON."""
    import json
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :p a owl:ObjectProperty ; owl:inverseOf :q .
    :q a owl:ObjectProperty .
    """
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    el_samples = result["el"]["sample_violations"]
    samples = [s for s in el_samples if s["axiom_type"] == "owl:inverseOf"]
    assert samples
    sample = samples[0]
    # Should not raise
    serialized = json.dumps(sample)
    parsed = json.loads(serialized)
    assert parsed["manchester"] == sample["manchester"]
