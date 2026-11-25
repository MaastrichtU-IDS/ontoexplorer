# Peer-auth-aware ingestion download — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach a configured federation peer's API key to an ingestion download fetch when (and only when) the target host is that peer's host, so gated MOD-API distributions (e.g. AgroPortal `/download`) ingest instead of 401-ing — mirroring the federation client's security contract and never persisting the key.

**Architecture:** Extract the federation client's pure auth helpers into a shared `modules/federation/auth.py` (single source of the security policy), then add an auth-aware streaming fetch branch to `modules/ingestion/source_resolver.py` that uses them. The common (non-peer) download path is unchanged byte-for-byte.

**Tech Stack:** Python 3.13, httpx (sync `httpx.Client` + `httpx.MockTransport` in tests), pytest.

**Spec:** docs/superpowers/specs/2026-11-25-ingest-peer-auth-design.md

## Global Constraints

- The API key is NEVER stored: not in `source_url`, not in any DB column, not in logs. Resolved from the env var named by `auth.secret_ref` at fetch time only.
- The key is attached ONLY when the request URL host == a configured peer's base-URL host (exact, lower-cased). Withheld on every other host, including after a redirect.
- Refuse an `https→http` downgrade on the peer host (would carry the key in cleartext). An off-host downgrade is just an unauthenticated public fetch and is allowed.
- Every hop goes through `guarded_transport()` (SSRF). The streaming size cap (`ingest_max_source_bytes`) still applies to the final body.
- The federation client's existing behavior and its 18 tests (`tests/unit/test_federation_client.py`) must stay green unchanged — Task 1 is a pure move + rewire.
- `apikey_param` peers carry the key in the query string: never log a raw URL or raw exception string on the authed path.

## Review Focus

- A download URL whose host matches NO configured peer must take the existing simple path and attach no key, no header, no query param (regression: the common case). → Task 2 test.
- A configured peer with an UNSET secret env var must fall back to an unauthenticated request without crashing ingestion. → Task 2 test.
- An authed `/download` that 302s to a non-peer public host (CDN/S3) must be followed, but with the key withheld on that off-peer hop. → Task 2 test.
- The size cap must still abort an oversized body on the authed path (both declared Content-Length and mid-stream). → Task 2 test.
- An `apikey_param` key must never appear on a request to any host other than the peer host, even across multiple redirects. → Task 2 test.

---

### Task 1: Extract shared federation auth helpers

