# GitHub Discovery Source — Design

**Status:** draft for approval · **Date:** 2026-11-26
**Author:** Claude Code (with owner)
**Related:** `2026-11-24-bulk-discovery-ingest-feasibility.md` (feasibility), `2026-11-24-mod-api-harvest-increment.md` (the harvest machinery this reuses), memory `ontoexplorer-github-dedup-feasibility`.

## Intent & why

Index ontologies held in **GitHub** repositories as a `DiscoverySource`, so a *second* OntoExplorer instance can self-populate its catalogue from GitHub. The main instance then demonstrates **client-side MOD-API federation** (Project 1, shipped) against that second instance as a peer — a live federated demo for the ESWC Resources Track paper, with genuinely distinct content in each catalogue.

**Why a second instance rather than ingesting GitHub into the main catalogue:** federation *stores nothing* — it fans out and shows a separate "also found in other catalogues" block. Keeping GitHub content in its own instance **dissolves the deduplication problem** entirely (measured unsafe to auto-merge: import-closure collisions merge distinct ontologies — zfa/zfs, food/wine; see `ontoexplorer-github-dedup-feasibility`). Catalogues stay separate by design; no schema migration, no cross-ontology merge risk.

## Goals

- A `GithubDiscoverySource` implementing the existing `DiscoverySource` protocol, enumerating ontology files on GitHub via **both** a curated org/repo seed list **and** code search (owner's earlier choice).
- Reuse the shipped harvest pipeline unchanged: `run_harvest` → `admit` gate → `ingest_ontology`, with `source_catalogue="github"` provenance.
- **OFF by default** and **dry-run by default**, matching the MOD harvest (feasibility lever: see what *would* ingest without mutating).
- Secret hygiene: a GitHub PAT read from env (value in Vault, name in config), never logged, never persisted.
- Dry-run validatable on the **current** dev instance before the second instance exists.

## Non-goals / anti-goals

- **No change to the admission gate's dedup semantics.** Content-fingerprint auto-dedup is out of scope (measured unsafe). Identity and dedup are the ingestion pipeline's job, per ontology, at ingest time.
- **No bulk/unthrottled crawl.** Bounded by `RunBudget` + a GitHub-appropriate rate limiter; code search is 10/min, REST 5000/hr.
- **Not wired into Celery beat.** Admin-triggered only, like `harvest_peer`.
- No GitHub *write* access, no cloning; read-only API + raw blob download.
- Not building the second instance or federation config here — that is a parallel infra track (owner-gated). This spec is the source only.

## Approach

### Discovery is metadata-only (cheap); the pipeline owns identity

Per candidate, `discover()` does **no blob download or parse**:

1. **Enumerate** `{owner, repo, path, sha, html_url}` from two inputs, deduped by blob `sha`:
   - **Curated:** for each configured `owner/repo`, list ontology-extension files (`git/trees?recursive=1`, filter by extension).
   - **Code search:** `GET /search/code` with the feasibility queries (`owl:Ontology extension:owl|ttl|rdf`). Excludes forks by default.
2. **Repo license** (cached per repo, one `GET /repos/{owner}/{repo}` → `.license.spdx_id`): the decisive filter (feasibility: ~33% eligible). When `github_require_compliant_license` (default **true**), skip any candidate whose SPDX is not in `compliant_license_set()` — GitHub has no license metadata beyond the repo, so we require an explicit compliant repo license rather than lean on the gate's lenient "absence ≠ violation" rule.
3. **Emit** a `Candidate`:
   - `canonical_iri` = the raw blob URL (`raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}`) — an http(s) URL, so it passes the gate's `bad_iri` check. It is a *provisional* identity used only by the gate; the real ontology IRI is derived at ingest.
   - `download_url` = same raw blob URL → `ingest_target()` returns `("url", raw_url)`, so the GitHub **copy** is ingested (not the ontology's canonical purl, which may resolve elsewhere/newer).
   - `title` = provisional `"{repo}/{path}"` (satisfies the `no_title` check; the pipeline overrides with the parsed `dcterms:title`/`rdfs:label`).
   - `license` = repo SPDX (the gate re-checks it).
   - `acronym` = `None` (GitHub has no stable catalogue acronym) → #477 shortname derivation falls to prefix→title→IRI-tail from the parsed content.
   - `landing_url` = the blob `html_url`; `source_catalogue_id="github"`, `source_catalogue_label="GitHub"`.

The ingestion pipeline then downloads, parses, derives real identity + shortname, runs the real quality gate (`decide_publish_status`), and dedups via `find_ontology_by_canonical_iri` on the *parsed* IRI. Non-ontology files and true duplicates are rejected there. **Consequence (accepted):** the pre-enqueue `duplicate` check is weak for GitHub (it sees the raw URL, not the real IRI), so a few dup/non-ontology files reach ingest and are rejected one job later. Feasibility showed these are rare (~1/60). The decisive license filter stays cheap (no download).

*Alternative considered — parse-in-discovery* (download+parse each blob in `discover()` to emit the real IRI/title, as the feasibility probe did): gives a strong pre-gate but **double-downloads** every file (discover + ingest). Rejected: the pipeline already parses, and license (the decisive filter) needs no download.

### GitHub API client

New `ontoexplorer/modules/discovery/github_client.py`: a thin async httpx wrapper over `api.github.com` (search, repo, tree) with:
- Bearer auth from `settings.github_api_token`; `Authorization` header never logged (log ids/counts/typed reasons only, mirroring `mod_harvest`'s discipline).
- A `PeerRateLimiter` tuned for GitHub (`github_min_interval_ms`, default 6500 ≈ 10/min for code search); REST calls share it (well under 5000/hr).
- Honors `Retry-After` / secondary-rate-limit 403s with a bounded backoff; raises a typed `GithubDiscoveryError` (no token/URL in the message).
- Downloads are **not** done here — they go through the ingestion pipeline's existing SSRF-guarded `source_resolver` fetch at ingest time (`raw.githubusercontent.com` is public, unauthenticated; the peer-auth path from #476 is not involved).

### Config (new settings, `config.py`)

| setting | default | purpose |
|---|---|---|
| `github_discovery_enabled` | `False` | master off switch |
| `github_api_token` | `None` (env `GITHUB_API_TOKEN`) | PAT, read-only public repos; value in Vault |
| `github_seed_repos` | `[]` | explicit `owner/repo` list (curated input) |
| `github_search_queries` | the 3 feasibility queries | code-search input |
| `github_min_interval_ms` | `6500` | rate limiter |
| `github_require_compliant_license` | `True` | require allowlisted repo SPDX upstream |
| `github_max_file_bytes` | `8*1024*1024` | skip oversized blobs (enumeration-time size from the tree/search item) |

### Task + endpoint

- Celery task `discover_github` (light queue, opt-in, **not** in beat): builds `GithubDiscoverySource` from settings, calls `run_harvest(..., source_catalogue="github", groups=["github"])`, logs a `HarvestReport` line (`task_ignore_result=True`, so the report is read from the worker-light log, same as MOD).
- Admin endpoint `POST /api/v1/admin/harvest/github` (admin-only, **dry-run default**, `limit` 1–200), mirroring `POST /admin/harvest`. Returns the dry-run `HarvestReport` inline when run in-process, or enqueues the task.

### Provenance & tagging

`source_catalogue="github"` on the version (column exists). `groups=["github"]` tags the ontology (see `ontoexplorer-ontology-tags`), so the second instance's GitHub-sourced rows are filterable and the federation demo can point at them.

## Constraints / Global

- Repo is **public** (Apache-2.0): the PAT lives only in Vault/env; config holds the env-var name. No token in git, logs, DB, or error messages.
- SSRF: all downloads go through the existing guarded `source_resolver`. The GitHub client talks only to fixed `api.github.com`.
- Dry-run is the default at every entry point; `github_discovery_enabled=False` ships disabled.
- Reuses `Candidate`, `DiscoverySource`, `admit`, `run_harvest`, `RunBudget`, `PeerRateLimiter`, `source_catalogue`/`source_acronym` threading unchanged.

## Review focus (inputs the tests must pin)

- A candidate from a repo with **no / non-allowlisted license** → skipped in discovery when `require_compliant_license` (never reaches the gate).
- A **fork** result from code search → excluded (GitHub excludes forks by default; assert the query, don't rely on luck).
- A **secondary-rate-limit 403 / `Retry-After`** → bounded backoff, typed error, no token in the message.
- An oversized blob (> `github_max_file_bytes`) → skipped at enumeration (no download).
- `discover(limit=0)` → `[]`; `limit` honored across both inputs with sha-dedup.
- Token **absent** while `github_discovery_enabled=True` → clean typed failure, not a crash or a logged `None`.
- `dry_run=True` (default) → nothing enqueued; report tallies `would-admit`.

## Owner decisions (please confirm / adjust)

1. **PAT provisioning** *(blocks live run only)*: owner mints a read-only GitHub PAT (public repos + code search) and puts it in the target instance's Vault as `GITHUB_API_TOKEN`. Build + dry-run don't need it (tests mock GitHub; feasibility used the workstation `gh` token).
2. **Seed org/repo list** (`github_seed_repos`): proposed starter set to curate — e.g. `BFO-ontology/BFO`, `obophenotype/upheno`, `Onto-Med/GFO`, `knowrob/knowrob`, `OBOFoundry/COB`, plus whatever ontology repos you want the demo to feature. Code search fills the long tail. Your call on the exact list (it's config, easily tuned).
3. **License strictness** (`github_require_compliant_license`, default **True**): require an explicit allowlisted repo license for GitHub (stricter than the MOD gate's lenient rule), since GitHub carries no per-file license. Confirm True.

## Update 2026-11-27 — discovery strategy (measured)

After measuring GitHub's API against the real population (and reviewing the Shapes of You prior art, `github.com/vemonet/shapes-of-you`), the discovery design is:

- **Primary input: repo-topic discovery** (`github_topics`, default `owl,skos`). Search repos by topic (`search_repositories`, `sort=updated` for freshness), tree-walk each for ontology files. Why primary: the tree-walk **raw-downloads** files, so it reaches **large ontologies that code search cannot** (measured: GitHub's code index returns **0** results for `size:>384000` — every ontology over ~384 KB is invisible to code search). Topic-tagged repos are also more intentional than the code-search firehose. This follows the Shapes-of-You model (`topic:owl/obofoundry/bioportal/skos`), **trimmed by measurement** (2026-11-27, repo-count + content-density sampling): `owl` (1157 repos, dense with real community OWL ontologies) and `skos` (223, real SKOS vocabularies) carry the distinct unregistered content; `obofoundry` (272) and `bioportal` (**10**) largely duplicate the registries already ingested, and the broad topics `ontology` (3077) / `vocabulary` (2157) are mostly non-RDF noise (code-maps, agent-record systems, language-learning apps). Any set is reachable via `github_topics`.
- **Complement: code search** (`github_search_queries`) for the **untagged long tail** repos the topic path misses. Kept bounded: GitHub caps any query at **1000 results** (10 pages × 100) regardless of total, and can't sort/filter by date. Exhaustive size-sharding was considered and **rejected** — it still can't see >384 KB files and would need hundreds of shards / hours at 10/min for a mostly-noise result.
- **Backbone stays the registries** (OBO/BioPortal/AgroPortal/LOV, already ingested). GitHub discovery is additive — its unique value is *unregistered* ontologies. Note: `topic:obofoundry`/`bioportal` repos largely **overlap** the registry holdings, so for distinct content (e.g. the federation demo) prefer `owl`/general topics + the untagged tail.
- **Noise filter** (`_is_noise_path`): live runs showed modern OBO repos use the ODK layout, flooding the tree-walk with editor components, imports, dosdp patterns, subsets, test fixtures and historical release modules. A conservative path denylist (segments `components/imports/patterns/subsets/modules/test/archive/…`, suffixes `-module/-import/merged_import`) drops these; the `-edit` source file is kept. Applied to both tree-walk and code-search hits.
- **Freshness / re-harvest (future):** code search can't order by date, but repo search can (`sort=updated`, `pushed:>…`), and a file's real last-modified is one `commits?path=…&per_page=1` call — the key for an incremental re-harvest (only re-ingest changed files).

Config added for this: `github_topics`, `github_max_repos_per_topic` (25). `search_repositories` added to the client (search rate limiter). All still OFF + dry-run by default.

## Sequencing (out of this spec, for reference)

1. Build + unit-test this source → dry-run on **current dev** (mutates nothing).
2. (Parallel, owner infra) stand up trimmed 2nd instance + `FEDERATION_ENABLED`/peers.
3. Provision PAT → live-run GitHub ingest **into the 2nd instance** → demo federation main→2nd.
