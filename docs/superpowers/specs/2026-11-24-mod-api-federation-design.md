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
               └─ dedup remote-vs-local by canonical IRI, source-attribute ──┤
                                                                             ▼
   { ontologies:[local...], federated:{ catalogues:[{id,label,status,count}], results:[remote rows...] } }
```

### Component 1 — Peer config & models

**Config** (`ontoexplorer/config.py`, following the existing comma-list / env idiom): a single structured setting rather than a flat allowlist, because a peer needs more than a URL.

- `federation_enabled: bool = False`
- `federation_peers_json: str = "[]"` — a JSON array in the configmap, parsed at read time (cached) into `Peer` objects. Shape per peer:
  ```json
  { "id": "agroportal", "label": "AgroPortal",
    "base_url": "https://data.agroportal.eu",
    "mod_path": "/", "timeout_ms": 3000, "adapter": "dcat2",
    "auth": { "kind": "apikey_param", "name": "apikey", "secret_ref": "FEDERATION_AGROPORTAL_KEY" } }
  ```
  (`secret_ref` names an env/secret key resolved at call time — the actual key never sits in the configmap JSON. `auth` is omitted/null for peers that need none, e.g. our own instance.)
- The set of `base_url`s **is** the SSRF allowlist (parsed into a frozenset at the read site, mirroring `is_admin()` / `ingest_fetch_allow_hosts`). User input never contributes a URL.
- `federation_fanout_timeout_ms: int = 3000`, `federation_cache_ttl_s: int = 300`, `federation_max_results_per_peer: int = 25`, `federation_max_response_bytes: int = 4_000_000`, `federation_max_redirects: int = 3`.

> **My call (confirm):** JSON-in-env for peer config rather than a `seeds/federation.yaml` file, because dev is configmap-driven (ArgoCD) and peers are an ops concern, not source. If you'd rather version the peer list in-repo, a `seeds/federation.yaml` loaded at boot is a drop-in alternative.

**Models** (`ontoexplorer/modules/federation/models.py`): `Peer` (dataclass from config), `ArtefactRow` (normalised: `iri, acronym, title, description, publisher?, license?, homepage?, source_catalogue_id, source_catalogue_label, source_landing_url, remote=True`), `CatalogueStatus` (`id, label, status: ok|timeout|error|empty, count, took_ms`).

### Component 2 — MOD-API client + per-peer adapter

`ontoexplorer/modules/federation/client.py`:

- `async def fetch_catalogue(peer) -> dict` — GET `{base_url}{mod_path}` with `Accept: application/ld+json`, to confirm a peer is a MOD-API and read its label/counts (used at config-validation / health time, not per query).
- `async def search_artefacts(peer, q, limit) -> list[ArtefactRow]` — GET `{base_url}/mod/artefacts?q={q}&page_size={limit}` (the MOD-API artefact-list with title/acronym filter — exactly what our own `list_artefacts` at `mod.py:171` emits), parse the JSON-LD `hydra:Collection` of `mod:SemanticArtefact` members into `ArtefactRow`s.
  - Fallback to `/mod/search/metadata?q=` for peers whose `/mod/artefacts` lacks a `q` filter. **Which one a given peer supports is unverified and must be probed per peer during config validation** (our own supports both; AgroPortal's `q` support is unconfirmed — see Demo peers).
- **Auth is first-class, not an afterthought.** Real OntoPortal-family peers (AgroPortal included) **require an API key** — an unauthenticated or bad-key request returns `401`, which would otherwise show as a silent empty peer. `Peer.auth` supports `{"kind":"apikey_param","name":"apikey","secret_ref":"..."}` (OntoPortal style, key as a query param) and `{"kind":"bearer","secret_ref":"..."}` (Authorization header). The secret is resolved from env/secret, never from the configmap JSON, and is sent **only** to that peer's host. A `401`/`403` from a peer surfaces as `CatalogueStatus(status="error")` with the reason logged, so a misconfigured key is visible, not silent.
- **Per-peer adapter** (`adapters/`): the MOD-API is young and implementers diverge (spec v0.0.1 vs AgroPortal's v1.0 DCAT2-based; JSON-LD framing/compaction differs). Each adapter maps one peer flavour's response → `ArtefactRow`, keyed off `peer.adapter` (`"ontoexplorer"`, `"dcat2"`, `"generic"`). The `generic` adapter reads the common MOD/DCAT predicates (`mod:acronym`, `dcterms:title`, `dcterms:description`, `foaf:homepage`, `dcterms:license`) and is the default. **Adapters are validated against captured response fixtures** — one from our own `/mod/artefacts`, one from a real AgroPortal response — so schema variance is pinned by test, not assumed.
- **Outbound HTTP hardening (the federation client owns these; the guard does not provide all of them):**
  - Transport = `async_guarded_transport()` (`ontoexplorer/clients/fetch_guard.py`) for DNS-pinning, private/metadata-IP blocking, and egress-proxy routing. Do not hand-roll httpx.
  - **Response size cap is NOT in the guard** (the guard has no size handling; the ingestion streaming cap lives in `source_resolver.py`). The client must **stream the response and abort past `federation_max_response_bytes`** (default a few MB) so a hostile/huge peer response is bounded.
  - **Redirect policy:** follow at most N hops, re-validate **every** hop through the guard (blocks inward redirects), and require the **final host to be on the peer allowlist**. A peer that legitimately lives behind a cross-host redirect (AgroPortal 302s lirmm.fr→agroportal.eu and downgrades to http) must be configured with its **current, final host as `base_url`** rather than relying on us to chase the redirect to a non-allowlisted host. An https→http downgrade to a non-allowlisted host is refused.
  - Per-peer `httpx.Timeout(peer.timeout_ms/1000)`.

### Component 3 — Federation service

`ontoexplorer/modules/federation/service.py`:

- `async def federated_artefacts(q, peers, limit) -> tuple[list[ArtefactRow], list[CatalogueStatus]]`:
  1. For each peer: check Redis cache `(peer.id, norm(q))`; on miss call `client.search_artefacts` under the peer timeout.
  2. `asyncio.gather(*tasks, return_exceptions=True)` — an exception/timeout for one peer yields a `CatalogueStatus(status="timeout"|"error")` and contributes zero rows; it never propagates.
  3. Cache each successful peer result (best-effort `setex`, `federation_cache_ttl_s`).
  4. Return rows + per-catalogue statuses.
- **Merge = dedup + append, NOT rank-fusion** (revised after review). Cross-peer scores aren't comparable, and `list_ontologies` paginates in SQL (DISTINCT ON + offset/limit in Postgres), so only one local page (≤50 rows) is ever in hand — fusing against a single local page and re-running the peer fan-out per page would be both wrong and costly. So:
  - Federation runs **only on the first page** (`offset == 0` and `q` present); deeper pages are local-only. (Documented limitation; correct for discovery and fine for the demo.)
  - Remote rows are **deduped against the local result by canonical ontology IRI**: a remote artefact that already exists locally is dropped (local is the clickable, authoritative copy). Federation thus surfaces *ontologies we don't already have*, grouped by source catalogue, each keeping its `source_*` attribution. This sidesteps the `rrf_merge` dedup-collapse hazard (its `setdefault` on `iri` would silently hide the remote source) by never interleaving remote into the local corpus.
  - Within each source, preserve the peer's own ordering. Between sources, a stable catalogue order.
  - `rrf_merge` (`pg_search.py:531`) is **not reused** — it is a 2-list, same-corpus fusion; federation is N disjoint sources with a different dedup rule.

### Component 4 — API wiring

Extend `GET /api/v1/ontologies` (`ontoexplorer/api/ontologies.py:824` `list_ontologies`) with `federated: bool = False`:

- When `federated` and `federation_enabled` and `offset == 0` and `q`: run the existing local list query **and** `FederationService.federated_artefacts(q, ...)` concurrently; dedup remote-vs-local; return the remote rows in a **separate** block (they are **not** interleaved into `ontologies[]`, so no existing `Ontology[]` consumer — detail-link nav, the `recordView` beacon, the `view='list'` projection — has to null-guard a missing `ontology_id`):
  ```json
  { "ontologies": [ ...local Ontology rows only... ],
    "offset": 0, "limit": 50, "total": N,
    "federated": {
      "catalogues": [ {"id","label","status","count","took_ms"} ],
      "results": [ {"iri","acronym","title","description","source":{"id","label"},"source_landing_url","remote":true} ]
    } }
  ```
- Remote rows live only under `federated.results` and carry `source` + `source_landing_url` (what the UI links out to). They are never addressable by local `ontology_id/version_id`.
- Federation only augments the **keyword** path (`q` present); filters like `profile`/`reuses`/`language` apply to local rows only (remote peers don't expose them uniformly).

> **My call (confirm):** reuse `/api/v1/ontologies?federated=true` rather than a new `/api/v1/federated/search`, so the existing catalogue UI and `api.ontologies.list` extend naturally. A standalone endpoint would duplicate the list projection for no demo benefit.

### Component 5 — Frontend

- `frontend/src/pages/Home.tsx` "ontology" mode (the catalogue search at `Home.tsx:117`, `api.ontologies.list(...)`): add an **"Include federated catalogues"** toggle beside the mode switch; when on, pass `federated:true` through `api.ontologies.list`.
- `frontend/src/lib/api.ts` `api.ontologies.list(...)` (line ~1547 — already 9 positional args + an `opts` object): add `federated?: boolean` **to the `opts` object** (not a 10th positional) → `&federated=true`; extend the return type with the optional `federated` block (`catalogues` + `results`).
- **Separate section, not interleaved:** local results render as today; below them a distinct **"Also found in other catalogues"** section lists `federated.results`, each row with a catalogue **source badge** (mirror the `match_type` badge pattern in `Search.tsx`) linking **out** to `source_landing_url` (new tab). A small "N of M catalogues responded" line surfaces `federated.catalogues` statuses (including which timed out). This keeps remote rows visually and structurally distinct from the clickable local catalogue.
- `Ontologies.tsx` (the full catalogue table) may adopt the same toggle later; Home is enough for the demo.

### Component 6 — Config, demo peers, docs

- Configmap: `FEDERATION_ENABLED=true`, `FEDERATION_PEERS_JSON=[...]` (services repo, dev).
- **Demo peers** (with the review's live-probe reality folded in):
  - (1) a **second OntoExplorer instance** — guaranteed MOD-API-compatible since we emit it, the reliability anchor. **Prerequisite:** no second instance is confirmed in-repo; one must actually be deployed/reachable for the demo. *Owner decision — see Prerequisites.*
  - (2) **AgroPortal** — a real, independent external SAC. **It is NOT drop-in:** live probing shows `data.agroportal.lirmm.fr` **302-redirects to `http://data.agroportal.eu`** (host moved + https→http downgrade) and the MOD endpoints return **HTTP 401 without a valid API key**. So AgroPortal requires: configure `base_url` to the **current** host, provision an **AgroPortal API key** (sent via the `apikey` auth kind), and **verify `/mod/artefacts` supports `q`** there (else use the `/mod/search/metadata` fallback). Until the key is provisioned the demo is self-federation only. *Owner decision — see Prerequisites.*
  - Add OLS/ShowVoc/OntoPortal/Prez via config as their MOD-APIs come online (SciDataCon 2025 reports 11 SACs adopting; none confirmed live here).
