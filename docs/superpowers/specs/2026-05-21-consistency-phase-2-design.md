# Phase 2: Joint-Reasoning Consistency Analysis — Design

## Context

Phase 1 of the ontology-reuse analysis (shipped 2026-05-20, merge commit `c872b15`) classifies how ontologies in the OntoExplorer fleet reuse other ontologies — `owl:imports` closure, term-IRI namespace overlap, MIREOT-pattern detection, and cross-ontology mapping assertions. It detects MIREOT'd terms (foreign-namespace IRI, minimal axiomatization in the host, source ontology NOT in `owl:imports` closure) but does NOT check whether those MIREOT'd terms actually agree with their source's constraints.

The headline worry from the original brainstorming (and from the user's prior [bioportal-ontology-analysis](https://github.com/micheldumontier/bioportal-ontology-analysis) work) is: **MIREOT bypasses source constraints. Does this create cross-import inconsistencies?** Phase 2 answers that question via joint reasoning across the merged closure.

The 2023 DMKG-workshop evaluation of OWL 2 DL reasoners on the ORE 2015 + BioPortal datasets ranked **Konclude** strongest overall on consistency checking, with HermiT a close second. Konclude is a native C++ binary (no JVM startup), supports full OWL 2 DL via SROIQV, and is actively maintained. We use it as the primary runtime reasoner; HermiT-via-ROBOT remains available as a publication-style cross-check (since OBO Foundry uses HermiT, and Matentzoglu 2020 used HermiT for the comparable joint-reasoning analysis we are extending).

## Goal (one sentence)

For every ontology version in the OntoExplorer fleet, compute and cache three consistency verdicts — under the host ontology alone, under host + declared `owl:imports` closure, and under host + closure + fetched MIREOT-source ontologies — each with the list of unsatisfiable classes and a justification per class.

## Scope

**In scope:**
- Three reasoning scopes per version:
  - `host_only` — just the version's own axioms (baseline)
  - `host_plus_imports` — host merged with everything reachable via `owl:imports` closure (Matentzoglu-style joint reasoning)
  - `host_plus_imports_plus_mireot` — additionally fetch each MIREOT'd term's source ontology (per Phase 1's MIREOT detector output) and merge it in (the headline test)
- Konclude as the production reasoner (CLI shell-out from a Celery worker, parsed results)
- ROBOT `explain` for per-unsatisfiable-class justification extraction (capped at the top 10 unsat classes per scope to bound cost)
- Async Celery task `check_consistency` triggered post-indexing; status polling via API
- Redis cache keyed `consistency:{version_id}` with 30-day TTL
- API endpoints `/api/v1/ontologies/{id}/{vid}/consistency` (per-version) + `/api/v1/consistency/fleet` (rollup) + `?consistency=inconsistent` filter on the list endpoint
- Frontend: per-ontology `ConsistencySection` (three cards) + fleet `Consistency` tab + filter pill, all mirroring Phase 1's `Reuse` shape
- HermiT cross-check pipeline as a separate script under `scripts/consistency_bench/`, NOT in the runtime hot path

**Out of scope (deferred):**
- Interactive proof-exploration UI (Phase 3 — needs graph viz which the project doesn't have yet)
- Auto-suggesting fixes (Phase 4+)
- ELK fast-path for EL ontologies (premature optimization for a 19-ontology fleet; revisit when scaling to BioPortal)
- Library extraction to `pyowl2-consistency` — defer until the API stabilizes (same pattern as `pyowl2-profiles` extraction post-stable-API)
- Cross-version consistency tracking ("this version became inconsistent in v2.3")
- BioPortal-scale population rerun (defer; the Phase 1 BioPortal rerun was metadata-only, but consistency requires ontology bodies — too expensive at 1,200+ ontologies)

## Architecture

### Module layout

```
ontoexplorer/modules/consistency/
    __init__.py                 # public type re-exports
    cache.py                    # consistency_cache_key(version_id) -> str
    merger.py                   # build_merge(version_id, scope) -> Path to N-Triples blob
    konclude.py                 # run_konclude(nt_path) -> KoncludeResult (consistent? unsat classes?)
    robot_explain.py            # explain_unsatisfiability(nt_path, iri) -> Justification
    mireot_source_resolver.py   # fetch missing MIREOT sources via bioregistry + import_resolver
    detector.py                 # orchestrator — runs all 3 scopes, assembles ConsistencyReport
```

### Reasoning pipeline (per scope, per version)

`detector.detect_consistency(version_id, ontology_id, scope) -> ScopeResult`:

1. **Build the merged graph** via `merger.build_merge(version_id, scope)`:
   - `host_only`: serialize only the host's named graph from Oxigraph to N-Triples
   - `host_plus_imports`: include all transitively-imported named graphs
   - `host_plus_imports_plus_mireot`: additionally pull MIREOT-source ontologies (see step 2)
2. **(MIREOT scope only) Fetch missing sources** via `mireot_source_resolver.resolve(version_id)`:
   - Read Phase 1's reuse cache to get the list of MIREOT'd source prefixes
   - For each unique source prefix not already in the imports closure:
     - Use `bioregistry.get_uri_prefix(prefix)` to derive the canonical ontology IRI
     - Call `ontoexplorer.modules.ingestion.import_resolver.resolve_one(iri)` (already MinIO-caches)
     - Append the resolved Turtle/RDF/XML to the merge blob
     - On unreachable: record in `mireot_sources_skipped`, mark scope status as `partial`, continue
3. **Run Konclude** via `konclude.run_konclude(nt_path)`:
   - Shell out to `konclude consistency --input <nt_path>` for the consistency boolean
   - Shell out to `konclude classify --input <nt_path>` and parse for `owl:Nothing` subclasses to get the unsatisfiable-class list
   - Both with a 600s timeout (per scope; abort whole scope if exceeded, mark as `timeout`)
4. **For each unsatisfiable class (cap at top 10 per scope)**: run `robot_explain.explain_unsatisfiability(nt_path, iri)`:
   - Shell out to `robot explain --input <nt_path> --reasoner hermit --axiom "<iri> SubClassOf: owl:Nothing"`
   - Parse the Manchester-syntax justification into our existing `ManchesterToken[]` shape (reuses `pyowl2_profiles.manchester` from Phase 1)
5. **Return `ScopeResult`** with status, unsat list, elapsed time, MIREOT skip list

### Celery task

```python
@celery_app.task(name="ontoexplorer.check_consistency", time_limit=3600)
def check_consistency(version_id: str, ontology_id: str) -> dict:
    """Run all three scopes, cache the combined report, return summary."""
    from ontoexplorer.modules.consistency.detector import detect_consistency
    from ontoexplorer.modules.consistency.cache import consistency_cache_key
    
    scopes = {}
    for scope_name in ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot"):
        scopes[scope_name] = asdict(detect_consistency(version_id, ontology_id, scope_name))
    
    report = {
        "version_id": version_id,
        "host_iri": ...,
        "scopes": scopes,
        "job_status": "done",
        "started_at": ...,
        "finished_at": ...,
    }
    _get_redis().setex(consistency_cache_key(version_id), _SEARCH_TTL, json.dumps(report))
    return {"status": "done", "version_id": version_id, ...}
```

### Indexer hook

In `ontoexplorer/modules/search/indexer.py::build_index`, after the existing `_populate_reuse_cache(...)` call: enqueue the Celery task (don't run it inline). The cache initially holds a `{"job_status": "pending"}` placeholder so the API doesn't 404.

### Data model

```python
@dataclass(frozen=True)
class JustificationAxiom:
    manchester: list[ManchesterToken]  # reuses Phase 1's token shape
    source_ontology_iri: str | None    # which ontology contributed this axiom (best-effort)

@dataclass(frozen=True)
class UnsatisfiableClass:
    iri: str
    label: str | None
    justification: list[JustificationAxiom]  # the minimum-module explanation

@dataclass
class ScopeResult:
    scope: str  # "host_only" | "host_plus_imports" | "host_plus_imports_plus_mireot"
    status: str  # "consistent" | "inconsistent" | "partial" | "timeout" | "error"
    unsatisfiable_classes: list[UnsatisfiableClass]
    mireot_sources_fetched: list[str] = field(default_factory=list)
    mireot_sources_skipped: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error_message: str | None = None

@dataclass
class ConsistencyReport:
    version_id: str
    host_iri: str
    scopes: dict[str, ScopeResult]
    job_status: str  # "pending" | "running" | "done" | "failed"
    started_at: str | None = None
    finished_at: str | None = None
```

### API surface

```
GET /api/v1/ontologies/{ontology_id}/{version_id}/consistency  → ConsistencyReport (or pending status)
GET /api/v1/consistency/fleet                                  → fleet rollup
GET /api/v1/ontologies?consistency=inconsistent                → filter (analogous to ?reuses=)
POST /api/v1/ontologies/{id}/{vid}/consistency/refresh          → enqueue a fresh check (admin/owner only)
```

Per-version response distinguishes the four job states clearly via `job_status`. UI handles `pending`/`running` by polling every 5s; switches to results display when `done` or `failed`.

### Frontend

- **Per-ontology:** `ConsistencySection` on `OntologyPage.tsx` as a new `detailTab` value `'consistency'`. Three cards (one per scope) side-by-side; each shows the verdict (✓/✗/⚠️ partial/⏱ timeout), unsatisfiable class count, and an expandable list of unsat classes with their inline Manchester justifications (reusing `ManchesterInline` from Phase 1's OwlProfileSection).
- **Fleet view:** `Consistency` page rendered as a new tab inside `Ontologies.tsx` at `/ontologies?tab=consistency`. Sortable table: ontology / host-only verdict / host+imports verdict / host+imports+MIREOT verdict / total unsat count. Filter pill `?consistency=inconsistent` integrated with the list endpoint.
- **Pending-state UX:** when `job_status` is `pending` or `running`, show a spinner with "Consistency analysis running — this can take a few minutes for large ontologies."

### HermiT cross-check (separate script, NOT runtime)

`scripts/consistency_bench/` mirrors Phase 1's `scripts/bioportal_reuse/` pattern:

```
scripts/consistency_bench/
    README.md
    run.py        # CLI entry: iterate fleet, for each version run ROBOT/HermiT consistency
    compare.py    # diff Konclude verdicts (from production cache) vs HermiT verdicts
    publish.py    # render comparison CSV/JSON
```

This is the publication-comparability layer. Run on-demand against the OntoExplorer fleet (and optionally against any subset of BioPortal ontologies) to confirm Konclude's verdicts match HermiT's. Output goes into a `consistency_bench_results/` directory in the user's documentation repo, not into OntoExplorer's runtime.

## Critical files (reused infrastructure)

- [ontoexplorer/modules/reuse/cache.py](ontoexplorer/modules/reuse/cache.py) — pattern for the Redis cache-key helper
- [ontoexplorer/modules/jobs/tasks.py::refresh_reuse](ontoexplorer/modules/jobs/tasks.py) — pattern for the Celery task
- [ontoexplorer/modules/jobs/tasks.py::_run_reasoning](ontoexplorer/modules/jobs/tasks.py) — pattern for sync→async wrapper inside Celery
- [ontoexplorer/modules/ingestion/import_resolver.py](ontoexplorer/modules/ingestion/import_resolver.py) — MIREOT-source fetcher reuses this
- [ontoexplorer/api/reuse.py](ontoexplorer/api/reuse.py) — pattern for the new `consistency.py` router
- [ontoexplorer/modules/owl_profile](ontoexplorer/modules/owl_profile) — shells out to ROBOT for cross-validation; same shell-out pattern applies to Konclude
- [frontend/src/components/OwlProfileSection.tsx](frontend/src/components/OwlProfileSection.tsx) + [frontend/src/pages/Reuse.tsx](frontend/src/pages/Reuse.tsx) — UI patterns to mirror

Files to be created:
- `ontoexplorer/modules/consistency/{__init__,cache,merger,konclude,robot_explain,mireot_source_resolver,detector}.py`
- `ontoexplorer/api/consistency.py`
- `frontend/src/components/ConsistencySection.tsx`
- `frontend/src/pages/Consistency.tsx`
- `scripts/consistency_bench/{run,compare,publish}.py` + `README.md`
- Tests: `tests/unit/consistency/test_{merger,konclude,robot_explain,mireot_source_resolver,detector}.py`, `tests/integration/test_consistency_api.py`

Files to be modified:
- `ontoexplorer/modules/search/indexer.py` — enqueue `check_consistency` post-indexing
- `ontoexplorer/modules/jobs/tasks.py` — add `check_consistency` task
- `ontoexplorer/main.py` — mount consistency router
- `ontoexplorer/api/ontologies.py` — add `?consistency=` filter
- `frontend/src/lib/api.ts` — add types + fetchers
- `frontend/src/pages/Ontologies.tsx` — register `consistency` tab
- `frontend/src/pages/OntologyPage.tsx` — add `consistency` detailTab branch
- Docker image: add Konclude binary (Linux x86_64) to runtime container; ROBOT JAR is already shipped (used by `scripts/owl_profile_bench/`)

## Verification

End-to-end:
1. Reindex a fleet ontology known to be consistent in isolation (e.g., RO). Wait for `check_consistency` to complete (poll the per-version endpoint).
2. Confirm `host_only.status == "consistent"`, `host_plus_imports.status == "consistent"`, `host_plus_imports_plus_mireot.status == "consistent"` with empty unsat lists.
3. Construct a hand-crafted fixture ontology that imports IAO (declaring `owl:imports`) AND has a class that contradicts an IAO axiom. Confirm `host_only.consistent` but `host_plus_imports.inconsistent` with the offending class in the unsat list and a non-empty justification.
4. Construct a fixture that MIREOTs a class from IAO (foreign IRI, minimal axioms, NO `owl:imports`) and adds a host-side constraint that contradicts an axiom in the IAO source. Confirm `host_only.consistent`, `host_plus_imports.consistent`, `host_plus_imports_plus_mireot.inconsistent`.
5. Hit `/api/v1/consistency/fleet` and verify the rollup includes all three fixtures with the expected verdicts.
6. Open `/ontologies?tab=consistency` and confirm the sortable table renders + the filter pill works.

Unit tests:
- `merger.py`: scope=host_only produces only host triples; scope=host_plus_imports includes transitively-imported triples; scope=host_plus_imports_plus_mireot additionally includes the MIREOT-source ontologies.
- `konclude.py`: parse a sample Konclude output for a known-inconsistent + known-consistent input.
- `robot_explain.py`: parse ROBOT explain output for a known unsatisfiable class.
- `mireot_source_resolver.py`: bioregistry-known prefix maps to canonical IRI; unreachable IRI handled fail-soft.
- `detector.py`: orchestrator wires the four together correctly for each scope.

Cross-check:
- For one fleet ontology, run `scripts/consistency_bench/run.py` and confirm Konclude's verdicts match HermiT's via ROBOT. Verdict-agreement target: 100% on host_only and host_plus_imports; may differ on the MIREOT scope due to non-determinism in source fetches (acceptable; both should agree on the underlying axiomatic consistency given identical inputs).

## Risks / open questions

- **Konclude packaging:** must add the Linux x86_64 binary (~30 MB) to the runtime Docker image. Mitigation: pin a specific Konclude release; document the version in the README; provide a checksum.
- **Memory on NCBITaxon-scale closures:** Konclude on a 5M-axiom merge needs significant heap. Mitigation: per-scope 600s timeout + worker memory ceiling enforced by Celery's `worker_max_memory_per_child`; if a scope OOMs, status becomes `error` and the user can re-queue with a beefier worker.
- **ROBOT explain is slow per axiom:** capped at top 10 unsat classes per scope (acceptable trade-off; users can use the CLI bench for exhaustive explanations).
- **MIREOT source fetch flakiness:** bioregistry has good URL coverage but some IRIs 404 or rate-limit. Mitigation: fail-soft per source, mark scope `partial`, surface the skip list in the UI.
- **Source-ontology version drift:** Phase 2 merges whatever version of the source ontology the import_resolver fetches *now*. That may differ from what the host ontology originally MIREOT'd against. Document this caveat in the UI ("MIREOT scope reasoned against current source-ontology versions, which may have evolved since this ontology was authored").
- **Konclude vs HermiT divergence:** if the bench finds disagreements, treat them as bugs to investigate, not noise. Document any known divergences in the report alongside the verdict.

## Next steps

After approval of this spec, run `superpowers:writing-plans` to produce the step-by-step implementation plan. Phase 3 (interactive dependency visualization at the class/property level) gets its own brainstorm cycle later.
