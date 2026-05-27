"""Unit tests for ingestion pipeline components (no external services needed)."""


_OWL_XML = b"""<?xml version="1.0"?>
<Ontology xmlns="http://www.w3.org/2002/07/owl#"
          ontologyIRI="http://example.org/test.owl">
  <Declaration><Class IRI="http://example.org/MyClass"/></Declaration>
</Ontology>"""

_TURTLE = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/test> a owl:Ontology .
<http://example.org/A> a owl:Class .
<http://example.org/B> a owl:Class .
"""


def test_format_detect_turtle():
    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, detect_format

    fmt = detect_format(_TURTLE, filename="onto.ttl")
    assert fmt == OntologyFormat.TURTLE


def test_format_detect_owl_xml():
    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, detect_format

    fmt = detect_format(_OWL_XML, filename="onto.owl")
    assert fmt == OntologyFormat.OWL_XML


def test_parse_turtle():
    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
    from ontoexplorer.modules.ingestion.parser import parse_ontology

    graph = parse_ontology(_TURTLE, OntologyFormat.TURTLE)
    assert len(graph) >= 3


def test_parse_ontology_rejects_manchester():
    """Manchester Syntax has no parser in the stack; reject with a clear, actionable error."""
    import pytest

    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
    from ontoexplorer.modules.ingestion.parser import parse_ontology

    with pytest.raises(ValueError, match="not supported"):
        parse_ontology(b"Class: Pizza", OntologyFormat.MANCHESTER)


def test_compute_sha256_stable():
    """Same graph content always produces the same SHA-256."""
    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
    from ontoexplorer.modules.ingestion.deduplicator import compute_sha256
    from ontoexplorer.modules.ingestion.parser import parse_ontology

    g1 = parse_ontology(_TURTLE, OntologyFormat.TURTLE)
    g2 = parse_ontology(_TURTLE, OntologyFormat.TURTLE)
    assert compute_sha256(g1) == compute_sha256(g2)


def test_compute_sha256_differs_for_different_content():
    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
    from ontoexplorer.modules.ingestion.deduplicator import compute_sha256
    from ontoexplorer.modules.ingestion.parser import parse_ontology

    other_turtle = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/other> a owl:Ontology .
"""
    g1 = parse_ontology(_TURTLE, OntologyFormat.TURTLE)
    g2 = parse_ontology(other_turtle, OntologyFormat.TURTLE)
    assert compute_sha256(g1) != compute_sha256(g2)


def test_void_stats():
    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
    from ontoexplorer.modules.ingestion.parser import parse_ontology
    from ontoexplorer.modules.metadata.void import compute_void_stats

    graph = parse_ontology(_TURTLE, OntologyFormat.TURTLE)
    stats = compute_void_stats(graph)
    assert stats.triple_count >= 3
    assert stats.class_count >= 2


def test_source_resolve_bytes():
    from ontoexplorer.modules.ingestion.source_resolver import SourceMode, resolve_bytes

    src = resolve_bytes(_TURTLE, content_type="text/turtle")
    assert src.data == _TURTLE
    assert src.mode == SourceMode.BYTES


def test_dcat_build():
    """DCAT record builder produces a non-empty RDF graph."""
    import rdflib

    from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
    from ontoexplorer.modules.ingestion.parser import parse_ontology
    from ontoexplorer.modules.metadata.dcat import build_dcat_record
    from ontoexplorer.modules.metadata.void import compute_void_stats

    graph = parse_ontology(_TURTLE, OntologyFormat.TURTLE)
    stats = compute_void_stats(graph)
    dcat = build_dcat_record(
        ontology_id="test-id",
        version_id="ver-id",
        ontology_iri="http://example.org/test",
        version_iri=None,
        minio_download_url="http://localhost/download",
        format_ext="ttl",
        void_stats=stats,
    )
    assert isinstance(dcat, rdflib.Graph)
    assert len(dcat) > 0


def test_prov_build():
    """PROV-O activity builder produces a non-empty RDF graph."""
    import rdflib

    from ontoexplorer.modules.metadata.prov import build_ingestion_activity

    prov = build_ingestion_activity(
        version_id="ver-id",
        ontology_iri="http://example.org/test",
        source_url="http://example.org/test.ttl",
        mode="url",
        sha256="abc123",
        triple_count=3,
    )
    assert isinstance(prov, rdflib.Graph)
    assert len(prov) > 0
