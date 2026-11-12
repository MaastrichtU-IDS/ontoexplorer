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


def _cand(iri, version_id, ontology_id, score, type="class"):
    """A vector-query candidate row (cols: iri/type/version_id/ontology_id/score)."""
    r = MagicMock()
    r.iri = iri
    r.type = type
    r.version_id = version_id
    r.ontology_id = ontology_id
    r.score = score
    return r


def _meta(iri, version_id, primary_label, short="", source=""):
    """An enrichment row (cols: version_id/iri/primary_label/short/source)."""
    r = MagicMock()
    r.iri = iri
    r.version_id = version_id
    r.primary_label = primary_label
    r.short = short
    r.source = source
    return r


def _two_call_db(cand_rows, meta_rows):
    """A db whose execute() calls return the vector candidates, then the no-op
    `SET LOCAL plan_cache_mode = force_custom_plan` (#402), then the enrichment rows.
    semantic_search issues the vector query, forces a custom plan, then enriches."""
    db = AsyncMock()
    vec_result = MagicMock()
    vec_result.all.return_value = cand_rows
    enrich_result = MagicMock()
    enrich_result.all.return_value = meta_rows
    db.execute.side_effect = [vec_result, MagicMock(), enrich_result]
    return db


def _executed_sql(db) -> str:
    """All SQL text passed to db.execute, joined — for asserting the force_custom_plan
    SET actually runs before enrichment (#402)."""
    return "\n".join(str(c.args[0]) for c in db.execute.call_args_list if c.args)


@pytest.mark.asyncio
async def test_semantic_search_deduplicates_iris(monkeypatch):
    """Results with the same IRI from different versions appear only once (the
    highest-scoring row wins). Vector search (call 1) finds candidates; metadata
    comes from a second entity_index lookup (call 2), keyed to those candidates —
    no Redis (#242 Stage 3), no 64-partition join (#402)."""
    from ontoexplorer.modules.search.semantic import semantic_search

    monkeypatch.setattr(
        "ontoexplorer.modules.search.semantic.embed_query",
        lambda q: [0.1] * 768,
    )

    iri = "http://example.org/Heart"
    db = _two_call_db(
        [_cand(iri, "v1", "ont1", 0.95), _cand(iri, "v2", "ont2", 0.88)],
        [_meta(iri, "v1", "heart", "Heart"), _meta(iri, "v2", "heart", "Heart")],
    )

    result = await semantic_search("cardiac organ", db, ["v1", "v2"], limit=10)

    assert len(result) == 1
    assert result[0]["iri"] == iri
    assert result[0]["label"] == "heart"
    assert result[0]["score"] == 0.95
    # The enrichment must run under a forced custom plan so the bound version_id array
    # prunes partitions instead of locking all 64 (#402).
    assert "force_custom_plan" in _executed_sql(db)


@pytest.mark.asyncio
async def test_semantic_search_skips_candidate_with_no_entity_index_row(monkeypatch):
    """A vector candidate with no matching entity_index row (NULL primary_label /
    missing enrichment) is skipped — it has no label to render. Preserves the old
    LEFT-JOIN-then-skip behavior after the #402 split."""
    from ontoexplorer.modules.search.semantic import semantic_search

    monkeypatch.setattr(
        "ontoexplorer.modules.search.semantic.embed_query",
        lambda q: [0.1] * 768,
    )

    labelled = "http://example.org/Heart"
    orphan = "http://example.org/Orphan"
    db = _two_call_db(
        [_cand(labelled, "v1", "ont1", 0.95), _cand(orphan, "v1", "ont1", 0.90)],
        [_meta(labelled, "v1", "heart", "Heart")],  # no row for the orphan
    )

    result = await semantic_search("cardiac organ", db, ["v1"], limit=10)

    assert [r["iri"] for r in result] == [labelled]


@pytest.mark.asyncio
async def test_semantic_related_pg_splits_and_shapes(monkeypatch):
    """The Postgres branch of semantic_related also splits into vector + enrichment
    (#402). It returns the rich entity_index dicts (labels/definitions/ontology_*)
    plus score, keeps distance order, and drops candidates with no enrichment row.
    The optional ontology filter builds without touching entity_index."""
    from ontoexplorer.modules.search import semantic

    monkeypatch.setattr(semantic, "embed_query", lambda q: [0.1] * 768)

    def _vcand(iri, version_id, score):
        r = MagicMock()
        r.iri = iri
        r.version_id = version_id
        r.score = score
        return r

    a, b = "http://ex/A", "http://ex/B"
    vec_result = MagicMock()
    vec_result.all.return_value = [_vcand(a, "v1", 0.9), _vcand(b, "v1", 0.7)]
    enrich_result = MagicMock()
    enrich_result.mappings.return_value.all.return_value = [
        {"version_id": "v1", "iri": a, "primary_label": "Alpha", "labels": ["Alpha"],
         "short": "A", "type": "class", "ontology_id": "o1", "source": "",
         "definitions": ["an alpha"], "ontology_title": "Onto", "ontology_shortname": "ONT"},
        # no row for B → B is dropped
    ]

    db = AsyncMock()
    bind = MagicMock()
    bind.dialect.name = "postgresql"
    db.get_bind = MagicMock(return_value=bind)
    # vector, then SET LOCAL force_custom_plan (#402), then enrichment
    db.execute.side_effect = [vec_result, MagicMock(), enrich_result]

    out = await semantic.semantic_related(
        db, "alpha", "class", ["v1"], ["o1"], 10)

    assert [r["iri"] for r in out] == [a]           # B dropped (no enrichment)
    assert out[0]["labels"] == ["Alpha"]
    assert out[0]["definitions"] == ["an alpha"]
    assert out[0]["ontology_title"] == "Onto"
    assert out[0]["score"] == 0.9
    assert "force_custom_plan" in _executed_sql(db)  # the #402 lock fix ran


@pytest.mark.asyncio
async def test_semantic_search_logs_and_returns_empty_on_embed_failure(monkeypatch):
    from ontoexplorer.modules.search import semantic
    from ontoexplorer.modules.search.embed_client import EmbeddingError

    def boom(q):
        raise EmbeddingError("backend down")

    warnings = []
    monkeypatch.setattr(semantic, "embed_query", boom)
    monkeypatch.setattr(semantic.log, "warning", lambda event, **kw: warnings.append((event, kw)))
    db = AsyncMock()
    result = await semantic.semantic_search("heart", db, ["v1"], limit=5)
    assert result == []
    db.execute.assert_not_called()
    assert warnings and warnings[0][0] == "semantic_search_embed_failed"
    assert "backend down" in warnings[0][1]["error"]
