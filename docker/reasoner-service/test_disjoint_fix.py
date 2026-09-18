"""Tests for the owl:AllDisjointClasses reader work-around (disjoint_fix).

horned-owl's RDF reader drops owl:AllDisjointClasses, which made defined-class
subsumptions that depend on disjointness (e.g. the four-cheese pizza) go
un-inferred. These cover the pure-string injectors, the RDF group extractor, and
the end-to-end rustdl classification of the pizza case.
"""
from __future__ import annotations

import pytest

import disjoint_fix

P = "https://w3id.org/ontostart/pizza/"
HDP = "https://w3id.org/sulo/hasDirectPart"
CHEESES = ["Mozzarella", "Gorgonzola", "Parmesan", "PecorinoRomano"]


# ── pure-string injectors (no RDF deps) ────────────────────────────────────────

def test_inject_ofn_disjointness_appends_before_close():
    ofn = "Ontology(<http://ex/o>\n    Declaration(Class(<http://ex/A>))\n)\n"
    out = disjoint_fix.inject_ofn_disjointness(ofn, [["http://ex/A", "http://ex/B", "http://ex/C"]])
    assert "DisjointClasses(<http://ex/A> <http://ex/B> <http://ex/C>)" in out
    # The axiom must land inside the ontology, before the closing paren.
    assert out.rstrip().endswith(")")
    assert out.index("DisjointClasses") < out.rstrip().rindex(")")


def test_inject_ofn_strips_imports():
    ofn = "Ontology(<http://ex/o>\n    Import(<http://ex/other>)\n    Declaration(Class(<http://ex/A>))\n)\n"
    out = disjoint_fix.inject_ofn_disjointness(ofn, [])
    assert "Import(" not in out
    assert "Declaration(Class(<http://ex/A>))" in out


def test_inject_owx_disjointness_before_close_tag():
    owx = '<?xml version="1.0"?><Ontology xmlns="http://www.w3.org/2002/07/owl#"></Ontology>'
    out = disjoint_fix.inject_owx_disjointness(owx, [["http://ex/A", "http://ex/B"]])
    assert '<DisjointClasses><Class IRI="http://ex/A"/><Class IRI="http://ex/B"/></DisjointClasses>' in out
    assert out.index("DisjointClasses") < out.index("</Ontology>")


def test_inject_noop_when_no_groups():
    owx = "<Ontology></Ontology>"
    assert disjoint_fix.inject_owx_disjointness(owx, []) == owx


# ── RDF group extraction (needs pyoxigraph) ────────────────────────────────────

def test_all_disjoint_class_groups_reads_members_list():
    pyoxigraph = pytest.importorskip("pyoxigraph")
    import io
    nt = (
        f"_:d <{disjoint_fix._RDF}type> <{disjoint_fix._OWL}AllDisjointClasses> .\n"
        f"_:d <{disjoint_fix._OWL}members> _:l1 .\n"
        f"_:l1 <{disjoint_fix._RDF}first> <{P}A> .\n"
        f"_:l1 <{disjoint_fix._RDF}rest> _:l2 .\n"
        f"_:l2 <{disjoint_fix._RDF}first> <{P}B> .\n"
        f"_:l2 <{disjoint_fix._RDF}rest> _:l3 .\n"
        f"_:l3 <{disjoint_fix._RDF}first> <{P}C> .\n"
        f"_:l3 <{disjoint_fix._RDF}rest> <{disjoint_fix._RDF}nil> .\n"
    )
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    assert disjoint_fix.has_all_disjoint_classes(store) is True
    groups = disjoint_fix.all_disjoint_class_groups(store)
    assert len(groups) == 1
    assert set(groups[0]) == {f"{P}A", f"{P}B", f"{P}C"}


def test_no_groups_when_absent():
    pyoxigraph = pytest.importorskip("pyoxigraph")
    import io
    nt = f"<{P}A> <{disjoint_fix._RDF}type> <{disjoint_fix._OWL}Class> .\n"
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    assert disjoint_fix.has_all_disjoint_classes(store) is False
    assert disjoint_fix.all_disjoint_class_groups(store) == []


# ── end-to-end: the pizza four-cheese case ─────────────────────────────────────

