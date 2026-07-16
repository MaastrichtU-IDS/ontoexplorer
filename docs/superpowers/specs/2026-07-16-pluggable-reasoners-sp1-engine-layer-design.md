# Pluggable Reasoners — SP1: Reasoner Engine Layer

**Date:** 2026-07-16
**Status:** Design (approved shape, pending spec review)
**Scope:** Sub-project 1 of 3. Engine layer only — no ontoexplorer-app or UI changes.

## Background

The reasoning microservice is currently named `elk-service` but does not run
ELK. It runs **whelk** (a PyO3 binding) by default, with a legacy pure-`rdflib`
CR1–CR6 classifier as a fallback, selected by the `CLASSIFIER_BACKEND=whelk|rdflib`
environment switch (`docker/elk-service/main.py:29-40`). The service owns the
whole reasoning surface the rest of the stack depends on:

- the `POST /classify` → poll → `GET /classify/{version_id}` HTTP contract that
  the Celery workers call (`ontoexplorer/clients/reasoning.py`, `modules/jobs/tasks.py:479`),
- Redis result / justification / input-axiom caching (`cache.py`),
- the consistency endpoint and the justification endpoint,
- in-progress tracking and a single-threaded classifier pool.

We want two new reasoners available as first-class, selectable engines:

- **Konclude** — the DL speed leader, all OWL 2 profiles. **No** justification /
  explanation facility (its interface is classification / consistency /
  realization / SPARQL only).
- **rustdl** (`github.com/MaastrichtU-IDS/rustdl`, cloned at `~/code/rustdl`) — a
  sound OWL 2 DL (SROIQ) reasoner in Rust. Ships a PyO3 binding (`import rustdl`,
  crate `owl-dl-py`) exposing **both** classification and a native, sound
  explanation suite (`justify`, `justify_all`, `diagnose`, `repair`). FP=0;
  fastest on EL; competitive on DL.

Overall product decisions (fixed during brainstorming, apply across SP1–SP3):

- Reasoner selection is **first-class**: a global default in `.env`, overridable
  **per-ontology in the admin UI at ingest time**, bound to the ontology/version.
- Justification behaviour: **explanations follow the reasoner** — rustdl uses its
  native `justify`; whelk keeps its current proof-trace path; Konclude's explain
  feature is **disabled** for Konclude-classified ontologies.

SP1 delivers only the engine layer: everything testable through the service's
own HTTP API, with no dependency on app or UI work. SP2 (app plumbing) and SP3
(admin/UI) get their own specs.

## Goals

1. Rename the service `elk-service` → `reasoner-service` (directory, compose
   service, config, env vars, client base URL) so the code stops lying.
2. Replace the two-way `CLASSIFIER_BACKEND` if/else with a **capability-aware
   reasoner registry**.
3. Add a **`rustdl`** backend (classify + justify) via the `owl-dl-py` PyO3 binding.
4. Add a **`konclude`** backend (classify + consistency, no justify) via a CLI
   subprocess, with Konclude **built from source** for a native-arch image.
5. Make the HTTP contract reasoner-aware and backward-compatible; add
   `GET /reasoners` for capability discovery.
6. Build a fully native `reasoner-service` image (rustdl via maturin, Konclude
   from source, whelk/horned-owl from source — the arm64 path the override
   already uses).

## Non-goals (SP1)

- No Postgres `reasoner` column, no `DEFAULT_REASONER` in the *app* config, no
  ingest-API changes, no `reason_ontology` task changes — that is SP2.
- No admin dropdown / capability-driven UI — that is SP3.
- No side-by-side "compare reasoners" feature. (The cache key is designed to
  permit it later without rework, but it is not built.)
- No mapping of rustdl `diagnose`/`repair`/`prove` into app-facing endpoints yet
  — SP1 exposes rustdl `justify` only, to match the existing justification shape.

## Architecture

### Reasoner registry + capabilities

Replace the module-level `classify = _whelk_classify | _rdflib_classify` switch
with a registry keyed by reasoner name. Each backend implements a uniform
interface and declares a capability set:

