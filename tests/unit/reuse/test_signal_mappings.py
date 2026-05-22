import pyoxigraph

from ontoexplorer.modules.reuse.signals.mappings import extract_mappings


GRAPH = "urn:test:graph"


def _make_store(turtle: str) -> pyoxigraph.Store:
    store = pyoxigraph.Store()
    store.load(turtle.encode(), "text/turtle",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    return store


def test_skos_close_match_extracted():
    store = _make_store("""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        <http://example.org/host#A> skos:closeMatch
            <http://purl.obolibrary.org/obo/CHEBI_12345> .
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    assert "skos:closeMatch" in out
    assert len(out["skos:closeMatch"]) == 1
    entry = out["skos:closeMatch"][0]
    assert entry.target_prefix == "chebi"


def test_obo_xref_extracted():
    store = _make_store("""
        @prefix oboInOwl: <http://www.geneontology.org/formats/oboInOwl#> .
        <http://example.org/host#A> oboInOwl:hasDbXref
            <http://purl.obolibrary.org/obo/MESH_D123> .
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    assert "oboInOwl:hasDbXref" in out


def test_no_mappings_returns_empty_dict():
    store = _make_store("""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://example.org/host#A> a owl:Class .
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    assert out == {}


def test_samples_capped_at_five_per_predicate_prefix():
    triples = "\n".join(
        f"<http://example.org/host#A{i}> skos:closeMatch "
        f"<http://purl.obolibrary.org/obo/CHEBI_{i:05d}> ."
        for i in range(10)
    )
    store = _make_store(f"""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        {triples}
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    # 10 mappings, but samples capped at 5
    entries = out["skos:closeMatch"]
    chebi_entries = [e for e in entries if e.target_prefix == "chebi"]
    assert len(chebi_entries) == 1
    assert chebi_entries[0].count == 10
    assert len(chebi_entries[0].sample_pairs) == 5