def _four_cheese_ntriples() -> str:
    """Build the four-cheese ontology as N-Triples, with disjointness stated via
    owl:AllDisjointClasses (exactly as OBO tooling emits it) — the shape that
    horned-owl's RDF reader drops."""
    rdflib = pytest.importorskip("rdflib")
    from rdflib import Graph, BNode, Literal, URIRef
    from rdflib.namespace import RDF, RDFS, OWL, XSD
    from rdflib.collection import Collection

    g = Graph()
    C = lambda n: URIRef(P + n)  # noqa: E731
    hdp = URIRef(HDP)
    g.add((hdp, RDF.type, OWL.ObjectProperty))
    for n in ["Pizza", "Cheese", *CHEESES, "FourCheesePizza", "TraditionalFourCheesePizza"]:
        g.add((C(n), RDF.type, OWL.Class))
    for n in CHEESES:
        g.add((C(n), RDFS.subClassOf, C("Cheese")))

    adc, lst = BNode(), BNode()
    g.add((adc, RDF.type, OWL.AllDisjointClasses))
    Collection(g, lst, [C(n) for n in CHEESES])
    g.add((adc, OWL.members, lst))

    def qcard(n: int, cls) -> BNode:
        r = BNode()
        g.add((r, RDF.type, OWL.Restriction))
        g.add((r, OWL.onProperty, hdp))
        g.add((r, OWL.qualifiedCardinality, Literal(n, datatype=XSD.nonNegativeInteger)))
        g.add((r, OWL.onClass, cls))
        return r

    def intersection(parts) -> BNode:
        ce, il = BNode(), BNode()
        g.add((ce, RDF.type, OWL.Class))
        Collection(g, il, parts)
        g.add((ce, OWL.intersectionOf, il))
        return ce

    # FourCheesePizza ≡ Pizza ⊓ (=4 hasDirectPart.Cheese)
    g.add((C("FourCheesePizza"), OWL.equivalentClass,
           intersection([C("Pizza"), qcard(4, C("Cheese"))])))

    # closure: ∀hasDirectPart.(Mozzarella ⊔ Gorgonzola ⊔ Parmesan ⊔ PecorinoRomano)
    union_ce, ul = BNode(), BNode()
    g.add((union_ce, RDF.type, OWL.Class))
    Collection(g, ul, [C(n) for n in CHEESES])
    g.add((union_ce, OWL.unionOf, ul))
    closure = BNode()
    g.add((closure, RDF.type, OWL.Restriction))
    g.add((closure, OWL.onProperty, hdp))
    g.add((closure, OWL.allValuesFrom, union_ce))

    trad_parts = [C("Pizza")] + [qcard(1, C(n)) for n in CHEESES] + [closure]
    g.add((C("TraditionalFourCheesePizza"), OWL.equivalentClass, intersection(trad_parts)))

    return g.serialize(format="nt")


def test_rustdl_classifies_four_cheese_with_alldisjoint():
    """The regression: Traditional ⊑ FourCheese must be inferred. It only holds
    once the dropped AllDisjointClasses is reinstated by the fix."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("pyhornedowl")
    pytest.importorskip("rustdl")
    from rustdl_backend import RustdlBackend

    nt = _four_cheese_ntriples()
    result = RustdlBackend().classify_ntriples(nt, "test-four-cheese")
    supers = result.superclasses.get(P + "TraditionalFourCheesePizza", [])
    assert P + "FourCheesePizza" in supers, (
        "TraditionalFourCheesePizza should be inferred ⊑ FourCheesePizza "
        f"(AllDisjointClasses reinstated); got superclasses={supers}"
    )


def test_rustdl_falls_back_when_disjoint_builder_panics(monkeypatch):
    """A pyo3 PanicException in the OWL/XML builder (py-horned-owl serializer
    panics on some multi-byte UTF-8) must NOT kill the classify — it must degrade
    to the plain RDF path. PanicException is a BaseException, not an Exception, so
    the backend catches BaseException; this guards that wiring."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("pyhornedowl")
    pytest.importorskip("rustdl")
    import disjoint_fix
    from rustdl_backend import RustdlBackend

    class FakePanic(BaseException):
        pass

    def boom(*_a, **_k):
        raise FakePanic("simulated serializer panic")

    monkeypatch.setattr(disjoint_fix, "owl_xml_with_disjointness_from_rdf", boom)

    nt = _four_cheese_ntriples()
    # Must return a valid classification (via the rdf-xml fallback) rather than
    # raising. The fallback drops the disjointness, so the subsumption is absent —
    # the point of this test is that it did not crash.
    result = RustdlBackend().classify_ntriples(nt, "test-fallback")
    assert result.class_count > 0
    supers = result.superclasses.get(P + "TraditionalFourCheesePizza", [])
    assert P + "FourCheesePizza" not in supers
