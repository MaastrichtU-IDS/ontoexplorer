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


_OWL_RESTRICTION  = ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")
_OWL_ON_PROPERTY  = ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty")
_OWL_SOME_VALUES  = ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom")


def test_bnode_restriction_with_different_ids_is_not_a_diff():
    """Two structurally identical owl:Restriction bnodes (different IDs) must not appear as a diff."""
    pizza = ox.NamedNode("http://example.org/Pizza")
    hasTopping = ox.NamedNode("http://example.org/hasTopping")
    tomato = ox.NamedNode("http://example.org/Tomato")

    # FROM: restriction is bnode "b1"
    b1 = ox.BlankNode("b1")
    from_quads = [
        (pizza, _RDF_TYPE, _OWL_CLASS),
        (pizza, _RDFS_SC, b1),
        (b1, _RDF_TYPE, _OWL_RESTRICTION),
        (b1, _OWL_ON_PROPERTY, hasTopping),
        (b1, _OWL_SOME_VALUES, tomato),
    ]
    # TO: same restriction but bnode is "different_id_xyz"
    b2 = ox.BlankNode("different_id_xyz")
    to_quads = [
        (pizza, _RDF_TYPE, _OWL_CLASS),
        (pizza, _RDFS_SC, b2),
        (b2, _RDF_TYPE, _OWL_RESTRICTION),
        (b2, _OWL_ON_PROPERTY, hasTopping),
        (b2, _OWL_SOME_VALUES, tomato),
    ]
    s = _store(from_quads=from_quads, to_quads=to_quads)
    summary, _ = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 0, "structurally identical restrictions must not diff on bnode id"
    assert summary["added"] == 0
    assert summary["removed"] == 0


def test_bnode_restriction_with_real_change_is_detected():
    """Genuine difference inside a bnode restriction (different filler) must surface as a diff."""
    pizza = ox.NamedNode("http://example.org/Pizza")
    hasTopping = ox.NamedNode("http://example.org/hasTopping")
    tomato = ox.NamedNode("http://example.org/Tomato")
    cheese = ox.NamedNode("http://example.org/Cheese")

    b1 = ox.BlankNode("b1")
    from_quads = [
        (pizza, _RDF_TYPE, _OWL_CLASS),
        (pizza, _RDFS_SC, b1),
        (b1, _RDF_TYPE, _OWL_RESTRICTION),
        (b1, _OWL_ON_PROPERTY, hasTopping),
        (b1, _OWL_SOME_VALUES, tomato),
    ]
    b2 = ox.BlankNode("b2")
    to_quads = [
        (pizza, _RDF_TYPE, _OWL_CLASS),
        (pizza, _RDFS_SC, b2),
        (b2, _RDF_TYPE, _OWL_RESTRICTION),
        (b2, _OWL_ON_PROPERTY, hasTopping),
        (b2, _OWL_SOME_VALUES, cheese),
    ]
    s = _store(from_quads=from_quads, to_quads=to_quads)
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    assert summary["axiom_changes"] == 1


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


