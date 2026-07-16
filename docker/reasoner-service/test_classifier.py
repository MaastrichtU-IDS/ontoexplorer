"""Unit tests for the enhanced OWL-EL classifier."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import io
import rdflib
from rdflib.namespace import OWL, RDFS, RDF
from rdflib import URIRef

EX = "http://example.org/"

def g(ttl: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(io.StringIO(ttl), format="turtle")
    return graph


def test_cr2_transitivity():
    """A ⊑ B, B ⊑ C → infer A ⊑ C."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses[f"{EX}A"]
    assert f"{EX}C" in sups
    assert str(OWL.Thing) in sups
    assert f"{EX}B" not in sups  # asserted, not inferred


def test_cr3_conjunction():
    """A ⊑ B ⊓ C → infer A ⊑ B and A ⊑ C."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:BC a owl:Class ;
          owl:intersectionOf ( ex:B ex:C ) .
    ex:A rdfs:subClassOf ex:BC .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses[f"{EX}A"]
    assert f"{EX}B" in sups
    assert f"{EX}C" in sups


def test_cr4_existential_propagation():
    """If ∃r.B ⊑ D and A ⊑ ∃r.B, then A ⊑ D."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:D a owl:Class .
    ex:r a owl:ObjectProperty .
    ex:A rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty ex:r ;
        owl:someValuesFrom ex:B
    ] .
    [ a owl:Restriction ;
      owl:onProperty ex:r ;
      owl:someValuesFrom ex:B ] rdfs:subClassOf ex:D .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses.get(f"{EX}A", [])
    assert f"{EX}D" in sups


def test_cr5_role_hierarchy():
    """r ⊑ s: ∃r.A ⊑ ∃s.A — propagate existentials up role hierarchy."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:r a owl:ObjectProperty ; rdfs:subPropertyOf ex:s .
    ex:s a owl:ObjectProperty .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:A rdfs:subClassOf [
        a owl:Restriction ; owl:onProperty ex:r ; owl:someValuesFrom ex:B
    ] .
    [ a owl:Restriction ; owl:onProperty ex:s ; owl:someValuesFrom ex:B ]
        rdfs:subClassOf ex:C .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses.get(f"{EX}A", [])
    assert f"{EX}C" in sups


def test_cr6_unsatisfiable():
    """A ⊑ B and A ⊑ ¬B (DisjointWith) → A is unsatisfiable."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """
    result = classify(g(ttl), "v1")
    assert f"{EX}A" in result.unsatisfiable


def test_proof_trace_recorded():
    """Every inferred axiom has an entry in proof_traces."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    result = classify(g(ttl), "v1")
    key = f"{EX}A|{EX}C"
    assert key in result.proof_traces
    step = result.proof_traces[key][0]
    assert step["rule"] == "CR2"
    assert "axioms" in step
    assert len(step["axioms"]) >= 2


def test_direct_superclasses_only_one_hop():
    """direct_superclasses contains only immediately asserted parents."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    result = classify(g(ttl), "v1")
    assert result.direct_superclasses[f"{EX}A"] == [f"{EX}B"]
    assert f"{EX}C" not in result.direct_superclasses[f"{EX}A"]


def test_cache_round_trip(tmp_path, monkeypatch):
    """ClassificationResult serialises to/from Redis correctly."""
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)

    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class .
    """
    result = classify(g(ttl), "test-version")
    cache_mod.store_classification(result, "rdflib")
    loaded = cache_mod.load_classification("test-version", "rdflib")
    assert loaded is not None
    assert loaded.class_count == result.class_count
    assert loaded.superclasses == result.superclasses


def test_cache_miss_returns_none(monkeypatch):
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)
    assert cache_mod.load_classification("no-such-version", "rdflib") is None


def test_justification_simple():
    """Justification for A ⊑ C (via A ⊑ B, B ⊑ C) is exactly those two axioms."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class ; rdfs:subClassOf ex:D .
    ex:D a owl:Class .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=1)
    assert len(justs) == 1
    j = justs[0]
    # Must contain A ⊑ B and B ⊑ C; must NOT contain B ⊑ D or C ⊑ D
    axiom_strs = " ".join(j)
    assert f"{EX}A" in axiom_strs
    assert f"{EX}B" in axiom_strs
    assert f"{EX}C" in axiom_strs
    # Minimality: exactly 2 axioms
    assert len(j) == 2


def test_justification_minimality():
    """Removing any axiom from a justification breaks the inference."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=1)
    assert len(justs) == 1
    j = justs[0]
    for i in range(len(j)):
        reduced = j[:i] + j[i+1:]
        reduced_g = rdflib.Graph()
        for ax in reduced:
            try:
                reduced_g.parse(data=ax, format="nt")
            except Exception:
                pass
        reduced_result = classify(reduced_g, "v1")
        sups = reduced_result.superclasses.get(f"{EX}A", [])
        assert f"{EX}C" not in sups, f"Axiom {i} was not load-bearing"


def test_multiple_justifications():
    """Two independent paths yield two distinct justifications."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:X .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:X a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=0)
    assert len(justs) == 2
    # Justifications should be different sets
    assert set(justs[0]) != set(justs[1])


def test_justification_unsatisfiable():
    """Justification for unsatisfiability contains the disjointness axiom."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", str(OWL.Nothing), max_justifications=1)
    assert len(justs) >= 1
    axiom_strs = " ".join(justs[0])
    assert "disjointWith" in axiom_strs
