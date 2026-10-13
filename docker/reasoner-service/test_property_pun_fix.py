"""Tests for the property-kind-pun work-around (property_pun_fix).

horned-owl aborts the parse ("Types of two properties do not match") when an
owl:equivalentProperty / rdfs:subPropertyOf links properties of different kinds.
These cover the store-level dropper and the end-to-end classify that only succeeds
once the offending axiom is dropped.
"""
from __future__ import annotations

import io

import pytest

import property_pun_fix as ppf

A = "http://ex/a"
B = "http://ex/b"
EQ = ppf._OWL + "equivalentProperty"
SUB = ppf._RDFS + "subPropertyOf"
DISJ = ppf._OWL + "propertyDisjointWith"
SKOS_CONCEPT = "http://www.w3.org/2004/02/skos/core#Concept"


def _load(nt: str):
    pyoxigraph = pytest.importorskip("pyoxigraph")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    return store


def _decl(iri: str, kind: str) -> str:
    return f"<{iri}> <{ppf._RDF}type> <{ppf._OWL}{kind}> .\n"


def _has(store, pred: str) -> bool:
    import pyoxigraph
    return any(True for _ in store.quads_for_pattern(None, pyoxigraph.NamedNode(pred), None, None))


# ── store-level dropper ─────────────────────────────────────────────────────────

def test_drops_object_vs_data_mismatch():
    nt = _decl(A, "ObjectProperty") + _decl(B, "DatatypeProperty") + f"<{A}> <{EQ}> <{B}> .\n"
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1
    assert not _has(store, EQ)


def test_drops_bare_rdf_property_operand():
    # dct:creator (bare rdf:Property) equivalentProperty foaf:maker (untyped) — the
    # dominant real pattern.
    nt = f"<{A}> <{ppf._RDF}type> <{ppf._RDF}Property> .\n" + f"<{A}> <{EQ}> <{B}> .\n"
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1


def test_drops_subpropertyof_mismatch():
    nt = _decl(A, "ObjectProperty") + _decl(B, "AnnotationProperty") + f"<{A}> <{SUB}> <{B}> .\n"
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1


def test_keeps_matching_kinds():
    # Both object properties -> no mismatch, keep the axiom.
    nt = _decl(A, "ObjectProperty") + _decl(B, "ObjectProperty") + f"<{A}> <{EQ}> <{B}> .\n"
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, EQ)


def test_keeps_when_kinds_not_locally_visible():
    # Neither operand typed in the local graph -> not locally detectable, leave it
    # (that case is for the upstream horned-owl fix, which has the external kind info).
    nt = f"<{A}> <{EQ}> <{B}> .\n"
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, EQ)


def test_bare_rule_is_equivalentproperty_only_not_subpropertyof():
    # The bare-rdf:Property heuristic must NOT fire on subPropertyOf: a bare property
    # horned-owl may promote to an object property by usage carries a real role edge,
    # and role hierarchy affects class subsumption. subPropertyOf with a bare operand
    # is KEPT; the same shape as equivalentProperty is dropped.
    nt_sub = f"<{A}> <{ppf._RDF}type> <{ppf._RDF}Property> .\n<{A}> <{SUB}> <{B}> .\n"
    store = _load(nt_sub)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, SUB)

    nt_eq = f"<{A}> <{ppf._RDF}type> <{ppf._RDF}Property> .\n<{A}> <{EQ}> <{B}> .\n"
    store2 = _load(nt_eq)
    assert ppf.drop_mismatched_property_axioms(store2) == 1


def test_valid_subpropertyof_survives_alongside_dropped_mismatch():
    # A valid same-kind subPropertyOf must survive even when a mismatched
    # equivalentProperty elsewhere in the same store is dropped.
    C, D = "http://ex/c", "http://ex/d"
    nt = (
        _decl(C, "ObjectProperty") + _decl(D, "ObjectProperty") + f"<{C}> <{SUB}> <{D}> .\n"
        + _decl(A, "ObjectProperty") + _decl(B, "DatatypeProperty") + f"<{A}> <{EQ}> <{B}> .\n"
    )
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1  # only the bad equivalentProperty
    assert _has(store, SUB)  # the valid role edge is kept


def test_doubly_typed_operand_is_a_false_negative():
    # A property punned as BOTH object and annotation on one IRI: kind() returns the
    # first (ObjectProperty), so a same-other-kind axiom is NOT dropped (documented
    # under-drop — that ontology just isn't recovered here, left to upstream).
    nt = (
        _decl(A, "ObjectProperty") + _decl(A, "AnnotationProperty")
        + _decl(B, "ObjectProperty") + f"<{A}> <{EQ}> <{B}> .\n"
    )
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0


