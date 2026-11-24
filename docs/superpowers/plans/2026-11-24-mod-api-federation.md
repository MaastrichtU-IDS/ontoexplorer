# MOD-API Federation (client side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `federated=true` discovery mode that fans out to configured remote MOD-API catalogues, dedups their artefacts against the local catalogue, and returns them source-attributed in a separate block — storing nothing.

**Architecture:** A new `ontoexplorer/modules/federation/` package (config-driven peers → per-peer MOD-API client with guarded transport/auth/size-cap → async fan-out service with partial-failure tolerance, Redis cache, dedup+append) wired into `GET /api/v1/ontologies` and surfaced as a toggle + "other catalogues" section on Home.

**Tech Stack:** FastAPI (async), httpx via `async_guarded_transport()`, pydantic-settings, Redis, rdflib (JSON-LD parse, already used by the MOD builder), React 18 + inline styles, pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-11-24-mod-api-federation-design.md`

## Global Constraints

- **Federation is OFF by default:** `federation_enabled=False`. No behavior change to `/api/v1/ontologies` unless `federated=true` AND enabled AND `offset==0` AND `q` present.
- **Store nothing.** No DB writes, no ingest. Remote rows are transient response data.
- **Remote rows never enter `ontologies[]`** — they live only under `federated.results`, so no existing `Ontology[]` consumer must null-guard a missing `ontology_id`.
- **SSRF:** all outbound calls use `async_guarded_transport()` (`ontoexplorer/clients/fetch_guard.py`); allowlist = configured peer hosts only; the `federated` param is a boolean (never a URL); redirects re-validated per hop, final host must be allowlisted; https→http downgrade to a non-allowlisted host refused.
- **Secrets** (per-peer auth) resolve from env/secret, never from the configmap JSON, and are sent only to that peer's host.
- **Client owns the response size cap** (streaming abort at `federation_max_response_bytes`) — the guard has no size handling.
- **No new Python/JS dependencies.** Reuse httpx, rdflib, redis client already in the tree.
- Add to `api.ts` `list()` via its `opts` object (not a 10th positional arg).

## Review Focus

- **Dead/hung peer** → fan-out must honor the per-peer timeout and the overall budget; local response still returns; peer reported `status:"timeout"`. (Task 4)
- **401/403 peer** (missing/bad key) → surfaces `status:"error"` with reason, never a silent empty peer. (Task 3)
- **Peer redirect to internal/private host, cross-host, or https→http downgrade** → blocked by guard + redirect policy. (Task 3)
- **Oversize peer response** → streaming abort at the cap. (Task 3)
- **Malformed / schema-variant JSON-LD** → adapter yields what it can, never raises into the service. (Task 2)
- **Remote artefact duplicating a local ontology** (the overlap case) → deduped out by canonical IRI. (Task 4)
- **Redis unavailable / corrupt cache** → best-effort; a cache miss or error never fails the request. (Task 4)

---

### Task 1: Federation config & Peer model

**Files:**
- Modify: `ontoexplorer/config.py` (add settings)
- Create: `ontoexplorer/modules/federation/__init__.py`, `ontoexplorer/modules/federation/config.py`
- Test: `tests/unit/test_federation_config.py`

**Interfaces:**
- Produces: `Peer` dataclass (`id, label, base_url, mod_path, adapter, timeout_ms, auth: PeerAuth|None`); `PeerAuth` (`kind: "apikey_param"|"bearer", name?, secret_ref`); `get_federation_peers() -> list[Peer]` (parses `federation_peers_json`, resolves nothing secret yet); `peer_host_allowlist() -> frozenset[str]`; settings `federation_enabled`, `federation_peers_json`, `federation_fanout_timeout_ms`, `federation_cache_ttl_s`, `federation_max_results_per_peer`, `federation_max_response_bytes`, `federation_max_redirects`.

- [ ] **Step 1: Write failing tests** — valid JSON → N `Peer`s; malformed JSON → `[]` + logged warning (never raises at import/boot); `peer_host_allowlist()` = set of `base_url` hosts; `federation_enabled` defaults False; a peer with `auth.kind="apikey_param"` parses its `secret_ref` but does not embed a secret.
- [ ] **Step 2: Run tests, verify they fail**
- [ ] **Step 3: Implement** the settings fields (mirror the comma-list idiom / `get_settings()` cache) and `config.py` parsing. Follow the `is_admin()`/`ingest_fetch_allow_hosts` pattern for the allowlist.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

### Task 2: ArtefactRow + per-peer adapters (fixtures)

**Files:**
- Create: `ontoexplorer/modules/federation/models.py` (`ArtefactRow`, `CatalogueStatus`), `ontoexplorer/modules/federation/adapters.py`
- Test: `tests/unit/test_federation_adapters.py`
- Fixtures: `tests/fixtures/federation/ours_artefacts.jsonld`, `tests/fixtures/federation/agroportal_artefacts.jsonld` (capture a real sample of each; if AgroPortal is unreachable at build time, hand-author a representative DCAT2 sample and note it)

**Interfaces:**
- Consumes: nothing from Task 1 except `Peer` (for `source_*` attribution).
- Produces: `ArtefactRow` (`iri, acronym, title, description, publisher?, license?, homepage?, source_landing_url, source: {id,label}, remote=True`); `adapter_for(name) -> Callable[[dict, Peer], list[ArtefactRow]]`; adapters `parse_ontoexplorer`, `parse_dcat2`, `parse_generic` (default). Each parses a JSON-LD `hydra:Collection` of `mod:SemanticArtefact` members.

- [ ] **Step 1: Write failing tests** — each adapter parses its fixture into the expected `ArtefactRow`s (assert counts + key fields incl. `source_landing_url`); a member missing optional predicates still yields a row (title/iri required); a malformed/empty doc yields `[]` and never raises; `parse_generic` reads the common MOD/DCAT predicates.
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** adapters using rdflib (same JSON-LD handling the MOD builder uses) or direct JSON-LD dict traversal against the compacted context. `source_landing_url` = the artefact's `foaf:homepage` if present, else `{base_url}/mod/artefacts/{id}` or the peer's catalogue landing.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

### Task 3: MOD-API client (auth, redirect policy, size cap, timeout)

**Files:**
- Create: `ontoexplorer/modules/federation/client.py`
- Test: `tests/unit/test_federation_client.py` (mock transport — a stub `httpx.MockTransport`/respx-style handler, no network)

**Interfaces:**
- Consumes: `Peer`/`PeerAuth` (Task 1), `adapter_for`/`ArtefactRow` (Task 2), `async_guarded_transport()` (`ontoexplorer/clients/fetch_guard.py`), secret resolution from env.
- Produces: `async def search_artefacts(peer, q, limit) -> list[ArtefactRow]`; `async def fetch_catalogue(peer) -> dict` (for config validation/health); raises typed `FederationFetchError(reason)` on 401/403/timeout/oversize/blocked-redirect.

- [ ] **Step 1: Write failing tests** (mock transport): auth `apikey_param` → key appears as a query param only on requests to the peer host; `bearer` → `Authorization` header; a `401` response → `FederationFetchError("unauthorized")`; a redirect to a private/loopback IP → blocked (guard); a redirect whose final host is not allowlisted → blocked; an https→http downgrade to a non-allowlisted host → refused; a response body exceeding `federation_max_response_bytes` → aborted with `FederationFetchError("oversize")`; a slow handler beyond `timeout_ms` → `FederationFetchError("timeout")`; a happy path → parsed `ArtefactRow`s via the peer's adapter.
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** with `httpx.AsyncClient(transport=async_guarded_transport(), timeout=..., follow_redirects=False)` and a manual redirect loop (≤ `federation_max_redirects`) that re-validates each hop's host against the allowlist + guard; stream the body with an incremental byte cap; resolve `secret_ref` from env at call time.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

### Task 4: Federation service (fan-out, partial-failure, cache, dedup+append)

**Files:**
- Create: `ontoexplorer/modules/federation/service.py`
- Test: `tests/unit/test_federation_service.py`

**Interfaces:**
- Consumes: `search_artefacts` (Task 3), peers + settings (Task 1), Redis (`_get_redis`).
- Produces: `async def federated_artefacts(q, local_iris: set[str], peers, limit) -> tuple[list[ArtefactRow], list[CatalogueStatus]]`. `local_iris` is the set of canonical IRIs already in the local page/catalogue, for dedup.

- [ ] **Step 1: Write failing tests** — two peers (one healthy, one hanging past timeout) → healthy rows returned, hanging peer `status:"timeout"` with zero rows, call completes within ~fanout budget (use fake clients, assert no exception propagates); a remote `ArtefactRow` whose `iri ∈ local_iris` is dropped; remote-only rows kept, grouped by source, stable order; **cache**: first call misses → calls client + `setex`; second identical call hits Redis, no client call; Redis `get` raising → falls through to a live fetch (best-effort).
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** `asyncio.gather(*[_one_peer(p) for p in peers], return_exceptions=True)`; per-peer cache key `federation:{peer.id}:{sha(norm(q))}`; map `FederationFetchError`/exceptions → `CatalogueStatus`; dedup by IRI against `local_iris`; cap per peer at `federation_max_results_per_peer`.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

### Task 5: API wiring on `list_ontologies`

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` (`list_ontologies`, ~line 824)
- Test: `tests/integration/test_federation_api.py`

