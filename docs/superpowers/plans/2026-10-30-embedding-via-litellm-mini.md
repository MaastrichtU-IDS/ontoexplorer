# Embedding via LiteLLM / Mac mini (B2: llama-server fallback) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all OntoExplorer embedding (ingest + query) through the LiteLLM gateway's `nomic-embed-text` model (Mac mini, Metal GGUF) as the primary backend, with a co-located CPU `llama-server` running the identical GGUF as an automatic fallback, so the app becomes a thin OpenAI `/v1/embeddings` client and every stored vector comes from one embedder.

**Architecture:** The app's `embedder.py` stops loading fastembed/ONNX in-process and instead calls an OpenAI-compatible `/v1/embeddings` endpoint. Primary base-URL is the LiteLLM gateway (model `nomic-embed-text`, served by `llama-server` on the mini via Metal). Fallback base-URL is a `llama-server` sidecar in the same pod, serving the identical `nomic-embed-text-v1.5.Q8_0.gguf` on CPU. Both backends run the same GGUF through the same server software, so stored and query vectors are consistent **provided their flags match** (pooling, normalization, context/ubatch, llama.cpp build) — this plan pins and verifies that, it does not assume it. A one-time re-embed migrates the existing (differently-produced, non-text-prefixed) index onto the unified GGUF producer via a shadow table + one-shot HNSW build + atomic swap, and the backfill completes **before** the app flips producers so there is no mixed-producer interim.

**Tech Stack:** Python 3.12, FastAPI, Celery, SQLAlchemy (async, asyncpg), pgvector (`Vector(768)`, HNSW), `httpx` (already a dependency), LiteLLM gateway, `llama-server` (llama.cpp), k3s/ArgoCD GitOps across the app repo (`MaastrichtU-IDS/ontoexplorer`) and services repo (`MaastrichtU-IDS/services`, dev pins at `ids3/projects/ontoexplorer/dev/app.yaml`).

**Spec:** This document's Design section below (brainstormed in-session 2026-10-30, issue #229 follow-up). Reviewed once by a Fable-model agent; its verified corrections are folded in.

---

## Design (the decisions this plan locks in)

1. **One embedder, two hosts.** The ONLY embedding runtime is `llama-server` on `nomic-embed-text-v1.5.Q8_0.gguf`. fastembed and onnxruntime are removed from the app entirely. "Primary" (mini, Metal) and "fallback" (sidecar, CPU) are the same model artifact and flags, so they share one `model_rev`; the fallback is a *degraded-speed*, not degraded-consistency, path — **but only if** the mini's `llama-server` flags/build match the sidecar's (Task 0 pins and verifies this; it is not assumed).
2. **The app is a thin HTTP client.** `embed_texts` / `embed_query` keep their current signatures and call sites; their bodies become HTTP calls. Which host is used is a base-URL choice (primary → fallback on error).
3. **Prefixing is owned explicitly, and the existing index is NOT text-prefixed.** fastembed 0.8.0 does **not** prepend nomic's `search_document:` / `search_query:` text prefixes (verified: no such string in the package), so the current 3.95M vectors are untext-prefixed and were produced by a different runtime. `llama-server` also does not prefix. The client MUST prepend `search_document: ` for documents (`embed_texts`) and `search_query: ` for queries (`embed_query`). This makes the re-embed **mandatory** (not hygiene) and means ONNX/fastembed output must NOT be used as the cosine reference in Task 0.
4. **Vectors are L2-normalized client-side** regardless of the server's `--embd-normalize` setting, so cosine distance in the HNSW index is well-defined and backend-independent.
5. **Dimension is fixed at 768.** Any response whose vector length ≠ 768 is an error; never insert a wrong-dim vector (the column is `Vector(768)` and the HNSW index assumes it).
6. **Producer stamp.** Add `model_rev` to `term_embeddings`. GGUF-era value: `nomic-embed-text-v1.5-q8_0-gguf`. Pre-existing rows (NULL) are legacy. The column future-proofs later model changes and drives the incremental re-embed; it does NOT distinguish mini vs sidecar (identical).
7. **One-time re-embed via shadow table, backfill BEFORE the flip.** Build `term_embeddings_new` **with** PK + `UNIQUE(version_id, entity_iri)` + FK + `(version_id)` index but **without** the HNSW index, backfill all vectors from the gateway (while prod still runs fastembed), build the HNSW index once, then flip the app and atomically swap in one window, then reconcile any rows written to the old table during backfill.
8. **Scope:** both the batch ingest path (`embed_ontology` in the worker) and the query path (`semantic.py` in the api). Each pod type that embeds gets its own `llama-server` sidecar fallback.
9. **Dev only.** All config, keys, netpol, and the re-embed target the `ontoexplorer-dev` namespace against the single (prod) LiteLLM gateway.

