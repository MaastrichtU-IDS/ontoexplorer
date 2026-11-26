# GitHub Discovery Source — Implementation Plan

> **For agentic workers:** executed natively (plan carries the design) + one whole-branch review on the token-leak surface before the dry-run.

**Goal:** Add a `GithubDiscoverySource` that enumerates GitHub-hosted ontology files (curated repos + code search), license-filters them cheaply, and feeds the shipped harvest pipeline — off + dry-run by default.

**Spec:** `docs/superpowers/specs/2026-11-26-github-discovery-source-design.md`

**Tech:** Python/async, httpx (injectable transport, as `mod_harvest`), pydantic-settings, FastAPI admin router, Celery. Reuses `Candidate`, `admit`, `run_harvest`, `RunBudget`, `PeerRateLimiter`, `source_catalogue`/`source_acronym`.

## Global Constraints

- Repo is **public**: the PAT (`settings.github_api_token`, env `GITHUB_API_TOKEN`) never appears in git, logs, DB, or error messages. The `Authorization` header is never logged; typed errors carry no token and no URL.
- Talks only to fixed `api.github.com`; downloads happen later via the pipeline's SSRF-guarded resolver (not here).
- Off by default (`github_discovery_enabled=False`); every entry point is dry-run by default.
- No change to gate/runner/dedup semantics.

## Review Focus (pin with tests)

- No/non-allowlisted repo license → skipped in discovery (never reaches gate) when `require_compliant_license`.
- Fork result → excluded (assert query includes fork exclusion + skip `repository.fork`).
- Secondary rate limit (403 + `Retry-After`) → bounded backoff, typed `GithubDiscoveryError`, **no token in message or logs**.
- Oversized curated-tree blob → skipped at enumeration.
- `discover(limit=0)` → `[]`; `limit` honored across both inputs with sha-dedup.
- Token absent while enabled → clean typed failure, not a crash or a logged `None`.
- `dry_run=True` default → nothing enqueued.

---

### Task 1: GitHub API client — `ontoexplorer/modules/discovery/github_client.py`

**Files:** Create `github_client.py`; Test `tests/unit/discovery/test_github_client.py`.

**Interfaces — Produces:**
- `class GithubDiscoveryError(Exception)` — `reason: str`; str carries no token/URL.
- `class GithubClient(token, *, rate_limiter=None, transport=None, api_base="https://api.github.com")`:
  - `async search_code(query: str, *, per_page=100) -> list[dict]` → raw `items`.
  - `async get_repo(full_name: str) -> dict` (cached per repo) → repo object (`.license.spdx_id`, `.default_branch`, `.fork`).
  - `async list_tree(full_name: str, *, default_branch: str) -> list[dict]` → tree entries (`path`,`sha`,`size`,`type`).
  - Each call: `await rate_limiter.wait()`; headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.
  - On 403 with `Retry-After` (or `x-ratelimit-remaining: 0`): bounded backoff (sleep `min(retry_after, cap)`, injectable `sleep`), retry ≤ `_MAX_RETRIES` (2), else raise `GithubDiscoveryError("rate_limited")`.
  - Empty/missing token at construction-use → raise `GithubDiscoveryError("no_token")` before any request.
  - Logger discipline: log ids/counts/typed reasons only; **never** the header, token, or full URL.

**Steps:** write failing tests (MockTransport: search parses items; get_repo extracts license+branch+caches, one HTTP call on repeat; 403+Retry-After → one backoff then success, assert `sleep` called; 403 exhausted → `GithubDiscoveryError`; empty token → `no_token`; caplog never contains the token string) → implement → green → ruff → commit.

### Task 2: Discovery source — `ontoexplorer/modules/discovery/github_source.py`

**Files:** Create `github_source.py`; Test `tests/unit/discovery/test_github_source.py`.

**Interfaces — Consumes:** `GithubClient` (Task 1), `Candidate`, `compliant_license_set`, `canonicalize_license`.
**Produces:** `class GithubDiscoverySource(client, *, seed_repos: list[str], queries: list[str], require_compliant_license=True, max_file_bytes=8*1024*1024)`, `name="github"`, `async discover(*, limit) -> list[Candidate]`.

