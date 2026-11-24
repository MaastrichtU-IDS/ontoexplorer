# MOD-API Federation (client side) — Design

**Status:** Design, awaiting approval to plan/build. Issue: [#415](https://github.com/MaastrichtU-IDS/ontoexplorer/issues/415) (Project 1 of 2 — see the companion feasibility doc `2026-11-24-bulk-discovery-ingest-feasibility.md` for Project 2).

**Goal:** Let one OntoExplorer instance present a **federated discovery view** across remote Semantic Artefact Catalogues (SACs) by querying their MOD-APIs at request time, merging and source-attributing the results — **without ingesting or storing any remote content.**

**Primary driver:** a live federated demo for the ESWC resource-track paper, and a low-commitment way to assess whether federated search is worth offering day to day.

---

## Why this is its own project

OntoExplorer already implements the **server side** of the FAIR-IMPACT MOD-API (`ontoexplorer/api/mod.py`, `ontoexplorer/modules/mod/builder.py`): it publishes its own catalogue under `/mod/*` as content-negotiated RDF, so it is already a federatable node. This project adds the **client side**: consuming *other* SACs' MOD-APIs.

It is deliberately separated from the "grow our collection by harvesting remote content" idea (Project 2). This project **stores nothing** — remote artefacts stay remote and federated rows link out to their home catalogue. That single constraint is what keeps it small, demo-ready, and free of the dedup / licensing / capacity problems that make Project 2 a program rather than a feature.

## Goals

- A `federated=true` mode on catalogue search that fans out to configured remote SACs, merges their artefact results with local ones, and attributes each result to its source catalogue.
- Partial-failure tolerance: a slow or dead peer is dropped, never blocks or fails the local response; the response reports which catalogues answered.
- A UI toggle + source-attribution badge; federated rows link out to the remote artefact.
- A server-configured allowlist of trusted peers (no user-supplied URLs — SSRF-safe).
- A credible live demo across ≥2 independent catalogues.

## Non-goals (and anti-goals)

- **No ingestion/mirroring of remote content** — that is Project 2. Federated rows are discovery pointers, not locally browsable ontologies.
- **No remote term-level browse/reason/SPARQL** — we federate the *catalogue* surface (artefact discovery), not per-ontology entity search. (A future extension could federate `/mod/search/content`, but it is out of scope here.)
- **No live SPARQL `SERVICE` federation** — deliberately disabled for SSRF (`api/sparql.py`); this project does not reopen it.
- **Anti-goal:** letting the federated client become an SSRF vector, or letting a peer's latency degrade the core product.

## Architecture

```
GET /api/v1/ontologies?q=...&federated=true
        │
        ├─ local catalogue search (existing list_ontologies path)         ──┐
        │                                                                    │
        └─ FederationService.search(q)                                       │
               ├─ fan out concurrently to each configured Peer:             │
               │     ModApiClient.search_artefacts(peer, q)  (per-peer      │
               │        adapter normalises MOD/DCAT variants → ArtefactRow) │
               │     • async_guarded_transport() + per-peer timeout          │
               │     • best-effort Redis cache keyed (peer_id, norm_query)   │
               │     • asyncio.gather(..., return_exceptions=True)           │
               │                                                             │
               └─ merge: RRF across peers+local, source-attribute each row ──┤
                                                                             ▼
                        { ontologies:[...], federated:{ catalogues:[{id,label,status,count}] } }
```

### Component 1 — Peer config & models

**Config** (`ontoexplorer/config.py`, following the existing comma-list / env idiom): a single structured setting rather than a flat allowlist, because a peer needs more than a URL.

- `federation_enabled: bool = False`
- `federation_peers_json: str = "[]"` — a JSON array in the configmap, parsed at read time (cached) into `Peer` objects. Shape per peer:
  ```json
  { "id": "agroportal", "label": "AgroPortal",
    "base_url": "https://data.agroportal.lirmm.fr",
    "mod_path": "/", "auth": null, "timeout_ms": 3000, "adapter": "dcat2" }
  ```
- The set of `base_url`s **is** the SSRF allowlist (parsed into a frozenset at the read site, mirroring `is_admin()` / `ingest_fetch_allow_hosts`). User input never contributes a URL.
- `federation_fanout_timeout_ms: int = 3000`, `federation_cache_ttl_s: int = 300`, `federation_max_results_per_peer: int = 25`.

> **My call (confirm):** JSON-in-env for peer config rather than a `seeds/federation.yaml` file, because dev is configmap-driven (ArgoCD) and peers are an ops concern, not source. If you'd rather version the peer list in-repo, a `seeds/federation.yaml` loaded at boot is a drop-in alternative.

**Models** (`ontoexplorer/modules/federation/models.py`): `Peer` (dataclass from config), `ArtefactRow` (normalised: `iri, acronym, title, description, publisher?, license?, homepage?, source_catalogue_id, source_catalogue_label, source_landing_url, remote=True`), `CatalogueStatus` (`id, label, status: ok|timeout|error|empty, count, took_ms`).

### Component 2 — MOD-API client + per-peer adapter

`ontoexplorer/modules/federation/client.py`:

- `async def fetch_catalogue(peer) -> dict` — GET `{base_url}{mod_path}` with `Accept: application/ld+json`, to confirm a peer is a MOD-API and read its label/counts (used at config-validation / health time, not per query).
- `async def search_artefacts(peer, q, limit) -> list[ArtefactRow]` — GET `{base_url}/mod/artefacts?q={q}&page_size={limit}` (the MOD-API artefact-list with title/acronym filter — exactly what our own `list_artefacts` at `mod.py:171` emits), parse the JSON-LD `hydra:Collection` of `mod:SemanticArtefact` members into `ArtefactRow`s.
  - Fallback to `/mod/search/metadata?q=` for peers whose `/mod/artefacts` lacks a `q` filter.
- **Per-peer adapter** (`adapters/`): the MOD-API is young and implementers diverge (spec v0.0.1 vs AgroPortal's v1.0 DCAT2-based; JSON-LD framing/compaction differs). Each adapter maps one peer flavour's response → `ArtefactRow`, keyed off `peer.adapter` (`"ontoexplorer"`, `"dcat2"`, `"generic"`). The `generic` adapter reads the common MOD/DCAT predicates (`mod:acronym`, `dcterms:title`, `dcterms:description`, `foaf:homepage`, `dcterms:license`) and is the default.
- **All outbound calls use `async_guarded_transport()`** (`ontoexplorer/clients/fetch_guard.py`) + an explicit `httpx.Timeout(peer.timeout_ms/1000)` + a response size cap. Reuse the guard; do not hand-roll httpx. (Public peers route through the egress proxy by hostname, which the guard already handles.)

### Component 3 — Federation service

`ontoexplorer/modules/federation/service.py`:

- `async def federated_artefacts(q, peers, limit) -> tuple[list[ArtefactRow], list[CatalogueStatus]]`:
  1. For each peer: check Redis cache `(peer.id, norm(q))`; on miss call `client.search_artefacts` under the peer timeout.
  2. `asyncio.gather(*tasks, return_exceptions=True)` — an exception/timeout for one peer yields a `CatalogueStatus(status="timeout"|"error")` and contributes zero rows; it never propagates.
  3. Cache each successful peer result (best-effort `setex`, `federation_cache_ttl_s`).
  4. Return rows + per-catalogue statuses.
- **Merge/ranking** (`merge.py`): cross-peer relevance scores are not comparable, so use **Reciprocal-Rank Fusion** over each source's own ordering (local catalogue included as one source) — reuse the RRF approach already in `modules/search/pg_search.py` (`rrf_merge`). Each row keeps its `source_*` attribution; local rows are flagged `remote=False`.

### Component 4 — API wiring

Extend `GET /api/v1/ontologies` (`ontoexplorer/api/ontologies.py:824` `list_ontologies`) with `federated: bool = False`:

- When `federated` and `federation_enabled`: run the existing local list query **and** `FederationService.federated_artefacts(q, ...)` concurrently; RRF-merge; return
  ```json
  { "ontologies": [ ...local+remote rows... ],
    "offset": 0, "limit": 50, "total": N,
    "federated": { "catalogues": [ {"id","label","status","count","took_ms"} ] } }
  ```
- Remote rows carry `remote:true`, `source:{id,label}`, and `source_landing_url` (what the UI links to). They are **not** addressable by local `ontology_id/version_id`.
- Federation only augments the **keyword** path (`q` present); filters like `profile`/`reuses`/`language` apply to local rows only (remote peers don't expose them uniformly). Pagination stays local-authoritative; federated rows append after the local page (documented limitation, fine for the demo).

> **My call (confirm):** reuse `/api/v1/ontologies?federated=true` rather than a new `/api/v1/federated/search`, so the existing catalogue UI and `api.ontologies.list` extend naturally. A standalone endpoint would duplicate the list projection for no demo benefit.

### Component 5 — Frontend

- `frontend/src/pages/Home.tsx` "ontology" mode (the catalogue search at `Home.tsx:117`, `api.ontologies.list(...)`): add an **"Include federated catalogues"** toggle beside the mode switch; when on, pass `federated:true` through `api.ontologies.list`.
- `frontend/src/lib/api.ts` `api.ontologies.list(...)` (line 1547): add a `federated?: boolean` option → `&federated=true`; extend the return type with the optional `federated.catalogues` block and row fields `remote`, `source`, `source_landing_url`.
- **Source badge:** federated rows render a catalogue badge (mirror the existing `match_type` badge pattern in `Search.tsx`) and the whole row links **out** to `source_landing_url` (new tab) rather than into local detail. A small "N of M catalogues responded" line surfaces `federated.catalogues` statuses.
- `Ontologies.tsx` (the full catalogue table) may adopt the same toggle later; Home is enough for the demo.

### Component 6 — Config, demo peers, docs

- Configmap: `FEDERATION_ENABLED=true`, `FEDERATION_PEERS_JSON=[...]` (services repo, dev).
- **Demo peers:** (1) a **second OntoExplorer instance** — guaranteed MOD-API-compatible since we emit it, fully in our control, the reliability anchor for the live demo; (2) **AgroPortal** — a real, independent external SAC with a confirmed live MOD-API v1.0 (DCAT2), which carries the paper's "federate across separate catalogues" claim. Add OLS/ShowVoc/OntoPortal/Prez via config as their MOD-APIs come online (SciDataCon 2025 reports 11 SACs adopting).
- Docs: a `docs/features/` page + README note; update the MOD-API compatibility doc to note client support.

## Security

- **Allowlist-only.** Outbound requests go only to the server-configured `base_url`s. No endpoint accepts a peer URL from the client — the `federated` param is a boolean. This mirrors the SPARQL `SERVICE` SSRF concern (`api/sparql.py`) without reopening it.
- **Guarded transport** (`async_guarded_transport()`) on every call: DNS-pinned, redirect-validated, private/metadata IPs blocked, egress-proxy routing. Per-peer timeout + response size cap. A peer that redirects to an internal address is blocked by the guard.
- **No secrets to untrusted peers:** optional per-peer `auth` is only ever sent to that peer's configured host.
- Rate-limit / backoff per peer so we are a polite client (respect remote limits, as the issue requires).

## Acceptance

- With ≥1 configured remote SAC, `GET /api/v1/ontologies?q=...&federated=true` returns merged, source-attributed results; the UI toggle shows remote rows with a catalogue badge that links out.
- A dead/slow peer: local results still return within the local latency budget; the dead peer shows `status:"timeout"` and contributes nothing.
- A malicious peer URL cannot be injected (allowlist) and a peer redirecting inward is blocked (guard).
- Live demo: one search surfaces artefacts from the local catalogue **and** AgroPortal **and** a second OntoExplorer node, each badged to its source.

## Open calls I made (please check)

1. **Peer config = JSON-in-configmap** (vs `seeds/federation.yaml`). Ops concern → env. Easy to flip.
2. **Reuse `/api/v1/ontologies?federated=true`** (vs new `/federated/search`).
3. **Federate the catalogue/artefact surface only** (discovery), not per-ontology term search. Term-level federation is a later extension.
4. **RRF merge** with local included as one source; **remote rows link out**, not into local detail.
5. **Demo peers = self (2nd instance) + AgroPortal**; others via config later.
6. **Federation augments the keyword path only**; local filters/pagination stay authoritative, remote rows append.

## Rough task decomposition (for the plan, if approved)

1. Peer config + models + settings parse (+ validation of the JSON).
2. MOD-API client + `generic`/`dcat2`/`ontoexplorer` adapters (unit-tested against captured fixtures from our own `/mod/artefacts` and an AgroPortal sample).
3. Federation service: fan-out, timeouts, partial-failure, Redis cache, RRF merge.
4. API: `federated` param on `list_ontologies` + response shape + concurrency.
5. Frontend: toggle, source badge, link-out, `api.ts`, "N of M responded".
6. Config + demo peers (services repo) + docs.

Tasks 1–4 are backend and mostly independent of 5; 2 is the one needing care (schema variance) and should land first with fixtures.
