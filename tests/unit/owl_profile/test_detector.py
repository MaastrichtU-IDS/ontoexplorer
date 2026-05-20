"""Unit tests for ontoexplorer.modules.owl_profile.detector.detect_profiles."""
import pyoxigraph
from ontoexplorer.modules.owl_profile.detector import detect_profiles


def _store_from_ttl(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), pyoxigraph.RdfFormat.TURTLE)
    return s


def test_pure_subclass_in_all_profiles():
    ttl = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/x#> .
:A a owl:Class . :B a owl:Class ; rdfs:subClassOf :A ."""
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    for p in ("el", "rl", "ql", "dl"):
        assert result[p]["in_profile"] is True


def test_inverse_of_violates_el_but_not_dl():
    ttl = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix : <http://example.org/x#> .
:p a owl:ObjectProperty ; owl:inverseOf :q .
:q a owl:ObjectProperty ."""
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    assert result["el"]["in_profile"] is False
    assert "owl:inverseOf" in result["el"]["violations_by_axiom_type"]
    assert result["dl"]["in_profile"] is True  # inverseOf is allowed in DL


def test_punning_violates_dl():
    ttl = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix : <http://example.org/x#> .
:p a owl:ObjectProperty, owl:AnnotationProperty ."""
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    assert result["dl"]["in_profile"] is False
    assert "punning" in result["dl"]["violations_by_axiom_type"]


def test_indexed_at_iso_format():
    store = pyoxigraph.Store()
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    assert "indexed_at" in result
    assert "T" in result["indexed_at"]  # ISO datetime separator


def test_dl_violation_propagates_to_subprofiles():
    """OWL 2 EL/RL/QL are strict subsets of OWL 2 DL. An ontology that's not
    in DL cannot be in EL/RL/QL either, even if no EL/RL/QL-specific patterns
    matched. Verifies the propagation in detect_profiles."""
    ttl = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix : <http://example.org/x#> .
:p a owl:ObjectProperty, owl:AnnotationProperty ."""
    store = _store_from_ttl(ttl)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    # DL: punning violation
    assert result["dl"]["in_profile"] is False
    assert "punning" in result["dl"]["violations_by_axiom_type"]
    # EL/RL/QL: must propagate to False even though no profile-specific
    # patterns matched (no profile-specific violations recorded)
    for p in ("el", "rl", "ql"):
        assert result[p]["in_profile"] is False, (
            f"{p} must be False when DL is False (EL/RL/QL ⊂ DL)"
        )


def test_empty_store_all_profiles_clean():
    store = pyoxigraph.Store()
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    for p in ("el", "rl", "ql", "dl"):
        assert result[p]["in_profile"] is True
        assert result[p]["total_violations"] == 0
        assert result[p]["sample_violations"] == []


def test_result_shape_complete():
    """All four profiles present with required keys."""
    store = pyoxigraph.Store()
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    assert set(result.keys()) == {"el", "rl", "ql", "dl", "indexed_at"}
    for p in ("el", "rl", "ql", "dl"):
        assert "in_profile" in result[p]
        assert "total_violations" in result[p]
        assert "violations_by_axiom_type" in result[p]
        assert "sample_violations" in result[p]


def test_sample_violations_capped_at_50():
    """Sample violations list must not exceed 50 entries per profile."""
    # Build an ontology with many disjoint pairs to generate lots of EL violations
    prefixes = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n@prefix : <http://example.org/x#> .\n"
    triples = ""
    for i in range(60):
        triples += f":C{i} a owl:Class .\n"
        triples += f":C{i} owl:disjointWith :C{i}extra .\n"
    store = _store_from_ttl(prefixes + triples)
    result = detect_profiles(store, graph_iri=None, ontology_id="t", version_id="v")
    assert len(result["el"]["sample_violations"]) <= 50
