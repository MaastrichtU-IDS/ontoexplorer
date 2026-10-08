import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_semantic_search_empty_version_ids():
    from ontoexplorer.modules.search.semantic import semantic_search
    db = AsyncMock()
    result = await semantic_search("heart disease", db, [], limit=5)
    assert result == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_semantic_search_blank_query():
    from ontoexplorer.modules.search.semantic import semantic_search
    db = AsyncMock()
    result = await semantic_search("   ", db, ["v1"], limit=5)
    assert result == []


@pytest.mark.asyncio
async def test_semantic_search_returns_empty_on_db_error(monkeypatch):
    from ontoexplorer.modules.search.semantic import semantic_search

    monkeypatch.setattr(
        "ontoexplorer.modules.search.semantic.embed_query",
        lambda q: [0.1] * 768,
    )
    db = AsyncMock()
    db.execute.side_effect = Exception("pgvector not available")
    result = await semantic_search("heart", db, ["v1"], limit=5)
    assert result == []


@pytest.mark.asyncio
async def test_semantic_search_deduplicates_iris(monkeypatch):
    """Results with the same IRI from different versions appear only once (the
    first/highest-scoring row wins). Metadata comes from the entity_index join on
    the query row — no Redis (#242 Stage 3)."""
    from ontoexplorer.modules.search.semantic import semantic_search

    monkeypatch.setattr(
        "ontoexplorer.modules.search.semantic.embed_query",
        lambda q: [0.1] * 768,
    )

    def _row(version_id, ontology_id, score):
        # Column names match the SELECT aliases in semantic_search (iri/type/…).
        r = MagicMock()
        r.iri = "http://example.org/Heart"
        r.type = "class"
        r.version_id = version_id
        r.ontology_id = ontology_id
        r.score = score
        r.primary_label = "heart"
        r.short = "Heart"
        r.source = ""
        return r

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.all.return_value = [_row("v1", "ont1", 0.95), _row("v2", "ont2", 0.88)]
    db.execute.return_value = execute_result

    result = await semantic_search("cardiac organ", db, ["v1", "v2"], limit=10)

    assert len(result) == 1
    assert result[0]["iri"] == "http://example.org/Heart"
    assert result[0]["label"] == "heart"
    assert result[0]["score"] == 0.95
