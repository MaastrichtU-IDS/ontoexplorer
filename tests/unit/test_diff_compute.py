"""Unit tests for the ontology diff compute module.

Uses an in-memory pyoxigraph.Store — no mocking needed.
"""
import pyoxigraph as ox
import pytest

from ontoexplorer.modules.diff.compute import run_diff

OID = "test-ont"
FROM_VID = "v1"
TO_VID = "v2"

_OWL_CLASS = ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
_RDF_TYPE  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_RDFS_LBL  = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
_RDFS_SC   = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")


def _store(from_quads: list[tuple], to_quads: list[tuple]) -> ox.Store:
    """Build an in-memory store with two named graphs."""
    store = ox.Store()
    from_g = ox.NamedNode(f"urn:ontology:{OID}:{FROM_VID}")
    to_g   = ox.NamedNode(f"urn:ontology:{OID}:{TO_VID}")
    store.add_graph(from_g)
    store.add_graph(to_g)
    for s, p, o in from_quads:
        store.add(ox.Quad(s, p, o, from_g))
    for s, p, o in to_quads:
        store.add(ox.Quad(s, p, o, to_g))
    return store


def test_added_class():
    iri = ox.NamedNode("http://example.org/NewClass")
    s = _store(
        from_quads=[],
        to_quads=[
            (iri, _RDF_TYPE, _OWL_CLASS),
            (iri, _RDFS_LBL, ox.Literal("New Class")),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["added"] == 1
    assert summary["removed"] == 0
    assert summary["modified"] == 0
    assert diff_data["added"][0]["iri"] == str(iri.value)
    assert diff_data["added"][0]["entity_type"] == "class"
    assert diff_data["added"][0]["label"] == "New Class"


def test_removed_class():
    iri = ox.NamedNode("http://example.org/OldClass")
    s = _store(
        from_quads=[(iri, _RDF_TYPE, _OWL_CLASS)],
        to_quads=[],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["removed"] == 1
    assert diff_data["removed"][0]["iri"] == str(iri.value)


def test_label_change():
    iri = ox.NamedNode("http://example.org/ChangedClass")
    shared = [(iri, _RDF_TYPE, _OWL_CLASS)]
    s = _store(
        from_quads=shared + [(iri, _RDFS_LBL, ox.Literal("Old Label", language="en"))],
        to_quads=shared   + [(iri, _RDFS_LBL, ox.Literal("New Label", language="en"))],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    assert summary["literal_changes"] == 1
    assert summary["axiom_changes"] == 0
    m = diff_data["modified"][0]
    assert m["iri"] == str(iri.value)
    lc = m["literal_changes"][0]
    assert lc["removed"] == "Old Label"
    assert lc["added"] == "New Label"
    assert lc["lang"] == "en"
    assert lc["predicate"] == str(_RDFS_LBL.value)


def test_axiom_change():
    iri        = ox.NamedNode("http://example.org/MovedClass")
    parent_old = ox.NamedNode("http://example.org/ParentOld")
    parent_new = ox.NamedNode("http://example.org/ParentNew")
    shared = [(iri, _RDF_TYPE, _OWL_CLASS)]
    s = _store(
        from_quads=shared + [(iri, _RDFS_SC, parent_old)],
        to_quads=shared   + [(iri, _RDFS_SC, parent_new)],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    assert summary["axiom_changes"] == 1
    assert summary["literal_changes"] == 0
    m = diff_data["modified"][0]
    ops = {ac["op"] for ac in m["axiom_changes"]}
    assert ops == {"added", "removed"}


def test_unchanged_class_omitted():
    iri = ox.NamedNode("http://example.org/Stable")
    quads = [(iri, _RDF_TYPE, _OWL_CLASS), (iri, _RDFS_LBL, ox.Literal("Stable"))]
    s = _store(quads, quads)
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 0
    assert summary["added"] == 0
    assert summary["removed"] == 0


def test_by_entity_type_counts():
    cls = ox.NamedNode("http://example.org/C")
    prop = ox.NamedNode("http://example.org/P")
    _OWL_OBJ_PROP = ox.NamedNode("http://www.w3.org/2002/07/owl#ObjectProperty")
    s = _store(
        from_quads=[],
        to_quads=[
            (cls,  _RDF_TYPE, _OWL_CLASS),
            (prop, _RDF_TYPE, _OWL_OBJ_PROP),
        ],
    )
    summary, _ = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["by_entity_type"]["class"]["added"] == 1
    assert summary["by_entity_type"]["object_property"]["added"] == 1


def test_literal_lang_tag_change():
    """run_diff must not crash when a literal gains or loses a language tag."""
    iri = ox.NamedNode("http://example.org/TaggedClass")
    shared = [(iri, _RDF_TYPE, _OWL_CLASS)]
    s = _store(
        from_quads=shared + [(iri, _RDFS_LBL, ox.Literal("Foo"))],          # no lang tag
        to_quads=shared   + [(iri, _RDFS_LBL, ox.Literal("Foo", language="en"))],  # with lang tag
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    assert summary["literal_changes"] == 1
    m = diff_data["modified"][0]
    assert len(m["literal_changes"]) == 2  # removed untagged, added tagged
