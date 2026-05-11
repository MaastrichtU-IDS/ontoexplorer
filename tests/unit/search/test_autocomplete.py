"""Unit tests for the autocomplete engine."""
import fakeredis
from unittest.mock import patch

from ontoexplorer.modules.search.autocomplete import get_completions, Completion
from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key


def _setup_redis(version_id: str) -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis(decode_responses=True)
    key = _prefix_key(version_id)
    # Two "cell death" entries with different IRIs (ambiguous)
    r.zadd(key, {"cell death|class|http://go.org/CD": 0})
    r.zadd(key, {"cell death|class|http://mondo.org/CD": 0})
    r.zadd(key, {"cell division|class|http://go.org/CDV": 0})
    r.zadd(key, {"has part|property|http://bfo.org/HP": 0})
    r.hset(_iri_key(version_id, "http://go.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://go.org/CD", "short": "GO:CD", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://mondo.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://mondo.org/CD", "short": "MONDO:CD", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://go.org/CDV"), mapping={
        "label": "cell division", "type": "class",
        "iri": "http://go.org/CDV", "short": "GO:CDV", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://bfo.org/HP"), mapping={
        "label": "has part", "type": "property",
        "iri": "http://bfo.org/HP", "short": "BFO:HP", "synonyms": "",
    })
    return r


def test_completions_open_quote_returns_entities():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell d", cursor=7, version_id="v1", limit=10)
    texts = [c.text for c in completions]
    assert any("cell death" in t for t in texts)
    assert any("cell division" in t for t in texts)


def test_completions_disambiguated_label_shown_for_ambiguous():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell death", cursor=11, version_id="v1", limit=10)
    # Should see two completions with CURIE disambiguation
    inserts = [c.insert for c in completions if c.type == "class"]
    assert any("GO:CD" in ins for ins in inserts)
    assert any("MONDO:CD" in ins for ins in inserts)
    # Both inserts should end with closing quote
    assert all(ins.endswith("'") for ins in inserts)


def test_completions_unambiguous_label_no_curie():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell div", cursor=9, version_id="v1", limit=10)
    inserts = [c.insert for c in completions]
    assert any(ins == "cell division'" for ins in inserts)


def test_completions_after_entity_returns_restriction_and_boolean_keywords():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'Cell'", cursor=6, version_id="v1", limit=20)
    kw_texts = {c.text for c in completions if c.type == "keyword"}
    assert "some" in kw_texts
    assert "only" in kw_texts
    assert "and" in kw_texts
    assert "or" in kw_texts


def test_completions_after_some_returns_only_classes():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'hasPart' some 'cell", cursor=20, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "class" in types
    assert "property" not in types


def test_completions_after_min_returns_int_hint():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'hasPart' min ", cursor=14, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "cardinality" in types