```python
Capability = Literal["classify", "consistency", "justify", "diagnose", "repair"]

class Reasoner(Protocol):
    name: str
    profile: str                      # e.g. "EL", "DL (SROIQ)", "OWL 2 (all profiles)"
    capabilities: frozenset[Capability]
    available: bool                   # backend actually importable / binary present

    def classify(self, ntriples: str, version_id: str) -> ClassificationResult: ...
    def justify(self, ntriples: str, sub: str, sup: str,
                max_justifications: int) -> list[Justification] | None: ...
    #   returns None when "justify" not in capabilities
```

`ClassificationResult` is the existing dataclass (`classifier.py:52-62`):
`version_id, classified_at, class_count, superclasses, subclasses,
direct_superclasses, direct_subclasses, unsatisfiable, proof_traces,
duration_ms`. All backends must populate these fields (proof_traces may be `{}`
for backends that do not produce them, exactly as whelk does today).

Registry entries for SP1:

| name       | profile              | capabilities                                   | integration        |
|------------|----------------------|------------------------------------------------|--------------------|
| `whelk`    | EL                   | classify, consistency, justify (proof-trace)   | PyO3 (existing)    |
| `rdflib`   | legacy EL            | classify, consistency                          | pure Python (existing) |
| `rustdl`   | DL (SROIQ)           | classify, consistency, justify (native, sound) | PyO3 `import rustdl` |
| `konclude` | OWL 2 (all profiles) | classify, consistency                          | CLI subprocess     |

The existing `whelk`/`rdflib` code moves behind the registry unchanged in behaviour.

### rustdl backend

- **Classify:** the service already converts N-Triples → RDF/XML via pyoxigraph
  for the whelk path; reuse that conversion and call
  `rustdl.classify_bytes(rdfxml, format="rdf-xml", per_pair_timeout_ms=…,
  global_deadline_ms=…)`. Build the result dicts from the `PyClassification` API:
  iterate `classes`, use `direct_subsumers(c)` → `direct_superclasses`,
  `superclasses_of(c)` → `superclasses` (minus asserted), invert for
  `subclasses`/`direct_subclasses`, `unsatisfiable` from `.unsatisfiable`.
  Record `.complete`/`.timed_out_pairs` in a log line; a non-complete result is
  still returned (sound superset), matching rustdl's contract.
- **Justify:** `rustdl.justify(path, ["subclass", sub, sup])` (and `["unsat", c]`
  when `sup == owl:Nothing`). It takes a **file path**, so materialize the cached
  input N-Triples to a temp `.rdf` (RDF/XML) file per call and clean up. Map the
  returned Manchester axiom strings into the justification response's
  `justifications` field. `proof_traces` is left `[]` for rustdl in SP1 (rustdl's
  `prove` step-tree is deferred to a later SP).
- **Timeouts:** expose `per_pair_timeout_ms` / `global_deadline_ms` via env
  (`RUSTDL_PER_PAIR_TIMEOUT_MS`, `RUSTDL_GLOBAL_DEADLINE_MS`) with sane defaults.

### konclude backend

- **Classify / consistency:** write RDF/XML to a temp file, run
  `Konclude classification -i in.owl -o inferred.owl` (and/or
  `Konclude consistency`), parse the inferred `SubClassOf` / unsatisfiable output
  back into `ClassificationResult`. `capabilities = {classify, consistency}`.
- **Justify:** not supported. `justify()` returns `None`; the HTTP layer turns
  that into a 422 with a clear message (see contract).
- **Concurrency:** runs inside the existing single-threaded classifier pool like
  the other backends; subprocess gives crash isolation.

### HTTP contract changes (backward-compatible)

