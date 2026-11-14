# FAIR Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a consolidated, FOOPS!-aligned FAIR assessment — a per-ontology FAIR report and a catalogue-wide FAIR overview — computed entirely from signals OntoExplorer already stores, with no new ingest computation and no new storage.

**Architecture:** A pure scoring function turns the signals already persisted on `versions.*` (resolvability, license/SPDX compliance, OWL profile + language tier, vocabulary reuse, imports/mappings, PROV-O provenance, MOD metadata roles, term label/definition coverage) into a 19-check report scored per FAIR principle. Two read endpoints expose it: one per ontology (assembled on request), one fleet aggregate (Redis-cached, self-healing on miss — the same precompute pattern as `graph_counts`/`coverage`/`reuse`). The frontend renders a report card on the ontology page and an overview panel on a catalogue route; each check deep-links to the existing panel that already renders its signal. Mock/spec: `docs` artifact at claude.ai/artifact/54qcYfeUGdGMvC61Fzgp6G.

**Tech Stack:** FastAPI + async SQLAlchemy, Celery/Redis (cache only), React + TypeScript + Vite, pytest (`.venv/bin/pytest`), vitest (`node_modules/.bin/vitest`).

**Spec:** this plan (derived from the FOOPS! catalogue at w3id.org/foops/catalog and the in-session FAIR-signal inventory of the codebase).

## Global Constraints

- **No DB migration and no new storage.** Every input already exists on `versions.*` / related tables (`owl_profile`, `reuse`, `coverage`, meta-profile, `resolvable`/`resolve_detail`, `license`/`license_compliant`, `groups`, `imports`). The report is derived on read.
- **No new ingest-time computation.** The scorer only reads already-persisted signals; it never parses, resolves, or calls an external service.
- **No new network egress.** No HTTP from the scorer or endpoints. `userEmail` is never placed in any request/URL/payload.
- **Fleet aggregate follows the stats-precompute pattern** ([[ontoexplorer-stats-precompute]]): Redis-cached, recomputed from durable `versions.*` columns on cache miss, never the sole source of truth; must not silently drop aged versions (compute over the same "ready versions" population the catalogue uses).
- **Scoring model:** each check yields pass = 1.0 / partial = 0.5 / graded = a fraction in [0,1]; a principle score is the mean of its checks; the overall score is the mean of the four principle scores. Round for display only. Thresholds: ≥ 0.85 strong, 0.50–0.84 fair, < 0.50 weak.
- **FOOPS!-aligned check IDs** (F1–F6, A1–A3, I1–I4, R1–R6) are stable identifiers in the API payload.
- **Graceful degradation:** any missing input scores its check as fail/partial with an explicit reason, never raises. A brand-new version with mostly-NULL signals must still produce a renderable report.

## Review Focus

- **Tier-only `owl_profile` (the ~14% parser-rejected versions).** `owl_profile.profiles_unavailable == true` means I1 (language tier) passes but I2 (OWL 2 profile) is **partial**, not a crash — the el/ql/rl/dl keys are absent. Covered in Task 1 tests. See [[ontoexplorer-owl-profile-parse-gap]].
- **Zero-term ontologies / missing `coverage` row.** R5/R6 divide label/definition counts by term count; a version with no `coverage` row or zero indexed terms must yield definition/label coverage = 0 (or "not applicable"), never a ZeroDivisionError. Covered in Task 1.
- **License present but non-compliant (NC/ND).** R1 passes (license present) while R2 is **partial** (present but fails the SPDX compliance allowlist) — distinct from "no license" (both fail). Covered in Task 1.
- **NULL-heavy new version.** A version mid-ingest (no resolvability check yet, no reuse/coverage) must produce a report where those checks read "not yet computed" and score fail/partial, with the overall score rendering. Covered in Task 2.
- **Fleet population drift.** `/fair/fleet` must aggregate over the current ready-version set and recompute on cache miss, so a newly-ready or newly-retired version is reflected and aged versions are not dropped. Covered in Task 3.

---

### Task 1: FAIR scoring module (pure, offline)

**Files:**
- Create: `ontoexplorer/modules/fair/__init__.py`
- Create: `ontoexplorer/modules/fair/score.py`
- Test: `tests/unit/fair/test_score.py`

