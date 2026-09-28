"""Unit tests for embed_ontology task wiring (no DB or embedder calls)."""
from unittest.mock import MagicMock


def test_embed_ontology_task_registered():
    from ontoexplorer.modules.jobs.tasks import celery_app
    assert "ontoexplorer.embed_ontology" in celery_app.tasks


def test_embed_ontology_skips_empty_index(monkeypatch):
    """Task returns skip status when no entities are in the Redis index."""
    from ontoexplorer.modules.jobs.tasks import embed_ontology

    mock_redis = MagicMock()
    mock_redis.smembers.return_value = set()
    mock_redis.incr.return_value = 1  # attempt-cap guard reads an int
    monkeypatch.setattr(
        "ontoexplorer.modules.search.indexer._get_redis",
        lambda: mock_redis,
    )

    # embed_ontology is now bind=True, so invoke via .apply() (which binds `self`
    # and provides a request context) rather than calling it directly.
    result = embed_ontology.apply(
        args=("test-version-id",), kwargs={"ontology_id": "test-ontology-id"}
    ).get()
    assert result["status"] == "skip"