Module constants: `DEFAULT_QUERIES = ["owl:Ontology extension:owl", "owl:Ontology extension:ttl", "a owl:Ontology extension:rdf"]`; `_ONTOLOGY_EXTS = {"owl","ttl","rdf","rdfs","n3","nt","jsonld","trig","owx"}`.

`discover()`:
1. `limit<=0` → `[]`.
2. Collect raw candidates `{full_name, path, sha, html_url, fork}`: from each `seed_repo` via `get_repo`+`list_tree` (filter `type=="blob"`, ext in set, `size<=max_file_bytes`); from each query via `search_code` (items carry `repository.full_name`, `path`, `sha`, `html_url`, `repository.fork`). Skip `fork=True`.
3. Dedup by `sha`.
4. Per candidate (until `limit`): `repo = await client.get_repo(full_name)` (cached); `spdx = repo.license.spdx_id`; if `require_compliant_license` and `canonicalize_license(spdx) not in compliant_license_set()` → skip. Build `raw_url = f"https://raw.githubusercontent.com/{full_name}/{quote(default_branch)}/{path}"`.
5. Emit `Candidate(canonical_iri=raw_url, title=f"{full_name}/{path}", download_url=raw_url, license=spdx, landing_url=html_url, source_catalogue_id="github", source_catalogue_label="GitHub", acronym=None)`. Stop at `limit`.

**Steps:** failing tests with a stub client (canned repos/trees/search) → enumerate seed+search, sha-dedup, license skip, fork exclusion, `limit` honored, `limit=0`→[], `require_compliant_license=False` admits absent license, raw_url uses default_branch → implement → green → ruff → commit.

### Task 3: Config + task + endpoint

**Files:** Modify `ontoexplorer/config.py` (7 settings), `ontoexplorer/modules/jobs/tasks.py` (new `discover_github` task), `ontoexplorer/api/admin/harvest.py` (add `POST /harvest/github`); Test `tests/unit/discovery/test_github_task.py` (+ endpoint smoke if cheap).

**Config (after the harvest block):**
```
github_discovery_enabled: bool = False
github_api_token: str = ""
github_seed_repos: str = ""          # comma-separated owner/repo
github_search_queries: str = ""      # comma-separated; empty => DEFAULT_QUERIES
github_min_interval_ms: int = 6500   # ~10/min code search
github_require_compliant_license: bool = True
github_max_file_bytes: int = 8 * 1024 * 1024
```

**Task** `discover_github` (mirror `harvest_peer`): name `ontoexplorer.discover_github`, `time_limit=900`, `dry_run=True` default. Guard `if not settings.github_discovery_enabled: return {"status":"disabled"}`; guard `if not settings.github_api_token: return {"status":"no_token"}`. Build `GithubClient(token, rate_limiter=PeerRateLimiter(github_min_interval_ms))`; `GithubDiscoverySource(client, seed_repos=_split(github_seed_repos), queries=_split(github_search_queries) or DEFAULT_QUERIES, require_compliant_license=..., max_file_bytes=...)`; `RunBudget(limit or 50)`; `run_harvest(db, source, budget, dry_run=dry_run, source_catalogue="github", groups=["github"])`; log `github_discover_complete seen/admitted/enqueued`.

**Endpoint** in `harvest.py`: `class GithubHarvestRequest(BaseModel){limit: int|None gt=0 le=MAX_HARVEST_LIMIT; dry_run: bool=True}`; `@router.post("/harvest/github")` admin-gated → `discover_github.delay(limit=..., dry_run=...)` → `{"task_id","dry_run"}`.

**Steps:** failing tests (disabled flag → `{"status":"disabled"}`; no token → `{"status":"no_token"}`; `_split` helper; endpoint enqueues with dry_run default True, requires admin) → implement → green → ruff → full `uv run pytest tests/unit -q` → commit.

## Self-review notes
- Type consistency: `get_repo` returns the dict both the source (license+branch+fork) and client cache use; `search_code` items shape matches what `discover()` reads.
- `_split(s)` = `[x.strip() for x in s.split(",") if x.strip()]` — shared, used for both list settings.
- raw_url built from `default_branch` (current HEAD) not blob sha (blob sha isn't a ref); blob sha still used for dedup.
- Search path can't cheaply know blob size → size cap enforced there by the pipeline's `ingest_max_source_bytes`; curated-tree path filters by `size`.
