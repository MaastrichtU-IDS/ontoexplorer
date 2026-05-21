from pathlib import Path

import pyoxigraph
import pytest

from ontoexplorer.modules.consistency.merger import build_merge


HOST_GRAPH = "urn:test:host"
IMPORT_GRAPH = "urn:test:import"


@pytest.fixture
def populated_store(monkeypatch):
    """A pyoxigraph store with two named graphs: host + an import."""
    store = pyoxigraph.Store()
    store.load(
        b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
            <http://example.org/host#A> a owl:Class .""",
        "text/turtle",
        to_graph=pyoxigraph.NamedNode(HOST_GRAPH),
    )
    store.load(
        b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
            <http://purl.obolibrary.org/obo/BFO_0000001> a owl:Class .""",
        "text/turtle",
        to_graph=pyoxigraph.NamedNode(IMPORT_GRAPH),
    )
    # Patch get_store so build_merge uses our test store
    monkeypatch.setattr(
        "ontoexplorer.modules.consistency.merger.get_store",
        lambda: store,
    )
    return store


def test_host_only_scope_contains_only_host(populated_store, tmp_path):
    out = build_merge(
        out_dir=tmp_path,
        host_graph_iri=HOST_GRAPH,
        import_graph_iris=[IMPORT_GRAPH],
        mireot_source_paths=[],
        scope="host_only",
    )
    content = out.read_text()
    assert "host#A" in content
    assert "BFO_0000001" not in content


def test_host_plus_imports_includes_imports(populated_store, tmp_path):
    out = build_merge(
        out_dir=tmp_path,
        host_graph_iri=HOST_GRAPH,
        import_graph_iris=[IMPORT_GRAPH],
        mireot_source_paths=[],
        scope="host_plus_imports",
    )
    content = out.read_text()
    assert "host#A" in content
    assert "BFO_0000001" in content


def test_host_plus_imports_plus_mireot_appends_source_bytes(populated_store, tmp_path):
    mireot_src = tmp_path / "mireot_iao.nt"
    mireot_src.write_text(
        "<http://purl.obolibrary.org/obo/IAO_0000115> "
        "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        "<http://www.w3.org/2002/07/owl#AnnotationProperty> .\n"
    )
    out = build_merge(
        out_dir=tmp_path,
        host_graph_iri=HOST_GRAPH,
        import_graph_iris=[IMPORT_GRAPH],
        mireot_source_paths=[mireot_src],
        scope="host_plus_imports_plus_mireot",
    )
    content = out.read_text()
    assert "host#A" in content
    assert "BFO_0000001" in content
    assert "IAO_0000115" in content


def test_invalid_scope_raises(populated_store, tmp_path):
    with pytest.raises(ValueError, match="unknown scope"):
        build_merge(
            out_dir=tmp_path,
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            mireot_source_paths=[],
            scope="invalid",
        )
