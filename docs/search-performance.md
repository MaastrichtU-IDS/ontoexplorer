# Search performance

This document is the as-built reference for OntoExplorer's search and
term-detail stack after the May 2026 perf work. Three endpoints sit in the
hot path:

| Endpoint | Purpose | Hot | Cold |
|---|---|---|---|
| `GET /api/v1/search` | cross-ontology entity / MOS search | ~3 ms | ~17 ms |
| `GET /api/v1/autocomplete` | per-keystroke completions | ~5 ms | ~25–150 ms |
| `GET /api/v1/ontologies/{oid}/{vid}/terms/{iri}` | term-detail panel | ~7 ms | ~1.0 s |

"Hot" = served from the relevant Redis response cache. "Cold" = miss path.
Numbers measured on a 25-ontology dev instance with ~275 k entities indexed.

## Architecture

Three storage layers serve the search path. Each has a clear role.

```
┌────────────────────────────────────────────────────────────────────┐
│   Frontend (React + tanstack-query)                                │
│   • client-side cache, in-flight cancellation, hover prefetch      │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────┐
│   API (FastAPI / asyncio)                                          │
│   • response cache (60s for /search, 5min for /terms)              │
│   • parallel fan-out (asyncio.gather)                              │
└──────────┬──────────────┬───────────────┬───────────────┬──────────┘
           │              │               │               │
   ┌───────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
   │ Postgres     │ │ Redis      │ │ Oxigraph    │ │ ELK         │
   │ entity_index │ │ caches     │ │ (RocksDB)   │ │ service     │
   │ + pgvector   │ │ + sorted-  │ │             │ │             │
   │              │ │ set legacy │ │ asserted    │ │ inferred    │
   │ canonical    │ │            │ │ triples     │ │ classifn    │
   │ keyword      │ │ response-  │ │ per-version │ │             │
   │ index, slim  │ │ cache only │ │ named graph │ │ 24h cache   │
   │ row per      │ │            │ │             │ │ in Redis    │
   │ (ver, iri)   │ │            │ │             │ │             │
   └──────────────┘ └────────────┘ └─────────────┘ └─────────────┘
```

**Postgres `entity_index`** is the source of truth for keyword search and
label lookups. Schema in `alembic/versions/f6e1d2c3b4a5_add_entity_index.py`.
Populated from Redis after every ingest (see
[`ontoexplorer/modules/search/pg_indexer.py`](../ontoexplorer/modules/search/pg_indexer.py)).

**Redis** holds three TTL'd response caches and the legacy sorted-set index
(retained as a fallback via `?backend=redis` on `/search`; can be removed
once the PG path has soaked):

| Key prefix | TTL | Invalidated on |
|---|---|---|
| `search:result:*` | 60 s | ingest, deprecation |
| `search:autocomplete:*` | 60 s | ingest, deprecation |
| `search:term:*` | 5 min | ingest, deprecation |
| `elk:sub:*`, `elk:super:*` | 24 h | `invalidate_cache(version_id)` |

**Oxigraph** holds the raw triples per named graph (`urn:ontology:{oid}:{vid}`).
Used for term-detail SPARQL only — search no longer hits Oxigraph directly.

**ELK service** answers per-IRI inferred sub/super-class queries via HTTP.
Results are cached in Redis with a 24-hour TTL because they're immutable for
the lifetime of a version.

## `/search` — cross-ontology entity / MOS search

[`ontoexplorer/api/global_search.py`](../ontoexplorer/api/global_search.py),
[`ontoexplorer/modules/search/pg_search.py`](../ontoexplorer/modules/search/pg_search.py).

Default backend is Postgres. Query strategy is a **two-stage** lookup:

1. **Prefix tier** — `btree(primary_label_norm text_pattern_ops)` range scan
   on `primary_label_norm LIKE 'q%'`. Sorts by `(tier, LENGTH, norm, iri)`
   where tier 0 = exact match, tier 1 = prefix. Length-ranking surfaces the
   tighter target ("membrane" outranks "membrana tympaniformis" for q=membran).
2. **Word-suffix tier** — `GIN(search_tsv)` `@@ to_tsquery('simple', 'w1 & w2:*')`
   for the rest. Only invoked when the prefix tier doesn't fill the limit.

**camelCase / snake_case handling**: indexing time runs
`split_compound_labels()` on the primary label so `PizzaSauce` produces
`primary_label_norm = "pizza sauce"`. Query "pizza sauce" matches as tier-0
exact rather than fall-through-to-tsv. `search_text` includes both forms so
either spelling tokenizes correctly.

