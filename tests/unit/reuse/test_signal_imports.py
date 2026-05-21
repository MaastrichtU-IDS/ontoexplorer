from dataclasses import asdict

from ontoexplorer.modules.reuse.signals.imports import ImportEdge, build_closure


def test_single_import_resolves_prefix():
    # A version V imports BFO directly
    rows = [
        {"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/bfo.owl", "depth": 1},
    ]
    edges = build_closure(rows)
    assert len(edges) == 1
    assert edges[0].target_iri == "http://purl.obolibrary.org/obo/bfo.owl"
    assert edges[0].target_prefix == "bfo"
    assert edges[0].depth == 1
    assert edges[0].resolved is True


def test_unresolved_import_flagged():
    rows = [{"version_id": "v1", "import_iri": "http://example.com/x.owl", "depth": 1}]
    edges = build_closure(rows)
    assert len(edges) == 1
    assert edges[0].resolved is False


def test_multiple_imports_at_same_depth():
    rows = [
        {"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/bfo.owl", "depth": 1},
        {"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/ro.owl", "depth": 1},
    ]
    edges = build_closure(rows)
    prefixes = {e.target_prefix for e in edges}
    assert prefixes == {"bfo", "ro"}


def test_import_edge_serializes_to_dict():
    rows = [{"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/bfo.owl", "depth": 1}]
    edges = build_closure(rows)
    d = asdict(edges[0])
    assert "target_prefix" in d and "target_iri" in d
