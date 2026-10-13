"""Tests for the RDF/XML reserved-syntax-predicate work-around (reserved_predicate_fix).

pyoxigraph's RDF/XML serializer aborts ("reserved syntax term is not allowed as a
predicate") when a triple's predicate is an RDF/XML reserved term (rdf:about,
rdf:resource, …). rustdl serialises to RDF/XML before classifying, so one such
stray triple crashes the whole classification. These cover the store-level
dropper and the end-to-end classify that only succeeds once it's dropped.
"""
from __future__ import annotations

import io

import pytest

import reserved_predicate_fix as rpf

RDF = rpf._RDF
OWL = "http://www.w3.org/2002/07/owl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def _load(nt: str):
    pyoxigraph = pytest.importorskip("pyoxigraph")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    return store


def _has(store, pred: str) -> bool:
    import pyoxigraph
    return any(True for _ in store.quads_for_pattern(None, pyoxigraph.NamedNode(pred), None, None))


# ── store-level dropper ─────────────────────────────────────────────────────────

def test_drops_rdf_about_predicate():
    # The exact mex-perf / mex-core shape: rdf:about leaked onto the ontology node
    # with a plain-literal object.
    O = "http://mex.aksw.org/mex-perf"
    nt = (
        f'<{O}> <{RDF}type> <{OWL}Ontology> .\n'
        f'<{O}> <{RDF}about> "http://mex.aksw.org/mex-doc-perf#" .\n'
    )
    store = _load(nt)
    assert rpf.drop_reserved_syntax_predicate_triples(store) == 1
    assert not _has(store, RDF + "about")
    assert _has(store, RDF + "type")  # the legitimate triple is untouched


def test_drops_each_reserved_term_once():
    reserved = ["about", "resource", "parseType", "nodeID", "datatype", "li",
                "ID", "bagID", "aboutEach", "aboutEachPrefix", "Description", "RDF"]
    nt = "".join(f'<http://ex/s> <{RDF}{t}> "x" .\n' for t in reserved)
    store = _load(nt)
    assert rpf.drop_reserved_syntax_predicate_triples(store) == len(reserved)


def test_keeps_rdf_type_and_normal_predicates():
    nt = (
        f'<http://ex/C1> <{RDF}type> <{OWL}Class> .\n'
        f'<http://ex/C1> <{RDFS}subClassOf> <http://ex/C2> .\n'
        f'<http://ex/b> <{RDF}first> <http://ex/x> .\n'   # rdf:first/rest are NOT reserved
        f'<http://ex/b> <{RDF}rest> <{RDF}nil> .\n'
    )
    store = _load(nt)
    assert rpf.drop_reserved_syntax_predicate_triples(store) == 0
    assert _has(store, RDF + "type")
    assert _has(store, RDFS + "subClassOf")
    assert _has(store, RDF + "first")


def test_keeps_container_membership_properties():
    # rdf:_1 / rdf:_2 are container-membership props, not reserved syntax terms.
    nt = (
        f'<http://ex/bag> <{RDF}_1> <http://ex/a> .\n'
        f'<http://ex/bag> <{RDF}_2> <http://ex/b> .\n'
    )
    store = _load(nt)
    assert rpf.drop_reserved_syntax_predicate_triples(store) == 0


def test_idempotent():
    nt = f'<http://ex/s> <{RDF}about> "x" .\n'
    store = _load(nt)
    assert rpf.drop_reserved_syntax_predicate_triples(store) == 1
    assert rpf.drop_reserved_syntax_predicate_triples(store) == 0


# ── end-to-end ──────────────────────────────────────────────────────────────────

def test_rdfxml_serialize_recovers_after_drop():
    """The RDF/XML serialize that rustdl runs must abort as-is and succeed after
    the drop — proving the drop is what unblocks classification."""
    pyoxigraph = pytest.importorskip("pyoxigraph")
    nt = (
        f'<http://ex/C1> <{RDF}type> <{OWL}Class> .\n'
        f'<http://ex/C1> <{RDF}about> "junk" .\n'
    )
    def _serialize(store):
        return pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        )
    store = _load(nt)
    with pytest.raises(Exception):   # OSError: reserved syntax term not allowed as a predicate
        _serialize(store)
    rpf.drop_reserved_syntax_predicate_triples(store)
    _serialize(store)  # no raise


def test_rustdl_classifies_after_dropping_reserved_predicate():
    """An ontology carrying a reserved-term predicate (mex-perf shape) must classify
    once it's dropped, with the repair recorded."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("rustdl")
    from rustdl_backend import RustdlBackend

    C1, C2 = "http://ex/C1", "http://ex/C2"
    O = "http://ex/onto"
    nt = (
        f'<{O}> <{RDF}type> <{OWL}Ontology> .\n'
        f'<{O}> <{RDF}about> "http://ex/doc#" .\n'       # the stray syntax triple
        f'<{C1}> <{RDF}type> <{OWL}Class> .\n'
        f'<{C2}> <{RDF}type> <{OWL}Class> .\n'
        f'<{C1}> <{RDFS}subClassOf> <{C2}> .\n'
    )
    result = RustdlBackend().classify_ntriples(nt, "test-reserved-predicate")
    assert result.class_count >= 2
    assert C2 in result.direct_superclasses.get(C1, [])
    assert result.repairs.get("dropped_reserved_syntax_predicates") == 1