**Files:**
- Create: `ontoexplorer/modules/federation/auth.py`
- Modify: `ontoexplorer/modules/federation/client.py` (remove the two private helpers' bodies, import from `auth`)
- Create: `tests/unit/test_federation_auth.py`

**Interfaces:**
- Produces:
  - `resolve_secret(auth: PeerAuth | None) -> str | None` — env read of `auth.secret_ref`; `None` (with a logged warning) if auth is None or the env var is unset/empty. Moved verbatim from `client._resolve_secret`.
  - `apply_auth(url: httpx.URL, headers: dict[str, str], auth: PeerAuth | None, secret: str | None, peer_host: str) -> tuple[httpx.URL, dict[str, str]]` — moved verbatim from `client._apply_auth` (apikey_param → `url.copy_set_param(name, secret)`; bearer → `Authorization` header; attaches only when `url.host.lower() == peer_host` and both auth and secret are present).
  - `peer_for_host(host: str | None) -> Peer | None` — first `get_federation_peers()` entry whose `urlsplit(base_url).hostname.lower()` equals `host.lower()`, else `None`. `None`/empty host → `None`.
- Consumes: `Peer`, `PeerAuth`, `get_federation_peers` from `modules/federation/config`.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_federation_auth.py`:
  - `resolve_secret(None) is None`; with a `PeerAuth(secret_ref="K")` and `K` set → the value; with `K` unset → `None` (no raise).
  - `apply_auth` attaches `?apikey=s3cret` only when `url.host == peer_host`; withholds on a different host; sets the bearer header for `kind="bearer"`; returns input unchanged when `secret is None`.
  - `peer_for_host` returns the configured peer for its own host (set `FEDERATION_PEERS_JSON` the way `test_federation_client.py` does), `None` for an unknown host, `None` for `None`.
  Use `monkeypatch.setenv` + `get_settings.cache_clear()` (autouse fixture, as the existing resolver test does).

- [ ] **Step 2: Run the tests, verify they fail** (`ModuleNotFoundError` / `AttributeError`).
  Run: `.venv/bin/python -m pytest tests/unit/test_federation_auth.py -q`

- [ ] **Step 3: Create `auth.py`** by moving `_resolve_secret` and `_apply_auth` out of `client.py` verbatim (renamed without the leading underscore) and adding `peer_for_host`. Keep the same logging.

- [ ] **Step 4: Rewire `client.py`** — delete the two moved function bodies; add `from ontoexplorer.modules.federation.auth import apply_auth as _apply_auth, resolve_secret as _resolve_secret` so the two existing call sites (lines ~159, ~167) are untouched.

- [ ] **Step 5: Run both suites green.**
  Run: `.venv/bin/python -m pytest tests/unit/test_federation_auth.py tests/unit/test_federation_client.py -q`
  Expected: new tests PASS and all 18 federation-client tests still PASS.

- [ ] **Step 6: Commit** (`git add` the three files; message `refactor: extract federation auth helpers into federation/auth.py`).

---

### Task 2: Auth-aware ingestion download fetch

**Files:**
- Modify: `ontoexplorer/modules/ingestion/source_resolver.py`
- Create: `tests/unit/ingestion/test_source_resolver_peer_auth.py`

**Interfaces:**
- Consumes: `resolve_secret`, `apply_auth`, `peer_for_host` from `modules/federation/auth`; `get_settings().ingest_max_source_bytes`; `guarded_transport` (existing).
- Produces: no new public symbols. `resolve_url`/`resolve_iri` are unchanged signatures; the dispatch happens inside `_fetch`.

Design (implement in `_fetch(url, headers)`):
- Factor the existing size-cap streaming into a helper `_stream_capped(resp, max_size) -> bytes` (checks declared Content-Length, then caps mid-stream) and use it in both branches.
- At the top of `_fetch`: `peer = peer_for_host(urlsplit(url).hostname)`; `secret = resolve_secret(peer.auth) if peer else None`.
  - If `peer is None or secret is None`: run the **existing** simple path unchanged (`httpx.Client(follow_redirects=True, transport=guarded_transport())`, one `client.stream`, `_stream_capped`). This is the regression-critical common case.
  - Else: run `_fetch_authed(url, headers, peer_host, peer.auth, secret, max_size)`.
- `_fetch_authed`: `httpx.Client(follow_redirects=False, transport=guarded_transport())`; manual loop up to `get_settings()`-derived (reuse federation's `federation_max_redirects`, or a local constant `_MAX_REDIRECTS = 5`) hops:
  - `req_url, req_headers = apply_auth(current, {**headers}, auth, secret, peer_host)` (auth attaches only on the peer host).
  - `with client.stream("GET", req_url, headers=req_headers) as resp:`
    - if `resp.is_redirect`: compute `nxt = resp.url.join(resp.headers["location"])`; if `current.host == peer_host` and `current.scheme == "https"` and `nxt.scheme == "http"` → raise `ValueError` (refuse authed cleartext downgrade); else `current = nxt; continue` (off-host hops will simply not get auth next iteration).
    - `resp.raise_for_status()`; `return _stream_capped(resp, max_size), resp.headers.get("content-type"), str(resp.url)`.
  - Exhausted budget → raise `ValueError("too many redirects")`.
  - Guard the loop so an exception's string (which may contain the apikey query param) is not logged raw.

- [ ] **Step 1: Write failing tests** in `tests/unit/ingestion/test_source_resolver_peer_auth.py` (mirror `_mock_client` + `_fresh_settings` from `test_source_resolver_size_limit.py`, and set `FEDERATION_PEERS_JSON` + the secret env var the way `test_federation_client.py` does). Cover the five Review-Focus cases:
  1. **Non-peer host, no auth:** URL host not in peers → handler asserts `request.url.params.get("apikey") is None` and `"authorization" not in request.headers`; returns payload; `resolve_url` returns it.
  2. **Peer host, apikey attached:** configured apikey_param peer, secret set → handler asserts `request.url.params.get("apikey") == secret`; payload returned.
  3. **Missing secret → unauthenticated, no crash:** peer configured, secret env var unset → handler asserts no apikey; `resolve_url` still returns the body.
  4. **Cross-host redirect withholds key:** peer host 302s to a non-peer public host; assert the key is present on the peer-host request and absent on the off-host request; final body returned.
  5. **Size cap on authed path:** peer host, secret set, oversized Content-Length → `ValueError(match="size limit")` before body is read; and an undeclared oversized body aborts mid-stream.
  Plus: **bearer** peer sets `Authorization: Bearer …` only on the peer host.

- [ ] **Step 2: Run tests, verify they fail.**
  Run: `.venv/bin/python -m pytest tests/unit/ingestion/test_source_resolver_peer_auth.py -q`

- [ ] **Step 3: Implement** `_stream_capped` + the `_fetch` dispatch + `_fetch_authed` per the design above.

- [ ] **Step 4: Run the new tests green**, then the existing resolver tests to prove no regression.
  Run: `.venv/bin/python -m pytest tests/unit/ingestion/test_source_resolver_peer_auth.py tests/unit/ingestion/test_source_resolver_size_limit.py -q`

- [ ] **Step 5: Commit** (`git add` the two files; message `feat: attach federation peer API key to ingestion downloads on the peer host`).

---

### Task 3: Full targeted suite + changelog note

**Files:**
- Modify: `CHANGELOG.md` if the repo keeps one (check first; skip the edit if absent).

- [ ] **Step 1:** Run the federation + ingestion unit tests together green.
  Run: `.venv/bin/python -m pytest tests/unit/test_federation_auth.py tests/unit/test_federation_client.py tests/unit/ingestion -q`
- [ ] **Step 2:** If `CHANGELOG.md` exists, add one line under its unreleased/top section: ingestion downloads now authenticate to a configured MOD-API peer's own host (no key persisted). Commit it. If absent, skip with a ledger note.
