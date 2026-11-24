# Gated MOD-API Harvest Increment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harvest ontologies from one curated remote MOD-API catalogue, admit only the candidates that pass a cheap pre-enqueue gate (dedup / license / quality / budget), and enqueue each survivor through the existing ingestion pipeline with catalogue provenance recorded — the gate, not the harvest, is the deliverable.

**Architecture:** A new `ontoexplorer/modules/discovery/` package. A `DiscoverySource` yields normalised `Candidate` objects; the first concrete source, `ModApiHarvestSource`, pages a peer's `/mod/artefacts` catalogue (reusing the Project-1 federation client + adapters, which are now on `main`) and resolves each artefact's download URL. An `AdmissionGate` decides admit/reject per candidate using the existing dedup helper and license gate. A `run_harvest` orchestrator applies peer-politeness throttling and a per-run budget, then enqueues admitted candidates via the existing `ingest_ontology.delay`, stamping each with its source catalogue. A `harvest_peer` Celery task and a thin admin endpoint trigger it, with a **dry-run** mode (the default-safe path) that reports what *would* be admitted without touching the catalogue — the feasibility-assessment lever.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy async / Celery / httpx (via the SSRF-guarded federation client) / Alembic / pytest-anyio.

**Spec:** `docs/superpowers/specs/2026-11-24-bulk-discovery-ingest-feasibility.md` and `docs/superpowers/plans/2026-11-24-bulk-discovery-ingest-program.md` (Project 2 feasibility writeup, approved). This plan implements Phase 1+2 (gated single-peer harvest) only; GitHub scanning (Phase 4) and the freshness/re-harvest loop are out of scope.

## Global Constraints

- **Reuse, do not re-implement, the federation client.** All outbound HTTP to a peer goes through `ontoexplorer/modules/federation/client.py` (SSRF guard, redirect re-validation, byte cap, per-peer auth). The harvest source must not open its own `httpx.AsyncClient` or call the network directly.
- **Off by default.** Harvest does nothing unless `HARVEST_ENABLED` is true AND a valid `HARVEST_PEER_ID` names a configured federation peer. New settings default to disabled/empty.
- **Dry-run is the safe default.** `run_harvest`/`harvest_peer`/the admin endpoint default `dry_run=True`. A live run (enqueue) happens only when `dry_run=False` is explicitly passed.
- **Never launder a license.** The pre-enqueue gate may *reject* on a recognised-non-compliant catalogue license, but it must never set `declared_license` to make content pass. Admitted candidates enter the normal pipeline, whose post-ingest quality gate (`decide_publish_status`) holds non-compliant/untitled versions as `needs_review`. The pre-gate is an optimisation + politeness filter, not the safety boundary.
- **Secret hygiene.** Peer auth secrets stay in the client (resolved from env at call time). Never log a download URL or peer URL at a level that could capture an `apikey_param` query string; follow the client's existing `type(exc).__name__` logging pattern.
- **Alembic:** the single current head is `b2d5f8a1c3e4`; the one new migration sets `down_revision = "b2d5f8a1c3e4"`.
- **Provenance is additive and nullable.** The new `source_catalogue` column is nullable; every existing ingest path (upload, URL, IRI, webhook) keeps working with it unset.

## Review Focus

- **A peer with no `/distributions/latest` for an artefact** → the source must fall back to ingesting by the artefact's own IRI (conneg), not drop the candidate or crash. (Task 5 test.)
- **A catalogue page that repeats artefacts across pages, or never shrinks** → pagination must dedup by IRI within a run and stop at the per-run budget even if the peer keeps returning full pages. (Task 5 test.)
- **A candidate whose catalogue license is present but unmappable** (proprietary URL, "All rights reserved") → admit it (absence-of-proof ≠ proof-of-non-compliance); the post-ingest gate holds it. Only a license that *canonicalizes to an SPDX id outside the allowlist* is rejected pre-enqueue. (Task 3 tests.)
- **Harvest invoked while disabled, or with an unknown peer id** → `harvest_peer`/the endpoint returns a clean "disabled"/"unknown peer" report, enqueues nothing, never raises. (Task 6/7 tests.)
- **A transient peer fetch error mid-enumeration** → the run records the error in the report and continues/stops gracefully; one bad artefact never aborts the whole harvest. (Task 5/6 tests.)

---

### Task 1: Provenance column + thread-through