**Multi-word queries**: built as `w1 & w2 & w3:*` (AND with the last token
prefix-matched). Single-word stays `w:*`.

**Hybrid ranking** (when `?semantic=true`): keyword and pgvector HNSW
results are fused via Reciprocal Rank Fusion (`1/(60+rank)`) — see
[`pg_search.py:rrf_merge`](../ontoexplorer/modules/search/pg_search.py).
Avoids the BM25-vs-cosine score-normalization problem.

**Response cache**: 60 s, key `blake2b(q | limit | lang | semantic | backend)`.
Invalidation drops the namespace on ingest + deprecation.

## `/autocomplete` — per-keystroke completions

Same backing store and patterns as `/search`. Differences:

- **Minimum 2 chars** enforced at the API layer. Single-letter prefixes
  match tens of thousands of rows and trigger full-table sort regardless of
  index choice; not useful for autocomplete.
- **Context-aware**: `partial_parse` from the MOS parser classifies the
  cursor position. `EXPECT_KEYWORD`, `EXPECT_INT`, and empty-`EXPECT_ENTITY`
  contexts return constant lists with zero I/O. Only `OPEN_QUOTE` and
  `EXPECT_ENTITY` with partial hit Postgres.
- **Frontend debounce** (200 ms) keeps per-keystroke load down. With the
  response cache, refinement keystrokes after the first usually hit warm.

## `/terms/{iri}` — term detail

Largest endpoint of the three, by far the most work. The handler is in
[`ontoexplorer/api/ontologies.py`](../ontoexplorer/api/ontologies.py) under
`get_term`. Cold path is ~1 s; hot (response cache or hover-prefetched) is
single-digit ms.

### Work breakdown (parallel where possible)

```
                   props + asserted_sub SPARQL  (always, ~50 ms)
                            │
                  is_property check from rdf:type
                            │
                 ┌──────────┴──────────┐
                 │                     │
       class:  ELK sub + super        property:  skip ELK entirely
        (parallel, cached            (saves ~2.6 s wall-clock)
         24h in Redis)
                 │                     │
                 └──────────┬──────────┘
                            │
              ┌─────────────┼─────────────┬───────────────┐
              │ asyncio.gather across:                    │
              │  • Oxigraph sync block (quad walks)       │
              │  • _check_is_inverse_target (SPARQL ASK)  │
              │  • usage SPARQL (if property)             │
              │  • schema_props SPARQL (if class)         │
              └─────────────┬─────────────────────────────┘
                            │
              if class: class_usage SPARQL  (uses _adc_map)
                            │
                       JSON response
```

### Three response-cache TTL layers

A click on a term in the class tree typically sequences:

```
hover → queryClient.prefetchQuery     (warms client + server caches)
click → useTerm                       (fast path: client cache hit)
        useTermExpanded               (parallel fetch of deferred sections)
```

### Deferred-to-lazy sections

Three expensive ancestor-walking sections moved off the main response into
`GET /ontologies/{oid}/{vid}/term-expanded/{iri}`:

- `inferred_superclass_expressions` (anonymous superclass restrictions
  inherited via named superclasses — 20-ancestor quad walk)
- `inferred_disjoint_with` (pairwise disjointWith + `owl:AllDisjointClasses`
  membership across all ancestors)
- `inherited_schema_properties` (SPARQL with 30-ancestor VALUES clause)

The frontend fetches both endpoints in parallel; the deferred sections fill
in ~10 ms after the main panel renders because they reuse the ELK Redis
cache populated by the main call.

### Usage-table pagination

`usage` (when property) and `class_usage` (when class) default to 10 rows in
the main response with `usage_has_more` / `class_usage_has_more` flags.
"Show more" calls
`GET /ontologies/{oid}/{vid}/term-usage/{iri}?offset=N&limit=10` which routes
to property-usage or class-usage SPARQL based on the term's `rdf:type`.

### Hover prefetch

`ClassTree` calls `queryClient.prefetchQuery` on `onMouseEnter`. With the
5-minute Redis response cache, the click is served from the client's
in-memory cache (instant) or from Redis (~7 ms). For users browsing siblings
in the tree, this turns most clicks into a 0-ms render.

## Concurrency model

