"""Unit tests for the search indexer."""
import fakeredis
import pytest
from unittest.mock import patch

from ontoexplorer.modules.search.indexer import (
    normalise_label,
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


def test_build_index_extracts_skos_concepts():
    """A pure-SKOS vocabulary (terms typed only skos:Concept, no OWL/RDFS types)
    must index its concepts as ``concept`` entities rather than indexing to zero.
    Not marked slow — _populate_reuse_cache is patched out (it would open a real
    Postgres session), so this runs in CI."""
    r = _make_redis()
    concept_rows = _make_sparql_rows([
        {"entity": "http://ex.org/concept/Apple"},
        {"entity": "http://ex.org/concept/Pear"},
    ])
    label_rows = _make_sparql_rows([
        {"entity": "http://ex.org/concept/Apple", "label": "apple", "lang": "en"},
        {"entity": "http://ex.org/concept/Pear", "label": "pear", "lang": "en"},
    ])

    def fake_sparql(q):
        if "skos/core#Concept" in q:
            return concept_rows
        if "?label" in q:
            return label_rows
        return []  # no owl:Class / rdfs:Class / properties / individuals

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query", side_effect=fake_sparql), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"), \
         patch("ontoexplorer.modules.search.indexer._populate_reuse_cache", return_value=None):
        stats = build_index("v1", "o1")

    assert stats.concept_count == 2
    assert stats.class_count == 0
    for iri in ("http://ex.org/concept/Apple", "http://ex.org/concept/Pear"):
        assert stats.entities[iri]["type"] == "concept"
        assert r.hgetall(_iri_key("v1", iri))["type"] == "concept"


def test_build_index_owl_type_wins_over_skos_concept():
    """A term typed BOTH owl:AnnotationProperty and skos:Concept keeps its OWL
    type — skos:Concept is queried last and is first-wins in the entities map."""
    r = _make_redis()
    iri = "http://ex.org/dualTyped"
    rows = _make_sparql_rows([{"entity": iri}])

    def fake_sparql(q):
        # the term is returned by BOTH the annotation-property and skos queries
        if "owl#AnnotationProperty" in q or "skos/core#Concept" in q:
            return rows
        if "?label" in q:
            return _make_sparql_rows([{"entity": iri, "label": "dual", "lang": "en"}])
        return []

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query", side_effect=fake_sparql), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"), \
         patch("ontoexplorer.modules.search.indexer._populate_reuse_cache", return_value=None):
        stats = build_index("v1", "o1")

    assert stats.entities[iri]["type"] == "annotation_property"


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


def test_build_index_skips_redis_search_writes_when_gate_off(monkeypatch):
    """#242 Workstream B write-gate: with INDEX_WRITE_REDIS=false, build_index
    must not write ANY ``search:*`` entity-index keys (the per-entity ``:iri:``
    hashes, type-sets, prefix-zset, meta, langs, deprecated/individuals sets).
    The producer still runs and returns IndexStats — those readers now live on
    Postgres entity_index — but the Redis search index stays empty.

    build_index reads the flag per call via ``os.getenv("INDEX_WRITE_REDIS")``,
    so setting the env var off here routes every pipe.* write through _NoopPipe.
    _populate_reuse_cache is patched to a no-op because it would otherwise open a
    real Postgres session (unrelated to this gate assertion).
    """
    r = _make_redis()
    monkeypatch.setenv("INDEX_WRITE_REDIS", "false")

    entity_rows = _make_sparql_rows([{"entity": "http://ex.org/Cell"}])
    label_rows = _make_sparql_rows([
        {"entity": "http://ex.org/Cell", "label": "cell", "lang": "en"},
    ])

    def fake_sparql(q):
        if "owl#Class" in q:
            return entity_rows
        if "?label" in q:
            return label_rows
        return []

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query", side_effect=fake_sparql), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"), \
         patch("ontoexplorer.modules.search.indexer._populate_reuse_cache", return_value=None):
        stats = build_index("v1", "o1")

    # The in-memory producer still ran and classified the entity.
    assert stats.class_count == 1
    assert stats.entities and "http://ex.org/Cell" in stats.entities
    # ...but nothing was written to the Redis search index.
    assert r.keys("search:*") == []
