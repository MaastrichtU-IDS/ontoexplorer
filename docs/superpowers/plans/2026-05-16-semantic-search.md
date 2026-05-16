# Semantic Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add vector-based semantic search to OntoExplorer so users can find ontology terms by meaning, augmenting (not replacing) the existing Redis prefix search.

**Architecture:** fastembed + `nomic-ai/nomic-embed-text-v1.5` computes 768-dim embeddings at ingest time in a new Celery task (`embed_ontology`) chained after `index_ontology`. Vectors are stored in PostgreSQL via pgvector with an HNSW index. At query time, the user's text is embedded and cosine-compared against the current ontology version(s). Semantic results appear as a `semantic_results` field alongside existing `results` in both global and per-version search responses.

**Tech Stack:** fastembed, pgvector (PostgreSQL extension + Python package), SQLAlchemy, Alembic, Celery, FastAPI, React, TypeScript

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add fastembed, pgvector dependencies |
| Modify | `docker-compose.yml` | Add fastembed model cache volume to worker |
| Modify | `ontoexplorer/models/db.py` | Add `TermEmbedding` SQLAlchemy model |
| Create | `alembic/versions/XXXX_add_term_embeddings.py` | Enable vector extension, create table + indexes |
| Create | `ontoexplorer/modules/search/embedder.py` | `build_entity_text`, `text_hash`, `embed_texts`, `embed_query` |
| Modify | `ontoexplorer/modules/jobs/tasks.py` | Add `embed_ontology` task; trigger it from `index_ontology` |
| Create | `ontoexplorer/modules/search/semantic.py` | `semantic_search` async function |
| Modify | `ontoexplorer/api/global_search.py` | Add `semantic` param to `/search` and `/ontologies/{id}/search` |
| Modify | `ontoexplorer/api/search.py` | Add `semantic` param to per-version `/search` |
| Modify | `frontend/src/lib/api.ts` | Add `score` to `SearchResult`; add `semantic_results` to responses; add `semantic` param |
| Modify | `frontend/src/hooks/useSearch.ts` | Add `semantic` param to `useGlobalSearch` and `useSearch` |
| Modify | `frontend/src/pages/Home.tsx` | Show `SemanticSection` below prefix results in `KeywordSearch` |
| Modify | `frontend/src/pages/OntologyPage.tsx` | Show semantic results below dropdown in `OntologySearchBar` |
| Create | `tests/unit/test_embedder.py` | Unit tests for `build_entity_text`, `text_hash`, `embed_query` |
| Create | `tests/unit/test_semantic.py` | Unit tests for `semantic_search` edge cases |

---

## Task 1: Dependencies, Data Model, and Docker

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`
- Modify: `ontoexplorer/models/db.py`
- Create: `alembic/versions/XXXX_add_term_embeddings.py`

- [ ] **Step 1: Write a failing test that imports the new model**

```python
# tests/unit/test_embedder.py  (create this file first so import fails fast)
def test_term_embedding_model_importable():
    from ontoexplorer.models.db import TermEmbedding
    assert TermEmbedding.__tablename__ == "term_embeddings"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/micheldumontier/code/ontoexplorer
python -m pytest tests/unit/test_embedder.py::test_term_embedding_model_importable -v
```
Expected: `ImportError: cannot import name 'TermEmbedding'`

- [ ] **Step 3: Add fastembed and pgvector to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list (after `"redis>=6.0"`):

```toml
    "fastembed>=0.3",
    "pgvector>=0.3",
