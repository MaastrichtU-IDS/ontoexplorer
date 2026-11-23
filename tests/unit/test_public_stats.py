"""Home-page public-stats caching: a warm cache must serve instantly without the
multi-second recompute (the beat task keeps it warm off the request path)."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


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


@pytest.mark.parametrize(
    "rows, expected",
    [
        # Two versions with full graph_counts: totals are the sums.
        (
            [
                {"class_count": 10, "object_property_count": 2, "datatype_property_count": 1,
                 "annotation_property_count": 3, "triple_count": 100, "individual_count": 5},
                {"class_count": 7, "object_property_count": 1, "datatype_property_count": 0,
                 "annotation_property_count": 2, "triple_count": 40, "individual_count": 4},
            ],
            {"total_classes": 17, "total_object_properties": 3, "total_data_properties": 1,
             "total_annotation_properties": 5, "total_axioms": 140, "total_individuals": 9},
        ),
        # A NULL graph_counts (not yet indexed) and a partial one: NULLs count 0,
        # missing sub-keys count 0 — no all-or-nothing wipe like the Redis path.
        (
            [None, {"class_count": 7, "triple_count": 40}],
            {"total_classes": 7, "total_object_properties": 0, "total_data_properties": 0,
             "total_annotation_properties": 0, "total_axioms": 40, "total_individuals": 0},
        ),
    ],
)
async def test_totals_come_from_durable_graph_counts_not_redis(monkeypatch, rows, expected):
    """Regression for the home-page total_* = 0 bug: totals must be summed from the
    durable OntologyVersion.graph_counts column, never the 30-day-TTL Redis
    version_stats cache (which zeroed every total when Redis was restarted). This
    path must not touch Redis at all."""
    from ontoexplorer.modules.stats import public_stats as ps

    # Any Redis access from the totals path is a regression.
    def _boom():
        raise AssertionError("totals must not read Redis")
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", _boom)

    scalars = MagicMock()
    scalars.all.return_value = rows
    result_obj = MagicMock()
    result_obj.scalars.return_value = scalars
    db = MagicMock()
    db.execute = AsyncMock(return_value=result_obj)

    totals = await ps._totals_from_graph_counts(db, ["v1", "v2"])
    assert totals == expected


async def test_cold_miss_serves_snapshot_and_recomputes_in_background(monkeypatch):
    """Redis cold miss must NOT block on the ~110s recompute: serve the durable
    last-good snapshot immediately and kick the recompute into the background."""
    from ontoexplorer.modules.stats import public_stats as ps

    mock_r = MagicMock()
    mock_r.get.return_value = None  # cold cache
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: mock_r)

    snapshot = {"total_ontologies": 1898, "total_classes": 42}
    monkeypatch.setattr(ps, "_read_snapshot", AsyncMock(return_value=snapshot))
    dispatch = AsyncMock()
    monkeypatch.setattr(ps, "_dispatch_background_refresh", dispatch)
    # An inline recompute on this path is the bug we're preventing.
    monkeypatch.setattr(ps, "compute_public_stats",
                        AsyncMock(side_effect=AssertionError("cold miss must not recompute inline")))

    result = await ps.read_public_stats(MagicMock())

    assert result == snapshot
    dispatch.assert_awaited_once()


async def test_cold_miss_without_snapshot_computes_inline(monkeypatch):
    """Only the truly first-ever miss (no snapshot yet) falls through to an inline
    recompute — after that the snapshot always exists."""
    from ontoexplorer.modules.stats import public_stats as ps

    mock_r = MagicMock()
    mock_r.get.return_value = None
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: mock_r)
    monkeypatch.setattr(ps, "_read_snapshot", AsyncMock(return_value=None))
    refresh = AsyncMock(return_value={"total_ontologies": 3})
    monkeypatch.setattr(ps, "refresh_public_stats_cache", refresh)

    result = await ps.read_public_stats(MagicMock())

    assert result == {"total_ontologies": 3}
    refresh.assert_awaited_once()


async def test_refresh_upserts_durable_snapshot(monkeypatch):
    """The refresh path writes the durable StatsSnapshot (id='public') so a later
    Redis wipe still has a last-good value to serve."""
    from ontoexplorer.modules.stats import public_stats as ps

    payload = {"total_ontologies": 7, "total_classes": 99}
    monkeypatch.setattr(ps, "compute_public_stats", AsyncMock(return_value=payload))
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: MagicMock())

    db = MagicMock()
    db.get = AsyncMock(return_value=None)   # no existing row → insert
    db.add = MagicMock()
    db.commit = AsyncMock()

    result = await ps.refresh_public_stats_cache(db)

    assert result == payload
    added = db.add.call_args[0][0]
    assert added.id == ps.PUBLIC_STATS_SNAPSHOT_ID
    assert added.payload == payload
    db.commit.assert_awaited()


async def test_totals_from_graph_counts_empty_version_ids():
    from ontoexplorer.modules.stats import public_stats as ps
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError("no query for empty ids"))
    totals = await ps._totals_from_graph_counts(db, [])
    assert totals == {
        "total_classes": 0, "total_object_properties": 0, "total_data_properties": 0,
        "total_annotation_properties": 0, "total_axioms": 0, "total_individuals": 0,
    }