**Interfaces:**
- Consumes: plain Python inputs only (no DB/session) — an assembled `FairInputs` dataclass holding the already-loaded signal values (booleans, counts, the `owl_profile`/`reuse`/`coverage` dicts, meta-profile role set, `license`/`license_compliant`, `groups`, imports/mappings counts).
- Produces:
  - `@dataclass FairCheck{id:str, principle:str, name:str, status:"pass"|"partial"|"fail", score:float, evidence:str, panel:str, tests:list[tuple[str,str]], detail:dict|None}` — `tests` is the exact criteria evaluated as (label, matched-value) pairs so the UI can expand each check to the predicates it tested; `detail` carries structured extras, used by R4 to return the full recommended-role breakdown `{"roles":[{"role":str,"predicates":[iri],"filled":bool,"excluded":bool}, ...]}` (all 29 roles from `meta_profile.registry.ALL_META_ROLES`, with the 8 optional MOD roles flagged `excluded` and left out of the fraction, so the expanded view lists every predicate, which matched, and which are shown-but-not-scored).
  - `@dataclass PrincipleScore{principle:str, score:float, checks:list[FairCheck]}`
  - `@dataclass FairReport{overall:float, verdict:str, principles:list[PrincipleScore], n_checks:int, n_passed:float}`
  - `def compute_fair_report(inp: FairInputs) -> FairReport`
  - `def build_fair_inputs(version, ontology, owl_profile, reuse, coverage, meta_roles, imports_count, mappings_count) -> FairInputs` (pure assembler from already-loaded values; no I/O)

- [ ] **Step 1: Write failing tests** covering the full matrix: a fully-FAIR version → overall ≈ 0.92 band and all principle scores present; a tier-only `owl_profile` (`profiles_unavailable=True`) → I1 pass, I2 partial, no KeyError; a version with `license` set but `license_compliant=False` → R1 pass, R2 partial; a version with no `coverage` / zero terms → R5/R6 score 0.0, no ZeroDivisionError; an all-NULL version → report renders, overall low, every check `fail`/`partial` with a non-empty `evidence`. Assert exact `FairCheck.id` set `{F1..F6,A1..A3,I1..I4,R1..R6}` (19) and that each `principle` mean equals the mean of its checks.

```python
def test_tier_only_profile_scores_i2_partial():
    inp = make_inputs(owl_profile={"language": {"tier": "OWL"}, "profiles_unavailable": True})
    rep = compute_fair_report(inp)
    i1 = find(rep, "I1"); i2 = find(rep, "I2")
    assert i1.status == "pass" and i2.status == "partial"
```

- [ ] **Step 2: Run tests, verify they fail** (`.venv/bin/pytest tests/unit/fair/test_score.py -v` → ImportError/assertion).
- [ ] **Step 3: Implement `score.py`.** Map each check to its input per the table below; pass/partial/graded per the rules in Global Constraints. A3 is a constant pass for any version the platform holds (it is a durability guarantee, not a probe) — document that in a comment. Use `inp` getters that tolerate `None`.

  | ID | Check | Rule from inputs |
  |---|---|---|
  | F1 | stable identifier | `identity_stable` true (canonical self-IRI, no instability reason) |
  | F2 | IRI resolves | `resolvable is True` |
  | F3 | version IRI declared | `version_iri` non-empty |
  | F4 | title + description | both meta roles present |
  | F5 | prefix declared | shortname/prefix present |
  | F6 | registry presence | any registry tag in `groups` (lov/obo/bioportal) |
  | A1 | content negotiation → RDF | `resolve_detail` indicates RDF conneg (fallback: resolvable) |
  | A2 | open protocol | source scheme is http(s) |
  | A3 | metadata persists | **constant pass** (MinIO + MOD-API) |
  | I1 | language tier | `owl_profile.language.tier` present |
  | I2 | OWL 2 profile | profiles present → pass; `profiles_unavailable` → partial; neither → fail |
  | I3 | vocabulary reuse | `reuse` reused-source count > 0 |
  | I4 | qualified refs | imports>0 → pass; mappings/mireot>0 only → partial; else fail |
  | R1 | license present | `license_raw`/`license` present |
  | R2 | machine-readable+compliant | `license` SPDX set AND `license_compliant` → pass; SPDX set not compliant → partial; else fail |
  | R3 | provenance | creator OR (created date AND publisher) present |
  | R4 | recommended metadata | graded: filled / **21 scored** roles. Scored = `ALL_META_ROLES` minus the 8 optional MOD relationship/usage roles `{competency_question, endorsed_by, relies_on, similar, generalizes, specializes, known_usage, used_in_project}` (define `R4_EXCLUDED_ROLES` as a frozenset). `detail.roles` still lists all 29 with `filled` and an `excluded` flag so the UI can show the excluded 8 separately; only non-excluded count toward the fraction. |
  | R5 | term labels | graded: `coverage.with_label / terms` (0 if no terms) |
  | R6 | term definitions | graded: `coverage.with_definition / terms` (0 if no terms) |

- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** (`feat(fair): pure FAIR scoring module aligned to FOOPS! checks`).

### Task 2: Per-ontology FAIR endpoint

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` (add route near the version/profile reads)
- Test: `tests/unit/fair/test_fair_endpoint.py`

**Interfaces:**
- Consumes: `compute_fair_report`, `build_fair_inputs` (Task 1); existing loaders for `owl_profile`, `reuse`, `coverage`, meta roles, imports/mappings; `_get_version_or_404`.
- Produces: `GET /ontologies/{ontology_id}/fair` (optional `?version_id=`; default latest ready) → `FairReport` as JSON (dataclasses → dict). No auth beyond the existing public read.

- [ ] **Step 1: Write failing test** — seed a version with known signals; assert the endpoint returns 19 checks, the expected overall band, and that a version with NULL `owl_profile`/`coverage` still returns 200 with a renderable report (Review Focus: NULL-heavy new version).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement the route** — resolve version, load the already-persisted signals (reuse the same loaders `list_versions`/`/reuse`/`/coverage`/`/meta` use), `build_fair_inputs`, `compute_fair_report`, return. No recomputation of signals.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** (`feat(fair): GET /ontologies/{id}/fair`).

### Task 3: Fleet FAIR aggregate endpoint

**Files:**
- Create: `ontoexplorer/modules/fair/fleet.py`
- Modify: `ontoexplorer/api/ontologies.py` or a small `api/fair.py` router (follow the repo's router convention)
- Test: `tests/unit/fair/test_fair_fleet.py`

**Interfaces:**
- Consumes: Task 1 scorer; a batched read of the ready-version signal columns; the Redis cache helper used by the other fleet stats.
- Produces: `GET /fair/fleet` → `{n, overall_histogram:[{bucket,count}], principle_means:{F,A,I,R}, check_pass_rate:[{id,name,rate,n}], computed_at}`; cache key in Redis; `invalidate_*` hook consistent with the other stats.

- [ ] **Step 1: Write failing test** — seed N versions across score bands; assert histogram buckets sum to N (ready only), principle means in [0,1], and per-check pass rates computed over N; assert a cache miss recomputes from the DB rather than returning empty (Review Focus: fleet population drift).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — iterate ready versions in batches, score each via Task 1, aggregate; cache the aggregate; recompute on miss. Buckets `<50 / 50–69 / 70–84 / 85–100`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** (`feat(fair): GET /fair/fleet cached aggregate`).

### Task 4: Frontend API client + types

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: covered via Task 5/6 component tests (no separate step)

**Interfaces:**
- Produces: `FairCheck`, `PrincipleScore`, `FairReport`, `FairFleet` TS types; `api.fair.report(ontologyId, versionId?)`, `api.fair.fleet()`.

- [ ] **Step 1: Add the types** mirroring the Task 1 dataclasses and the Task 3 aggregate shape.
- [ ] **Step 2: Add the two client methods** next to `api.ontologies.*`.
- [ ] **Step 3: `node_modules/.bin/tsc --noEmit` clean. Commit** (`feat(fair): api client + types`).

### Task 5: Per-ontology report card component

**Files:**
- Create: `frontend/src/components/FairReportSection.tsx`
- Modify: the ontology page to mount it (beside `OwlProfileSection`/`ReuseSection`)
- Test: `frontend/src/components/FairReportSection.test.tsx`

**Interfaces:** Consumes `api.fair.report`. Renders the score ring, four principle bars, and expandable per-principle check lists. **Each check row is itself expandable** (a nested disclosure): collapsed it shows status glyph + one-line evidence; expanded it shows the `tests` pairs (the exact predicates evaluated and what matched) and, for R4, the full 29-role grid from `detail.roles` (each role's predicate IRIs + ✓/✕), plus a deep link to the owning panel (`#resolvable`, `#reuse`, `#profile`, `#coverage`, `#metadata`). Visual reference: the published mock (v3).

