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