- Docs: a `docs/features/` page + README note; update the MOD-API compatibility doc to note client support.

## Security

- **Allowlist-only.** Outbound requests go only to the server-configured `base_url`s. No endpoint accepts a peer URL from the client — the `federated` param is a boolean. This mirrors the SPARQL `SERVICE` SSRF concern (`api/sparql.py`) without reopening it.
- **Guarded transport** (`async_guarded_transport()`) on every call: DNS-pinned, private/metadata IPs blocked, egress-proxy routing. A peer that redirects to an internal address is blocked. **Every redirect hop is re-validated through the guard; the final host must be on the peer allowlist**, and an https→http downgrade to a non-allowlisted host is refused (see Component 2 redirect policy).
- **Response size cap is the client's own streaming abort** (`federation_max_response_bytes`) — the guard does not bound size. Per-peer timeout bounds latency.
- **No secrets to untrusted peers:** per-peer `auth` secrets are resolved from env/secret (never the configmap JSON) and sent **only** to that peer's configured host.
- Rate-limit / backoff per peer so we are a polite client (respect remote limits, as the issue requires).

## Acceptance

- With ≥1 configured remote SAC, `GET /api/v1/ontologies?q=...&federated=true` returns local rows plus a separate `federated.results` block of source-attributed remote rows (deduped against local); the UI shows them in a distinct "other catalogues" section with a badge that links out.
- A dead/slow peer: local results still return within the local latency budget; the dead peer shows `status:"timeout"` and contributes nothing.
- A malicious peer URL cannot be injected (boolean param + allowlist); a peer redirecting inward is blocked (guard); an oversize peer response is aborted (client size cap).
- Live demo: one search surfaces artefacts from the local catalogue **and** AgroPortal **and** a second OntoExplorer node, each badged to its source.

