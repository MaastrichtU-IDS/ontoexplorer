import pyoxigraph

from ontoexplorer.modules.reuse.signals.mireot import MireotTerm, detect_mireot


GRAPH = "urn:test:graph"
HOST_NS = "http://example.org/host#"


def _make_store(turtle: str) -> pyoxigraph.Store:
    store = pyoxigraph.Store()
    store.load(turtle.encode(), "text/turtle",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    return store


def test_mireot_term_detected_when_minimally_axiomatized():
    # IAO_0000115 (definition) brought in as MIREOT: a label + one parent, no imports
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <{HOST_NS}LocalClass> a owl:Class ; rdfs:label "Local" .
        <http://purl.obolibrary.org/obo/IAO_0000115> a owl:AnnotationProperty ;
            rdfs:label "definition" ;
            rdfs:subPropertyOf <http://www.w3.org/2000/01/rdf-schema#comment> .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set=set(),  # no imports — IAO must be MIREOT
    )
    assert len(found) == 1
    assert isinstance(found[0], MireotTerm)
    assert found[0].source_prefix == "iao"
    assert found[0].iri == "http://purl.obolibrary.org/obo/IAO_0000115"


def test_no_mireot_when_source_is_imported():
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <http://purl.obolibrary.org/obo/IAO_0000115> a owl:AnnotationProperty ;
            rdfs:label "definition" .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set={"iao"},  # IAO imported — not MIREOT
    )
    assert found == []


def test_no_mireot_when_term_has_rich_axiomatization():
    # IAO term with an equivalentClass axiom → NOT minimal → not MIREOT
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <http://purl.obolibrary.org/obo/IAO_0000115> a owl:Class ;
            owl:equivalentClass <{HOST_NS}OtherClass> .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set=set(),
    )
    assert found == []


def test_native_terms_never_flagged():
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <{HOST_NS}LocalClass> a owl:Class ; rdfs:label "Local" .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set=set(),
    )
    assert found == []
