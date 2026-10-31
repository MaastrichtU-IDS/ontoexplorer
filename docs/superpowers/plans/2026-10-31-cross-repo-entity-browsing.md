# Cross-repository entity browsing (`/browse`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each Home stat card land on a page that surfaces the entities it counts — a `/browse` page with unified text+semantic search, a searchable ontology facet, expandable definitions, and keyset browse — plus a structured-query mode for the Axioms card.

**Architecture:** Three small read endpoints over the existing `entity_index` + `term_embeddings` (FastAPI/SQLAlchemy), and a React page `EntityBrowser.tsx`. Reuse existing helpers (`pg_entity_search`, `semantic_search`'s join, `latest_ready_versions`, `read_public_stats`) rather than new query machinery. Semantic ranking degrades to "unavailable" until the embedding migration's swap lands, so the text/browse half ships independently.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Postgres + pgvector, Alembic; React + Vite + TypeScript, react-query.

**Spec:** `docs/superpowers/specs/2026-10-31-cross-repo-entity-browsing-design.md`

## Global Constraints

- **Version scope = latest-ready-per-ontology.** Every listing/count/facet is scoped to `version_id IN [v.id for v in await latest_ready_versions(db)]`. Never a `status NOT IN (...)` join — `entity_index` keeps rows for every indexed version.
- **`approx_total` unfiltered = the stat cards' cached total** (`read_public_stats(db)` → `total_classes`/`total_object_properties`/`total_data_properties`/`total_annotation_properties`/`total_individuals`). Do NOT recompute it for the no-filter case; it must equal the clicked number.
- **Individuals use `type = 'individual'`** (count parity with the card), NOT `is_individual = true`.
- **Keyset only for browse** (empty `q`): order `(primary_label_norm, iri, version_id)`, opaque `base64(json)` cursor; no `OFFSET` anywhere. **Text search uses `pg_entity_search` bounded top-N**, never rank-keyset paging.
- **Semantic** embeds via `embedder.embed_query` (applies `search_query:` prefix) in `asyncio.to_thread`; filters `term_embeddings.entity_type`; an embed-backend raise → `unavailable:true` (HTTP 200), never a 5xx.
- **Definition snippet** = `definitions[0]["value"]` (list of `{value, lang}`), trimmed; `""` when absent.
- **Page is `EntityBrowser.tsx`**, route `/browse`. `Browse.tsx` is an unrelated existing page — do not touch it.
- **Entity-type allow-list:** `class, object_property, data_property, annotation_property, individual`; anything else → 422.
- Tests run on the SQLite test DB where the existing suite does; Redis-dependent paths use the existing best-effort fallback so tests pass with Redis absent.

## Review Focus

- **Empty / zero-entity type** → browse shows a designed empty state, not a crash or a broken pager (Task 7, Task 2).
- **Embedding backend down or no embeddings yet** → `/entities/related` returns `{entities:[], unavailable:true}` (HTTP 200) and the page simply drops the Related section (Task 3, Task 7).
- **Malformed/tampered cursor** → 422, never a 500 or a silent full scan (Task 2).
- **Punned Class+NamedIndividual** → appears under Classes, absent from Individuals; counts still match the cards (Task 2).
- **Unknown/empty `ontology` filter** → empty result, not an error (Task 2).
- **High-frequency term ("cell", "protein")** in text search → stays bounded (reuses `pg_entity_search`), does not trigger a `ts_rank` full scan (Task 2).

---

### Task 1: Keyset index migration

**Files:**
- Create: `alembic/versions/<rev>_entity_index_browse_keyset.py`
- Test: `tests/unit/test_entity_browse_index.py`

**Interfaces:**
- Produces: a btree index `ix_entity_index_browse` on `entity_index (type, primary_label_norm, iri, version_id)`.

- [ ] **Step 1:** Write the failing test: assert the index exists after `upgrade` and is gone after `downgrade` (follow the pattern in the existing `test_entity_index_type_label_index` migration test if present; otherwise introspect `pg_indexes` / SQLite `PRAGMA index_list`).
- [ ] **Step 2:** Run it, confirm it fails.
- [ ] **Step 3:** Write the migration: `op.create_index("ix_entity_index_browse", "entity_index", ["type","primary_label_norm","iri","version_id"])` and the matching `drop_index` in `downgrade`. Set `down_revision` to current head.
- [ ] **Step 4:** Run the test, confirm pass; run `alembic upgrade head` on the test DB.
- [ ] **Step 5:** Commit.

---

### Task 2: `GET /entities` — listing + text search

**Files:**
- Create: `ontoexplorer/api/entities.py` (router `entities_router`)
- Create: `ontoexplorer/modules/search/browse.py` (query helpers)
- Modify: `ontoexplorer/main.py` (register `entities_router` next to `global_search_router`, same prefix convention)
- Test: `tests/integration/test_entities_list.py`

**Interfaces:**
- Consumes: `latest_ready_versions(db)`; `pg_entity_search(db, q, limit, types=, ontology_ids=)`; `read_public_stats(db)`.
- Produces:
  - `GET /api/v1/entities?type&q?&ontology?&limit=50&cursor?&lang?`
  - response `{"entities":[EntityRow], "next": str|None, "approx_total": int, "limit": int}`
  - `EntityRow = {iri, primary_label, short, type, ontology_id, ontology_title, version_id, source, definition}`
  - `browse.encode_cursor(row)->str`, `browse.decode_cursor(str)->dict` (opaque base64(json) of `{al,ai,av}`), raising `ValueError` on malformed input.
  - `browse.ENTITY_TYPES` allow-list; `browse.predicate_for(type)` → `("type = :t", {"t": type})` for all, individuals mapped to `type='individual'`.

- [ ] **Step 1:** Failing tests in `test_entities_list.py` (seed two ontologies, one with two ready versions so scope correctness is exercised):
  - browse returns rows of the type ordered by `(primary_label_norm, iri, version_id)`, only from latest-ready versions (the superseded version's rows absent);
  - page 2 via page 1's `next` cursor: no overlap, no gap; `next` null on last page;
  - unknown `type` → 422; malformed `cursor` → 422;
  - unknown `ontology` id → `{entities:[], ...}` (no error);
  - a punned Class+NamedIndividual is present under `type=class` and absent under `type=individual`;
  - `definition` equals the trimmed `definitions[0]["value"]`;
  - `q` set → delegates to `pg_entity_search` (assert a known label matches), `next` null (top-N, no deep page);
  - `approx_total` for the unfiltered case equals the public-stats total (monkeypatch `read_public_stats` to a known dict).
- [ ] **Step 2:** Run, confirm failures.
- [ ] **Step 3:** Implement `browse.py` (cursor encode/decode, allow-list, keyset WHERE builder: `(primary_label_norm, iri, version_id) > (:al,:ai,:av)` written in expanded OR-form so it runs on SQLite too) and the endpoint:
  - compute `vids = [v.id for v in await latest_ready_versions(db)]`;
  - empty `q`: keyset SELECT over `entity_index` with `type` predicate + `version_id = ANY(vids)` (+ `ontology_id = ANY(ontology)` when given), `ORDER BY primary_label_norm, iri, version_id LIMIT limit+1`; derive `next` from the `limit+1`-th row; join `ontologies` for `ontology_title`;
  - non-empty `q`: `pg_entity_search(db, q, limit, types=[type], ontology_ids=ontology or None)`, map to `EntityRow`, `next=None`;
  - `approx_total`: unfiltered → the matching `read_public_stats` total; filtered (`q` or `ontology`) → a Redis-cached scoped `COUNT(*)` (best-effort, direct-count fallback).
- [ ] **Step 4:** Run tests, confirm pass.
- [ ] **Step 5:** Commit.

---

### Task 3: `GET /entities/related` — semantic neighbors

**Files:**
- Modify: `ontoexplorer/api/entities.py` (add the route)
- Modify: `ontoexplorer/modules/search/semantic.py` (add `semantic_related`)
- Test: `tests/integration/test_entities_related.py`

**Interfaces:**
- Consumes: `embedder.embed_query`; `latest_ready_versions(db)`; the `term_embeddings → entity_index` join from `semantic_search`.
- Produces:
  - `GET /api/v1/entities/related?type&q&ontology?&k=8&lang?` → `{"entities":[EntityRow+{"score":float}], "unavailable": bool}`
  - `semantic_related(db, query, type, version_ids, ontology_ids, k) -> list[dict]` — raises `EmbeddingError`/`Exception` from the embed step through to the caller (does NOT swallow it like `semantic_search`).

- [ ] **Step 1:** Failing tests (seed `term_embeddings` rows with known vectors):
  - returns type-filtered neighbors ordered by score desc, scoped to latest-ready versions, each with `score` and the `EntityRow` fields;
  - rows of other `entity_type` never appear;
  - when `embed_query` raises (monkeypatch it to raise) → endpoint returns `{entities:[], unavailable:true}` and HTTP 200 (never 5xx);
  - no embeddings for the type → `{entities:[], unavailable:false}`.
- [ ] **Step 2:** Run, confirm failures.
- [ ] **Step 3:** Implement `semantic_related` (clone `semantic_search`'s SQL, add `AND te.entity_type = :type` and `te.version_id = ANY(:vids)` + optional ontology filter, `LIMIT k`, let the embed exception propagate). Endpoint wraps it in try/except: `EmbeddingError`/`Exception` from the embed → `unavailable:true`; otherwise `{entities, unavailable:false}`.
- [ ] **Step 4:** Run tests, confirm pass.
- [ ] **Step 5:** Commit.

---

### Task 4: `GET /entities/facets` — ontology counts

**Files:**
- Modify: `ontoexplorer/api/entities.py` (add the route)
- Modify: `ontoexplorer/modules/search/browse.py` (add `facet_counts`)
- Test: `tests/integration/test_entities_facets.py`

**Interfaces:**
- Consumes: `latest_ready_versions(db)`.
- Produces:
  - `GET /api/v1/entities/facets?type` → `{"ontologies":[{ontology_id, short, title, count}]}` (desc by count).
  - `facet_counts(db, type) -> list[dict]` — `GROUP BY ontology_id` over `entity_index` for the type, scoped to latest-ready `version_id`s, joined to `ontologies` for `short`/`title`; Redis-cached (TTL ~300s, best-effort with direct fallback).

- [ ] **Step 1:** Failing tests: counts per ontology for the type are correct and scoped to latest-ready (a second ready version does not double-count); unknown `type` → 422; result ordered by count desc; fallback path works with Redis absent.
- [ ] **Step 2:** Run, confirm failures.
- [ ] **Step 3:** Implement `facet_counts` + the route.
- [ ] **Step 4:** Run tests, confirm pass.
- [ ] **Step 5:** Commit.

---

### Task 5: Frontend API client + hooks

**Files:**
- Modify: `frontend/src/lib/api.ts` (add `api.entities`)
- Create: `frontend/src/hooks/useEntities.ts`, `useRelated.ts`, `useFacets.ts`
- Test: `frontend/src/hooks/useEntities.test.tsx`

**Interfaces:**
- Consumes: the three endpoints from Tasks 2–4.
- Produces (typescript types + funcs):
  - `EntityRow`, `EntityListResponse {entities, next, approx_total, limit}`, `RelatedResponse {entities, unavailable}`, `Facet {ontology_id, short, title, count}`.
  - `api.entities.list({type, q?, ontology?, limit?, cursor?, lang?}) -> EntityListResponse`
  - `api.entities.related({type, q, ontology?, k?, lang?}) -> RelatedResponse`
  - `api.entities.facets(type) -> Facet[]`
  - `useEntities(params)`, `useRelated(params, enabled)`, `useFacets(type)` — react-query hooks mirroring `useOntologies`.

- [ ] **Step 1:** Failing test for `useEntities` (mock fetch; assert it calls the right URL and returns parsed rows; `useRelated` disabled when `q` empty).
- [ ] **Step 2:** Run, confirm fail.
- [ ] **Step 3:** Implement the client methods + hooks (follow the `api.ts` `request`/`authFetch` and `useOntologies` patterns; `useRelated` `enabled: !!q`).
- [ ] **Step 4:** Run, confirm pass.
- [ ] **Step 5:** Commit.

---

### Task 6: Extract `MOSQuery` into a shared module

**Files:**
- Create: `frontend/src/components/MOSQuery.tsx` (moved out of `Home.tsx`, with its deps — `RelationChips`, the relation state it owns — exported)
- Modify: `frontend/src/pages/Home.tsx` (import from the new module; delete the inlined copy)
- Modify/Test: `frontend/src/pages/Home.test.tsx` (still passes; structured-query path unchanged)

**Interfaces:**
- Produces: `export function MOSQuery(props)` (and any sub-components it needs) importable by both `Home.tsx` and `EntityBrowser.tsx`. Keep the component's existing props/behavior (including `not_classified` handling) byte-for-byte — this is a move, not a redesign.

- [ ] **Step 1:** Run the existing Home tests to capture the green baseline.
- [ ] **Step 2:** Move `MOSQuery` (+ deps) to `components/MOSQuery.tsx`, export it; import it in `Home.tsx`; remove the inlined definition.
- [ ] **Step 3:** Run Home tests (and `tsc`/vitest); fix imports until green. Behavior must be unchanged.
- [ ] **Step 4:** Commit.

---

### Task 7: `EntityBrowser.tsx` page + Home stat-card wiring

**Files:**
- Create: `frontend/src/pages/EntityBrowser.tsx`
- Modify: `frontend/src/App.tsx` (add `/browse` route in the public shell)
- Modify: `frontend/src/pages/Home.tsx` (rewire the seven `StatCard` `to` targets per the routing table)
- Test: `frontend/src/pages/EntityBrowser.test.tsx`

**Interfaces:**
- Consumes: `useEntities`, `useRelated`, `useFacets` (Task 5); `MOSQuery` (Task 6).
- Routing table (Home `StatCard` `to`): Ontologies→`/ontologies`; Classes→`/browse?type=class`; Object/Data/Annotation Properties→`/browse?type=object_property|data_property|annotation_property`; Individuals→`/browse?type=individual`; Axioms→`/browse?mode=query`.

- [ ] **Step 1:** Failing tests (`EntityBrowser.test.tsx`, mock the hooks):
  - reads `type`/`mode` from the URL; type tab switch updates URL `type` and resets the cursor stack, facet selection, and expanded set;
  - empty query → keyset list renders; Next uses the returned `next` cursor and renders new rows; Previous returns; `next===null` disables Next;
  - non-empty query → exact-match rows then a "Related by meaning" divider + related rows; when `related.unavailable` the Related section is absent;
  - definition caret toggles one row; global Show/Hide definitions flips all;
  - facet search filters the list; checking an ontology narrows results;
  - a row link points to `/ontologies/<slug>/<version_id>?term=<iri>`;
  - `mode=query` renders `MOSQuery`.
  - Plus a Home test: the Classes card links to `/browse?type=class` and Axioms to `/browse?mode=query`.
- [ ] **Step 2:** Run, confirm failures.
- [ ] **Step 3:** Implement `EntityBrowser.tsx`: mode switch (List/Structured query); type tabs; unified debounced search box (`useDebounced`) firing `useEntities` always and `useRelated` when `q` non-empty, composing exact + related sections; searchable ontology facet (`useFacets`, client-side text filter, checkbox selection → `ontology` param); per-row caret + global definitions toggle; Next/Previous cursor stack; query mode renders `MOSQuery` with the "browse axioms in SPARQL →" link. Register the route; rewire Home cards.
- [ ] **Step 4:** Run tests + `tsc`/vitest, confirm pass.
- [ ] **Step 5:** Commit.

---

## Notes for the executor

- Backend tasks (1–4) and the MOSQuery extraction (6) are independent and can land in any order; Task 5 depends on 2–4's contracts (documented above, so it can be written in parallel against them); Task 7 depends on 5 and 6.
- The semantic feature is correct but inert until the embedding migration's atomic swap is live and `EMBEDDING_*` is configured on the API; `/entities/related` returning `unavailable:true` before then is expected, not a bug.
- Follow the existing router prefix convention when registering `entities_router` (match `global_search_router`'s prefix so the public path is `/api/v1/entities`).