- [ ] **Step 1: Write failing test** — given a mocked `FairReport`, renders 19 rows, the overall number, and a tier-only payload renders I2 as partial (no crash); expanding R4 renders all 29 role entries with their predicates and ✓/✕ state; expanding another check renders its `tests` pairs. Use the status→glyph mapping; never color-only (glyph + label).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the component (loading/empty/error states; theme-token colors; graded checks show their %).
- [ ] **Step 4: Run, verify pass; `tsc --noEmit` clean. Commit** (`feat(fair): ontology FAIR report card`).

### Task 6: Catalogue FAIR overview

**Files:**
- Create: `frontend/src/components/FairOverview.tsx`
- Modify: the stats/catalogue route to mount it
- Test: `frontend/src/components/FairOverview.test.tsx`

**Interfaces:** Consumes `api.fair.fleet`. Renders the distribution histogram, per-principle means, and per-check pass-rate list.

- [ ] **Step 1: Write failing test** — given a mocked `FairFleet`, renders four principle means and the histogram buckets; empty/loading states safe.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (follow `dataviz`: status palette by score band, glyph/label, theme tokens, tabular-nums).
- [ ] **Step 4: Run, verify pass; `tsc --noEmit` clean. Commit** (`feat(fair): catalogue FAIR overview`).

### Task 7: MOD-API quality exposure (optional, ship-behind-flag)

**Files:**
- Modify: `ontoexplorer/modules/mod/builder.py` + `api/mod.py`
- Test: `tests/unit/fair/test_mod_fair.py`

**Interfaces:** Add the four principle sub-scores + overall to the artefact's MOD record as a quality block, so federated SAC nodes can read a node's FAIR self-assessment.

- [ ] **Step 1: Write failing test** — the `/mod/artefacts/{id}` record includes the FAIR sub-scores.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (derive via Task 1 from the already-loaded version; no new store).
- [ ] **Step 4: Run, verify pass. Commit** (`feat(fair): expose sub-scores via MOD-API`).

## Files
- `ontoexplorer/modules/fair/{__init__,score,fleet}.py` — scorer + aggregate.
- `ontoexplorer/api/ontologies.py` (or `api/fair.py`) — `/ontologies/{id}/fair`, `/fair/fleet`.
- `ontoexplorer/modules/mod/builder.py`, `api/mod.py` — optional MOD exposure.
- `frontend/src/lib/api.ts`, `frontend/src/components/FairReportSection.tsx`, `frontend/src/components/FairOverview.tsx`.
- `tests/unit/fair/*`, `frontend/src/components/Fair*.test.tsx`.

## Reused building blocks (do not re-implement)
The already-persisted signals and their loaders (`owl_profile`, `reuse`, `coverage`, meta-profile `/meta`, `resolvable`/`resolve_detail`, `license`/`license_compliant`, `groups`, `imports`); the Redis fleet-stats cache + invalidate pattern ([[ontoexplorer-stats-precompute]]); the existing per-signal panels for deep links; `_get_version_or_404`.

## Verification
1. **Unit:** `.venv/bin/pytest tests/unit/fair -q` green (scorer matrix, endpoints, fleet aggregate).
2. **Frontend:** `node_modules/.bin/tsc --noEmit` clean; `node_modules/.bin/vitest run src/components/Fair*` green.
3. **Live on dev:** `GET /ontologies/{sio}/fair` returns a sane SIO report (~0.9); `GET /fair/fleet` returns a histogram summing to the ready-version count; spot-check a tier-only version (I2 partial, no 500) and a held/non-compliant-license version (R2 partial). Then eyeball both UI surfaces in the browser, light + dark.

## Rollout
Standard two-repo GitOps: PR to `MaastrichtU-IDS/ontoexplorer` → user merges → tag next `0.4.x` → release build → services lockstep pin bump (`ids3/projects/ontoexplorer/dev/app.yaml`) → user merges → ArgoCD rolls → verify on dev via `git_ref` on `/api/v1/version`. **No DB migration.**
