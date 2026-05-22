"""Tests for the OWL-EL reasoning service logic."""

import sys
import os


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
    from classifier import classify  # type: ignore[import]

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    g = _load_turtle(ttl)
    result = classify(g, "v1")

    a = "http://example.org/A"
    b = "http://example.org/B"
    c = "http://example.org/C"

    assert c in result.superclasses[a]
    assert b not in result.superclasses[a]  # asserted, not inferred


def test_classify_reflexive_not_in_result():
    """Reflexive subClassOf (A ⊑ A) should not appear in the inferred set."""
    from classifier import classify  # type: ignore[import]

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    """
    g = _load_turtle(ttl)
    result = classify(g, "v1")
    a = "http://example.org/A"
    assert a not in result.superclasses.get(a, [])


def test_classify_equivalent_class():
    """A ≡ B → infer A ⊑ B and B ⊑ A."""
    from classifier import classify  # type: ignore[import]

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:A owl:equivalentClass ex:B .
    """
    g = _load_turtle(ttl)
    result = classify(g, "v1")
    a = "http://example.org/A"
    b = "http://example.org/B"
    # equivalentClass-derived subClassOf edges land in direct_superclasses (asserted)
    all_a = result.superclasses.get(a, []) + result.direct_superclasses.get(a, [])
    all_b = result.superclasses.get(b, []) + result.direct_superclasses.get(b, [])
    assert b in all_a or a in all_b


def test_classify_owl_thing_superclass():
    """Every named class is a subclass of owl:Thing."""
    from classifier import classify  # type: ignore[import]

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    """
    g = _load_turtle(ttl)
    result = classify(g, "v1")
    a = "http://example.org/A"
    assert "http://www.w3.org/2002/07/owl#Thing" in result.superclasses[a]


def test_classify_chain():
    """Four-level chain A⊑B⊑C⊑D produces A⊑C, A⊑D, B⊑D."""
    from classifier import classify  # type: ignore[import]

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
    result = classify(g, "v1")

    A, B, C, D = [f"http://example.org/{x}" for x in "ABCD"]
    assert C in result.superclasses[A]
    assert D in result.superclasses[A]
    assert D in result.superclasses[B]


def test_cr3_conjunction_via_service():
    """CR3: A ⊑ intersectionOf(B, C) → infer A ⊑ B and A ⊑ C."""
    import io
    import rdflib
    sys.path.insert(0, _ELK_DIR)
    from classifier import classify  # type: ignore[import]

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:BC a owl:Class ; owl:intersectionOf ( ex:B ex:C ) .
    ex:A rdfs:subClassOf ex:BC .
    """
    g = rdflib.Graph()
    g.parse(io.StringIO(ttl), format="turtle")
    result = classify(g, "v-cr3")
    a = "http://example.org/A"
    assert "http://example.org/B" in result.superclasses.get(a, [])
    assert "http://example.org/C" in result.superclasses.get(a, [])


def test_cr6_unsatisfiable_via_service():
    """CR6: disjointWith creates unsatisfiable class."""
    import io
    import rdflib
    sys.path.insert(0, _ELK_DIR)
    from classifier import classify  # type: ignore[import]

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """
    g = rdflib.Graph()
    g.parse(io.StringIO(ttl), format="turtle")
    result = classify(g, "v-cr6")
    assert "http://example.org/A" in result.unsatisfiable
