"""model_rev producer stamp on term_embeddings + self-healing incremental embed (#229).

The unit-test DB is SQLite (no pgvector / ON CONFLICT on Vector), so embed_ontology is
driven through a fake session — same pattern as test_embed_task.py — that EMULATES the
term_embeddings table for the existing-hash SELECT (honouring the :rev filter exactly as
the SQL text asks for it) and captures the real Insert statement for inspection.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from ontoexplorer.modules.search.embed_client import MODEL_REV

IRI = "http://example.org/C1"


def _entity_row(iri):
    return SimpleNamespace(
        iri=iri, primary_label="Term", short="Term", type="class", source=None,
        labels={"en": "Term"}, synonyms=[], definitions=[], types=[], is_individual=False,
    )


def _run(monkeypatch, stored_rows):
    """Run embed_ontology for one entity. `stored_rows`: [(iri, text_hash, model_rev)]
    already in term_embeddings. Returns (result, insert_stmts, hash_query_params)."""
    from ontoexplorer.modules.jobs.tasks import embed_ontology

    inserts: list = []
    hash_params: list = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt, params=None):
            res = MagicMock()
            sql = str(stmt).lower()
            if "from term_embeddings" in sql and "text_hash" in sql:
                hash_params.append(params)
                rows = stored_rows
                if "model_rev = :rev" in sql:  # emulate the WHERE filter
                    rows = [r for r in rows if r[2] == params["rev"]]
                res.all.return_value = [
                    SimpleNamespace(entity_iri=r[0], text_hash=r[1]) for r in rows]
            elif "entity_index" in sql:
                res.scalars.return_value.all.return_value = [_entity_row(IRI)]
            else:
                if type(stmt).__name__ == "Insert":
                    inserts.append(stmt)
                res.scalar.return_value = 0
            return res

        async def commit(self):
            pass

    r = MagicMock()
    r.incr.return_value = 1
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: r)
    monkeypatch.setattr("ontoexplorer.clients.oxigraph.sparql_query", lambda *a, **k: [])
    monkeypatch.setattr("ontoexplorer.modules.search.embedder.embed_texts",
                        lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr("ontoexplorer.database.make_celery_db_session",
                        lambda: (lambda: _Session()))
    job = MagicMock()
    job.id = "j"
    monkeypatch.setattr("ontoexplorer.modules.jobs.tracker.create_job", AsyncMock(return_value=job))
    for n in ("mark_running", "mark_done", "mark_failed"):
        monkeypatch.setattr(f"ontoexplorer.modules.jobs.tracker.{n}", AsyncMock())
    res = embed_ontology.apply(args=("v1",), kwargs={"ontology_id": "o1"}).get()
    return res, inserts, hash_params


def _current_hash():
    from ontoexplorer.modules.search.embedder import build_entity_text, text_hash
    from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict
    return text_hash(build_entity_text(entity_index_to_legacy_dict(_entity_row(IRI)), [], []))


def test_embed_ontology_stamps_model_rev(monkeypatch):
    res, inserts, _ = _run(monkeypatch, [])
    assert res["status"] == "done"
    assert len(inserts) == 1
    comp = inserts[0].compile(dialect=postgresql.dialect())
    assert MODEL_REV == "nomic-embed-text-v1.5-q8_0-gguf"
    assert MODEL_REV in comp.params.values()
    assert "model_rev" in str(comp)


def test_existing_hashes_ignores_other_model_rev(monkeypatch):
    # Legacy (NULL rev) row, text unchanged -> must still be re-embedded and re-stamped.
    res, inserts, hash_params = _run(monkeypatch, [(IRI, _current_hash(), None)])
    assert hash_params[0]["rev"] == MODEL_REV
    assert res["status"] == "done", res  # not skipped as "unchanged"
    assert len(inserts) == 1
    sql = str(inserts[0].compile(dialect=postgresql.dialect()))
    # The conflict update must fire for an unchanged hash with a different rev,
    # and must write model_rev.
    assert "IS DISTINCT FROM" in sql.upper()
    assert "model_rev = excluded.model_rev" in sql


def test_up_to_date_row_is_still_skipped(monkeypatch):
    res, inserts, _ = _run(monkeypatch, [(IRI, _current_hash(), MODEL_REV)])
    assert res["status"] == "skip" and res["reason"] == "unchanged"
    assert inserts == []
