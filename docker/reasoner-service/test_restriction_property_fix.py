"""Tests for the restriction-property-kind work-around (restriction_property_fix).

horned-owl aborts the parse ("Unexpected property kind in restriction") when an
owl:Restriction's onProperty is an annotation property, a bare rdf:Property, or
undeclared. These cover the store-level reconciler (object vs data inference, the
conservative no-guess cases, the class guard) and the end-to-end classify that
only succeeds once the property kind is reconciled.
"""
from __future__ import annotations

import io

import pytest

import restriction_property_fix as rpf

RDF = rpf._RDF
OWL = rpf._OWL
RDFS = rpf._RDFS
XSD = rpf._XSD
P = "http://ex/p"
C1, C2 = "http://ex/C1", "http://ex/C2"


def _load(nt: str):
    pyoxigraph = pytest.importorskip("pyoxigraph")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    return store


def _restriction(prop: str, filler_pred: str, filler: str) -> str:
    # an owl:Restriction blank node on `prop` with one filler, placed as a
    # superclass of C1 so it is a real class axiom.
    return (
        f"<{C1}> <{RDFS}subClassOf> _:r .\n"
        f"_:r <{RDF}type> <{OWL}Restriction> .\n"
        f"_:r <{OWL}onProperty> <{prop}> .\n"
        f"_:r <{filler_pred}> {filler} .\n"
    )


def _kinds(store, iri: str):
    import pyoxigraph
    return {q.object.value for q in store.quads_for_pattern(
        pyoxigraph.NamedNode(iri), pyoxigraph.NamedNode(RDF + "type"), None, None)
        if isinstance(q.object, pyoxigraph.NamedNode)}


# ── object-filler reconciliation ────────────────────────────────────────────────

def test_annotation_property_object_restriction_retyped_to_object():
    nt = (f"<{P}> <{RDF}type> <{OWL}AnnotationProperty> .\n"
          f"<{C2}> <{RDF}type> <{OWL}Class> .\n"
          + _restriction(P, OWL + "someValuesFrom", f"<{C2}>"))
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    k = _kinds(store, P)
    assert OWL + "ObjectProperty" in k
    assert OWL + "AnnotationProperty" not in k   # the confusing typing is stripped