def test_run_diff_produces_manchester_frame_for_modified_entity():
    """A class whose only change is a SubClassOf restriction swap should yield
    a manchester_frame with header + keyword + - and + lines."""
    pizza = ox.NamedNode("http://example.org/Pizza")
    p = ox.NamedNode("http://example.org/hasTopping")
    cheese = ox.NamedNode("http://example.org/Cheese")
    tofu = ox.NamedNode("http://example.org/Tofu")
    OR = ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")
    ON_P = ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty")
    SOME = ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")

    s = _store(
        from_quads=[
            (pizza, _RDF_TYPE, _OWL_CLASS),
            (pizza, label_pred, ox.Literal("Pizza", language="en")),
            (pizza, _RDFS_SC, ox.BlankNode("rOld")),
            (ox.BlankNode("rOld"), _RDF_TYPE, OR),
            (ox.BlankNode("rOld"), ON_P, p),
            (ox.BlankNode("rOld"), SOME, cheese),
        ],
        to_quads=[
            (pizza, _RDF_TYPE, _OWL_CLASS),
            (pizza, label_pred, ox.Literal("Pizza", language="en")),
            (pizza, _RDFS_SC, ox.BlankNode("rNew")),
            (ox.BlankNode("rNew"), _RDF_TYPE, OR),
            (ox.BlankNode("rNew"), ON_P, p),
            (ox.BlankNode("rNew"), SOME, tofu),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    mod = diff_data["modified"][0]
    assert mod["iri"] == pizza.value
    frame = mod.get("manchester_frame")
    assert frame is not None, "manchester_frame must be populated for modified entities"
    expected = (
        f"Class: Pizza  ({pizza.value})\n"
        "    SubClassOf:\n"
        "-       hasTopping some Cheese\n"
        "+       hasTopping some Tofu"
    )
    assert frame == expected


def test_run_diff_axiom_changes_use_manchester_strings():
    """Each axiom_changes entry's axiom string is in Manchester format, not raw triple."""
    pizza = ox.NamedNode("http://example.org/Pizza")
    food = ox.NamedNode("http://example.org/Food")
    s = _store(
        from_quads=[(pizza, _RDF_TYPE, _OWL_CLASS)],
        to_quads=[
            (pizza, _RDF_TYPE, _OWL_CLASS),
            (pizza, _RDFS_SC, food),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    mod = diff_data["modified"][0]
    axiom_strs = [a["axiom"] for a in mod["axiom_changes"]]
    assert axiom_strs == ["SubClassOf: Food"]


def test_structural_triples_returns_terms_with_fingerprints():
    """The refactored helper must return both the comparable (pred, repr) set
    AND a lookup from (pred, repr) -> the actual ox.Term object, so the
    Manchester renderer can walk bnode subgraphs later."""
    from ontoexplorer.modules.diff.compute import _structural_triples
    iri = ox.NamedNode("http://example.org/Foo")
    obj_uri = ox.NamedNode("http://example.org/Bar")
    obj_bn  = ox.BlankNode("b1")
    store = ox.Store()
    g = ox.NamedNode("urn:test")
    store.add_graph(g)
    store.add(ox.Quad(iri, _RDFS_SC, obj_uri, g))
    store.add(ox.Quad(iri, _RDFS_SC, obj_bn,  g))
    store.add(ox.Quad(obj_bn, _RDF_TYPE,
                      ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction"), g))

    triples, terms = _structural_triples(store, g, iri.value)
    # Comparable set: two entries
    assert len(triples) == 2
    # NamedNode entry — direct lookup
    named_key = ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
                 "http://example.org/Bar")
    assert named_key in triples
    assert terms[named_key].value == "http://example.org/Bar"
    assert isinstance(terms[named_key], ox.NamedNode)
    # BlankNode entry — repr is a fingerprint
    bn_keys = [k for k in triples if k[1].startswith("_:fp:")]
    assert len(bn_keys) == 1
    assert isinstance(terms[bn_keys[0]], ox.BlankNode)


def test_axioms_for_entity_returns_all_outgoing_triples_except_declaring_type():
    """For a class declared as owl:Class with one rdfs:subClassOf and one
    rdfs:label, _axioms_for_entity returns the two non-declaration triples."""
    from ontoexplorer.modules.diff.compute import _axioms_for_entity

    iri = ox.NamedNode("http://example.org/Foo")
    parent = ox.NamedNode("http://example.org/Bar")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = ox.Store()
    g = ox.NamedNode("urn:test")
    store.add_graph(g)
    store.add(ox.Quad(iri, _RDF_TYPE, _OWL_CLASS, g))
    store.add(ox.Quad(iri, _RDFS_SC, parent, g))
    store.add(ox.Quad(iri, label_pred, ox.Literal("Foo", language="en"), g))

    axioms = _axioms_for_entity(store, g, iri.value)
    predicates = {p for p, _ in axioms}
    # rdf:type owl:Class is EXCLUDED (declaring triple)
    assert _RDF_TYPE.value not in predicates
    # The other two are INCLUDED
    assert _RDFS_SC.value in predicates
    assert "http://www.w3.org/2000/01/rdf-schema#label" in predicates
    assert len(axioms) == 2


def test_axioms_for_entity_keeps_non_declaring_rdf_type_triples():
    """A class can be typed both as owl:Class AND as some custom metaclass.
    Only the owl:Class declaration is excluded; other rdf:type triples remain
    so they can render as Characteristics or Types axioms."""
    from ontoexplorer.modules.diff.compute import _axioms_for_entity

    iri = ox.NamedNode("http://example.org/Foo")
    metaclass = ox.NamedNode("http://example.org/MyMetaclass")
    store = ox.Store()
    g = ox.NamedNode("urn:test")
    store.add_graph(g)
    store.add(ox.Quad(iri, _RDF_TYPE, _OWL_CLASS, g))
    store.add(ox.Quad(iri, _RDF_TYPE, metaclass, g))

    axioms = _axioms_for_entity(store, g, iri.value)
    # owl:Class declaration is excluded; metaclass triple remains.
    objects = [getattr(o, "value", str(o)) for _, o in axioms]
    assert _OWL_CLASS.value not in objects
    assert metaclass.value in objects
    assert len(axioms) == 1


def test_run_diff_added_class_with_subclassof_and_label_yields_manchester_frame():
    """An added class with one rdfs:subClassOf and one rdfs:label should
    produce a manchester_frame on the added entry with both blocks and
    '+ ' prefixes on every line."""
    new_class = ox.NamedNode("http://example.org/NewClass")
    parent    = ox.NamedNode("http://example.org/Parent")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")

    s = _store(
        from_quads=[],
        to_quads=[
            (new_class, _RDF_TYPE, _OWL_CLASS),
            (new_class, _RDFS_SC, parent),
            (new_class, label_pred, ox.Literal("New", language="en")),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["added"] == 1
    added = diff_data["added"][0]
    assert added["iri"] == new_class.value
    frame = added.get("manchester_frame")
    assert frame is not None, "manchester_frame must be populated for added entities"
    # Header + Annotations + SubClassOf, every line '+ ' prefixed.
    lines = frame.split("\n")
    assert all(line.startswith("+ ") for line in lines), \
        f"every line should start with '+ ', got:\n{frame}"
    assert "Annotations:" in frame
    assert 'rdfs:label "New"@en' in frame
    assert "SubClassOf:" in frame


def test_run_diff_removed_class_yields_manchester_frame_with_minus_prefix():
    old_class = ox.NamedNode("http://example.org/OldClass")
    parent    = ox.NamedNode("http://example.org/Parent")

    s = _store(
        from_quads=[
            (old_class, _RDF_TYPE, _OWL_CLASS),
            (old_class, _RDFS_SC, parent),
        ],
        to_quads=[],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["removed"] == 1
    removed = diff_data["removed"][0]
    frame = removed.get("manchester_frame")
    assert frame is not None
    lines = frame.split("\n")
    assert all(line.startswith("- ") for line in lines)
    assert "SubClassOf:" in frame


def test_run_diff_bare_added_class_yields_header_only_frame():
    """A class declared with only `rdf:type owl:Class` and no other axioms
    produces a single-line frame: '+ Class: <name>  (<iri>)'."""
    bare = ox.NamedNode("http://example.org/Bare")
    s = _store(
        from_quads=[],
        to_quads=[(bare, _RDF_TYPE, _OWL_CLASS)],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    added = diff_data["added"][0]
    frame = added.get("manchester_frame")
    assert frame is not None
    # Exactly one line, header form.
    assert frame.count("\n") == 0
    assert frame.startswith("+ Class: ")
    assert "(http://example.org/Bare)" in frame
