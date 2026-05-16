# Semantic Search Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add vector-based semantic search to OntoExplorer so users can find ontology terms by meaning, not just by prefix match.

**Architecture:** fastembed + `nomic-ai/nomic-embed-text-v1.5` produces 768-dim embeddings at ingest time via a new Celery task. Vectors are stored in PostgreSQL via pgvector. At query time, the user's natural language query is embedded and compared via cosine similarity. Semantic results appear as a supplementary section below the existing prefix-search results.

**Tech Stack:** fastembed, pgvector (PostgreSQL extension), SQLAlchemy, Alembic, Celery, FastAPI, React

---

## Scope

- Semantic search runs against **current latest-ready versions only** — no stale/old versions.
- Available in **both** global cross-ontology search and per-ontology term search.
- The existing Redis prefix search is **unchanged** — semantic results augment, not replace it.
- Embeddings are computed **at ingest time** as a new Celery task chained after `index_ontology`.

---

## Data Model

### New table: `term_embeddings`

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE term_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id  UUID NOT NULL REFERENCES ontology_versions(id) ON DELETE CASCADE,
    entity_iri  TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    text_hash   TEXT NOT NULL,
    embedding   vector(768) NOT NULL,
    UNIQUE (version_id, entity_iri)
);
CREATE INDEX ON term_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON term_embeddings (version_id);
```

- `text_hash`: SHA-256 of the full embedded text (label + synonyms + definition + hierarchy labels). Used to skip re-embedding unchanged entities on re-ingest — upsert is idempotent.
- `ON DELETE CASCADE`: removing an ontology version automatically cleans up its embeddings.
- HNSW index: sub-millisecond approximate nearest neighbour search.

### SQLAlchemy model

New `TermEmbedding` model added to `ontoexplorer/models/db.py` using `pgvector.sqlalchemy.Vector`.

### Alembic migration

New migration enables the `vector` extension and creates the table + indexes.

---

## Embedding Text Format

Each entity is embedded as a single string:

```
{primary_label}. {definition}. Synonyms: {synonym1}; {synonym2}.
Superclasses: {parent1_label}, {parent2_label}.
Subclasses: {child1_label}, {child2_label}.
```

Rules:
- **Superclasses:** direct asserted `rdfs:subClassOf` parents, up to 5, excluding `owl:Thing` / `owl:topObjectProperty`. Labels fetched from Oxigraph via SPARQL.
- **Subclasses:** direct children, capped at 10 to avoid noise for broad classes.
- Sections with no content are omitted (e.g. no definition → skip definition sentence).
- fastembed handles `search_document:` / `search_query:` task prefixes internally via `passage_embed()` vs `query_embed()`.
- `text_hash` = SHA-256 of the full formatted string.

---

## Embedding Pipeline

### New file: `ontoexplorer/modules/search/embedder.py`

- `get_embedder() -> TextEmbedding` — process-level singleton; model downloaded to `FASTEMBED_CACHE_PATH` on first use (~270 MB).
- `build_entity_text(entity: dict, parent_labels: list[str], child_labels: list[str]) -> str` — formats the embedding string per the rules above.
- `embed_entities(entities: list[dict]) -> list[tuple[str, str, str, list[float]]]` — returns `(iri, entity_type, text_hash, embedding)` per entity; batches at 64 via `passage_embed()`.
- `embed_query(text: str) -> list[float]` — single query embedding via `query_embed()`.

### New Celery task: `embed_ontology`

Location: `ontoexplorer/modules/jobs/tasks.py`

```python
@celery_app.task(name="ontoexplorer.embed_ontology")
def embed_ontology(version_id: str, ontology_id: str = "") -> dict:
```

Triggered by `index_ontology` on success via `.delay()` (same pattern as `detect_profile` → `index_ontology`).

Steps:
1. Read all entities from the Redis search index (full scan of the version's prefix set).
2. Run two bulk SPARQL queries against Oxigraph for the full version's named graph: one for all direct superclass labels (`?entity rdfs:subClassOf ?parent`) and one for all direct subclass labels (`?child rdfs:subClassOf ?entity`). Build a `dict[iri → {parents, children}]` map in memory. This avoids N+1 queries.
3. Build embedding text, compute SHA-256 hash.
4. Call `embed_entities()` in batches of 64.
5. Upsert into `term_embeddings` (skip rows where `text_hash` matches — no re-embedding needed).
6. Log progress every 1 000 entities.
7. On failure: log and exit — prefix search continues working; semantic search degrades to empty results.

### Docker / environment

- New env var `FASTEMBED_CACHE_PATH` pointing to a named Docker volume so the model persists across container restarts.
- No new service — fastembed runs inside the existing Celery worker container.
- `fastembed` added to Python dependencies.
- `pgvector` added to Python dependencies.

---

## Search API

### New file: `ontoexplorer/modules/search/semantic.py`

```python
async def semantic_search(
    query: str,
    db: AsyncSession,
    version_ids: list[str],
    limit: int = 10,
) -> list[dict]:
```

- Embeds `query` via `embed_query()`.
- Runs a single pgvector cosine similarity query: `1 - (embedding <=> :vec)` as score, filtered to `version_id = ANY(:ids)`.
- Fetches label / type / source for each hit from Redis (same lookup as existing search).
- Returns list of dicts with `iri`, `label`, `type`, `source`, `score`, `match_type: "semantic"`, `ontology_id`.
- Returns `[]` gracefully if `version_ids` is empty or no embeddings exist yet.

### API changes

Both endpoints gain an optional `semantic=true` query param. Version resolution stays exactly as-is; the caller passes the resolved `version_ids` to `semantic_search`.

**Global:** `GET /api/v1/search?q=...&semantic=true`
- Uses existing `_latest_ingested_versions()` to get current version IDs.
- Passes all IDs to `semantic_search` — single pgvector query across all ontologies.

**Per-ontology:** `GET /api/v1/ontologies/{id}/search?q=...&semantic=true`
- Uses existing version resolution (already resolves to latest ready version).
- Passes the single `version_id` to `semantic_search`.

**Response shape** (both endpoints):
```json
{
  "mode": "entity",
  "query": "...",
  "results": [...],
  "semantic_results": [
    {
      "iri": "...", "label": "...", "type": "class",
      "score": 0.91, "match_type": "semantic",
      "source": "...", "ontology_id": "..."
    }
  ]
}
```

`semantic_results` is present only when `semantic=true` is passed. If embeddings are not yet available for a version, it returns `[]`.

---

## Frontend

### Where

- Global search page (wherever `GET /api/v1/search` is called)
- Per-ontology term browser (`TermPanel` / search input on `OntologyPage`)

### Behaviour

- `semantic=true` is appended to search requests when the query is ≥ 3 characters.
- If `semantic_results` is non-empty, a subtle separator and **"Semantically similar"** heading appear below the existing prefix results.
- Each semantic result uses the same entity row style as prefix results, with:
  - A small similarity score badge (e.g. `0.91`)
  - A dim `semantic` tag in place of `exact` / `prefix`
- Entities that already appear in the prefix results are visually de-emphasised (dimmed) in the semantic section — not hidden, so the user sees the overlap.
- If `semantic_results` is absent or empty, the semantic section is not rendered — no error, no spinner.

---

## Error Handling & Degradation

- If the `embed_ontology` task fails, prefix search is unaffected. `semantic_results` returns `[]`.
- If pgvector is unavailable, the `semantic_search` function catches the exception and returns `[]` — the API does not error.
- If the fastembed model has not been downloaded yet (first worker startup), the task logs a warning and exits; it will be retried on the next ingest.

---

## Testing

- Unit: `build_entity_text()` with various combinations of present/absent fields.
- Unit: `embed_query()` returns a list of 768 floats.
- Integration: ingest a small test ontology → assert `term_embeddings` rows created with correct `version_id` and `entity_type`.
- Integration: `semantic_search("cardiac muscle cell", db, [version_id])` returns results with `score > 0.5`.
- API: `GET /search?q=heart&semantic=true` returns both `results` and `semantic_results`.
- Frontend: semantic section visible when results present; absent when empty.