**Files:**
- Create: `alembic/versions/<newrev>_add_version_source_catalogue.py`
- Modify: `ontoexplorer/models/db.py` (OntologyVersion, after `source_url` ~line 203)
- Modify: `ontoexplorer/modules/ingestion/pipeline.py` (IngestionRequest ~line 94; version creation ~line 388)
- Modify: `ontoexplorer/modules/jobs/tasks.py` (`ingest_ontology` signature ~line 747; IngestionRequest construction ~line 781)
- Test: `tests/integration/test_harvest_provenance.py`

**Interfaces:**
- Produces: `OntologyVersion.source_catalogue: str | None`; `IngestionRequest(source_catalogue: str | None = None)`; `ingest_ontology(..., source_catalogue: str | None = None)` kwarg threaded to the version row.

- [ ] **Step 1: Write the failing test** — `test_request_source_catalogue_persists_on_version`: run `run_ingestion` with a small inline turtle ontology and `IngestionRequest(raw_bytes=..., source_catalogue="peer-x")`; assert the created `OntologyVersion.source_catalogue == "peer-x"`. Add `test_source_catalogue_defaults_null`: an ingest without it leaves the column `None`. (Mirror the existing ingestion integration-test harness/fixtures.)

- [ ] **Step 2: Run the test to verify it fails** — `pytest tests/integration/test_harvest_provenance.py -v`; expect FAIL (`TypeError: unexpected keyword 'source_catalogue'` or AttributeError).

- [ ] **Step 3: Add the column** — in `db.py`, add `source_catalogue: Mapped[str | None] = mapped_column(String, nullable=True)` to `OntologyVersion`.

- [ ] **Step 4: Thread it through the pipeline** — add `source_catalogue: str | None = None` to `IngestionRequest`; in `run_ingestion`'s `OntologyVersion(...)` construction add `source_catalogue=request.source_catalogue`.

- [ ] **Step 5: Thread it through the task** — add `source_catalogue: str | None = None` to `ingest_ontology`'s kwargs and pass it into the `IngestionRequest(...)` it builds.

- [ ] **Step 6: Write the Alembic migration** — new revision, `down_revision = "b2d5f8a1c3e4"`; `upgrade()` adds a nullable `source_catalogue` `sa.String` column to `ontology_versions`; `downgrade()` drops it. Follow the column-add style of a recent migration in `alembic/versions/`.

