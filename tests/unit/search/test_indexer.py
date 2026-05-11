"""Unit tests for the search indexer."""
import fakeredis
import pytest
from unittest.mock import patch

from ontoexplorer.modules.search.indexer import (
    normalise_label,
    entity_lookup,
    _prefix_key,
    _iri_key,
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
