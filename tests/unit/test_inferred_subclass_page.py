"""Paged inferred subClassOf axioms scan the predicate index, not ORDER BY.

The endpoint used to `SELECT ... ORDER BY ?sub ?sup LIMIT/OFFSET`, sorting the
whole :inferred graph before paging — >59 s on sphn's 404k-triple graph. The
replacement (inferred_subclass_page) scans the predicate-bound index and windows
it. These pin the behaviour it must preserve: IRI-only, graph-scoped, stable
pagination, cheap window.
"""
import pyoxigraph
import pytest

from ontoexplorer.clients.oxigraph import inferred_subclass_page

SUB = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
G = "urn:ontology:o1:v1:inferred"
OTHER_G = "urn:ontology:o1:v1"


def _iri(n):
    return pyoxigraph.NamedNode(f"http://ex.org/C{n:03d}")


@pytest.fixture
def store():
    s = pyoxigraph.Store()
    g = pyoxigraph.NamedNode(G)
    # 10 IRI–IRI subClassOf quads in the inferred graph
    for i in range(10):
        s.add(pyoxigraph.Quad(_iri(i), SUB, _iri(i + 100), g))
    # noise that must be excluded:
    s.add(pyoxigraph.Quad(pyoxigraph.BlankNode("b1"), SUB, _iri(1), g))       # blank subject
    s.add(pyoxigraph.Quad(_iri(2), SUB, pyoxigraph.Literal("x"), g))          # literal object
    s.add(pyoxigraph.Quad(_iri(3), pyoxigraph.NamedNode("http://ex/p"), _iri(4), g))  # other predicate
    s.add(pyoxigraph.Quad(_iri(5), SUB, _iri(6), pyoxigraph.NamedNode(OTHER_G)))      # other graph
    return s


def test_returns_only_iri_iri_pairs_in_this_graph(store):
    page = inferred_subclass_page(store, G, offset=0, limit=1000)
    assert len(page) == 10, "should return exactly the 10 IRI-IRI subClassOf quads"
    assert all(set(p) == {"subClass", "superClass"} for p in page)
    assert all(p["subClass"].startswith("http://ex.org/C") for p in page)
    # blank/literal/other-predicate/other-graph noise excluded
    supers = {p["superClass"] for p in page}
    assert "x" not in supers


def test_pagination_windows_and_is_stable(store):
    full = inferred_subclass_page(store, G, 0, 1000)
    p1 = inferred_subclass_page(store, G, 0, 4)
    p2 = inferred_subclass_page(store, G, 4, 4)
    p3 = inferred_subclass_page(store, G, 8, 4)
    assert p1 + p2 + p3 == full, "windows must tile the full result in the same order"
    assert len(p1) == 4 and len(p3) == 2
    # deterministic across repeated calls (immutable graph)
    assert inferred_subclass_page(store, G, 0, 1000) == full


def test_offset_past_end_is_empty(store):
    assert inferred_subclass_page(store, G, offset=100, limit=10) == []


def test_empty_graph_returns_empty(store):
    assert inferred_subclass_page(store, "urn:ontology:o1:v1:inferred:nonesuch", 0, 10) == []
