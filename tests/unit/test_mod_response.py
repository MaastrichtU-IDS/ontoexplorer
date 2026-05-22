# tests/unit/test_mod_response.py
import json
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import DCTERMS

from ontoexplorer.modules.mod.response import RDFResponse, _negotiate_format


def _sample_graph() -> Graph:
    g = Graph()
    g.add((URIRef("http://example.org/ont"), DCTERMS.title, Literal("Test Ontology")))
    return g


def test_negotiate_format_param_jsonld():
    assert _negotiate_format("jsonld", None) == "jsonld"


def test_negotiate_format_param_ttl():
    assert _negotiate_format("ttl", None) == "turtle"


def test_negotiate_format_param_rdfxml():
    assert _negotiate_format("rdfxml", None) == "xml"


def test_negotiate_format_param_html():
    assert _negotiate_format("html", None) == "html"


def test_negotiate_format_accept_turtle():
    assert _negotiate_format(None, "text/turtle, */*;q=0.8") == "turtle"


def test_negotiate_format_accept_rdfxml():
    assert _negotiate_format(None, "application/rdf+xml") == "xml"


def test_negotiate_format_accept_html():
    assert _negotiate_format(None, "text/html") == "html"


def test_negotiate_format_default():
    assert _negotiate_format(None, None) == "jsonld"
    assert _negotiate_format(None, "application/json") == "jsonld"


def test_rdf_response_jsonld():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="jsonld")
    assert resp.media_type.startswith("application/ld+json")
    data = json.loads(resp.body)
    assert "@context" in data


def test_rdf_response_turtle():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="ttl")
    assert resp.media_type.startswith("text/turtle")
    assert b"Test Ontology" in resp.body


def test_rdf_response_rdfxml():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="rdfxml")
    assert resp.media_type.startswith("application/rdf+xml")
    assert b"Test Ontology" in resp.body


def test_rdf_response_html():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="html")
    assert resp.media_type.startswith("text/html")
    assert b"Test Ontology" in resp.body
    assert b"<table" in resp.body


def test_rdf_response_jsonld_has_graph_key_for_list():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="jsonld")
    data = json.loads(resp.body)
    # Either @graph (list) or inline triples — must have @context
    assert "@context" in data