Per-request fan-out uses Python's default `asyncio` event loop plus the
`asyncio.to_thread` executor for the synchronous Oxigraph and Redis
operations. Key constraints discovered along the way:

- **Redis is single-threaded**. Concurrent pipelines from many threads
  serialize on Redis's CPU. The default executor size (`min(32, cpu+4)`)
  is enough — bigger pools just queue at Redis. We don't tune it.
- **The singleton Redis client** (`indexer._get_redis()`) shares a
  connection pool across threads. Without it, every call constructed a
  new pool, paying a TCP-connect tax per thread per fan-out.
- **`pyoxigraph` supports concurrent read queries** on the same store, so
  multiple SPARQL queries against the term graph can `asyncio.to_thread`
  in parallel without contention.
- **Mega-pipelines hurt under burst**. We tried collapsing all
  per-version Redis pipelines for `/autocomplete` into one — under
  concurrent requests the batches serialize end-to-end on the server,
  worse than per-thread interleaving. The autocomplete path stays
  per-version-pipeline; the response cache covers the burst case.

## Cache invalidation

Two flush triggers, both in the existing ingest / deprecation pipeline:

1. **On version-ready ingest** (`ontoexplorer/modules/jobs/tasks.py`):
   ```python
   for pattern in ("search:result:*", "search:autocomplete:*", "search:term:*"):
       for k in r.scan_iter(pattern, count=500):
           r.delete(k)
   ```
   Plus `invalidate_latest_ready_versions_cache()` for the in-process
   30-second `latest_ready_versions` cache.

2. **On deprecation** (`ontoexplorer/api/ontologies.py:deprecate_version`):
   Same Redis flush + `DELETE FROM entity_index WHERE version_id = :vid` so
   deprecated rows disappear immediately from search.

ELK Redis cache (`elk:sub:*`, `elk:super:*`) is flushed via
`ontoexplorer/clients/reasoning.py:invalidate_cache(version_id)`, called
from the deprecation handler.

## Migration / rebuild

To rebuild `entity_index` from scratch (e.g. after schema changes):

```bash
docker cp scripts/backfill_entity_index.py ontoexplorer-worker-1:/app/backfill_entity_index.py
docker exec ontoexplorer-worker-1 python /app/backfill_entity_index.py
```

Reads from Redis (per-version entity hashes set by `build_index` during
ingest) and bulk-INSERTs to Postgres. ~30 s for 275 k rows.

## Where to optimize next

Diminishing returns from here, but documented for future reference:

- **Per-section streaming endpoints**: split the main `/terms/{iri}`
  response into smaller per-section endpoints (subclasses, properties,
  usage, etc.) so the frontend can render incrementally. HTTP/2
  multiplexing makes this cheap. Would shave the ~1 s cold to ~500 ms
  perceived first-paint.
- **Precompute inferred-tree relationships at ingest** into a flat
  Postgres table (`inferred_subclasses(version_id, parent_iri, child_iri)`).
  Eliminates ELK calls from the request path entirely; ingest does the
  classification once and stores the result.
- **Retire the Redis sorted-set index** (`search:entities:*:prefix`).
  No production reader now uses it; only `?backend=redis` keeps it alive
  as a fallback. Drop the `build_index` Redis writes once you're
  confident in the PG path. Frees ~100 MB of Redis.
- **ONNX-quantized embedder** for semantic search. Current
  `nomic-embed-text-v1.5` runs in fp32 fastembed at ~200 ms / query.
  Int8 quantization gives 3-4× on CPU. Means hybrid mode could become
  default.
- **`/sparql/content` could use Postgres for label-resolution** in client
  IRI-resolver paths the same way `/terms/{iri}` does. Currently runs
  through Oxigraph for everything.

## Commit history

The work landed in roughly this order on `main`:

```
025907c  perf(terms): lazy /term-expanded endpoint + PG-backed label resolve
af119b3  perf(elk): cache per-IRI sub/superclass results in Redis
d646a13  perf(terms): paginate usage tables; hover-prefetch; skip ELK for properties
187d62f  perf(terms): parallelize independent SPARQL + Oxigraph work
977d9f1  perf(terms): response cache + pipelined label lookups
755de7e  fix(search): handle camelCase labels + multi-word queries
ab2d1a2  fix(search): rank shorter labels higher within prefix tier
6afa231  feat(search): migrate /autocomplete to Postgres; live search on home
99ad94e  feat(search): Postgres-backed entity_index with HNSW hybrid ranking
```
