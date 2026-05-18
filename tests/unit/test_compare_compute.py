"""Unit tests for ontoexplorer.modules.compare.compute.run_comparison."""
import pyoxigraph as ox

from ontoexplorer.modules.compare.compute import run_comparison

OID_A = "ont-a"
OID_B = "ont-b"
VID_A = "vA"
VID_B = "vB"

_OWL_CLASS = ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
_RDF_TYPE  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_RDFS_LBL  = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
_RDFS_SC   = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")


def _store(*, a_quads: list[tuple], b_quads: list[tuple]) -> ox.Store:
    """Build an in-memory store with two named graphs, one per ontology."""
    store = ox.Store()
    g_a = ox.NamedNode(f"urn:ontology:{OID_A}:{VID_A}")
    g_b = ox.NamedNode(f"urn:ontology:{OID_B}:{VID_B}")
    store.add_graph(g_a)
    store.add_graph(g_b)
    for s, p, o in a_quads:
        store.add(ox.Quad(s, p, o, g_a))
    for s, p, o in b_quads:
        store.add(ox.Quad(s, p, o, g_b))
    return store


def test_run_comparison_all_disjoint():
    """Two ontologies with no shared IRIs: everything lands in added/removed."""
    cls_a = ox.NamedNode("http://a.org/Foo")
    cls_b = ox.NamedNode("http://b.org/Bar")
    s = _store(
        a_quads=[(cls_a, _RDF_TYPE, _OWL_CLASS)],
        b_quads=[(cls_b, _RDF_TYPE, _OWL_CLASS)],
    )
    summary, diff_data = run_comparison(s, OID_A, VID_A, OID_B, VID_B)
    assert summary["added"] == 1
    assert summary["removed"] == 1
    assert summary["modified"] == 0
    assert diff_data["added"][0]["iri"] == cls_b.value
    assert diff_data["removed"][0]["iri"] == cls_a.value


def test_run_comparison_shared_iri_axioms_differ():
    """Same IRI declared as owl:Class in both, but axioms differ → modified."""
    cls = ox.NamedNode("http://shared.org/Thing")
    parent_a = ox.NamedNode("http://shared.org/ParentA")
    parent_b = ox.NamedNode("http://shared.org/ParentB")
    s = _store(
        a_quads=[
            (cls, _RDF_TYPE, _OWL_CLASS),
            (cls, _RDFS_SC, parent_a),
        ],
        b_quads=[
            (cls, _RDF_TYPE, _OWL_CLASS),
            (cls, _RDFS_SC, parent_b),
        ],
    )
    summary, diff_data = run_comparison(s, OID_A, VID_A, OID_B, VID_B)
    assert summary["modified"] == 1
    assert summary["axiom_changes"] == 1
    m = diff_data["modified"][0]
    assert m["iri"] == cls.value
    ops = {ac["op"] for ac in m["axiom_changes"]}
    assert ops == {"added", "removed"}


def test_run_comparison_same_ontology_same_version_yields_no_changes():
    """Comparing an ontology to itself (same graph IRIs) produces zero changes —
    sanity check that run_comparison composes correctly with _run_diff_core."""
    cls = ox.NamedNode("http://a.org/Foo")
    quads = [(cls, _RDF_TYPE, _OWL_CLASS), (cls, _RDFS_LBL, ox.Literal("Foo"))]
    s = _store(a_quads=quads, b_quads=quads)
    # Force same graph IRI on both sides by reusing OID_A/VID_A
    summary, diff_data = run_comparison(s, OID_A, VID_A, OID_A, VID_A)
    assert summary["added"] == 0
    assert summary["removed"] == 0
    assert summary["modified"] == 0
