"""Subsumption is read from the durable Oxigraph store (asserted ∪ inferred named
graphs), not the reasoner's TTL'd classification cache — so MOS/OLS never go cold
when that cache expires. These cover the SPARQL the reader builds and how it
parses results, with sparql_query stubbed (no real store needed)."""
from unittest.mock import patch

import pyoxigraph

from ontoexplorer.clients.reasoning import _oxi_related

OID = "00000000-1111-2222-3333-444444444444"
VID = "11111111-2222-3333-4444-555555555555"
IRI = "http://ex/A"
OWL_THING = "http://www.w3.org/2002/07/owl#Thing"


class _Sol:
    def __init__(self, iri):
        self._n = pyoxigraph.NamedNode(iri)

    def __getitem__(self, _key):
        return self._n


def _capture(results):
    captured = {}

    def _fake_sparql_query(q, *a, **k):
        captured["q"] = q
        return [_Sol(r) for r in results]

    return _fake_sparql_query, captured


def test_subclasses_union_of_asserted_and_inferred_graphs():
    fake, cap = _capture(["http://ex/B", "http://ex/C"])
    with patch("ontoexplorer.clients.oxigraph.sparql_query", new=fake):
        out = _oxi_related(OID, VID, IRI, want_subclasses=True, direct=False)
    assert set(out) == {"http://ex/B", "http://ex/C"}
    q = cap["q"]
    # Scopes to THIS version's two EXACT content graphs (asserted + inferred).
    assert f"urn:ontology:{OID}:{VID}" in q and f"urn:ontology:{OID}:{VID}:inferred" in q
    # subclasses: ?x subClassOf <IRI>
    assert f"?x <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{IRI}>" in q
    assert "NOT EXISTS" not in q  # transitive, no anti-join


def test_direct_uses_anti_join():
    fake, cap = _capture([])
    with patch("ontoexplorer.clients.oxigraph.sparql_query", new=fake):
        _oxi_related(OID, VID, IRI, want_subclasses=True, direct=True)
    assert "FILTER NOT EXISTS" in cap["q"]


def test_superclasses_reverses_the_pattern_and_excludes_thing_and_self():
    # The reader excludes owl:Thing and the class itself via a SPARQL FILTER; the
    # stub can't enforce that, so assert the FILTER is present and the direction.
    fake, cap = _capture(["http://ex/Parent"])
    with patch("ontoexplorer.clients.oxigraph.sparql_query", new=fake):
        out = _oxi_related(OID, VID, IRI, want_subclasses=False, direct=False)
    assert out == ["http://ex/Parent"]
    q = cap["q"]
    assert f"<{IRI}> <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?x" in q
    assert f"?x != <{IRI}>" in q and f"?x != <{OWL_THING}>" in q