## Global Constraints

- **Vector dimension:** exactly **768**, everywhere. `Vector(768)` and the HNSW index are fixed.
- **Model artifact:** `nomic-embed-text-v1.5.Q8_0.gguf`; gateway model name clients send is `nomic-embed-text`. The GGUF's sha256 must match on the mini and the sidecar (Task 0).
- **Prefixes (verbatim):** documents `search_document: `, queries `search_query: ` (trailing space included).
- **`model_rev` value (verbatim):** `nomic-embed-text-v1.5-q8_0-gguf`.
- **llama-server flags (both hosts):** `--embedding --pooling mean --embd-normalize 2 --ctx-size 8192 --ubatch-size 2048` (ubatch ≥ any single input's token count, else llama-server 500s on long inputs rather than truncating).
- **No search downtime:** the re-embed must not drop the live `term_embeddings` HNSW index until an atomic swap; the swap sets `lock_timeout`.
- **Release flow (unchanged):** app PR off `main` → squash-merge → tag `0.4.x` on main → GHCR Release builds 3 images → bump the 9 dev image pins in the services repo → merge roll PR → ArgoCD → verify `git_ref` on `/api/v1/version`. Commits end `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; PRs end `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Python 3.12; `httpx` only** for HTTP (already present) — do not add an OpenAI SDK.

## Review Focus

- **Both backends unreachable** (mini down AND sidecar down): embedding must raise so the Celery job retries — never write a zero/garbage/short vector. On the query path, `semantic.py:46` currently swallows and returns `[]`; it must at least log the embedding failure so the outage is visible. (Tasks 2, 6)
- **Prefix mismatch** (a document embedded with the query prefix or vice versa): silently wrecks recall. Tests assert the exact prefix on each path. (Tasks 2, 6)
- **Input too long for one ubatch:** `MAX_ENTITY_TEXT_CHARS=2000` (~512 tokens) plus IRI/synonym-heavy text can exceed a 512-token ubatch; llama-server returns 500, not truncation, on BOTH hosts → deterministic batch failure. Mitigate with the ubatch/ctx flags above AND a client batch-split on a too-large 4xx/5xx. (Tasks 2, 5)
- **Wrong dimension from the server** (model/response returns ≠768): rejected before any DB write. (Task 2)
- **Un-normalized server output** (`--embd-normalize` off/misbuilt): the client L2-normalizes so the index is correct regardless. (Task 2)
- **Response ordering:** OpenAI/LiteLLM `data[]` carries `index`; the client sorts by it, never assumes request order. (Task 2)
- **Re-embed coverage gap:** any `embed_ontology` write to the old table AFTER its version was snapshotted (new ingests, re-indexes, reconcile redispatches during the hours-long backfill) is absent from the new table. A post-swap row-level diff re-dispatches those versions before `_old` is dropped; `count(*)` alone is insufficient. (Task 7)
- **Gateway 429 / RPM-TPM limits during bulk backfill:** sustained 429s silently push the backfill onto the slow CPU sidecar. The client logs/counts fallback use; the backfill runs at bounded concurrency. (Tasks 2, 4)

---

## Execution order (dependencies)

`Task 0` (gate) → `1` (config) → `2` (client) → `3` (model_rev) → `4` (shadow backfill, prod still on fastembed) → `5` (sidecars) → `6` (flip app: embedder+conftest+Dockerfile) → `7` (dev config + roll + atomic swap + reconcile). Tasks 1-3 are ordinary TDD; 0,4,5,7 are infra/data with smoke verification.

---

### Task 0: Enablement & measurement (infra gate)

**Files:** services repo NetworkPolicy + vault key; no app code.

**Produces:** a reachable `EMBEDDING_BASE_URL` + `EMBEDDING_API_KEY` for dev; the GGUF sha256 + mini build/pooling from `/props`; a recorded mini throughput (texts/sec) and CPU-vs-Metal cosine.

- [ ] **Step 1:** Confirm the gateway Service DNS/port (namespace under `ids3/projects/litellm/prod`) or use the `litellm.k8s.semanticscience.org` ingress; add the NetworkPolicy egress allow from `ontoexplorer-dev`; provision a scoped LiteLLM virtual key into a dev secret.
- [ ] **Step 2:** From a dev pod, `POST /v1/embeddings` (`model: nomic-embed-text`) → confirm 768-dim. Confirm the gateway does NOT auto-prefix (prefixed vs unprefixed input must yield *different* vectors). (The probe script lives only in the session scratchpad; commit a small `scripts/embed_probe.py` for reuse.)
- [ ] **Step 3:** Capture the mini's `GET /props` (llama.cpp build + pooling) and the GGUF sha256 on the mini; record both so Task 5 can pin the identical build + file.
- [ ] **Step 4:** Measure mini throughput on ~256 realistic (~512-token) texts; record texts/sec — this sizes Task 4/7.
- [ ] **Step 5:** Stand up the sidecar image once (prefigures Task 5, same build/flags/GGUF as Step 3) and embed the same ~32 samples — **near-512-token and unicode/IRI-heavy, with the doc prefix** — via BOTH mini and sidecar; compute per-text cosine. Expect **min ≥ 0.999**; anything near 0.98 means a flag/build/file mismatch — STOP and reconcile flags, do not proceed.
- [ ] **Step 6:** Record all numbers here and in the #229 memory file.

---

### Task 1: Embedding config surface

**Files:** Modify `ontoexplorer/config.py`; Test `tests/unit/test_config_embedding.py`

**Produces** (names/types/defaults): `embedding_base_url: str = ""`, `embedding_api_key: str = ""`, `embedding_model: str = "nomic-embed-text"`, `embedding_fallback_base_url: str = "http://localhost:8090/v1"`, `embedding_timeout_s: float = 30.0`, `embedding_fallback_timeout_s: float = 120.0`, `embedding_dim: int = 768`, `embedding_doc_prefix: str = "search_document: "`, `embedding_query_prefix: str = "search_query: "`.

- [ ] **Step 1:** Failing test `test_embedding_settings_defaults_and_env_override` — asserts the defaults, then `EMBEDDING_BASE_URL`/`EMBEDDING_MODEL` env override.
- [ ] **Step 2:** Run, verify fails.
- [ ] **Step 3:** Add the fields to `Settings`.
- [ ] **Step 4:** Run, verify passes.
- [ ] **Step 5:** Commit.

---

### Task 2: The embedding HTTP client

**Files:** Create `ontoexplorer/modules/search/embed_client.py`; Test `tests/unit/test_embed_client.py`

**Produces:**
- `embed_batch(texts: list[str], *, prefix: str) -> list[list[float]]` — prepends `prefix`; POSTs `{model, input}` to primary `/embeddings`; retries 429/5xx (num_retries=2, bounded backoff) then falls back to `embedding_fallback_base_url` (its own `embedding_fallback_timeout_s`); on a "too large" 4xx/5xx **splits the batch and recurses** rather than failing; **sorts the response by `data[].index`**; L2-normalizes each vector; raises `EmbeddingError` if BOTH hosts fail or any vector length ≠ `embedding_dim`; increments a module counter / logs on each fallback use.
- `EmbeddingError(Exception)`; `MODEL_REV = "nomic-embed-text-v1.5-q8_0-gguf"`.
- Consumes `Settings` (Task 1).

- [ ] **Step 1:** Failing tests (monkeypatched httpx transport, no network): `test_embed_batch_prepends_prefix`, `test_embed_batch_normalizes` (‖v‖≈1), `test_embed_batch_rejects_wrong_dim`, `test_embed_batch_sorts_by_index` (server returns shuffled `index`), `test_embed_batch_splits_on_too_large` (413/500-too-large on a 2-item batch → two 1-item calls), `test_embed_batch_falls_back_on_primary_error`, `test_embed_batch_raises_when_both_fail`, `test_embed_batch_retries_then_falls_back_on_429`.
- [ ] **Step 2:** Run, verify fail.
- [ ] **Step 3:** Implement with a module-level `httpx.Client`; pure `_l2(vec)` helper.
- [ ] **Step 4:** Run, verify pass.
- [ ] **Step 5:** Commit.

---

### Task 3: `model_rev` column + stamp + self-healing incremental

**Files:** Modify `ontoexplorer/models/db.py` (TermEmbedding); Create `alembic/versions/<rev>_add_model_rev_to_term_embeddings.py`; Modify `ontoexplorer/modules/jobs/tasks.py` (`embed_ontology` upsert ~1958 sets `model_rev=MODEL_REV`; `_load_existing_hashes` ~1848 filters `WHERE model_rev = :rev` so legacy/other-producer rows count as changed and get re-embedded); Test `tests/unit/test_model_rev.py`.

**Produces:** `TermEmbedding.model_rev: Mapped[str | None]` (nullable, NULL = legacy); new rows carry `MODEL_REV`; the incremental path re-embeds any row whose `model_rev != MODEL_REV`.

- [ ] **Step 1:** Failing tests: `test_embed_ontology_stamps_model_rev`; `test_existing_hashes_ignores_other_model_rev` (a legacy NULL-rev row with matching text_hash is still re-embedded).
- [ ] **Step 2:** Run, verify fail (column missing).
- [ ] **Step 3:** Add column; alembic migration (add nullable String; downgrade drops); set it in the upsert; add the `model_rev` filter to `_load_existing_hashes`.
- [ ] **Step 4:** Run tests + `alembic upgrade head`/`downgrade` on a scratch DB.
- [ ] **Step 5:** Commit.

---

### Task 4: Shadow-table backfill (prod still on fastembed)

**Files:** Create `scripts/reembed_backfill.py` (resumable, bounded-concurrency); runs from a dev pod using `embed_client.embed_batch` directly against the gateway. Gated on Task 0's measured rate for scheduling.

**Consumes:** Tasks 1-3 (client + column). Does NOT need Task 6 — the deployed app still runs fastembed, writing the *old* table; this script writes only `term_embeddings_new`.

- [ ] **Step 1:** Create `term_embeddings_new` with PK, `UNIQUE(version_id, entity_iri)`, FK `version_id → versions.id ON DELETE CASCADE`, `(version_id)` btree, `model_rev` — but **no HNSW index**. Do NOT use `LIKE ... INCLUDING ALL` (it copies the HNSW index and omits the FK); declare columns/constraints explicitly.
- [ ] **Step 2:** Backfill resumably, versions ordered by vector count desc (largest ~336k first): rebuild each entity's text (`build_entity_text`), `embed_batch(texts, prefix=doc_prefix)`, insert into `term_embeddings_new` with `model_rev=MODEL_REV` and `ON CONFLICT (version_id, entity_iri) DO NOTHING` (so a crash mid-version resumes cleanly). Checkpoint completed `version_id`s. Bounded concurrency; log fallback-use counter. ~3.95M vectors / 2010 versions.
- [ ] **Step 3:** Build the HNSW index on `term_embeddings_new` once, matching the live index's opclass/params. Size Postgres `maintenance_work_mem` ≥ ~12 GB (3.95M×768×4B graph) or the build spills to the slow on-disk path — state the value and the Postgres pod memory.
- [ ] **Step 4:** Verify `count(*)` ≈ old table (minus churn), all rows `model_rev=MODEL_REV`. Leave `_new` in place for Task 7's swap.

---

### Task 5: `llama-server` fallback sidecars (services repo)

**Files:** Modify `ids3/projects/ontoexplorer/dev/app.yaml` — add a `llama-server` sidecar to `worker-embed` (ingest fallback) and `api` (query fallback); provision the GGUF (sha256 from Task 0).

**Produces:** `http://localhost:8090/v1/embeddings` inside `worker-embed` and `api`, serving the GGUF on CPU with the pinned flags (Global Constraints), 768-dim.

- [ ] **Step 1:** Add the sidecar container pinned to the **same llama.cpp image tag as the mini** (Task 0 `/props`), e.g. `ghcr.io/ggml-org/llama.cpp:server-<tag>`, command carrying the pinned flags, `--host 127.0.0.1 --port 8090` (pod-local, no Service), modest CPU/mem requests. Provision the GGUF via init/volume; verify sha256 matches Task 0.
- [ ] **Step 2:** Branch + PR (services); after ArgoCD roll, `exec` into a `worker-embed` and an `api` pod, `curl localhost:8090/v1/embeddings` → assert 768-dim and (sanity) cosine≈1.0 vs the mini for one sample.
- [ ] **Step 3:** Confirm restarts=0 on both Deployments after roll.

---

### Task 6: Flip the app to the HTTP client; drop fastembed

**Files:** Modify `ontoexplorer/modules/search/embedder.py` (replace `get_embedder`/`embed_texts`/`embed_query`; KEEP `build_entity_text`, `text_hash`, the cap constants; fix the stale "sub-batches of 128" comment at `tasks.py:1923`); Modify `pyproject.toml` (remove `fastembed`/onnxruntime); Modify `tests/conftest.py:55` (patch `embed_batch` — or `embed_texts`/`embed_query` — instead of the now-deleted `get_embedder`, and keep the `main.py` warmup thread from hitting `localhost:8090` in tests); Modify `Dockerfile:66-68` (remove the `get_embedder()` bake step and `FASTEMBED_CACHE_PATH`); Modify services `app.yaml` (drop `FASTEMBED_CACHE_PATH` env + `fastembed-cache` mount where now unused, and the `worker-embed` 32Gi memory limit — it was sized for in-process ONNX; an HTTP client needs far less); Modify `ontoexplorer/main.py:144` warmup (already try/except — keep, it becomes a sidecar readiness probe). Test: `tests/unit/test_embedder.py`.

**Consumes:** Tasks 1-2.
**Produces** (signatures unchanged): `embed_texts(texts, batch_size=EMBED_BATCH_SIZE) -> list[list[float]]` → `embed_batch(texts, prefix=settings.embedding_doc_prefix)` chunked by `batch_size`; `embed_query(text) -> list[float]` → `embed_batch([text], prefix=settings.embedding_query_prefix)[0]`; re-export `MODEL_REV`.

- [ ] **Step 1:** Failing tests: `test_embed_texts_uses_doc_prefix`, `test_embed_query_uses_query_prefix`, `test_embedder_has_no_fastembed_import`; keep the existing `build_entity_text` cap tests.
- [ ] **Step 2:** Run, verify fail.
- [ ] **Step 3:** Rewrite the three functions; delete `get_embedder`/fastembed import; update `conftest.py:55`; remove the Dockerfile bake + `FASTEMBED_CACHE_PATH`; remove `fastembed` from `pyproject.toml`; fix the stale comment.
- [ ] **Step 4:** Run the FULL unit suite (not just `test_embedder.py`) — the conftest autouse fixture change must leave the whole suite green. Build the Docker image locally to confirm it no longer fails at the bake step.
- [ ] **Step 5:** Commit.

---

### Task 7: Dev rollout + atomic swap + reconcile

**Files:** Modify services dev `configmap`/secret (`EMBEDDING_BASE_URL`=gateway, `EMBEDDING_API_KEY`=Task 0 key, `EMBEDDING_FALLBACK_BASE_URL=http://localhost:8090/v1` for `api` + `worker-embed`); standard release flow for the Task 6 app image (tag + 9 dev pins).

**Consumes:** Tasks 4,5,6.

- [ ] **Step 1:** Ship the app image (Tasks 1-3,6) via the standard release flow; set the dev embedding env; roll; verify `git_ref`.
- [ ] **Step 2:** Confirm one `embed_ontology` on a small test version writes rows with `model_rev` set, 768-dim, and (via gateway logs/latency) reached the mini. Confirm the fallback by pointing `EMBEDDING_BASE_URL` at a dead host briefly → embedding still succeeds via the sidecar → restore.
- [ ] **Step 3:** Quiesce embeds (pause the `embed`/reconcile beat). Atomic swap with `lock_timeout` set: `BEGIN; ALTER TABLE term_embeddings RENAME TO term_embeddings_old; ALTER TABLE term_embeddings_new RENAME TO term_embeddings; COMMIT;`
- [ ] **Step 4:** Post-swap row-level diff BEFORE dropping `_old`: any `(version_id, entity_iri)` in `_old` absent from the new table (rows fastembed wrote during the backfill window) → re-dispatch `embed_ontology` for those `version_id`s (now GGUF-producing). Rows in `_old` already `model_rev=MODEL_REV` can be copied rather than re-embedded.
- [ ] **Step 5:** Verify: a handful of known semantic queries return sensible neighbors (spot-check captured against `_old` before the swap); all rows `model_rev=MODEL_REV`. Un-quiesce.
- [ ] **Step 6:** Rename `term_embeddings_new_*` indexes/constraints to the canonical names (alembic-autogenerate hygiene); drop `term_embeddings_old`.
