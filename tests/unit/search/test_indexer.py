"""Unit tests for the search indexer."""
import fakeredis
import pytest
from unittest.mock import patch

from ontoexplorer.modules.search.indexer import (
    normalise_label,
    entity_lookup,
    build_index,
    invalidate_index,
    _prefix_key,
    _iri_key,
    _meta_key,
)


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_normalise_label_lowercase():
    assert normalise_label("Cell Death") == "cell death"


def test_normalise_label_strips_punctuation():
    assert normalise_label("has-part") == "has part"


def test_normalise_label_collapses_whitespace():
    assert normalise_label("  cell   death  ") == "cell death"


def test_normalise_label_strips_leading_article():
    assert normalise_label("the Cell") == "cell"
    assert normalise_label("a Nucleus") == "nucleus"
    assert normalise_label("an Organelle") == "organelle"


def test_normalise_label_preserves_curie_colon():
    assert normalise_label("GO:0008219") == "go:0008219"


def test_entity_lookup_prefix_match():
    r = _make_redis()
    vid = "v1"
    # Manually insert prefix members
    key = _prefix_key(vid)
    r.zadd(key, {"cell death|class|http://ex.org/CellDeath": 0})
    r.zadd(key, {"cell division|class|http://ex.org/CellDiv": 0})
    r.zadd(key, {"neuron|class|http://ex.org/Neuron": 0})
    # Insert entity hashes
    r.hset(_iri_key(vid, "http://ex.org/CellDeath"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://ex.org/CellDeath", "short": "CellDeath", "synonyms": "",
    })
    r.hset(_iri_key(vid, "http://ex.org/CellDiv"), mapping={
        "label": "cell division", "type": "class",
        "iri": "http://ex.org/CellDiv", "short": "CellDiv", "synonyms": "",
    })

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        results = entity_lookup(vid, "cell", None, limit=10)

    assert len(results) == 2
    iris = {r["iri"] for r in results}
    assert "http://ex.org/CellDeath" in iris
    assert "http://ex.org/CellDiv" in iris
    assert "http://ex.org/Neuron" not in iris


def test_entity_lookup_type_filter():
    r = _make_redis()
    vid = "v1"
    key = _prefix_key(vid)
    r.zadd(key, {"has part|property|http://ex.org/HasPart": 0})
    r.zadd(key, {"has attribute|class|http://ex.org/HasAttr": 0})
    r.hset(_iri_key(vid, "http://ex.org/HasPart"), mapping={
        "label": "has part", "type": "property",
        "iri": "http://ex.org/HasPart", "short": "HasPart", "synonyms": "",
    })
    r.hset(_iri_key(vid, "http://ex.org/HasAttr"), mapping={
        "label": "has attribute", "type": "class",
        "iri": "http://ex.org/HasAttr", "short": "HasAttr", "synonyms": "",
    })

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        results = entity_lookup(vid, "has", "property", limit=10)

    assert len(results) == 1
    assert results[0]["iri"] == "http://ex.org/HasPart"


def test_entity_lookup_empty_prefix():
    r = _make_redis()
    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        results = entity_lookup("v1", "", None, limit=10)
    assert results == []


def _make_sparql_rows(rows):
    """Mock pyoxigraph QuerySolutions — each row is a dict of {name: value_str}."""
    class FakeNode:
        def __init__(self, v): self.value = v
    class FakeRow:
        def __init__(self, d): self._d = d
        def __getitem__(self, k): return FakeNode(self._d[k])
        def get(self, k, default=None):
            if k in self._d:
                return FakeNode(self._d[k])
            return default
        def __iter__(self): return iter(self._d)
    return [FakeRow(r) for r in rows]


@pytest.mark.slow
def test_build_index_populates_prefix_set():
    r = _make_redis()

    entity_rows = _make_sparql_rows([
        {"entity": "http://ex.org/CellDeath"},
        {"entity": "http://ex.org/Nucleus"},
    ])
    label_rows = _make_sparql_rows([
        {"entity": "http://ex.org/CellDeath", "label": "cell death", "lang": "en"},
        {"entity": "http://ex.org/Nucleus", "label": "nucleus", "lang": "en"},
    ])

    call_count = 0
    def fake_sparql(q):
        nonlocal call_count
        call_count += 1
        if "owl#Class" in q:
            return entity_rows
        if "?label" in q:
            return label_rows
        return []

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query", side_effect=fake_sparql), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"):
        stats = build_index("v1", "o1")

    assert stats.class_count == 2
    members = r.zrangebylex(_prefix_key("v1"), "[cell", "[cell\xff")
    assert any("celldeath" in m or "cell death" in m for m in members)


@pytest.mark.slow
def test_build_index_writes_entity_hash():
    r = _make_redis()
    entity_rows = _make_sparql_rows([{"entity": "http://ex.org/Cell"}])
    label_rows = _make_sparql_rows([{"entity": "http://ex.org/Cell", "label": "cell", "lang": "en"}])

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query",
               side_effect=lambda q: entity_rows if "owl#Class" in q else label_rows if "?label" in q else []), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"):
        build_index("v1", "o1")

    detail = r.hgetall(_iri_key("v1", "http://ex.org/Cell"))
    assert detail["iri"] == "http://ex.org/Cell"
    assert detail["type"] == "class"


def test_invalidate_index_removes_all_keys():
    r = _make_redis()
    vid = "v99"
    r.zadd(_prefix_key(vid), {"cell|class|http://ex.org/C": 0})
    r.hset(_iri_key(vid, "http://ex.org/C"), mapping={"label": "cell"})
    r.set(_meta_key(vid), "{}")

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        invalidate_index(vid)

    assert r.zcard(_prefix_key(vid)) == 0
    assert r.hgetall(_iri_key(vid, "http://ex.org/C")) == {}
    assert r.get(_meta_key(vid)) is None
