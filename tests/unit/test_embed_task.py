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
    monkeypatch.setattr(
        "ontoexplorer.modules.search.indexer._get_redis",
        lambda: mock_redis,
    )

    result = embed_ontology("test-version-id", ontology_id="test-ontology-id")
    assert result["status"] == "skip"
