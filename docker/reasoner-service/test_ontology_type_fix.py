"""Tests for the multi-typed-ontology-node reader work-around (ontology_type_fix).

horned-owl's strict RDF reader aborts the whole parse when the owl:Ontology
subject carries an extra rdf:type (e.g. voaf:Vocabulary) — the largest bucket of
the reasoned-coverage gap. These cover the store-level stripper and the end-to-end
rustdl classification that only succeeds once the extra type is stripped.
"""
from __future__ import annotations

import io

import pytest

import ontology_type_fix as otf

ONT = "http://ex/ontology"
A = "http://ex/A"
B = "http://ex/B"
VOAF_VOCAB = "http://purl.org/vocommons/voaf#Vocabulary"


def _load(nt: str):
    pyoxigraph = pytest.importorskip("pyoxigraph")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    return store


def _ontology_nt(extra_types: list[str]) -> str:
    """A minimal valid ontology (A ⊑ B) whose ontology node also carries each IRI
    in ``extra_types`` as an rdf:type."""
    lines = [
        f"<{ONT}> <{otf._RDF}type> <{otf._OWL}Ontology> .",
        f"<{A}> <{otf._RDF}type> <{otf._OWL}Class> .",
        f"<{B}> <{otf._RDF}type> <{otf._OWL}Class> .",
        f"<{A}> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{B}> .",
    ]
    for t in extra_types:
        lines.append(f"<{ONT}> <{otf._RDF}type> <{t}> .")
    return "\n".join(lines) + "\n"


# ── store-level stripper (needs pyoxigraph) ─────────────────────────────────────

def test_strips_extra_type_on_ontology_node():
    store = _load(_ontology_nt([VOAF_VOCAB]))
    removed = otf.strip_extra_ontology_types(store)
    assert removed == 1
    # owl:Ontology type survives; voaf:Vocabulary is gone.
    import pyoxigraph
    rdf_type = pyoxigraph.NamedNode(otf._RDF + "type")
    subj = pyoxigraph.NamedNode(ONT)
    types = {q.object.value for q in store.quads_for_pattern(subj, rdf_type, None, None)}
    assert types == {otf._OWL + "Ontology"}


def test_strips_multiple_extra_types():
    store = _load(_ontology_nt([
        VOAF_VOCAB,
        "http://www.w3.org/ns/adms#SemanticAsset",
        "http://www.w3.org/ns/dcat#Dataset",
    ]))
    assert otf.strip_extra_ontology_types(store) == 3


def test_noop_when_ontology_node_is_clean():
    store = _load(_ontology_nt([]))
    assert otf.strip_extra_ontology_types(store) == 0


def test_does_not_touch_non_ontology_subjects():
    # A class that is (pathologically) multi-typed must be left alone — only the
    # owl:Ontology subject's extra types are stripped.
    nt = _ontology_nt([]) + f"<{A}> <{otf._RDF}type> <{VOAF_VOCAB}> .\n"
    store = _load(nt)
    assert otf.strip_extra_ontology_types(store) == 0
    import pyoxigraph
    rdf_type = pyoxigraph.NamedNode(otf._RDF + "type")
    a_types = {q.object.value for q in
               store.quads_for_pattern(pyoxigraph.NamedNode(A), rdf_type, None, None)}
    assert VOAF_VOCAB in a_types


# ── end-to-end: the parse-crash regression ──────────────────────────────────────

def test_rustdl_classifies_despite_extra_ontology_type():
    """The regression: an ontology whose node is typed owl:Ontology AND
    voaf:Vocabulary must still classify (A ⊑ B). Without the fix horned-owl's RDF
    reader aborts with `Invalid annotation found` and the classify crashes."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("rustdl")
    from rustdl_backend import RustdlBackend

    nt = _ontology_nt([VOAF_VOCAB])
    result = RustdlBackend().classify_ntriples(nt, "test-extra-ontology-type")
    # The ontology parsed and classified: both classes are present and the
    # asserted A ⊑ B survived.
    assert result.class_count >= 2
    assert B in result.direct_superclasses.get(A, [])
