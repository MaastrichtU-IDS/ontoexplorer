# Fix #402: concurrent fleet-wide semantic search exhausts the Postgres shared lock table

**Goal:** make fleet-wide semantic search survive concurrency by removing the all-64-partition `entity_index` join from the hot query, so each request locks a handful of partitions instead of 64.

**Architecture:** split each semantic query into (1) a vector top-N over `term_embeddings` alone (+ `versions` for `ontology_id`), which touches **0** `entity_index` partitions and keeps the HNSW index, then (2) an enrichment lookup against `entity_index` keyed to the ≤N distinct versions actually in the top-N, which partition-prunes to those N partitions. Output shape is byte-for-byte unchanged. Plus a defense-in-depth Postgres `max_locks_per_transaction` bump in the services repo.

**Tech Stack:** FastAPI + SQLAlchemy async + asyncpg + pgvector (HNSW) + hash-partitioned `entity_index` (64 parts).

**Spec:** GitHub issue #402 (root cause + evidence). No design doc beyond this plan.

## Evidence this plan rests on (EXPLAIN on dev, 2026-11-12)

| plan | `entity_index` partitions in plan (= partition locks) |
|---|---|
| current single query, fleet-wide (`version_id = ANY(2013)`) | **64** |
| vector-only (`term_embeddings` + `versions`) | **0**, still `Index Scan using term_embeddings_new_embedding_idx` (HNSW) |
| enrichment `WHERE version_id = ANY(:vids) AND iri = ANY(:iris)`, 20 concrete versions | **19** (one per distinct version — pruning works) |
| enrichment, 1 version | **1** |

Current failure (k6, 150 VU, fleet-wide): 54% requests fail with `out of shared memory / increase max_locks_per_transaction`; the shared lock table is overflowed because 150 concurrent queries × 64 partition locks each.

## Global Constraints

