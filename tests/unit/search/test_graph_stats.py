"""Unit tests for the shared graph-level VoID count helper."""
from ontoexplorer.modules.search.graph_stats import (
    GRAPH_COUNT_KEYS,
    _count_queries,
    compute_graph_counts,
)

GRAPH = "urn:ontology:abc:def"


class _Cell:
    def __init__(self, value):
        self.value = value


class _Row:
    def __init__(self, value):
        self._value = value

    def __getitem__(self, key):
        assert key == "n"
        return _Cell(self._value)


class _FakeStore:
    """Returns a count keyed on which typed query ran; records every query."""

    def __init__(self, by_type: dict[str, int], triples: int):
        self.by_type = by_type
        self.triples = triples
        self.queries: list[str] = []

    def query(self, sparql: str):
        self.queries.append(sparql)
        if "COUNT(*)" in sparql:
            return [_Row(self.triples)]
        for owl_type, n in self.by_type.items():
            if f"owl:{owl_type}" in sparql:
                return [_Row(n)]
        return [_Row(0)]


def test_returns_all_six_keys_with_values():
    store = _FakeStore(
        by_type={
            "Class": 51986,
            "ObjectProperty": 9,
            "DatatypeProperty": 0,
            "AnnotationProperty": 62,
            "NamedIndividual": 0,
        },
        triples=1445043,
    )
    counts = compute_graph_counts(store, GRAPH)
    assert set(counts) == set(GRAPH_COUNT_KEYS)
    assert counts == {
        "triple_count": 1445043,
        "class_count": 51986,
        "object_property_count": 9,
        "datatype_property_count": 0,
        "annotation_property_count": 62,
        "individual_count": 0,
    }


def test_values_are_ints_not_strings():
    store = _FakeStore({"Class": 5}, triples=10)
    counts = compute_graph_counts(store, GRAPH)
    assert all(isinstance(v, int) for v in counts.values())


def test_empty_result_rows_count_as_zero():
    class _Empty:
        def query(self, sparql):
            return []

    counts = compute_graph_counts(_Empty(), GRAPH)
    assert counts == {k: 0 for k in GRAPH_COUNT_KEYS}


def test_unbound_variable_counts_as_zero():
    # A row whose ?n is unbound (pyoxigraph yields None for the key) must not
    # raise — the helper guards `v is not None` before int(v.value).
    class _UnboundRow:
        def __getitem__(self, key):
            return None

    class _Unbound:
        def query(self, sparql):
            return [_UnboundRow()]

    counts = compute_graph_counts(_Unbound(), GRAPH)
    assert counts == {k: 0 for k in GRAPH_COUNT_KEYS}


def test_queries_scope_to_the_named_graph_and_right_types():
    q = _count_queries(GRAPH)
    assert set(q) == set(GRAPH_COUNT_KEYS)
    # Triple count is the full-graph COUNT(*); the rest are typed COUNT DISTINCT.
    assert "COUNT(*)" in q["triple_count"]
    assert "owl:Class" in q["class_count"]
    assert "owl:ObjectProperty" in q["object_property_count"]
    assert "owl:DatatypeProperty" in q["datatype_property_count"]
    assert "owl:AnnotationProperty" in q["annotation_property_count"]
    assert "owl:NamedIndividual" in q["individual_count"]
    # Every query is fenced to the version's named graph.
    for sparql in q.values():
        assert f"GRAPH <{GRAPH}>" in sparql