### Test coverage (named, so the plan builds them)

- **Adapter fixtures:** `ontoexplorer`/`dcat2`/`generic` adapters each parse a captured real response (ours + an AgroPortal sample) → expected `ArtefactRow`s.
- **Partial-failure/timeout integration:** one healthy + one hanging peer → local latency budget respected, hung peer reported `status:"timeout"`, zero rows from it, response still returns.
- **Security:** a peer that 302s to an internal/private address is blocked by the guard; an oversize response is aborted at the cap; a `401` peer surfaces `status:"error"` (not silent-empty).
- **Dedup/merge determinism:** a remote artefact whose IRI matches a local ontology is dropped; remote-only artefacts appear under their source; ordering is stable across runs.
- **Cache:** second identical query within TTL hits Redis (no second outbound call); miss after TTL refetches.

## Prerequisites (owner decisions — block the *demo*, not the plan)

These are resources/decisions only you can supply; the plan can be built and tested with the self-instance + fixtures regardless, but the live external demo needs them:

1. **A reachable second OntoExplorer instance** for the reliability-anchor peer (confirm one exists or stand one up — e.g. a second dev namespace or the prod catalogue).
2. **An AgroPortal API key** (+ confirm the current `data.agroportal.eu` MOD host and whether `/mod/artefacts?q=` is supported there, else the metadata-search fallback). Without it, AgroPortal can't be a live peer.
3. Optional: provision keys/hosts for any additional SAC you want on stage (OLS/ShowVoc/etc. if/when live).

