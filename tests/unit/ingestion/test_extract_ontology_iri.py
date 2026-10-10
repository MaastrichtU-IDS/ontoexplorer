"""Regression tests for `_extract_ontology_iri_fast` and the parser fallback.

Background: The Roberts family-tree ontology declares itself as
`<owl:Ontology rdf:about="">` with `xml:base="http://www.co-ode.org/roberts/family-tree.owl"`.
An earlier version of the fast extractor had an unsafe fallback regex that
grabbed any `rdf:about="http..."` anywhere in the file's first 8 KB when the
primary regex missed. For the family file this picked
`http://www.w3.org/2000/01/rdf-schema#comment` (the rdf:about of the first
annotation-property declaration) and persisted it as the ontology IRI.
Fixed in c06e06f; this test guards against reintroducing that fallback.
"""
from ontoexplorer.modules.ingestion.pipeline import _extract_ontology_iri_fast
from ontoexplorer.modules.ingestion.format_detect import OntologyFormat


_FAMILY_LIKE_RDFXML = b"""<?xml version="1.0"?>
<rdf:RDF xmlns="http://www.co-ode.org/roberts/family-tree.owl#"
     xml:base="http://www.co-ode.org/roberts/family-tree.owl"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <owl:Ontology rdf:about="">
        <rdfs:comment>An ontology with an empty rdf:about (resolves to xml:base).</rdfs:comment>
    </owl:Ontology>
    <owl:AnnotationProperty rdf:about="http://www.w3.org/2000/01/rdf-schema#comment"/>
    <owl:Class rdf:about="http://www.co-ode.org/roberts/family-tree.owl#Person"/>
</rdf:RDF>
"""

_STANDARD_RDFXML = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <owl:Ontology rdf:about="http://example.org/ontologies/foo"/>
    <owl:Class rdf:about="http://example.org/ontologies/foo#A"/>
</rdf:RDF>
"""

_TURTLE_STANDARD = b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
<http://example.org/turtle-onto> a owl:Ontology .
"""


def test_extract_iri_returns_resolved_base_for_empty_rdf_about():
    """Empty `rdf:about=""` must resolve to xml:base — NOT to the first
    other rdf:about in the file (which used to be the bug)."""
    iri = _extract_ontology_iri_fast(_FAMILY_LIKE_RDFXML, OntologyFormat.RDF_XML)
    assert iri == "http://www.co-ode.org/roberts/family-tree.owl", (
        f"Expected resolved base IRI, got: {iri!r}. "
        "If this returned 'http://www.w3.org/2000/01/rdf-schema#comment' the "
        "unsafe fallback regex has been reintroduced (see c06e06f)."
    )


def test_extract_iri_finds_explicit_about_via_regex():
    iri = _extract_ontology_iri_fast(_STANDARD_RDFXML, OntologyFormat.RDF_XML)
    assert iri == "http://example.org/ontologies/foo"


def test_extract_iri_turtle():
    iri = _extract_ontology_iri_fast(_TURTLE_STANDARD, OntologyFormat.TURTLE)
    assert iri == "http://example.org/turtle-onto"


def test_extract_iri_returns_none_when_no_ontology_declaration():
    raw = b"<?xml version='1.0'?><rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'/>\n"
    assert _extract_ontology_iri_fast(raw, OntologyFormat.RDF_XML) is None


# ── #318: identity must not be grabbed arbitrarily from the import closure ──────
from unittest.mock import patch  # noqa: E402

from ontoexplorer.modules.ingestion import pipeline as _pl  # noqa: E402


class _Term:
    def __init__(self, v):
        self._v = v
    def __str__(self):
        return self._v


class _Row:
    def __init__(self, v):
        self._t = _Term(v)
    def __getitem__(self, _k):
        return self._t


def test_sparql_identity_prefers_submitted_iri():
    """When the submitted IRI is itself an owl:Ontology in the graph, use it —
    don't pick an arbitrary (possibly imported) owl:Ontology."""
    def fake(q):
        if q.lstrip().startswith("ASK"):
            return "http://host.example/onto" in q   # prefer IS an owl:Ontology
        return [_Row("http://imported.example/other")]  # SELECT would pick an import
    with patch("ontoexplorer.clients.oxigraph.sparql_query", side_effect=fake), \
         patch("ontoexplorer.clients.oxigraph.graph_iri", return_value="urn:g"):
        out = _pl._extract_ontology_iri_sparql("o", "v", prefer="http://host.example/onto")
    assert out == "http://host.example/onto"


def test_sparql_identity_fallback_excludes_imports_and_is_ordered():
    """Without a usable prefer, the SELECT must exclude owl:imports targets and be
    deterministically ordered (not a bare LIMIT 1)."""
    captured = {}
    def fake(q):
        if q.lstrip().startswith("ASK"):
            return False
        captured["select"] = q
        return [_Row("http://host.example/onto")]
    with patch("ontoexplorer.clients.oxigraph.sparql_query", side_effect=fake), \
         patch("ontoexplorer.clients.oxigraph.graph_iri", return_value="urn:g"):
        out = _pl._extract_ontology_iri_sparql("o", "v", prefer="http://not-present.example")
    assert out == "http://host.example/onto"
    assert "owl#imports" in captured["select"]
    assert "ORDER BY" in captured["select"]
