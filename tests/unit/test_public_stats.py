"""Home-page public-stats caching: a warm cache must serve instantly without the
multi-second recompute (the beat task keeps it warm off the request path)."""
import json
from unittest.mock import AsyncMock, MagicMock


async def test_read_public_stats_serves_warm_cache_without_recompute(monkeypatch):
    from ontoexplorer.modules.stats import public_stats as ps

    cached = {"total_ontologies": 1899, "total_classes": 42, "unique_classes": 7}
    mock_r = MagicMock()
    mock_r.get.return_value = json.dumps(cached)
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: mock_r)

    # A cache hit must NOT touch the DB (the expensive version_ids query) or Redis
    # set-paths; it just returns the cached blob.
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError("cache hit must not query the DB"))
    db.scalar = AsyncMock(side_effect=AssertionError("cache hit must not query the DB"))

    result = await ps.read_public_stats(db)

    assert result == cached
    mock_r.get.assert_called_once_with(ps.PUBLIC_STATS_CACHE_KEY)
    mock_r.set.assert_not_called()


async def test_refresh_writes_cache_with_ttl(monkeypatch):
    """The beat-task path recomputes and writes the cache under PUBLIC_STATS_TTL."""
    from ontoexplorer.modules.stats import public_stats as ps

    mock_r = MagicMock()
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: mock_r)
    # Stub the heavy compute so the test stays pure (no DB / Redis fan-out).
    monkeypatch.setattr(ps, "compute_public_stats", AsyncMock(return_value={"total_ontologies": 3}))

    result = await ps.refresh_public_stats_cache(db=MagicMock())

    assert result == {"total_ontologies": 3}
    key, payload = mock_r.set.call_args[0][0], mock_r.set.call_args[0][1]
    assert key == ps.PUBLIC_STATS_CACHE_KEY
    assert json.loads(payload) == {"total_ontologies": 3}
    assert mock_r.set.call_args[1]["ex"] == ps.PUBLIC_STATS_TTL
