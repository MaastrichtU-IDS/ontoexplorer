"""Unit tests for embed_ontology task wiring (no DB or embedder calls)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


def _fake_entity_row(iri: str):
    """An EntityIndex-shaped row the adapter (entity_index_to_legacy_dict) can read —
    the embedder now loads its entities from entity_index (#242 Workstream B)."""
    return SimpleNamespace(
        iri=iri, primary_label="Term", short="Term", type="class", source=None,
        labels={"en": "Term"}, synonyms=[], definitions=[], types=[], is_individual=False,
    )


def _entity_index_session(rows):
    """A fake async session whose entity_index SELECT yields `rows`; other
    statements (COUNT, inserts) are recorded in `calls` with a 0 scalar."""
    calls: list = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt, *a, **k):
            calls.append(stmt)
            res = MagicMock()
            if "entity_index" in str(stmt).lower():
                res.scalars.return_value.all.return_value = rows
            else:
                res.scalar.return_value = 0
            return res

        async def commit(self):
            pass

    return _FakeSession, calls


def test_embed_ontology_task_registered():
    from ontoexplorer.modules.jobs.tasks import celery_app
    assert "ontoexplorer.embed_ontology" in celery_app.tasks


def test_embed_ontology_skips_empty_index(monkeypatch):
    """Task returns skip status when entity_index has no entities for the version."""
    from ontoexplorer.modules.jobs.tasks import embed_ontology

    mock_redis = MagicMock()
    mock_redis.incr.return_value = 1  # attempt-cap guard reads an int
    monkeypatch.setattr(
        "ontoexplorer.modules.search.indexer._get_redis", lambda: mock_redis)
    _FakeSession, _ = _entity_index_session([])  # empty entity_index -> skip
    monkeypatch.setattr(
        "ontoexplorer.database.make_celery_db_session", lambda: (lambda: _FakeSession()))

    # embed_ontology is now bind=True, so invoke via .apply() (which binds `self`
    # and provides a request context) rather than calling it directly.
    result = embed_ontology.apply(
        args=("test-version-id",), kwargs={"ontology_id": "test-ontology-id"}
    ).get()
    assert result["status"] == "skip"


def test_embed_ontology_batches_upserts(monkeypatch):
    """Regression (#185): term_embeddings are written as ONE multi-row upsert per
    batch of BATCH(256), not one execute() per row. The per-row form issued a
    single-row INSERT per entity whose sustained IO starved concurrent
    entity_index writes on the shared store."""
    from ontoexplorer.modules.jobs.tasks import embed_ontology

    N = 300  # > 256 -> exactly 2 batches
    iris = [f"http://example.org/C{i}" for i in range(N)]

    mock_redis = MagicMock()
    mock_redis.incr.return_value = 1  # attempt-cap guard reads an int
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: mock_redis)

    # No hierarchy edges — keeps the SPARQL step a no-op.
    monkeypatch.setattr("ontoexplorer.clients.oxigraph.sparql_query", lambda *a, **k: [])
    # One dummy vector per input text (bypasses the real embedder).
    monkeypatch.setattr(
        "ontoexplorer.modules.search.embedder.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )

    # The embedder loads its entities from entity_index (#242 Workstream B).
    _FakeSession, execute_calls = _entity_index_session([_fake_entity_row(i) for i in iris])
    monkeypatch.setattr(
        "ontoexplorer.database.make_celery_db_session", lambda: (lambda: _FakeSession())
    )

    job = MagicMock()
    job.id = "job-1"
    monkeypatch.setattr("ontoexplorer.modules.jobs.tracker.create_job", AsyncMock(return_value=job))
    monkeypatch.setattr("ontoexplorer.modules.jobs.tracker.mark_running", AsyncMock())
    monkeypatch.setattr("ontoexplorer.modules.jobs.tracker.mark_done", AsyncMock())
    monkeypatch.setattr("ontoexplorer.modules.jobs.tracker.mark_failed", AsyncMock())

    result = embed_ontology.apply(args=("v1",), kwargs={"ontology_id": "o1"}).get()

    assert result["status"] == "done"
    assert result["total"] == N
    # 300 rows / 256 per batch = 2 batches -> 2 upsert execute() calls, NOT 300
    # (per-row). Filter to Inserts so the post-loop embed_count COUNT(*)/UPDATE
    # (a TextClause + an Update) don't count toward the batch total.
    inserts = [s for s in execute_calls if type(s).__name__ == "Insert"]
    assert len(inserts) == 2
    # Each batch write is wrapped in the pg-write mutex (#185 serialization).
    assert mock_redis.lock.called
    assert mock_redis.lock.call_args[0][0] == "ontoexplorer:pg_write_serialize"