## Open calls I made (please check)

1. **Peer config = JSON-in-configmap** (vs `seeds/federation.yaml`). Ops concern → env. Easy to flip.
2. **Reuse `/api/v1/ontologies?federated=true`** (vs new `/federated/search`).
3. **Federate the catalogue/artefact surface only** (discovery), not per-ontology term search. Term-level federation is a later extension.
4. **Dedup + append, not rank-fusion** (revised per review): remote rows deduped against local by canonical IRI, returned in a **separate `federated.results` block**, link out — never interleaved into `ontologies[]`, never RRF'd. Federation shows *ontologies we don't already have*.
5. **Demo peers = self (2nd instance) + AgroPortal**, both with unresolved prerequisites (see Prerequisites): a real second instance must exist, and AgroPortal needs a key + current host.
6. **Federation runs on the first page only** (`offset==0`, `q` present); deeper pages local-only; local filters/pagination stay authoritative.

## Rough task decomposition (for the plan, if approved)

1. Peer config + models + settings parse (+ validation of the JSON).
2. MOD-API client + `generic`/`dcat2`/`ontoexplorer` adapters (unit-tested against captured fixtures from our own `/mod/artefacts` and an AgroPortal sample).
3. Federation service: fan-out, timeouts, partial-failure, Redis cache, RRF merge.
4. API: `federated` param on `list_ontologies` + response shape + concurrency.
5. Frontend: toggle, source badge, link-out, `api.ts`, "N of M responded".
6. Config + demo peers (services repo) + docs.

Tasks 1–4 are backend and mostly independent of 5; 2 is the one needing care (schema variance) and should land first with fixtures.