- **Output shape is frozen.** `semantic_search` returns the same list of dicts (`iri,label,short,type,source,match_type,score,version_id,ontology_id`); `semantic_related` returns the same dicts (`iri,primary_label,labels,short,type,ontology_id,ontology_title,ontology_shortname,version_id,source,definitions,score`). Six callers (`api/search.py`, `api/global_search.py` ×3, `api/ols/llm.py` ×2, `api/entities.py`) must not change.
- **Preserve existing semantics:** dedup by `iri` keeping the highest-scoring row (results are distance-ordered); a candidate with no `entity_index` row / NULL `primary_label` is skipped (same as today's LEFT-JOIN-then-skip); embed-backend failure logs `semantic_search_embed_failed` and returns `[]` (search) / raises `EmbedUnavailable` (related); DB error logs `semantic_search_query_failed` and returns `[]`.
- **No migration, no backfill, no indexer change.** `term_embeddings` is not partitioned; the fix is read-path only.
- **Both `db.execute` calls run in the one request transaction** (same AsyncSession) — acceptable; combined locks ≈ 4 (vector) + ≤N (enrichment) ≪ 64.
- Ruff `select=["F"]` only; keep `from __future__ import annotations`.

## Review Focus

- A `term_embeddings` row with no matching `entity_index` row (orphan) → must be skipped, not emitted with empty label (covered by Task 1 skip test).
- Fewer than `limit` labelled candidates → return fewer, never pad or error (same as today).
- `semantic_related` with `ontology_ids=None` (fleet-wide) is the lock-prone path and must take the split; the `ontology_ids` filter must still apply — moved onto the `versions` join (`v.ontology_id = ANY(:onts)`), not `entity_index`.
- sqlite test lane: only the Postgres branch of `semantic_related` changes; the sqlite Python-ranking branch is untouched.

---

## Task 1: Split `semantic_search` into vector + enrichment

**Files:**
- Modify: `ontoexplorer/modules/search/semantic.py` (`semantic_search`, L17-92)
- Test: `tests/unit/test_semantic.py`

**Interfaces:**
- Consumes: `embed_query` (unchanged), `db.execute` (now called twice).
- Produces: identical return list; same signature `semantic_search(query, db, version_ids, limit=10)`.

- [ ] **Step 1 — update the mock-based tests to the two-call shape.** `test_semantic_search_deduplicates_iris`: `db.execute` now returns the *candidate* rows on call 1 (cols `iri,type,version_id,ontology_id,score`) and *enrichment* rows on call 2 (cols `version_id,iri,primary_label,short,source`). Use `db.execute.side_effect = [vec_result, enrich_result]`. Assert the single deduped `Heart` result with `label="heart"`, `score=0.95`. Keep `test_semantic_search_empty_version_ids`, `_blank_query`, `_returns_empty_on_db_error` (now: first `execute` raises → `[]`), `_logs_and_returns_empty_on_embed_failure` green.
- [ ] **Step 2 — add `test_semantic_search_skips_candidate_with_no_entity_index_row`:** two candidates, enrichment returns a row for only one `(version_id, iri)` → the unmatched candidate is skipped, result has the labelled one only. (Pins the orphan/NULL-label behavior.)
- [ ] **Step 3 — run the tests, watch them fail** (`.venv/bin/pytest tests/unit/test_semantic.py -q`), confirming the current single-call code can't satisfy the two-call mocks.
- [ ] **Step 4 — rewrite `semantic_search`:**
  - Keep the guard + `embed_query` block verbatim.
  - **Vector query** (`try/except` → `semantic_search_query_failed` → `[]`): `SELECT te.entity_iri AS iri, te.entity_type AS type, te.version_id, v.ontology_id, 1 - (te.embedding <=> CAST(:vec AS vector)) AS score FROM term_embeddings te JOIN versions v ON v.id = te.version_id WHERE te.version_id = ANY(:ids) ORDER BY te.embedding <=> CAST(:vec AS vector) LIMIT :lim`, params `{vec, ids, lim: limit}`. `cand = result.all()`; if empty → `[]`.
  - **Enrichment** (`try/except` → `semantic_search_enrich_failed` → `[]`): `vids = list({c.version_id for c in cand})`, `iris = list({c.iri for c in cand})`; `SELECT version_id, iri, primary_label, short, source FROM entity_index WHERE version_id = ANY(:vids) AND iri = ANY(:iris)`; build `meta[(version_id, iri)] = row`.
  - **Assemble:** iterate `cand` in order; skip if `iri` already `seen`; `m = meta.get((c.version_id, c.iri))`; skip if `m is None or m.primary_label is None`; else append the dict (same keys as today; `label=m.primary_label`, `short=m.short or ""`, `source=m.source or ""`, `type=c.type`, `score=round(float(c.score),4)`, `version_id=c.version_id`, `ontology_id=c.ontology_id`). `break` once `len(out) == limit`.
- [ ] **Step 5 — run tests to green.**
- [ ] **Step 6 — commit** (`fix(search): split semantic_search vector/enrichment to stop 64-partition lock (#402)`).

## Task 2: Split the Postgres branch of `semantic_related`

**Files:**
- Modify: `ontoexplorer/modules/search/semantic.py` (`semantic_related`, Postgres branch L122-146; leave the sqlite branch L148-173 untouched)
- Test: `tests/unit/test_semantic.py` (add a related-path test) or extend existing related coverage if present

**Interfaces:**
- Consumes: `embed_query`, optional `ontology_ids`. Produces identical dict rows + `score`.

- [ ] **Step 1 — add `test_semantic_related_pg_splits_and_shapes` (monkeypatch dialect to `postgresql`, mock `db.execute` side_effect = [vector rows, enrichment rows]):** assert the returned dicts carry `labels`, `definitions`, `ontology_title`, `score` and that the `ontology_ids` filter path builds without error. Verify it fails against current single-query code.
- [ ] **Step 2 — rewrite the Postgres branch:**
  - **Vector query:** `SELECT te.entity_iri AS iri, te.version_id, 1 - (te.embedding <=> CAST(:vec AS vector)) AS score FROM term_embeddings te JOIN versions v ON v.id = te.version_id WHERE te.entity_type = :type AND te.version_id = ANY(:ids) {AND v.ontology_id = ANY(:onts)} ORDER BY te.embedding <=> CAST(:vec AS vector) LIMIT :k`. `entity_type` lives on `term_embeddings`; the ontology filter moves to the `versions` join so `entity_index` is not touched here.
  - **Enrichment:** `SELECT ei.iri, ei.version_id, ei.primary_label, ei.labels, ei.short, ei.type, ei.ontology_id, ei.source, ei.definitions, o.title AS ontology_title, o.shortname AS ontology_shortname FROM entity_index ei JOIN ontologies o ON o.id = ei.ontology_id WHERE ei.version_id = ANY(:vids) AND ei.iri = ANY(:iris)` → `meta[(version_id, iri)]`.
  - **Assemble** in candidate (distance) order, keyed by `(version_id, iri)`; drop candidates with no enrichment row; emit the same dict shape with `score = round(float(c.score), 4)`. Keep `k` cap.
- [ ] **Step 3 — tests green** (`.venv/bin/pytest tests/unit/test_semantic.py tests/unit/test_global_search_semantic.py -q`).
- [ ] **Step 4 — commit.**

## Task 3: Defense-in-depth — raise `max_locks_per_transaction` (services repo)

**Files:**
- Modify: Postgres config in `MaastrichtU-IDS/services` (dev overlay; the same place `shared_buffers=8GB` / `max_connections=250` are set — grep the overlay for `max_connections`).

- [ ] **Step 1 — set `max_locks_per_transaction = 256`** (4× headroom; grows the shared lock table ~`256 × (max_connections+max_prepared)` slots — a few MB). This is a *static* parameter → requires a Postgres restart to take effect.
- [ ] **Step 2 — note in the PR** that this is a safety margin; Tasks 1-2 are the actual fix (they cut per-query locks 64 → ≤~24). Ship it as its own services PR (independent of the app roll; needs a planned PG restart).

## Verification

1. **Unit:** `.venv/bin/pytest tests/unit/test_semantic.py tests/unit/test_global_search_semantic.py -q` green; full `tests/unit` no new failures.
2. **Dev smoke (post-roll, in-cluster):** fleet-wide `GET /api/v1/search?q=glucose%20metabolism&semantic=true&backend=pg&limit=20` returns 200 with sensible hits; `EXPLAIN` of the new vector query shows 0 `entity_index` partitions + HNSW index scan; a scoped single-ontology semantic search still returns identical results to before.
3. **Load (the #402 acceptance gate):** re-run the in-cluster k6 semantic Job (`k6-semantic.js`, 150-VU ramp) → `http_req_failed < 5%`, **zero** `out of shared memory` in api logs across the run, p95 within budget. Capture api-fleet CPU (expected to stay low — CPU was already fixed by #394). Record before/after in the #402 comment.

## Rollout

App: PR to `MaastrichtU-IDS/ontoexplorer` → user merges → tag next `0.4.x` → release build → services lockstep bump (9 pins) → ArgoCD roll → verify. No DB migration. Services PR for Task 3 is separate (PG restart). Then run the k6 acceptance gate and update #402.
