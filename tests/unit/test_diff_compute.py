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
    ops = [line["op"] for line in frame["lines"]]
    # Header is unchanged (op=None) for modified entities.
    assert frame["lines"][0]["op"] is None
    assert "added" in ops and "removed" in ops
    # Concatenate text/iri tokens per line so we can substring-check filler names.
    line_text = [
        "".join(t.get("v", "") if t["t"] == "text" else t.get("label", "") for t in l["tokens"])
        for l in frame["lines"]
    ]
    assert any("Cheese" in txt for txt, l in zip(line_text, frame["lines"]) if l["op"] == "removed")
    assert any("Tofu"   in txt for txt, l in zip(line_text, frame["lines"]) if l["op"] == "added")


def test_run_diff_axiom_changes_use_manchester_strings():
    """Each axiom_changes entry's axiom payload is the flattened Manchester form
    (keyword text + filler label concatenated into a plain string) for the
    legacy frontend search filter; the structured token form lives on
    manchester_frame.lines."""
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
    axioms = [a["axiom"] for a in mod["axiom_changes"]]
    assert len(axioms) == 1
    s_axiom = axioms[0]
    assert isinstance(s_axiom, str)
    assert s_axiom.startswith("SubClassOf: ")
    assert "Food" in s_axiom


def test_run_diff_axiom_changes_axiom_field_is_a_plain_string():
    """The legacy axiom_changes[i].axiom field MUST be a string for the
    frontend search filter (which calls .toLowerCase() on it) to work."""
    cls = ox.NamedNode("http://example.org/X")
    a   = ox.NamedNode("http://example.org/A")
    b   = ox.NamedNode("http://example.org/B")
    s = _store(
        from_quads=[
            (cls, _RDF_TYPE, _OWL_CLASS),
            (cls, _RDFS_SC, a),
        ],
        to_quads=[
            (cls, _RDF_TYPE, _OWL_CLASS),
            (cls, _RDFS_SC, b),
        ],
    )
    _, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    modified = diff_data["modified"][0]
    for ac in modified.get("axiom_changes", []):
        assert isinstance(ac["axiom"], str), f"axiom field must be str, got {type(ac['axiom'])}"
        assert ac["axiom"]  # non-empty


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


def test_run_diff_added_class_yields_structured_frame_with_iri_tokens():
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
    added = diff_data["added"][0]
    frame = added["manchester_frame"]
    assert frame is not None and "lines" in frame
    assert all(line["op"] == "added" for line in frame["lines"])
    # Header line has the new-class IRI as an in_ontology iri token.
    header = frame["lines"][0]
    assert any(
        t["t"] == "iri" and t["iri"] == new_class.value and t["in_ontology"] is True
        for t in header["tokens"]
    )
    # SubClassOf line contains the parent IRI as an in_ontology iri token.
    assert any(
        any(
            t["t"] == "iri" and t["iri"] == parent.value and t["in_ontology"] is True
            for t in line["tokens"]
        )
        for line in frame["lines"]
    )


def test_run_diff_removed_class_yields_frame_with_op_removed_lines():
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
    frame = diff_data["removed"][0]["manchester_frame"]
    assert frame is not None
    assert all(line["op"] == "removed" for line in frame["lines"])