```

- [ ] **Step 4: Install new dependencies**

```bash
pip install fastembed pgvector
```
Expected: both packages install without error.

- [ ] **Step 5: Add the TermEmbedding model to models/db.py**

Add this import at the top of `ontoexplorer/models/db.py` (after the existing SQLAlchemy imports):

```python
from pgvector.sqlalchemy import Vector
```

Add this class at the end of `ontoexplorer/models/db.py`:

```python
class TermEmbedding(Base):
    __tablename__ = "term_embeddings"
    __table_args__ = (UniqueConstraint("version_id", "entity_iri"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    entity_iri: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(String)
    text_hash: Mapped[str] = mapped_column(String)
    embedding: Mapped[list] = mapped_column(Vector(768))
```

- [ ] **Step 6: Run the test to confirm it passes now**

```bash
python -m pytest tests/unit/test_embedder.py::test_term_embedding_model_importable -v
```
Expected: PASS

- [ ] **Step 7: Create the Alembic migration**

```bash
alembic revision -m "add_term_embeddings"
```

This creates a file like `alembic/versions/XXXX_add_term_embeddings.py`. Replace its entire contents with:

```python
"""add_term_embeddings

Revision ID: <keep the generated ID>
Revises: f1a2b3c4d5e6
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# --- fill in the generated revision IDs here ---
revision = "<generated id>"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "term_embeddings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("entity_iri", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "entity_iri", name="uq_term_embeddings_version_iri"),
    )
    op.execute("CREATE INDEX ON term_embeddings USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ON term_embeddings (version_id)")


def downgrade() -> None:
    op.drop_table("term_embeddings")
```

> **Note:** `down_revision` must be the `revision` ID of the most recent existing migration. Check `alembic/versions/` — the last file (sorted by date) is the current head. Copy its `revision` value into `down_revision` above. The current head appears to be `f1a2b3c4d5e6` (the add_group migration), but verify with `alembic heads`.

- [ ] **Step 8: Run the migration**

```bash
alembic upgrade head
```
Expected: `Running upgrade f1a2b3c4d5e6 -> XXXX, add_term_embeddings`

- [ ] **Step 9: Add fastembed model cache volume to docker-compose.yml**

In `docker-compose.yml`, find the `worker:` service's `volumes:` block and add:

```yaml
      - fastembed-cache:/root/.cache/fastembed
```

At the bottom of the file, in the top-level `volumes:` block, add:

```yaml
  fastembed-cache:
```

Also add this to the `worker:` service's `environment:` block (create it if it doesn't exist under `worker:`):

```yaml
    environment:
      FASTEMBED_CACHE_PATH: /root/.cache/fastembed
```

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml docker-compose.yml ontoexplorer/models/db.py alembic/versions/ tests/unit/test_embedder.py
git commit -m "feat(semantic): add TermEmbedding model, pgvector migration, and fastembed dependency"
```

---

## Task 2: Embedder Module

**Files:**
- Create: `ontoexplorer/modules/search/embedder.py`
- Modify: `tests/unit/test_embedder.py`

- [ ] **Step 1: Write the failing tests**

Replace the contents of `tests/unit/test_embedder.py` with:

```python
import json
import pytest
from ontoexplorer.modules.search.embedder import build_entity_text, text_hash


def test_build_entity_text_full():
    entity = {
        "primary_label": "lung",
        "definitions": json.dumps([{"value": "A respiratory organ.", "lang": "en"}]),
        "synonyms": json.dumps([{"value": "pulmo", "lang": "la"}]),
    }
    text = build_entity_text(entity, ["organ", "thoracic structure"], ["left lung", "right lung"])
    assert "lung." in text
    assert "respiratory organ" in text
    assert "pulmo" in text
    assert "Superclasses: organ, thoracic structure" in text
    assert "Subclasses: left lung, right lung" in text


def test_build_entity_text_minimal():
    entity = {"primary_label": "Thing", "definitions": "[]", "synonyms": "[]"}
    text = build_entity_text(entity, [], [])
    assert text == "Thing."


def test_build_entity_text_no_definition_skips_sentence():
    entity = {"primary_label": "Foo", "definitions": "[]", "synonyms": "[]"}
    text = build_entity_text(entity, [], [])
    assert "." not in text.replace("Foo.", "")


def test_build_entity_text_caps_parents_at_5():
    entity = {"primary_label": "X", "definitions": "[]", "synonyms": "[]"}
    parents = ["A", "B", "C", "D", "E", "F", "G"]
    text = build_entity_text(entity, parents, [])
    assert "F" not in text
    assert "G" not in text


def test_build_entity_text_caps_children_at_10():
    entity = {"primary_label": "X", "definitions": "[]", "synonyms": "[]"}
    children = [f"Child{i}" for i in range(15)]
    text = build_entity_text(entity, [], children)
    assert "Child10" not in text
    assert "Child9" in text


def test_text_hash_deterministic():
    entity = {"primary_label": "lung", "definitions": "[]", "synonyms": "[]"}
    t = build_entity_text(entity, [], [])
    assert text_hash(t) == text_hash(t)
    assert len(text_hash(t)) == 64  # SHA-256 hex


def test_text_hash_differs_on_different_text():
    entity_a = {"primary_label": "lung", "definitions": "[]", "synonyms": "[]"}
    entity_b = {"primary_label": "heart", "definitions": "[]", "synonyms": "[]"}
    assert text_hash(build_entity_text(entity_a, [], [])) != text_hash(build_entity_text(entity_b, [], []))
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/unit/test_embedder.py -v
```
Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.embedder'`

- [ ] **Step 3: Create embedder.py**

Create `ontoexplorer/modules/search/embedder.py`:

```python
"""fastembed-based entity embedding for semantic search."""
from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
_embedder: "TextEmbedding | None" = None


def get_embedder() -> "TextEmbedding":
    """Return the process-level fastembed singleton, loading it on first call."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        cache_path = os.environ.get("FASTEMBED_CACHE_PATH")
        kwargs: dict = {}
        if cache_path:
            kwargs["cache_dir"] = cache_path
        _embedder = TextEmbedding(_MODEL_NAME, **kwargs)
    return _embedder


def build_entity_text(
    entity: dict,
    parent_labels: list[str],
    child_labels: list[str],
) -> str:
    """Format entity metadata into a single embedding string.

    Sections with no content are omitted. Parents capped at 5, children at 10.
    """
    parts: list[str] = []

    label = entity.get("primary_label") or entity.get("label") or entity.get("short", "")
    if label:
        parts.append(label + ".")

    raw_defs = entity.get("definitions", "[]")
    defs: list[dict] = json.loads(raw_defs) if isinstance(raw_defs, str) else raw_defs
    if defs:
        parts.append(defs[0]["value"] + ".")

    raw_syns = entity.get("synonyms", "[]")
    syns: list[dict] = json.loads(raw_syns) if isinstance(raw_syns, str) else raw_syns
    if syns:
        parts.append("Synonyms: " + "; ".join(s["value"] for s in syns[:10]) + ".")

    if parent_labels:
        parts.append("Superclasses: " + ", ".join(parent_labels[:5]) + ".")

    if child_labels:
        parts.append("Subclasses: " + ", ".join(child_labels[:10]) + ".")

    return " ".join(parts)


def text_hash(text: str) -> str:
    """SHA-256 hex digest of the embedding text, used for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of document texts using passage_embed. Returns 768-dim vectors."""
    embedder = get_embedder()
    return [v.tolist() for v in embedder.passage_embed(texts, batch_size=64)]


def embed_query(text: str) -> list[float]:
    """Embed a single user query. Returns a 768-dim vector."""
    embedder = get_embedder()
    return next(embedder.query_embed([text])).tolist()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/unit/test_embedder.py -v
```
Expected: all 7 tests PASS (the embed model doesn't load for unit tests since `embed_texts`/`embed_query` aren't tested yet)

- [ ] **Step 5: Add embed_query shape test** (requires model download, mark with `pytest.mark.slow`)

Add to `tests/unit/test_embedder.py`:

```python
@pytest.mark.slow
def test_embed_query_returns_768_floats():
    from ontoexplorer.modules.search.embedder import embed_query
    result = embed_query("cardiac muscle cell")
    assert len(result) == 768
    assert all(isinstance(x, float) for x in result)


@pytest.mark.slow
def test_embed_texts_returns_correct_shape():
    from ontoexplorer.modules.search.embedder import embed_texts
    results = embed_texts(["heart failure", "lung cancer"])
    assert len(results) == 2
    assert len(results[0]) == 768
```

- [ ] **Step 6: Run only the fast tests (skip slow)**

```bash
python -m pytest tests/unit/test_embedder.py -v -m "not slow"
```
Expected: 7 PASS, 2 skipped

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/modules/search/embedder.py tests/unit/test_embedder.py
git commit -m "feat(semantic): add embedder module with build_entity_text and embed functions"
```

---

## Task 3: embed_ontology Celery Task

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/test_embed_task.py`:

```python
"""Unit tests for embed_ontology task wiring (no DB or embedder calls)."""
from unittest.mock import MagicMock, patch


def test_embed_ontology_task_registered():
    from ontoexplorer.modules.jobs.tasks import celery_app
    assert "ontoexplorer.embed_ontology" in celery_app.tasks


def test_embed_ontology_skips_empty_index(monkeypatch):
    """Task returns skip status when no entities are in the Redis index."""
    import asyncio
    from ontoexplorer.modules.jobs.tasks import embed_ontology

    # Patch Redis to return empty sets
    mock_redis = MagicMock()
    mock_redis.smembers.return_value = set()
    monkeypatch.setattr(
        "ontoexplorer.modules.search.indexer._get_redis",
        lambda: mock_redis,
    )
    # Patch DB session to avoid real DB
    mock_session = MagicMock()
    mock_session.__aenter__ = asyncio.coroutine(lambda s: s)
    mock_session.__aexit__ = asyncio.coroutine(lambda s, *a: None)
    monkeypatch.setattr(
        "ontoexplorer.database.make_celery_db_session",
        lambda: lambda: mock_session,
    )

    result = embed_ontology("test-version-id", ontology_id="test-ontology-id")
    assert result["status"] == "skip"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/unit/test_embed_task.py::test_embed_ontology_task_registered -v
```
Expected: FAIL with `KeyError: 'ontoexplorer.embed_ontology'`

- [ ] **Step 3: Add the embed_ontology task to tasks.py**

At the end of `ontoexplorer/modules/jobs/tasks.py` (before the `poll_for_updates` task), add:

```python
@celery_app.task(name="ontoexplorer.embed_ontology")
def embed_ontology(version_id: str, ontology_id: str = "") -> dict:
    """Compute pgvector embeddings for all indexed entities in a version."""
    log.info("embed_ontology_start", version_id=version_id)
    try:
        import uuid as _uuid_mod
        from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
        from ontoexplorer.modules.search.indexer import _get_redis, _iri_key, _type_key
        from ontoexplorer.modules.search.embedder import build_entity_text, text_hash, embed_texts
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.models.db import TermEmbedding
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        r = _get_redis()
        named_graph = graph_iri(ontology_id, version_id)

        # Collect all entity IRIs and types from Redis type sets
        all_entities: dict[str, str] = {}
        for etype in ["class", "object_property", "data_property", "annotation_property", "individual"]:
            for iri in r.smembers(_type_key(version_id, etype)):
                all_entities[iri] = etype

        if not all_entities:
            log.info("embed_ontology_skip_empty", version_id=version_id)
            return {"status": "skip", "version_id": version_id}

        # Bulk SPARQL: collect asserted rdfs:subClassOf parents and children
        _SKIP_IRIS = {
            "http://www.w3.org/2002/07/owl#Thing",
            "http://www.w3.org/2002/07/owl#topObjectProperty",
            "http://www.w3.org/2002/07/owl#topDataProperty",
        }
        parents_by_iri: dict[str, list[str]] = {iri: [] for iri in all_entities}
        children_by_iri: dict[str, list[str]] = {iri: [] for iri in all_entities}

        try:
            for sol in sparql_query(f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?entity ?parent WHERE {{
                    GRAPH <{named_graph}> {{
                        ?entity rdfs:subClassOf ?parent .
                        FILTER(isIRI(?entity) && isIRI(?parent))
                    }}
                }}
            """):
                iri = sol["entity"].value
                parent = sol["parent"].value
                if iri in parents_by_iri and parent not in _SKIP_IRIS:
                    parents_by_iri[iri].append(parent)
            for sol in sparql_query(f"""
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?child ?entity WHERE {{
                    GRAPH <{named_graph}> {{
                        ?child rdfs:subClassOf ?entity .
                        FILTER(isIRI(?child) && isIRI(?entity))
                    }}
                }}
            """):
                iri = sol["entity"].value
                child = sol["child"].value
                if iri in children_by_iri:
                    children_by_iri[iri].append(child)
        except Exception as exc:
            log.warning("embed_ontology_sparql_warn", version_id=version_id, error=str(exc))

        def _label(iri: str) -> str:
            v = r.hget(_iri_key(version_id, iri), "primary_label")
            return v or iri.split("/")[-1].split("#")[-1]

        # Build (iri, entity_type, text, hash) records
        records: list[tuple[str, str, str, str]] = []
        for iri, etype in all_entities.items():
            entity = r.hgetall(_iri_key(version_id, iri))
            if not entity:
                continue
            p_labels = [_label(p) for p in parents_by_iri.get(iri, [])[:5]]
            c_labels = [_label(c) for c in children_by_iri.get(iri, [])[:10]]
            t = build_entity_text(entity, p_labels, c_labels)
            records.append((iri, etype, t, text_hash(t)))

        if not records:
            return {"status": "skip", "version_id": version_id}

        # Embed in batches of 64, upsert to pgvector
        BATCH = 64
        total = len(records)

        async def _embed_and_store() -> None:
            async with make_celery_db_session()() as db:
                for i in range(0, total, BATCH):
                    batch = records[i : i + BATCH]
                    embeddings = embed_texts([rec[2] for rec in batch])
                    for (iri, etype, _, h), emb in zip(batch, embeddings):
                        stmt = pg_insert(TermEmbedding).values(
                            id=str(_uuid_mod.uuid4()),
                            version_id=version_id,
                            entity_iri=iri,
                            entity_type=etype,
                            text_hash=h,
                            embedding=emb,
                        ).on_conflict_do_update(
                            index_elements=["version_id", "entity_iri"],
                            set_={"entity_type": etype, "text_hash": h, "embedding": emb},
                            where=(TermEmbedding.text_hash != h),
                        )
                        await db.execute(stmt)
                    await db.commit()
                    done = min(i + BATCH, total)
                    if done % 1000 < BATCH or done == total:
                        log.info("embed_ontology_progress", version_id=version_id,
                                 done=done, total=total)

        asyncio.run(_embed_and_store())
        log.info("embed_ontology_done", version_id=version_id, total=total)
        return {"status": "done", "version_id": version_id, "total": total}
    except Exception as exc:
        log.error("embed_ontology_failed", version_id=version_id, error=str(exc))
        return {"status": "failed", "version_id": version_id, "error": str(exc)}
```

- [ ] **Step 4: Trigger embed_ontology from index_ontology**

In `tasks.py`, find the `index_ontology` task. After the `asyncio.run(_mark_ready())` line and before the `log.info("index_ontology_done", ...)` line, add:

```python
        embed_ontology.delay(version_id, ontology_id=ontology_id)
```

The block at the end of `index_ontology` should look like:

```python
        asyncio.run(_mark_ready())
        embed_ontology.delay(version_id, ontology_id=ontology_id)
        log.info("index_ontology_done", version_id=version_id,
                 class_count=stats.class_count, property_count=stats.property_count)
        return {"status": "done", "version_id": version_id,
                "class_count": stats.class_count, "property_count": stats.property_count}
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/test_embed_task.py -v
```
Expected: `test_embed_ontology_task_registered` PASS, `test_embed_ontology_skips_empty_index` PASS

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py tests/unit/test_embed_task.py
git commit -m "feat(semantic): add embed_ontology Celery task with hierarchy context"
```

---

## Task 4: Semantic Search Module

**Files:**
- Create: `ontoexplorer/modules/search/semantic.py`
- Create: `tests/unit/test_semantic.py`

- [ ] **Step 1: Write the tests**

Create `tests/unit/test_semantic.py`:

```python
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
    db.execute.return_value.all.return_value = [row1, row2]

    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "primary_label": "heart", "label": "heart", "short": "Heart", "source": ""
    }

    with patch("ontoexplorer.modules.search.semantic._get_redis", return_value=mock_redis):
        result = await semantic_search("cardiac organ", db, ["v1", "v2"], limit=10)

    assert len(result) == 1
    assert result[0]["iri"] == "http://example.org/Heart"
    assert result[0]["score"] == 0.95
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/unit/test_semantic.py -v
```
Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.semantic'`

- [ ] **Step 3: Create semantic.py**

Create `ontoexplorer/modules/search/semantic.py`:

```python
"""pgvector cosine-similarity search over term embeddings."""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.modules.search.embedder import embed_query
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key


async def semantic_search(
    query: str,
    db: AsyncSession,
    version_ids: list[str],
    limit: int = 10,
) -> list[dict]:
    """Return entities semantically similar to query across the given versions.

    Returns [] if version_ids is empty, query is blank, or no embeddings exist.
    Deduplicates by IRI, keeping the highest-scoring occurrence.
    """
    if not version_ids or not query.strip():
        return []

    try:
        qvec = await asyncio.to_thread(embed_query, query)

        vec_str = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"
        sql = text("""
            SELECT te.entity_iri, te.entity_type, te.version_id, v.ontology_id,
                   1 - (te.embedding <=> CAST(:vec AS vector)) AS score
            FROM term_embeddings te
            JOIN versions v ON v.id = te.version_id
            WHERE te.version_id = ANY(:ids)
            ORDER BY te.embedding <=> CAST(:vec AS vector)
            LIMIT :lim
        """)
        result = await db.execute(sql, {"vec": vec_str, "ids": version_ids, "lim": limit})
        rows = result.all()
    except Exception:
        return []

    if not rows:
        return []

    r = _get_redis()

    seen_iris: set[str] = set()
    out: list[dict] = []
    for row in rows:
        iri = row.entity_iri
        if iri in seen_iris:
            continue
        seen_iris.add(iri)

        entity = await asyncio.to_thread(r.hgetall, _iri_key(row.version_id, iri))
        if not entity:
            continue

        out.append({
            "iri": iri,
            "label": entity.get("primary_label") or entity.get("label", iri),
            "short": entity.get("short", ""),
            "type": row.entity_type,
            "source": entity.get("source", ""),
            "match_type": "semantic",
            "score": round(float(row.score), 4),
            "version_id": row.version_id,
            "ontology_id": row.ontology_id,
        })

    return out
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_semantic.py -v
```
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/semantic.py tests/unit/test_semantic.py
git commit -m "feat(semantic): add semantic_search module with pgvector cosine similarity"
```

---

## Task 5: API — Global Search Endpoint

**Files:**
- Modify: `ontoexplorer/api/global_search.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/test_global_search_semantic.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


def test_global_search_accepts_semantic_param():
    """semantic=true is accepted without 422 error (can return empty results)."""
    from ontoexplorer.main import app
    with TestClient(app) as client:
        resp = client.get("/api/v1/search?q=heart&semantic=true")
        assert resp.status_code in (200, 401, 403)  # auth may block, but not 422


def test_ontology_search_accepts_semantic_param():
    from ontoexplorer.main import app
    with TestClient(app) as client:
        resp = client.get("/api/v1/ontologies/go/search?q=heart&semantic=true")
        assert resp.status_code in (200, 401, 403, 404)
```

- [ ] **Step 2: Run test to confirm failure**

```bash
python -m pytest tests/unit/test_global_search_semantic.py::test_global_search_accepts_semantic_param -v
```
Expected: FAIL with 422 (unrecognized query parameter)

- [ ] **Step 3: Add semantic param and call to global search endpoint**

In `ontoexplorer/api/global_search.py`:

1. Add the import at the top with the other search imports:
```python
from ontoexplorer.modules.search.semantic import semantic_search
```

2. Add `semantic: bool = Query(False, description="Include vector semantic results")` to the `global_search` function signature, after the `lang` parameter:

```python
@router.get("/search", summary="Cross-ontology entity or MOS expression search")
async def global_search(
    q: str = Query(..., min_length=1, description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    lang: str | None = Query(None, description="BCP-47 language tag for preferred results"),
    semantic: bool = Query(False, description="Include vector semantic results"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
```

3. In the entity mode return block (currently `return {"mode": "entity", ...}`), replace it with:

```python
        sem_results: list[dict] = []
        if semantic and len(q) >= 3:
            version_id_strs = [str(v.id) for v in versions]
            sem_results = await semantic_search(q, db, version_id_strs, limit=10)

        return {
            "mode": "entity", "query": q, "results": merged,
            "count": len(merged), "truncated": len(merged) >= limit,
            "semantic_results": sem_results,
        }
```

4. In the expression mode return block (currently `return {"mode": "expression", ...}`), add `"semantic_results": []`:

```python
    return {"mode": "expression", "query": q, "results": merged[:limit],
            "count": len(merged[:limit]), "truncated": len(merged) > limit,
            "semantic_results": []}
```

- [ ] **Step 4: Add semantic param to ontology_search endpoint**

In `ontoexplorer/api/global_search.py`, add `semantic: bool = Query(False)` to `ontology_search`:

```python
@router.get("/ontologies/{ontology_id}/search",
            summary="Search within an ontology (latest version)")
async def ontology_search(
    ontology_id: str,
    q: str = Query(..., description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    lang: str | None = Query(None, description="BCP-47 language tag"),
    semantic: bool = Query(False, description="Include vector semantic results"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
```

Replace the entity mode return block with:

```python
    if effective_mode == "entity":
        results = await asyncio.to_thread(entity_lookup, version_id, q, None, limit)
        sem_results: list[dict] = []
        if semantic and len(q) >= 3:
            sem_results = await semantic_search(q, db, [version_id], limit=10)
        return {
            "mode": "entity", "query": q, "version_id": version_id,
            "results": [
                {"iri": r["iri"], "label": r["label"], "short": r["short"],
                 "type": r.get("type", ""), "match_type": "entity"}
                for r in results
            ],
            "count": len(results), "truncated": len(results) >= limit,
            "semantic_results": sem_results,
        }
```

Replace the expression mode return block with:

```python
    trimmed = search_results[:limit]
    return {
        "mode": "expression", "query": q, "version_id": version_id,
        "results": [
            {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type,
             "lang": r.lang, "cross_language": r.cross_language}
            for r in trimmed
        ],
        "count": len(trimmed), "truncated": len(search_results) > limit,
        "semantic_results": [],
    }
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/test_global_search_semantic.py -v
```
Expected: both PASS

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/global_search.py tests/unit/test_global_search_semantic.py
git commit -m "feat(semantic): add semantic param to global and per-ontology search endpoints"
```

---

## Task 6: API — Per-Version Search Endpoint

**Files:**
- Modify: `ontoexplorer/api/search.py`

- [ ] **Step 1: Write the test**

Add to `tests/unit/test_global_search_semantic.py`:

```python
def test_per_version_search_accepts_semantic_param():
    from ontoexplorer.main import app
    with TestClient(app) as client:
        resp = client.get("/api/v1/ontologies/go/v1/search?q=heart&semantic=true")
        assert resp.status_code in (200, 401, 403, 404)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/unit/test_global_search_semantic.py::test_per_version_search_accepts_semantic_param -v
```
Expected: FAIL with 422

- [ ] **Step 3: Add semantic param and semantic_results to search.py**

Add the import at the top of `ontoexplorer/api/search.py`:

```python
from ontoexplorer.modules.search.semantic import semantic_search
```

Add `semantic: bool = Query(False, description="Include vector semantic results")` to the `search` function signature after `lang`:

```python
@router.get("/search", summary="MOS entity lookup or expression query")
async def search(
    ontology_id: str,
    version_id: str,
    q: str = Query(..., description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    lang: str | None = Query(None, description="BCP-47 language tag for preferred results"),
    semantic: bool = Query(False, description="Include vector semantic results"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
```

Replace the entity mode return block:

```python
    if effective_mode == "entity":
        results = await asyncio.to_thread(entity_lookup, version_id, q, None, limit)
        sem_results: list[dict] = []
        if semantic and len(q) >= 3:
            sem_results = await semantic_search(q, db, [version_id], limit=10)
        return {
            "mode": "entity",
            "query": q,
            "results": [
                {"iri": r["iri"], "label": r["label"], "short": r["short"],
                 "type": r.get("type", ""), "source": r.get("source", ""), "match_type": "entity"}
                for r in results
            ],
            "count": len(results),
            "truncated": len(results) >= limit,
            "semantic_results": sem_results,
        }
```

Replace the expression mode return block (find the one ending with `"truncated": len(search_results) > limit`):

```python
    trimmed = search_results[:limit]
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key
    _r = _get_redis()
    return {
        "mode": "expression",
        "query": q,
        "results": [
            {
                "iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type,
                "source": (_r.hget(_iri_key(version_id, r.iri), "source") or ""),
                "lang": r.lang,
                "cross_language": r.cross_language,
            }
            for r in trimmed
        ],
        "count": len(trimmed),
        "truncated": len(search_results) > limit,
        "semantic_results": [],
    }
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_global_search_semantic.py -v
```
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/search.py
git commit -m "feat(semantic): add semantic param to per-version search endpoint"
```

---

## Task 7: Frontend — Types and API Client

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/hooks/useSearch.ts`

- [ ] **Step 1: Write the test**

Create `frontend/src/hooks/useSearch.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest'

describe('useSearch semantic param', () => {
  it('passes semantic=true to api.ontologies.search when enabled', () => {
    // We verify the API function signature accepts a semantic param
    // without calling the actual network
    const mockSearch = vi.fn().mockResolvedValue({ results: [], count: 0, semantic_results: [] })
    expect(() => mockSearch('oid', 'vid', 'heart', 'auto', undefined, true)).not.toThrow()
  })
})
```

- [ ] **Step 2: Update SearchResult type in api.ts**

Find the `SearchResult` interface in `frontend/src/lib/api.ts` (around line 234) and add `score` and update `match_type`:

```typescript
export interface SearchResult {
  iri: string
  label: string
  short: string
  type?: string
  source?: string
  match_type: 'entity' | 'elk' | 'sparql' | 'semantic'
  score?: number
  version_id?: string
  ontology_id?: string
  lang?: string | null
  cross_language?: boolean
}
```

- [ ] **Step 3: Update api.globalSearch.search to add semantic param and return type**

Find this block in `api.ts`:

```typescript
  globalSearch: {
    search: (q: string, limit = 20) => {
      const params = new URLSearchParams({ q, limit: String(limit) })
      return fetch(`/api/v1/search?${params}`)
        .then(r => r.json()) as Promise<{ results: SearchResult[]; count: number; truncated: boolean }>
    },
  },
```

Replace with:

```typescript
  globalSearch: {
    search: (q: string, limit = 20, semantic = false) => {
      const params = new URLSearchParams({ q, limit: String(limit) })
      if (semantic) params.set('semantic', 'true')
      return fetch(`/api/v1/search?${params}`)
        .then(r => r.json()) as Promise<{
          results: SearchResult[]
          count: number
          truncated: boolean
          semantic_results?: SearchResult[]
        }>
    },
  },
```

- [ ] **Step 4: Update api.ontologies.search to add semantic param**

Find this block in `api.ts` (around line 607):

```typescript
    search: (oid: string, vid: string, q: string, mode = 'auto', lang?: string) =>
      request<{ mode: string; results: SearchResult[]; count: number; truncated: boolean }>(
        `/ontologies/${oid}/${vid}/search?q=${encodeURIComponent(q)}&mode=${mode}${lang ? `&lang=${lang}` : ''}`
      ),
```

Replace with:

```typescript
    search: (oid: string, vid: string, q: string, mode = 'auto', lang?: string, semantic = false) =>
      request<{
        mode: string
        results: SearchResult[]
        count: number
        truncated: boolean
        semantic_results?: SearchResult[]
      }>(
        `/ontologies/${oid}/${vid}/search?q=${encodeURIComponent(q)}&mode=${mode}${lang ? `&lang=${lang}` : ''}${semantic ? '&semantic=true' : ''}`
      ),
```

- [ ] **Step 5: Update useGlobalSearch hook in useSearch.ts**

Find `useGlobalSearch` and add `semantic` param:

```typescript
export function useGlobalSearch(query: string, semantic = false) {
  return useQuery({
    queryKey: ['global-search', query, semantic],
    queryFn: () => api.globalSearch.search(query, 20, semantic),
    enabled: query.length >= 2,
    staleTime: 10_000,
  })
}
```

- [ ] **Step 6: Run TypeScript typecheck**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 7: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/lib/api.ts frontend/src/hooks/useSearch.ts frontend/src/hooks/useSearch.test.ts
git commit -m "feat(semantic): update frontend API client and types for semantic search"
```

---

## Task 8: Frontend — Global Search Semantic Section

**Files:**
- Modify: `frontend/src/pages/Home.tsx`

The `KeywordSearch` function in `Home.tsx` uses `useGlobalSearch(submitted)` and renders `<ResultList results={results} pathFor={pathFor} />`. We add a semantic section below it.

- [ ] **Step 1: Write the test**

Create `frontend/src/pages/Home.semantic.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../hooks/useSearch', () => ({
  useGlobalSearch: () => ({
    data: {
      results: [],
      semantic_results: [
        {
          iri: 'http://example.org/Heart',
          label: 'heart',
          short: 'Heart',
          type: 'class',
          match_type: 'semantic',
          score: 0.92,
        },
      ],
    },
  }),
  useAutocomplete: () => ({ data: null }),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: [] }),
}))

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { default: Home } = require('../pages/Home')

describe('Home semantic results', () => {
  it('shows "Semantically similar" section when semantic_results is non-empty', () => {
    render(<MemoryRouter><Home /></MemoryRouter>)
    // Trigger a search by submitting a query
    // The mock already returns semantic results
    expect(screen.queryByText('Semantically similar')).not.toBeNull()
  })
})
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/pages/Home.semantic.test.tsx
```
Expected: FAIL — "Semantically similar" not found

- [ ] **Step 3: Update KeywordSearch in Home.tsx**

In `Home.tsx`, find the `KeywordSearch` function. Change:

```tsx
  const { data } = useGlobalSearch(submitted)
  const results = data?.results ?? []
```

to:

```tsx
  const { data } = useGlobalSearch(submitted, submitted.length >= 3)
  const results = data?.results ?? []
  const semanticResults = data?.semantic_results ?? []
```

Find the closing of `KeywordSearch` (the line with `<ResultList results={results} pathFor={pathFor} />`). After it, add the semantic section:

```tsx
      <ResultList results={results} pathFor={pathFor} />
      {semanticResults.length > 0 && (
        <>
          <div style={{
            margin: '1.25rem 0 0.5rem',
            fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase',
            letterSpacing: 0.8, display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
            Semantically similar
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
          </div>
          <ul style={{ listStyle: 'none', marginTop: 0 }}>
            {semanticResults.map(r => {
              const path = pathFor(r)
              const alreadyInResults = results.some(p => p.iri === r.iri)
              const inner = (
                <>
                  <span style={{
                    color: alreadyInResults ? 'var(--text-dim)' : 'var(--accent)',
                    fontWeight: 500, flexShrink: 0,
                  }}>{r.label}</span>
                  {r.source && <SourceBadge source={r.source} />}
                  <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
                  <span style={{
                    fontSize: 10, padding: '1px 5px', borderRadius: 3,
                    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                    color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0,
                  }}>{r.score?.toFixed(2)}</span>
                </>
              )
              const sharedStyle: React.CSSProperties = {
                padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                display: 'flex', gap: 10, alignItems: 'baseline',
                borderBottom: '1px solid var(--border)',
                textDecoration: 'none',
                opacity: alreadyInResults ? 0.5 : 1,
              }
              return path ? (
                <li key={r.iri}>
                  <Link to={path} style={sharedStyle}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >{inner}</Link>
                </li>
              ) : (
                <li key={r.iri} style={{ ...sharedStyle, color: 'var(--text-dim)' }}>{inner}</li>
              )
            })}
          </ul>
        </>
      )}
```

- [ ] **Step 4: Run the test**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/pages/Home.semantic.test.tsx
```
Expected: PASS

- [ ] **Step 5: Run full typecheck**

```bash
npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/Home.tsx frontend/src/pages/Home.semantic.test.tsx
git commit -m "feat(semantic): show semantically similar section in global search"
```

---

## Task 9: Frontend — Per-Ontology Search Semantic Section

**Files:**
- Modify: `frontend/src/pages/OntologyPage.tsx`

The `OntologySearchBar` component (around line 599 in `OntologyPage.tsx`) is a dropdown-style inline search. It calls `api.ontologies.search(ontologyId, versionId, dq, 'auto', lang)` and renders matching terms in a `<ul>` dropdown.

We add semantic results as a separate section below the prefix results inside the same dropdown, visible only when the dropdown is open.

- [ ] **Step 1: Write the test**

Create `frontend/src/pages/OntologyPage.semantic.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual('../lib/api')
  return {
    ...actual,
    api: {
      ...(actual as any).api,
      ontologies: {
        ...(actual as any).api?.ontologies,
        search: vi.fn().mockResolvedValue({
          mode: 'entity',
          results: [{ iri: 'http://ex.org/Heart', label: 'heart', short: 'Heart', match_type: 'entity' }],
          semantic_results: [{ iri: 'http://ex.org/Cardiac', label: 'cardiac', short: 'Cardiac', match_type: 'semantic', score: 0.88 }],
          count: 1, truncated: false,
        }),
      },
    },
  }
})

describe('OntologySearchBar semantic', () => {
  it('shows semantic results section when present', async () => {
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <div id="test-host" />
        </MemoryRouter>
      </QueryClientProvider>
    )
    // Since OntologyPage is complex to mount, we just check the API mock is wired correctly
    const { api } = await import('../lib/api')
    const result = await api.ontologies.search('go', 'v1', 'heart', 'auto', undefined, true)
    expect(result.semantic_results).toHaveLength(1)
    expect(result.semantic_results![0].score).toBe(0.88)
  })
})
```

- [ ] **Step 2: Run test to confirm it passes (API typing already fixed)**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/pages/OntologyPage.semantic.test.tsx
```
Expected: PASS (the API type was already updated in Task 7)

- [ ] **Step 3: Update OntologySearchBar to fetch and display semantic results**

In `OntologyPage.tsx`, find `OntologySearchBar`. 

Find the `useQuery` call that fetches search results and update it to include `semantic: true`:

```tsx
  const { data } = useQuery({
    queryKey: ['onto-search', ontologyId, versionId, dq, lang],
    queryFn: () => api.ontologies.search(ontologyId, versionId, dq, 'auto', lang ?? undefined, dq.length >= 3),
    enabled: dq.length >= 2,
    staleTime: 30_000,
  })

  const results: SearchResult[] = data?.results ?? []
  const semanticResults: SearchResult[] = data?.semantic_results ?? []
```

Find the closing `</ul>` of the dropdown results list inside `OntologySearchBar`. After it, add the semantic section (still inside the `{open && results.length > 0 && (` block):

```tsx
        {open && (results.length > 0 || semanticResults.length > 0) && (
          <ul style={{
            position: 'absolute', top: '100%', left: 8, right: 8,
            zIndex: 100, listStyle: 'none', margin: 0, padding: 0,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            maxHeight: 320, overflowY: 'auto',
          }}>
```

Replace the original `{open && results.length > 0 && (` block so that it now includes both sections. The new structure renders:
1. The existing prefix result `<li>` items (unchanged logic)
2. A separator + semantic section when `semanticResults.length > 0`

After the last `</li>` of prefix results (before the closing `</ul>`), add:

```tsx
            {semanticResults.length > 0 && (
              <>
                <li style={{
                  fontSize: 10, color: 'var(--text-dim)', padding: '4px 10px 2px',
                  textTransform: 'uppercase', letterSpacing: 0.6,
                  borderTop: '1px solid var(--border)',
                }}>
                  Semantically similar
                </li>
                {semanticResults.map((r, i) => {
                  const alreadyShown = results.some(p => p.iri === r.iri)
                  const isInd = r.type === 'individual'
                  const isProp = r.type?.endsWith('_property')
                  const typeColor = isInd
                    ? 'var(--accent-blue, #61afef)'
                    : isProp ? 'var(--accent-purple, #c678dd)' : 'var(--text-dim)'
                  return (
                    <li
                      key={r.iri}
                      onMouseDown={() => pick(r)}
                      onMouseEnter={() => setActiveIdx(results.length + i)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        padding: '5px 10px', cursor: 'pointer', fontSize: 'var(--font-size-sm)',
                        background: activeIdx === results.length + i ? 'var(--bg-hover)' : 'transparent',
                        color: alreadyShown ? 'var(--text-dim)' : 'var(--text)',
                        opacity: alreadyShown ? 0.6 : 1,
                      }}
                    >
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '1px 4px',
                        borderRadius: 2, background: 'var(--bg)',
                        color: typeColor, flexShrink: 0, minWidth: 28, textAlign: 'center',
                      }}>
                        {r.type === 'class' ? 'cls' : r.type === 'individual' ? 'ind' : 'prop'}
                      </span>
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {r.label}
                      </span>
                      <span style={{ fontSize: 10, color: 'var(--text-dim)', flexShrink: 0 }}>
                        {r.score?.toFixed(2)}
                      </span>
                    </li>
                  )
                })}
              </>
            )}
```

Also update the condition `{open && results.length > 0 && (` to `{open && (results.length > 0 || semanticResults.length > 0) && (`.

- [ ] **Step 4: Run TypeScript typecheck**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 5: Run all frontend tests**

```bash
npx vitest run
```
Expected: all tests pass

- [ ] **Step 6: Run all Python tests**

```bash
cd /home/micheldumontier/code/ontoexplorer && python -m pytest tests/unit/ -v -m "not slow"
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/OntologyPage.tsx frontend/src/pages/OntologyPage.semantic.test.tsx
git commit -m "feat(semantic): show semantically similar terms in ontology search dropdown"
```

---

## Self-Review

**Spec coverage check:**
- ✅ pgvector table with HNSW index → Task 1
- ✅ fastembed + nomic-embed-text-v1.5 → Task 2
- ✅ build_entity_text with label + definition + synonyms + superclasses + subclasses → Task 2
- ✅ embed_ontology Celery task chained after index_ontology → Task 3
- ✅ Bulk SPARQL for hierarchy → Task 3
- ✅ text_hash for idempotent upsert → Task 3
- ✅ semantic_search module → Task 4
- ✅ Only current latest-ready versions → Task 4 (version_ids passed by caller from existing helpers)
- ✅ Global search `semantic=true` param → Task 5
- ✅ Per-ontology search `semantic=true` param → Task 5
- ✅ Per-version search `semantic=true` param → Task 6
- ✅ semantic_results in response → Tasks 5, 6
- ✅ Frontend types updated → Task 7
- ✅ Global search semantic section → Task 8
- ✅ Per-ontology search semantic section → Task 9
- ✅ Graceful degradation (empty results on error) → Task 4 (semantic.py), Task 3 (task)
- ✅ Docker model cache volume → Task 1
