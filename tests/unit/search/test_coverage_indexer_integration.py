"""Test that build_index writes a coverage record to Redis under the expected key."""
import json
from unittest.mock import patch

import fakeredis

from ontoexplorer.modules.search.coverage import coverage_cache_key
from ontoexplorer.modules.search.indexer import build_index


def _patch_query(rows):
    """Return a function that yields the given rows for any SPARQL call."""
    def _fake(_q):
        return iter(rows)
    return _fake


def test_build_index_writes_coverage_cache(monkeypatch):
    """Stub out SPARQL so build_index runs and emits a coverage cache key."""
    r = fakeredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr(
        "ontoexplorer.modules.search.indexer.sparql_query",
        _patch_query([]),
    )
    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        build_index(version_id="v-test", ontology_id="o-test")

    raw = r.get(coverage_cache_key("v-test"))
    assert raw is not None, "coverage cache key was not written"
    payload = json.loads(raw)
    assert "by_type" in payload
    assert "indexed_at" in payload
    assert set(payload["by_type"].keys()) == {
        "class", "object_property", "data_property", "annotation_property", "individual"
    }
    # Empty ontology → all totals zero
    for t, bucket in payload["by_type"].items():
        assert bucket["total"] == 0
        assert bucket["by_lang"] == {}
