"""detect_profiles must pass an explicit serialization literal to horned-owl for
Turtle/N-Triples, not fall back to auto-detect. Auto-detect mis-routes some Turtle
(SPARQL-style PREFIX/BASE headers, leading comments) to the RDF/XML reader, which
then fails with a spurious RDF/XML ParserError. py-horned-owl accepts the short
`ttl`/`nt` literals (only the long aliases turtle/ntriples/rdfxml are rejected).
"""
import pytest

pytest.importorskip("pyhornedowl")

import pyhornedowl
from ontoexplorer.modules.owl_profile import detector


def test_turtle_and_ntriples_route_to_explicit_reader(monkeypatch):
    captured = {}

    def fake_open(text, serialization=None, *a, **k):
        captured["ser"] = serialization
        return object()
    monkeypatch.setattr(pyhornedowl, "open_ontology_from_string", fake_open)

    for fmt, expected in [
        ("ttl", "ttl"), ("turtle", "ttl"),
        ("nt", "nt"), ("ntriples", "nt"), ("n-triples", "nt"),
        ("owl", "rdf"), ("rdf", "rdf"), ("owx", "owx"), ("ofn", "ofn"),
    ]:
        captured.clear()
        detector._load_ontology(b"<content>", fmt)
        assert captured["ser"] == expected, f"{fmt!r} -> {captured['ser']!r}, expected {expected!r}"


def test_ttl_is_a_real_horned_owl_literal():
    # Guards the assumption behind the fix: `ttl` is a valid serialization (unlike
    # the long alias `turtle`). A plain Turtle ontology loads with it.
    ttl = ("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
           "@prefix ex: <http://ex.org/> .\n"
           "ex:O a owl:Ontology .\nex:A a owl:Class .")
    pyhornedowl.open_ontology_from_string(ttl, "ttl")   # must not raise
    with pytest.raises(ValueError):                      # the long alias is not accepted
        pyhornedowl.open_ontology_from_string(ttl, "turtle")