def test_bare_rdf_property_retyped_to_object():
    nt = (f"<{P}> <{RDF}type> <{RDF}Property> .\n"
          + _restriction(P, OWL + "allValuesFrom", f"<{C2}>")
          + f"<{C2}> <{RDF}type> <{OWL}Class> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    assert OWL + "ObjectProperty" in _kinds(store, P)


def test_undeclared_property_object_restriction_retyped():
    nt = _restriction(P, OWL + "someValuesFrom", f"<{C2}>") + f"<{C2}> <{RDF}type> <{OWL}Class> .\n"
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    assert OWL + "ObjectProperty" in _kinds(store, P)


def test_bare_cardinality_defaults_to_object():
    nt = (f"<{C1}> <{RDFS}subClassOf> _:r .\n"
          f"_:r <{RDF}type> <{OWL}Restriction> .\n"
          f"_:r <{OWL}onProperty> <{P}> .\n"
          f'_:r <{OWL}cardinality> "1"^^<{XSD}nonNegativeInteger> .\n')
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    assert OWL + "ObjectProperty" in _kinds(store, P)


# ── data-filler reconciliation ──────────────────────────────────────────────────

def test_data_restriction_via_xsd_someValuesFrom_retyped_to_data():
    nt = _restriction(P, OWL + "someValuesFrom", f"<{XSD}string>")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    assert OWL + "DatatypeProperty" in _kinds(store, P)


def test_data_restriction_via_onDataRange_retyped_to_data():
    nt = (f"<{C1}> <{RDFS}subClassOf> _:r .\n"
          f"_:r <{RDF}type> <{OWL}Restriction> .\n"
          f"_:r <{OWL}onProperty> <{P}> .\n"
          f'_:r <{OWL}qualifiedCardinality> "1"^^<{XSD}nonNegativeInteger> .\n'
          f"_:r <{OWL}onDataRange> <{XSD}integer> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    assert OWL + "DatatypeProperty" in _kinds(store, P)


def test_literal_hasValue_retyped_to_data():
    nt = _restriction(P, OWL + "hasValue", '"42"')
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 1
    assert OWL + "DatatypeProperty" in _kinds(store, P)


# ── conservative no-op cases ────────────────────────────────────────────────────

def test_valid_object_property_left_untouched():
    nt = (f"<{P}> <{RDF}type> <{OWL}ObjectProperty> .\n"
          + _restriction(P, OWL + "someValuesFrom", f"<{C2}>") + f"<{C2}> <{RDF}type> <{OWL}Class> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 0


def test_object_characteristic_counts_as_object_kind():
    # A transitive property is an object property; an object restriction on it is fine.
    nt = (f"<{P}> <{RDF}type> <{OWL}TransitiveProperty> .\n"
          + _restriction(P, OWL + "someValuesFrom", f"<{C2}>") + f"<{C2}> <{RDF}type> <{OWL}Class> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 0


def test_opposite_real_kind_left_to_fail_not_restyped():
    # DatatypeProperty used in an OBJECT restriction: a genuine kind claim, don't
    # strip it / don't guess — leave it (documented false-negative).
    nt = (f"<{P}> <{RDF}type> <{OWL}DatatypeProperty> .\n"
          + _restriction(P, OWL + "someValuesFrom", f"<{C2}>") + f"<{C2}> <{RDF}type> <{OWL}Class> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 0
    assert _kinds(store, P) == {OWL + "DatatypeProperty"}


def test_object_and_data_pun_across_restrictions_left_alone():
    # P used in one object and one data restriction -> cannot satisfy both, skip.
    nt = (_restriction(P, OWL + "someValuesFrom", f"<{C2}>") + f"<{C2}> <{RDF}type> <{OWL}Class> .\n"
          + f"<{C1}> <{RDFS}subClassOf> _:r2 .\n"
            f"_:r2 <{RDF}type> <{OWL}Restriction> .\n"
            f"_:r2 <{OWL}onProperty> <{P}> .\n"
            f"_:r2 <{OWL}someValuesFrom> <{XSD}string> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 0


def test_class_misused_as_onProperty_not_retyped():
    # A node typed as a class and (mis)used as onProperty must not become a
    # class/property pun.
    nt = (f"<{P}> <{RDF}type> <{OWL}Class> .\n"
          + _restriction(P, OWL + "someValuesFrom", f"<{C2}>") + f"<{C2}> <{RDF}type> <{OWL}Class> .\n")
    store = _load(nt)
    assert rpf.reconcile_restriction_property_kinds(store) == 0
    assert _kinds(store, P) == {OWL + "Class"}


# ── end-to-end ──────────────────────────────────────────────────────────────────

def test_rustdl_classifies_after_reconciling_restriction_property():
    """An ontology that puts a restriction on an annotation property (voag/qudt
    shape) must classify once the property kind is reconciled, with the repair
    recorded."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("rustdl")
    from rustdl_backend import RustdlBackend

    nt = (
        f"<{C1}> <{RDF}type> <{OWL}Class> .\n"
        f"<{C2}> <{RDF}type> <{OWL}Class> .\n"
        # P is declared an annotation property but used in a class restriction:
        f"<{P}> <{RDF}type> <{OWL}AnnotationProperty> .\n"
        f"<{C1}> <{RDFS}subClassOf> _:r .\n"
        f"_:r <{RDF}type> <{OWL}Restriction> .\n"
        f"_:r <{OWL}onProperty> <{P}> .\n"
        f"_:r <{OWL}someValuesFrom> <{C2}> .\n"
    )
    result = RustdlBackend().classify_ntriples(nt, "test-restriction-property")
    assert result.class_count >= 2
    assert result.repairs.get("reconciled_restriction_properties") == 1