**Interfaces:**
- Consumes: `federated_artefacts` (Task 4), `get_federation_peers`/`federation_enabled` (Task 1).
- Produces: response gains optional `federated: {catalogues:[CatalogueStatus...], results:[ArtefactRow...]}`; `ontologies[]` unchanged.

- [ ] **Step 1: Write failing tests** — `federated=true` + `q` + `offset=0` + enabled → response has `federated` block (monkeypatch the service to return fixed rows/statuses); the local `ontologies[]` is unchanged and carries no remote rows; `federated=true` with `offset>0` OR missing `q` OR `federation_enabled=False` → no fan-out, no `federated` block; local query and fan-out run concurrently (service called once).
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** — add `federated: bool = False`; gather `local_iris` from the local page results; `await asyncio.gather(local_query, federated_artefacts(...))` guarded by the enable conditions; attach the block.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

### Task 6: Frontend toggle + "other catalogues" section

**Files:**
- Modify: `frontend/src/lib/api.ts` (`api.ontologies.list` opts + return type), `frontend/src/pages/Home.tsx` (ontology mode)
- Create: a small `FederatedResults` component (or inline in Home) + `frontend/src/pages/__tests__/federation.test.tsx` (or the repo's vitest convention)

**Interfaces:**
- Consumes: the `federated` response block (Task 5).
- Produces: `list(..., opts: { ..., federated?: boolean })` → `&federated=true`; return type extended with optional `federated`.

- [ ] **Step 1: Write failing tests (vitest)** — `api.ontologies.list` with `{federated:true}` includes `federated=true` in the URL and omits it otherwise; given a response with `federated.results`, the component renders a distinct "Also found in other catalogues" section with one badged, outbound (`target=_blank`) link per remote row and an "N of M catalogues responded" line from `federated.catalogues`.
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** the toggle in Home's ontology mode, pass `federated` through, render the separate section (badge pattern per `Search.tsx`). Local results rendering is untouched.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

### Task 7: Config, demo peers, docs (ops — not TDD)

**Files:**
- Services repo: `ids3/projects/ontoexplorer/dev/` configmap (`FEDERATION_ENABLED`, `FEDERATION_PEERS_JSON`, `FEDERATION_AGROPORTAL_KEY` as a secret ref)
- Modify: `docs/features/` (new federation page), README/MOD-API doc note

- [ ] **Step 1:** Add the self-instance peer (confirmed reachable) and, once the **prerequisites** are met (second instance deployed; AgroPortal key provisioned + current host + `q` support confirmed), the AgroPortal peer. Until then ship enabled with the self-peer only.
- [ ] **Step 2:** Docs page + MOD-API compatibility note (client support added).
- [ ] **Step 3:** Commit (app repo docs) + open the services-repo config PR separately (classifier-gated deploy, owner-approved).

> **Note:** Tasks 1–5 are backend and ship/test without any live peer (fixtures + mock transport + self-peer). The live external demo depends on the design's **Prerequisites** (second instance + AgroPortal key), which are owner decisions and do not block building/merging Tasks 1–6.

## Self-review notes

- Spec coverage: config (T1), client+adapters (T2–3), service (T4), API (T5), FE (T6), ops (T7) — all design components mapped.
- Review Focus: each item is pinned to a task's tests above (timeout/partial-failure T4; 401/redirect/size T3; schema variance T2; dedup T4; cache-unavailable T4).
- Proportion: interfaces + test names, not code bodies. T2/T3 carry the risk (schema variance + SSRF surface) and land before the service that depends on them.
