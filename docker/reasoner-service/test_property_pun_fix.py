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
