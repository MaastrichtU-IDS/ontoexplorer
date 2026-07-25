"""Unit test for parsing the Redis usage-counts hash into aggregates."""
from unittest.mock import MagicMock

from ontoexplorer.modules.usage.rollup import read_usage_counts


def test_read_usage_counts_parses_and_aggregates():
    r = MagicMock()
    r.hgetall.return_value = {
        "view:onto1:total": "5",
        "view:onto1:unique": "3",
        "download:onto1:total": "2",   # no unique field → defaults to 0
        "view:onto2:total": "1",
        "malformed-field": "9",         # ignored (not 3 parts)
        "view:onto3:bogus": "4",        # ignored (bad metric)
        "view:onto4:total": "notint",   # ignored (non-int)
    }
    agg = read_usage_counts(r, "20260725")
    assert agg[("view", "onto1")] == {"unique": 3, "total": 5}
    assert agg[("download", "onto1")] == {"unique": 0, "total": 2}
    assert agg[("view", "onto2")] == {"unique": 0, "total": 1}
    assert ("view", "onto3") not in agg
    assert ("view", "onto4") not in agg
    r.hgetall.assert_called_once_with("usage:counts:20260725")


def test_read_usage_counts_empty():
    r = MagicMock()
    r.hgetall.return_value = {}
    assert read_usage_counts(r, "20260725") == {}
