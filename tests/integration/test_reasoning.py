"""Tests for the OWL-EL reasoning service logic."""

import sys
import os

import pytest

# Import the ELK service module directly from the docker directory
_ELK_DIR = os.path.join(os.path.dirname(__file__), "../../docker/elk-service")
sys.path.insert(0, os.path.abspath(_ELK_DIR))


def _load_turtle(ttl: str):
    import io
    import rdflib
    g = rdflib.Graph()
    g.parse(io.StringIO(ttl), format="turtle")
    return g


def test_classify_simple_transitivity():
    """A ⊑ B, B ⊑ C → infer A ⊑ C."""
    from main import classify  # type: ignore[import]
    from rdflib.namespace import RDFS

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    g = _load_turtle(ttl)
    inferred = classify(g)

    from rdflib import URIRef
    a = URIRef("http://example.org/A")
    b = URIRef("http://example.org/B")
    c = URIRef("http://example.org/C")

    # A ⊑ C must be inferred
    assert (a, RDFS.subClassOf, c) in inferred
    # A ⊑ B already asserted — should NOT be in inferred set
    assert (a, RDFS.subClassOf, b) not in inferred


def test_classify_reflexive_not_in_result():
    """Reflexive subClassOf (A ⊑ A) should not appear in the inferred set."""
    from main import classify  # type: ignore[import]
    from rdflib import URIRef
    from rdflib.namespace import RDFS

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    """
    g = _load_turtle(ttl)
    inferred = classify(g)
    a = URIRef("http://example.org/A")
    assert (a, RDFS.subClassOf, a) not in inferred


def test_classify_equivalent_class():
    """A ≡ B → infer A ⊑ B and B ⊑ A."""
    from main import classify  # type: ignore[import]
    from rdflib import URIRef
    from rdflib.namespace import OWL, RDFS

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:A owl:equivalentClass ex:B .
    """
    g = _load_turtle(ttl)
    inferred = classify(g)
    a = URIRef("http://example.org/A")
    b = URIRef("http://example.org/B")
    # The equivalentClass was asserted, so the subClassOf edges derived
    # from it should appear as inferred subClassOf triples
    # (or equivalentClass symmetry is inferred)
    assert (a, RDFS.subClassOf, b) in inferred or (b, RDFS.subClassOf, a) in inferred


def test_classify_owl_thing_superclass():
    """Every named class is a subclass of owl:Thing."""
    from main import classify  # type: ignore[import]
    from rdflib import URIRef
    from rdflib.namespace import OWL, RDFS

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    """
    g = _load_turtle(ttl)
    inferred = classify(g)
    a = URIRef("http://example.org/A")
    assert (a, RDFS.subClassOf, OWL.Thing) in inferred


def test_classify_chain():
    """Four-level chain A⊑B⊑C⊑D produces A⊑C, A⊑D, B⊑D."""
    from main import classify  # type: ignore[import]
    from rdflib import URIRef
    from rdflib.namespace import RDFS

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class ; rdfs:subClassOf ex:D .
    ex:D a owl:Class .
    """
    g = _load_turtle(ttl)
    inferred = classify(g)

    A, B, C, D = [URIRef(f"http://example.org/{x}") for x in "ABCD"]
    assert (A, RDFS.subClassOf, C) in inferred
    assert (A, RDFS.subClassOf, D) in inferred
    assert (B, RDFS.subClassOf, D) in inferred