- [ ] **Step 7: Run the tests to verify they pass** — `pytest tests/integration/test_harvest_provenance.py -v`; expect PASS. Then `alembic upgrade head` against a scratch sqlite/url to confirm the migration applies cleanly (or the project's migration-smoke test).

- [ ] **Step 8: Commit** — `feat(discovery): record source_catalogue provenance on harvested versions`.

---

### Task 2: Candidate model + DiscoverySource interface

**Files:**
- Create: `ontoexplorer/modules/discovery/__init__.py`, `ontoexplorer/modules/discovery/models.py`, `ontoexplorer/modules/discovery/source.py`
- Test: `tests/unit/discovery/test_models.py`

**Interfaces:**
- Produces:
  - `Candidate` (pydantic BaseModel): `canonical_iri: str`, `title: str`, `license: str | None = None` (catalogue-declared, raw), `download_url: str | None = None`, `landing_url: str | None = None`, `source_catalogue_id: str`, `source_catalogue_label: str`. Helper `ingest_target() -> tuple[str, str]` returning `("url", download_url)` if a download URL is set else `("iri", canonical_iri)`.
  - `DiscoverySource` (Protocol or ABC): `async def discover(self, *, limit: int) -> list[Candidate]` and a `name: str` property for provenance/logging.

- [ ] **Step 1: Write the failing test** — `test_candidate_ingest_target_prefers_download_url`: a `Candidate` with `download_url` returns `("url", <download_url>)`; without one returns `("iri", <canonical_iri>)`. `test_candidate_requires_iri_and_title`: construction fails without `canonical_iri`/`title`.

- [ ] **Step 2: Run the test to verify it fails** — `pytest tests/unit/discovery/test_models.py -v`; expect FAIL (import error).

- [ ] **Step 3: Implement `Candidate` and `ingest_target()`** in `models.py`.

- [ ] **Step 4: Implement `DiscoverySource`** in `source.py` as a `typing.Protocol` with `name` and `async discover(self, *, limit)`.

- [ ] **Step 5: Run the test to verify it passes** — expect PASS.

- [ ] **Step 6: Commit** — `feat(discovery): Candidate model + DiscoverySource interface`.

---

### Task 3: Admission gate

**Files:**
- Create: `ontoexplorer/modules/discovery/gate.py`
- Test: `tests/unit/discovery/test_gate.py`

**Interfaces:**
- Consumes: `Candidate` (Task 2); `ontoexplorer.modules.ingestion.shortname.find_ontology_by_canonical_iri`; `ontoexplorer.modules.ingestion.license.{canonicalize_license, compliant_license_set}`.
- Produces:
  - `AdmissionDecision` (dataclass): `admit: bool`, `reason: str` (one of `"ok"`, `"duplicate"`, `"license_noncompliant"`, `"no_title"`, `"bad_iri"`).
  - `async def admit(db, candidate: Candidate) -> AdmissionDecision`.

- [ ] **Step 1: Write the failing tests** —
  - `test_admits_clean_candidate`: unknown IRI, titled, no/compliant license → `admit=True, reason="ok"`.
  - `test_rejects_known_duplicate`: `find_ontology_by_canonical_iri` returns a row (monkeypatch or seed) → `admit=False, reason="duplicate"`.
  - `test_rejects_recognised_noncompliant_license`: `license="http://creativecommons.org/licenses/by-nc/4.0/"` → `reason="license_noncompliant"`.
  - `test_admits_license_absent`: `license=None` → admit (full gate decides later).
  - `test_admits_unmappable_license`: `license="All rights reserved"` (canonicalizes to None) → admit.
  - `test_rejects_missing_title`: blank title → `reason="no_title"`.
  - `test_rejects_non_http_iri`: `canonical_iri="urn:uuid:…"` or empty → `reason="bad_iri"`.

- [ ] **Step 2: Run the tests to verify they fail** — `pytest tests/unit/discovery/test_gate.py -v`.

- [ ] **Step 3: Implement `admit`** — order: bad_iri (not http(s)) → no_title (blank) → duplicate (`find_ontology_by_canonical_iri` non-None) → license check. License rule: reject **only** when `candidate.license` canonicalizes to an SPDX id that is NOT in `compliant_license_set()` AND the set is non-empty; absent or unmappable (`canonicalize_license` → None) admits. First failing check wins; otherwise `AdmissionDecision(True, "ok")`.

- [ ] **Step 4: Run the tests to verify they pass** — expect PASS.

- [ ] **Step 5: Commit** — `feat(discovery): pre-enqueue admission gate (dedup/license/quality)`.

---

### Task 4: Peer-politeness throttle + run budget

**Files:**
- Create: `ontoexplorer/modules/discovery/throttle.py`
- Test: `tests/unit/discovery/test_throttle.py`

**Interfaces:**
- Produces:
  - `PeerRateLimiter(min_interval_ms: int)` with `async def wait(self) -> None` that sleeps so successive `wait()` calls are at least `min_interval_ms` apart (uses an injectable clock + sleep for testability: `__init__(self, min_interval_ms, *, now=time.monotonic, sleep=asyncio.sleep)`).
  - `RunBudget(max_candidates: int)` with `take() -> bool` (returns False once the budget is exhausted) and `remaining` property.

- [ ] **Step 1: Write the failing tests** — `test_rate_limiter_enforces_interval`: with a fake clock + recording sleep, two back-to-back `wait()`s sleep ~`min_interval_ms`; a `wait()` after enough elapsed time sleeps 0. `test_run_budget_caps`: `RunBudget(2)` → `take()` True, True, False; `remaining` counts down.

- [ ] **Step 2: Run the tests to verify they fail** — `pytest tests/unit/discovery/test_throttle.py -v`.

- [ ] **Step 3: Implement `PeerRateLimiter` and `RunBudget`.**

- [ ] **Step 4: Run the tests to verify they pass** — expect PASS.

- [ ] **Step 5: Commit** — `feat(discovery): peer-politeness rate limiter + run budget`.

---

### Task 5: MOD-API harvest source (paginating enumerator + distribution resolve)

**Files:**
- Modify: `ontoexplorer/modules/federation/client.py` (add a public `fetch_mod_json`)
- Create: `ontoexplorer/modules/discovery/mod_harvest.py`
- Test: `tests/unit/discovery/test_mod_harvest.py`

**Interfaces:**
- Consumes: `federation.config.Peer`; `federation.adapters.adapter_for`; `federation.client.fetch_mod_json`; `Candidate`, `DiscoverySource`, `RunBudget` (via caller), `PeerRateLimiter`.
- Produces:
  - In `client.py`: `async def fetch_mod_json(peer, url, *, transport=None) -> dict` — a thin public wrapper delegating to the existing `_fetch_json`, so the harvest source reuses the SSRF-guarded fetch without importing a private name. (Keep `_fetch_json` as-is; `fetch_mod_json` just forwards.)
  - `ModApiHarvestSource(peer: Peer, *, rate_limiter: PeerRateLimiter | None = None, transport=None)` implementing `DiscoverySource`: `name` = `f"mod-harvest:{peer.id}"`; `async def discover(self, *, limit)` pages `{mod_root}/artefacts?page=N&page_size=min(limit,200)`, parses each page with `adapter_for(peer.adapter)`, dedups by IRI, awaits the rate limiter between page/distribution fetches, and for each `ArtefactRow` resolves a download URL via `_resolve_download_url(acronym)` → `GET {mod_root}/artefacts/{acronym}/distributions/latest` extracting `dcat:downloadURL` (fallback `dcat:accessURL`); builds a `Candidate` (download_url from the distribution, else None → ingest-by-IRI fallback). Stops when a page yields 0 new rows, a short page (< page_size), or `limit` candidates collected.

- [ ] **Step 1: Write the failing tests** (httpx `MockTransport`, no network) —
  - `test_enumerates_two_pages`: transport serves page 1 (full `page_size` hydra members) then page 2 (short) then empty; `discover(limit=large)` returns all distinct artefacts as Candidates.
  - `test_resolves_distribution_download_url`: `/distributions/latest` serves a doc with `dcat:downloadURL`; the Candidate's `download_url` matches and `ingest_target()` → `("url", …)`.
  - `test_falls_back_to_iri_when_no_distribution`: `/distributions/latest` 404s → Candidate `download_url is None`, `ingest_target()` → `("iri", <artefact iri>)`.
  - `test_stops_at_limit`: `discover(limit=3)` returns exactly 3 even though the peer has more.
  - `test_dedups_repeated_iris_across_pages`: an artefact repeated on two pages appears once.
  - `test_distribution_fetch_error_skips_download_not_candidate`: a distributions fetch raising `FederationFetchError` still yields the Candidate (IRI fallback), does not abort enumeration.

- [ ] **Step 2: Run the tests to verify they fail** — `pytest tests/unit/discovery/test_mod_harvest.py -v`.

- [ ] **Step 3: Implement `fetch_mod_json`** in `client.py` (forward to `_fetch_json`), then `ModApiHarvestSource` + `_resolve_download_url` in `mod_harvest.py`. Reuse the adapters' context/URL helpers for the distribution parse (add a small `_download_url_from_distribution(doc)` using `adapters._context_map`/`_expand`/`_http_url`, or a minimal local parse of `dcat:downloadURL`/`dcat:accessURL`). The `mod_root` is `peer.base_url.rstrip("/") + (peer.mod_path or "")` — mirror `client._mod_root` (import or replicate the one-liner).

- [ ] **Step 4: Run the tests to verify they pass** — expect PASS.

- [ ] **Step 5: Commit** — `feat(discovery): paginating MOD-API harvest source with distribution resolve`.

---

### Task 6: Harvest runner + Celery task + provenance enqueue

**Files:**
- Create: `ontoexplorer/modules/discovery/runner.py`
- Modify: `ontoexplorer/modules/jobs/tasks.py` (new `harvest_peer` task)
- Modify: `ontoexplorer/config.py` (new settings)
- Test: `tests/unit/discovery/test_runner.py`

**Interfaces:**
- Consumes: `DiscoverySource`, `AdmissionGate.admit`, `RunBudget`, `Candidate.ingest_target()`, `ingest_ontology.delay`.
- Produces:
  - `HarvestReport` (dataclass → `.as_dict()`): `source: str`, `seen: int`, `admitted: int`, `enqueued: int`, `rejected: dict[str,int]` (reason→count), `errors: list[str]`, `dry_run: bool`.
  - `async def run_harvest(db, source, *, budget: RunBudget, dry_run: bool = True, source_catalogue: str, groups: list[str]) -> HarvestReport` — iterate `await source.discover(limit=budget.remaining)`, gate each with `admit`, tally rejects; for admitted, if not `dry_run`, call `ingest_ontology.delay(**{ingest_kind: value}, groups=groups, source_catalogue=source_catalogue)`; respect `budget.take()`.
  - Settings: `harvest_enabled: bool = False`, `harvest_peer_id: str = ""`, `harvest_max_candidates: int = 50`, `harvest_min_interval_ms: int = 1000`.

- [ ] **Step 1: Write the failing tests** (monkeypatch `ingest_ontology.delay` to a recorder; a fake `DiscoverySource` returning a fixed Candidate list; gate exercised for real against a seeded/mocked db) —
  - `test_dry_run_enqueues_nothing`: `dry_run=True` → `enqueued == 0`, `delay` never called, report still tallies `seen`/`admitted`/`rejected`.
  - `test_live_run_enqueues_admitted_with_provenance`: `dry_run=False` → `delay` called once per admitted candidate with `source_catalogue=<peer>`, `groups` including the peer tag, and the correct ingest kind (`url=` when download present, else `iri=`).
  - `test_rejected_tallied_by_reason`: a dupe + an NC-licensed candidate → `rejected == {"duplicate":1,"license_noncompliant":1}`, neither enqueued.
  - `test_budget_caps_enqueue`: budget 1, two admissible candidates → one enqueued.

- [ ] **Step 2: Run the tests to verify they fail** — `pytest tests/unit/discovery/test_runner.py -v`.

- [ ] **Step 3: Implement `HarvestReport` + `run_harvest`**; add the four settings to `config.py`.

- [ ] **Step 4: Implement `harvest_peer` Celery task** in `tasks.py`: `harvest_peer(self, peer_id: str | None = None, limit: int | None = None, dry_run: bool = True) -> dict`. Resolve peer via `get_federation_peers()`; if `not settings.harvest_enabled` → return `{"status":"disabled"}`; if peer id (arg or `settings.harvest_peer_id`) not found → `{"status":"unknown_peer"}`. Build `ModApiHarvestSource(peer, rate_limiter=PeerRateLimiter(settings.harvest_min_interval_ms))`, `RunBudget(limit or settings.harvest_max_candidates)`, run `run_harvest(..., dry_run=dry_run, source_catalogue=peer.id, groups=["mod-harvest", peer.id])` in a fresh celery db session; return `report.as_dict()`.

- [ ] **Step 5: Run the tests to verify they pass** — expect PASS. Add a focused `harvest_peer` test asserting the disabled/unknown-peer short-circuits return the right status and never call `delay`.

- [ ] **Step 6: Commit** — `feat(discovery): gated harvest runner + harvest_peer task + provenance enqueue`.

---

### Task 7: Thin admin trigger endpoint

**Files:**
- Modify: `ontoexplorer/api/admin/` (add a `harvest` route; follow the existing admin-router auth pattern used by `held.py`)
- Test: `tests/integration/test_admin_harvest.py`

**Interfaces:**
- Consumes: `harvest_peer` task; the admin-auth dependency the other admin routes use.
- Produces: `POST /api/v1/admin/harvest` body `{peer_id?: str, limit?: int, dry_run: bool = true}` → enqueues `harvest_peer.delay(...)` and returns `{task_id, dry_run, peer_id}`; `GET` variant optional (skip). Admin scope required.

- [ ] **Step 1: Write the failing tests** —
  - `test_requires_admin`: non-admin key → 401/403.
  - `test_enqueues_harvest_task`: admin key, `{"dry_run": true}` → 200, `harvest_peer.delay` called with `dry_run=True` (monkeypatch `.delay` recorder); response carries a task id.
  - `test_defaults_to_dry_run`: omitting `dry_run` → `delay` called with `dry_run=True`.

- [ ] **Step 2: Run the tests to verify they fail** — `pytest tests/integration/test_admin_harvest.py -v`.

- [ ] **Step 3: Implement the route** — mirror an existing admin POST route's auth dependency + router registration; validate `limit` (positive, ≤ a sane cap, e.g. 500); enqueue and return.

- [ ] **Step 4: Run the tests to verify they pass** — expect PASS.

- [ ] **Step 5: Commit** — `feat(discovery): admin endpoint to trigger a gated harvest (dry-run default)`.

---

## Self-review notes

- **Spec coverage:** interface (T2), gate (T3), throttle (T4), source/plugin (T5), provenance (T1 + T6 enqueue), orchestration + enqueue + off-by-default (T6), usable trigger with dry-run feasibility lever (T7). GitHub scan + re-harvest loop explicitly out of scope per the spec's phasing.
- **Type consistency:** `Candidate.ingest_target()` returns `(kind, value)` consumed verbatim by `run_harvest` → `ingest_ontology.delay(**{kind: value})`. `AdmissionDecision.reason` strings are the exact keys tallied in `HarvestReport.rejected`.
- **The safety boundary is the existing pipeline gate**, not the pre-gate — admitted content still faces `decide_publish_status` and lands `needs_review` if non-compliant/untitled. The pre-gate only avoids wasted work and obvious NC pulls.
