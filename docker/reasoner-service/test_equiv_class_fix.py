"""Tests for the undeclared-equivalentClass-operand work-around (equiv_class_fix).

horned-owl's strict RDF reader aborts the parse ("Unknown entity in equivalent
class statement") when an owl:equivalentClass operand is not a declared class. These
cover the store-level declaration injector and the end-to-end classify that only
succeeds once the missing declarations are injected.
"""
from __future__ import annotations

import io

import pytest

import equiv_class_fix as ecf

A = "http://ex/A"
B = "http://ex/B"
EXT = "http://web.resource.org/cc/Reproduction"


def _load(nt: str):
    pyoxigraph = pytest.importorskip("pyoxigraph")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    return store


def _types(store, iri):
    import pyoxigraph
    rt = pyoxigraph.NamedNode(ecf._RDF + "type")
    return {q.object.value for q in
            store.quads_for_pattern(pyoxigraph.NamedNode(iri), rt, None, None)}


# ── store-level injector (needs pyoxigraph) ─────────────────────────────────────

def test_injects_declaration_for_undeclared_operand():
    # A is a declared class; it is equivalent to EXT which is NOT declared.
    nt = (
        f"<{A}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
        f"<{A}> <{ecf._OWL}equivalentClass> <{EXT}> .\n"
    )
    store = _load(nt)
    injected = ecf.inject_equivalent_class_declarations(store)
    assert injected == [EXT]
    assert ecf._OWL + "Class" in _types(store, EXT)


def test_leaves_already_declared_operand_untouched():
    # EXT already typed (as something else) -> must NOT be re-declared.
    nt = (
        f"<{A}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
        f"<{EXT}> <{ecf._RDF}type> <{ecf._OWL}NamedIndividual> .\n"
        f"<{A}> <{ecf._OWL}equivalentClass> <{EXT}> .\n"
    )
    store = _load(nt)
    assert ecf.inject_equivalent_class_declarations(store) == []
    assert _types(store, EXT) == {ecf._OWL + "NamedIndividual"}


def test_noop_without_equivalent_class():
    nt = f"<{A}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
    store = _load(nt)
    assert ecf.inject_equivalent_class_declarations(store) == []


def test_skips_blank_node_operands():
    pyoxigraph = pytest.importorskip("pyoxigraph")
    # A ≡ [ anonymous class expression ] — the bnode operand must be skipped,
    # and A (already declared) is not re-injected.
    nt = (
        f"<{A}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
        f"<{A}> <{ecf._OWL}equivalentClass> _:x .\n"
        f"_:x <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
    )
    store = _load(nt)
    assert ecf.inject_equivalent_class_declarations(store) == []


def test_both_sides_injected_when_both_undeclared():
    nt = f"<{A}> <{ecf._OWL}equivalentClass> <{B}> .\n"
    store = _load(nt)
    assert ecf.inject_equivalent_class_declarations(store) == sorted([A, B])


def test_skips_reserved_vocabulary_operands():
    # A ≡ owl:Thing: owl:Thing is a built-in horned-owl knows without a
    # declaration, so it must not be injected (declaring a built-in is redundant).
    nt = (
        f"<{A}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
        f"<{A}> <{ecf._OWL}equivalentClass> <{ecf._OWL}Thing> .\n"
    )
    store = _load(nt)
    assert ecf.inject_equivalent_class_declarations(store) == []


# ── end-to-end: the parse-crash regression ──────────────────────────────────────

def test_rustdl_classifies_after_injecting_declarations():
    """A ≡ EXT with EXT undeclared crashes horned-owl ('Unknown entity in equivalent
    class statement'); injecting the declaration lets it classify."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("rustdl")
    import pyoxigraph
    from rustdl_backend import RustdlBackend

    nt = (
        f"<{A}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
        f"<{B}> <{ecf._RDF}type> <{ecf._OWL}Class> .\n"
        f"<{A}> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{B}> .\n"
        f"<{A}> <{ecf._OWL}equivalentClass> <{EXT}> .\n"
    )
    result = RustdlBackend().classify_ntriples(nt, "test-equiv-class")
    assert result.class_count >= 2
    assert B in result.direct_superclasses.get(A, [])
    # The repair must be reported (this is what gets surfaced as version metadata).
    assert result.repairs == {"injected_class_declarations": 1}
