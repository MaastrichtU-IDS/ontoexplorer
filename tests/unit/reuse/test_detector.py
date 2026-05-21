import pyoxigraph

from ontoexplorer.modules.reuse.detector import ReuseReport, detect_reuse


GRAPH = "urn:test:graph"


def _make_store(turtle: str) -> pyoxigraph.Store:
    store = pyoxigraph.Store()
    store.load(turtle.encode(), "text/turtle",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    return store


def test_report_has_all_four_signal_sections():
    store = _make_store(f"""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <http://example.org/host#A> a owl:Class .
        <http://purl.obolibrary.org/obo/BFO_0000001> a owl:Class ; rdfs:label "entity" .
    """)
    report = detect_reuse(
        store,
        graph_iri=GRAPH,
        version_id="v1",
        host_iri="http://example.org/host",
        host_namespaces=["http://example.org/host#"],
        db_imports=[],
        entities=[
            ("http://example.org/host#A", "class"),
            ("http://purl.obolibrary.org/obo/BFO_0000001", "class"),
        ],
    )
    assert isinstance(report, ReuseReport)
    assert hasattr(report, "imports")
    assert hasattr(report, "term_iri_reuse")
    assert hasattr(report, "mireot_terms")
    assert hasattr(report, "mappings")
    assert report.version_id == "v1"
    assert report.host_iri == "http://example.org/host"


def test_term_iri_section_populated_from_entities():
    store = _make_store("""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://purl.obolibrary.org/obo/BFO_0000001> a owl:Class .
    """)
    report = detect_reuse(
        store, graph_iri=GRAPH, version_id="v1",
        host_iri="http://example.org/host",
        host_namespaces=["http://example.org/host#"],
        db_imports=[],
        entities=[("http://purl.obolibrary.org/obo/BFO_0000001", "class")],
    )
    assert "bfo" in report.term_iri_reuse
    assert report.term_iri_reuse["bfo"].class_count == 1


def test_report_has_indexed_at_iso_timestamp():
    store = _make_store("""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://example.org/host#A> a owl:Class .
    """)
    report = detect_reuse(
        store, graph_iri=GRAPH, version_id="v1",
        host_iri="http://example.org/host",
        host_namespaces=["http://example.org/host#"],
        db_imports=[], entities=[],
    )
    # ISO-8601 with TZ
    assert "T" in report.indexed_at
    assert report.indexed_at.endswith("+00:00") or report.indexed_at.endswith("Z")