# ── propertyDisjointWith + unusable-operand extension ────────────────────────────

def test_drops_property_disjoint_with_over_bare_operands():
    # owl:propertyDisjointWith over bare rdf:Property operands (frad/frbr shape):
    # horned-owl can't reconcile the kind -> abort; drop it.
    nt = (f"<{A}> <{ppf._RDF}type> <{ppf._RDF}Property> .\n"
          f"<{B}> <{ppf._RDF}type> <{ppf._RDF}Property> .\n"
          f"<{A}> <{DISJ}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1
    assert not _has(store, DISJ)


def test_keeps_property_disjoint_with_over_valid_same_kind():
    # Two well-typed data properties, disjoint: valid, keep it (inertness —
    # tree-structure-brain shape, where FunctionalProperty must not read as object).
    nt = (f"<{A}> <{ppf._RDF}type> <{ppf._OWL}DatatypeProperty> .\n"
          f"<{A}> <{ppf._RDF}type> <{ppf._OWL}FunctionalProperty> .\n"
          f"<{B}> <{ppf._RDF}type> <{ppf._OWL}DatatypeProperty> .\n"
          f"<{B}> <{ppf._RDF}type> <{ppf._OWL}FunctionalProperty> .\n"
          f"<{A}> <{DISJ}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, DISJ)


def test_drops_equivalent_property_to_individual():
    # ldp shape: two owl:Individual (OWL 1 term) linked by equivalentProperty.
    nt = (_decl(A, "Individual") + _decl(B, "Individual") + f"<{A}> <{EQ}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1


def test_drops_equivalent_property_to_skos_concept():
    # military shape: a property equivalentProperty a skos:Concept.
    nt = (_decl(A, "ObjectProperty")
          + f"<{B}> <{ppf._RDF}type> <{SKOS_CONCEPT}> .\n"
          + f"<{A}> <{EQ}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1


def test_drops_equivalent_property_with_deprecated_only_operand():
    # cwrc shape: an owl:DeprecatedProperty (no real kind) equivalentProperty an
    # untyped property.
    nt = (_decl(A, "DeprecatedProperty") + f"<{A}> <{EQ}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 1


def test_keeps_punned_class_and_datatype_property_operand():
    # dcm shape: operand typed BOTH owl:Class and owl:DatatypeProperty — it HAS a real
    # property kind, so it is NOT unusable; the axiom is kept (inertness).
    nt = (_decl(A, "DatatypeProperty")
          + _decl(B, "DatatypeProperty") + _decl(B, "Class")
          + f"<{A}> <{EQ}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, EQ)


def test_subpropertyof_not_dropped_for_unusable_operand():
    # The unusable-operand rule must NOT apply to subPropertyOf (role edges matter):
    # a bare/individual operand on subPropertyOf is kept (only explicit mismatch drops).
    nt = (_decl(A, "Individual") + _decl(B, "ObjectProperty") + f"<{A}> <{SUB}> <{B}> .\n")
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, SUB)


def test_keeps_disjoint_both_untyped():
    # Fully-untyped operands on propertyDisjointWith: kind not locally decidable, leave
    # it (upstream territory).
    nt = f"<{A}> <{DISJ}> <{B}> .\n"
    store = _load(nt)
    assert ppf.drop_mismatched_property_axioms(store) == 0
    assert _has(store, DISJ)


# ── end-to-end ──────────────────────────────────────────────────────────────────

def test_rustdl_classifies_after_dropping_pun():
    """A real ontology that puns (dct:creator-style) must classify once the mismatched
    equivalentProperty is dropped."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("rustdl")
    from rustdl_backend import RustdlBackend

    C1, C2 = "http://ex/C1", "http://ex/C2"
    nt = (
        f"<{C1}> <{ppf._RDF}type> <{ppf._OWL}Class> .\n"
        f"<{C2}> <{ppf._RDF}type> <{ppf._OWL}Class> .\n"
        f"<{C1}> <{ppf._RDFS}subClassOf> <{C2}> .\n"
        # the pun that would abort the whole parse:
        f"<{A}> <{ppf._RDF}type> <{ppf._OWL}ObjectProperty> .\n"
        f"<{B}> <{ppf._RDF}type> <{ppf._OWL}DatatypeProperty> .\n"
        f"<{A}> <{EQ}> <{B}> .\n"
    )
    result = RustdlBackend().classify_ntriples(nt, "test-prop-pun")
    assert result.class_count >= 2
    assert C2 in result.direct_superclasses.get(C1, [])
    assert result.repairs.get("dropped_property_axioms") == 1
