"""SPARQL result serialisation must not 400 on a wildcard/absent Accept header.

pyoxigraph's from_media_type returns None (does not raise) for */* or text/html
— what a browser or plain client sends. The result serialiser must fall back to
a default format rather than passing format=None to serialize() (which raises
"format parameter is required"), which was a 400 on every such request.
"""
import json

import pyoxigraph
import pytest

from ontoexplorer.api.sparql import _serialize_result


@pytest.fixture
def store():
    s = pyoxigraph.Store()
    s.add(pyoxigraph.Quad(
        pyoxigraph.NamedNode("urn:a"), pyoxigraph.NamedNode("urn:p"),
        pyoxigraph.NamedNode("urn:o"), pyoxigraph.NamedNode("urn:g"),
    ))
    return s


@pytest.mark.parametrize("accept", ["*/*", "text/html", "", "application/sparql-results+json"])
def test_select_serialises_for_any_accept(store, accept):
    result = store.query("SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } }")
    body, ctype = _serialize_result(result, accept)
    parsed = json.loads(body)               # SELECT falls back to JSON
    assert parsed["results"]["bindings"][0]["s"]["value"] == "urn:a"
    assert "json" in ctype


@pytest.mark.parametrize("accept", ["*/*", "text/html", "application/rdf+xml"])
def test_construct_serialises_for_any_accept(store, accept):
    result = store.query("CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }")
    body, ctype = _serialize_result(result, accept)      # falls back to Turtle for */*
    assert b"urn:a" in body and ctype


def test_ask_serialises(store):
    result = store.query("ASK { GRAPH ?g { ?s ?p ?o } }")
    body, ctype = _serialize_result(result, "*/*")
    assert json.loads(body)["boolean"] is True
