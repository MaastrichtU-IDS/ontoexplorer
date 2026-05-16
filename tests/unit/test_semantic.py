import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
    """Results with the same IRI from different versions appear only once."""
    from ontoexplorer.modules.search.semantic import semantic_search

    monkeypatch.setattr(
        "ontoexplorer.modules.search.semantic.embed_query",
        lambda q: [0.1] * 768,
    )

    row1 = MagicMock()
    row1.entity_iri = "http://example.org/Heart"
    row1.entity_type = "class"
    row1.version_id = "v1"
    row1.ontology_id = "ont1"
    row1.score = 0.95

    row2 = MagicMock()
    row2.entity_iri = "http://example.org/Heart"
    row2.entity_type = "class"
    row2.version_id = "v2"
    row2.ontology_id = "ont2"
    row2.score = 0.88

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.all.return_value = [row1, row2]
    db.execute.return_value = execute_result

    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "primary_label": "heart", "label": "heart", "short": "Heart", "source": ""
    }

    with patch("ontoexplorer.modules.search.semantic._get_redis", return_value=mock_redis):
        result = await semantic_search("cardiac organ", db, ["v1", "v2"], limit=10)

    assert len(result) == 1
    assert result[0]["iri"] == "http://example.org/Heart"
    assert result[0]["score"] == 0.95