def test_run_diff_bare_added_class_yields_single_line_frame():
    bare = ox.NamedNode("http://example.org/Bare")
    s = _store(
        from_quads=[],
        to_quads=[(bare, _RDF_TYPE, _OWL_CLASS)],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    frame = diff_data["added"][0]["manchester_frame"]
    assert frame is not None
    assert len(frame["lines"]) == 1
    assert frame["lines"][0]["op"] == "added"


def test_run_diff_iri_referenced_in_filler_but_not_subject_marks_in_ontology_true():
    """An IRI that appears only as the object of a triple (never as subject)
    is still in_ontology=True, so it remains clickable."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")  # appears only as object of A's subClassOf
    s = _store(
        from_quads=[],
        to_quads=[
            (a, _RDF_TYPE, _OWL_CLASS),
            (a, _RDFS_SC, b),
        ],
    )
    _, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    frame = diff_data["added"][0]["manchester_frame"]
    assert frame is not None
    # Find the B token in any line.
    found = False
    for line in frame["lines"]:
        for tok in line["tokens"]:
            if tok["t"] == "iri" and tok["iri"] == b.value:
                assert tok["in_ontology"] is True, "B should be in_ontology because it appears as object"
                found = True
    assert found, "B's iri token must appear in some line"


# ---------------------------------------------------------------------------
# _reasoning_status_for_version helper (Phase 4 Task 1)
# ---------------------------------------------------------------------------


@pytest.fixture
async def make_version(db_session):
    """Create an Ontology + OntologyVersion row and return the version."""
    from ontoexplorer.models.db import Ontology, OntologyVersion

    async def _make(ont_iri: str, sha: str):
        ont = Ontology(iri=ont_iri)
        db_session.add(ont)
        await db_session.flush()
        ver = OntologyVersion(
            ontology_id=ont.id,
            minio_key=f"test/{sha}.ttl",
            sha256=sha,
            format="turtle",
            status="ready",
        )
        db_session.add(ver)
        await db_session.commit()
        return ver

    return _make


@pytest.mark.anyio
async def test_reasoning_status_returns_ready_for_done_job(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/x.owl", "rs001")
    db_session.add(Job(version_id=v.id, type="reason", status="done"))
    await db_session.commit()
    status = await _reasoning_status_for_version(db_session, v.id)
    assert status == "ready"


@pytest.mark.anyio
async def test_reasoning_status_returns_pending_for_running_job(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/y.owl", "rs002")
    db_session.add(Job(version_id=v.id, type="reason", status="running"))
    await db_session.commit()
    assert await _reasoning_status_for_version(db_session, v.id) == "pending"


@pytest.mark.anyio
async def test_reasoning_status_returns_failed_when_only_failure_jobs_exist(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/z.owl", "rs003")
    db_session.add(Job(version_id=v.id, type="reason", status="failed", error="oom"))
    await db_session.commit()
    assert await _reasoning_status_for_version(db_session, v.id) == "failed"


@pytest.mark.anyio
async def test_reasoning_status_returns_missing_when_no_reason_job(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version

    v = await make_version("http://example.org/q.owl", "rs004")
    assert await _reasoning_status_for_version(db_session, v.id) == "missing"


@pytest.mark.anyio
async def test_reasoning_status_prefers_ready_over_failed_when_both_exist(db_session, make_version):
    """If a later 'done' run succeeded after earlier failures, status is 'ready'."""
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/p.owl", "rs005")
    db_session.add(Job(version_id=v.id, type="reason", status="failed", error="x"))
    db_session.add(Job(version_id=v.id, type="reason", status="done"))
    await db_session.commit()
    assert await _reasoning_status_for_version(db_session, v.id) == "ready"


def test_non_trivial_inferred_drops_subclass_of_owl_thing():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    raw = [
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode("http://www.w3.org/2002/07/owl#Thing")),
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode("http://example.org/Animal")),
    ]
    out = _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=[])
    assert len(out) == 1
    pred, obj = out[0]
    assert obj.value == "http://example.org/Animal"


def test_non_trivial_inferred_drops_reflexive_subclass():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    raw = [
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode(entity)),  # reflexive
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode("http://example.org/Bar")),
    ]
    out = _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=[])
    assert len(out) == 1
    assert out[0][1].value == "http://example.org/Bar"


def test_non_trivial_inferred_drops_asserted_duplicate():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    parent = ox.NamedNode("http://example.org/Parent")
    pred = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
    raw = [(pred, parent)]
    asserted = [(pred, parent)]
    assert _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=asserted) == []


def test_non_trivial_inferred_drops_subproperty_of_owl_top_object_property():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/p"
    raw = [
        ("http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
         ox.NamedNode("http://www.w3.org/2002/07/owl#topObjectProperty")),
        ("http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
         ox.NamedNode("http://example.org/q")),
    ]
    out = _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=[])
    assert len(out) == 1
    assert out[0][1].value == "http://example.org/q"


def test_non_trivial_inferred_keeps_genuine_new_inference():
    """Positive test — a (pred, obj) absent from asserted, non-trivial → kept."""
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    new_parent = ox.NamedNode("http://example.org/InferredParent")
    raw = [("http://www.w3.org/2000/01/rdf-schema#subClassOf", new_parent)]
    out = _non_trivial_inferred_axioms(
        raw, entity_iri=entity,
        asserted_axioms=[
            ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
             ox.NamedNode("http://example.org/Other")),
        ],
    )
    assert len(out) == 1
    assert out[0][1].value == new_parent.value