- `POST /classify` request model gains `reasoner: str | None`. When omitted it
  falls back to the service env `DEFAULT_REASONER` (default `whelk`, preserving
  today's behaviour). Unknown/unavailable reasoner → 422.
- **Cache key includes the reasoner:** `classify:{version_id}:{reasoner}` (and
  likewise for input-axioms and justification keys). This prevents cross-reasoner
  collisions and leaves room for a future compare feature. `invalidate_version`
  clears all reasoner variants for a version.
- `POST /classify/{version_id}/justification` request gains `reasoner: str`.
  If that reasoner lacks the `justify` capability, respond **HTTP 422** with
  `{"detail": "reasoner '<name>' does not support justifications"}` (empty
  justifications, not a 500).
- **New `GET /reasoners`** → `[{name, profile, capabilities, available}]`.
  `available` is computed at startup: rustdl importable? Konclude binary on PATH?
  SP3's dropdown consumes this; SP1 just exposes it and tests it.
- `GET /health` additionally reports the set of available reasoners.

### Rename: elk-service → reasoner-service

Mechanical, part of SP1:

- `docker/elk-service/` → `docker/reasoner-service/` (incl. `Dockerfile`,
  `Dockerfile.arm64`, all `*.py`).
- `docker-compose.yml`: service `elk-service` → `reasoner-service`, `depends_on`,
  ports, `build:` context; likewise `docker-compose.override.yml` and
  `docker-compose.prod.yml`.
- App config: `ontoexplorer/config.py:57` `elk_service_url` →
  `reasoner_service_url`, `elk_service_timeout` → `reasoner_service_timeout`;
  update `clients/reasoning.py`, `api/health.py`, `api/admin/_common.py`,
  `api/admin/health.py`, `modules/jobs/tasks.py:479`.
- Env: `ELK_SERVICE_URL`/`ELK_SERVICE_TIMEOUT` → `REASONER_SERVICE_URL`/
  `REASONER_SERVICE_TIMEOUT` in `.env`, `.env.example`. (Accept the old names as
  a deprecated alias for one release to avoid breaking local `.env` files.)

This rename stays within SP1's "engine layer" boundary because it is confined to
the service and its client wiring; it does not touch data model or UI.

## Packaging

Single native image built via the `Dockerfile.arm64` path (already compiles
py-whelk / horned-owl from source; generalise it as the default multi-arch build):

- **rustdl:** `pip install maturin`, build `owl-dl-py` from the `~/code/rustdl`
  checkout (vendored into the build context or fetched by pinned git ref) →
  native wheel. No wheel-arch pain (Rust builds for the host arch).
- **Konclude:** build from source (native arch). **Risk:** Konclude's build pulls
  Qt and a custom build script — non-trivial and slow. Mitigation: a dedicated
  builder stage that is cached; if the source build proves too costly, the
  fallback is the prebuilt x86_64 binary run emulated (explicitly rejected for
  now per the design decision, but documented as the escape hatch).
- **whelk/horned-owl:** unchanged from the existing arm64 build.

The base `platform: linux/amd64` pin on the service can be dropped once all three
reasoners build native.

## Testing

- Per-backend unit tests mirroring `test_whelk_classifier.py`: a small fixture
  ontology (a handful of classes with a known inferred hierarchy) classified by
  `whelk`, `rustdl`, and `konclude`, asserting the same `superclasses` /
  `subclasses` / `unsatisfiable` shape across all three.
- Registry test: `GET /reasoners` reports all four with correct capabilities;
  Konclude has no `justify`.
- Contract tests: `POST /classify` with `reasoner=rustdl` round-trips; the
  justification endpoint returns real justifications for `rustdl`/`whelk` and
  **422** for `konclude`; cache keys are reasoner-scoped (two reasoners on the
  same version do not collide).
- A rustdl justify test asserting the returned axioms are a non-empty minimal set
  for a known entailment in the fixture.

## Risks / open items

- **Konclude source build weight** (Qt + custom build). Mitigation above.
- **rustdl completeness is partial** (sound, near-complete, not provably complete
  in general). SP1 surfaces `.complete`/`.timed_out_pairs` in logs; deciding how
  to present "possibly incomplete" to users is an SP3 concern.
- **rustdl justify reloads from a temp file per call** (the binding's `justify`
  takes a path). Acceptable for on-demand justification; revisit if it becomes a
  hotspot.
- **Manchester-string justifications** from rustdl differ from whelk's proof-trace
  structure. SP1 maps them into the `justifications` list only; unifying the
  richer `prove` tree into `proof_traces` is deferred.

## Forward pointers (not SP1)

- **SP2 — app plumbing:** `reasoner` column on the version (Alembic),
  `DEFAULT_REASONER` app config, `POST /api/v1/ontologies` accepts `reasoner`,
  `reason_ontology` task sends it, justification lookup routes by the version's
  reasoner + capability check.
- **SP3 — admin/UI:** reasoner dropdown at add-ontology time (populated from
  `GET /reasoners`), reasoner shown on the ontology detail, explain feature
  enabled/disabled by capability, "possibly incomplete" surfacing.
