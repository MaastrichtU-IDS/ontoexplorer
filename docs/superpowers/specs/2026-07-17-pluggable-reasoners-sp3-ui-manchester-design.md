# Pluggable Reasoners — SP3: Admin/UI + Manchester Unification

**Date:** 2026-07-17
**Status:** Design (approved)
**Depends on:** SP1 (reasoner-service, PR #7) + SP2 (app plumbing, PR #8). Branch `feat/pluggable-reasoners-sp3` off `feat/pluggable-reasoners-sp2`.
**Scope:** The user-facing half of pluggable reasoners — reasoner selection in the add-ontology UI, reasoner display, capability-driven explain, and a **cross-layer unification of justification rendering on horned-owl Manchester syntax**.

## Background

SP1 made the reasoner-service reasoner-aware (`GET /reasoners`, per-request reasoner, `format` on justifications). SP2 made the reasoner a per-ontology property selected at ingest and routed it end-to-end; rustdl justifications already return `format: "manchester"`, whelk/rdflib return `format: "ntriples"` and the app renders them into a typed `⊑/≡` AST.

SP3 finishes the feature for users, and — per the approved design — **unifies all justification rendering on horned-owl's Manchester renderer** so every reasoner's explanations look the same. A feasibility investigation established: py-horned-owl 1.4 cannot emit Manchester (`save_to_string` supports `ofn`/`owx`/`rdf` only), and rustdl's Manchester renderer (`AsManchester`) is internal to `justify`. So unification requires a small new rustdl API.

## Design decisions (approved)

1. **Reasoner selector — advanced disclosure.** The add-ontology form (`frontend/src/pages/Dashboard.tsx`) gets a collapsed "Advanced" section revealing a reasoner `<select>` populated from `GET /reasoners`, defaulting to the app default (whelk). Threaded into all submit modes.
2. **Unify justifications on horned-owl Manchester, server-side.** All reasoners' justifications are returned as `format: "manchester"`. Achieved via a new rustdl API (below); the app's N-Triples→typed-AST render path is retired.
3. **Capability-driven explain.** The per-inference explain control is disabled when the ontology's reasoner lacks the `justify` capability (Konclude), with an explanatory tooltip.
4. **Reasoner shown on the ontology detail** as a plain `Reasoner: <name>` badge (no profile/capability detail there — YAGNI).
5. **rustdl's "possibly incomplete" flag is NOT surfaced** in SP3 (YAGNI; revisit later).
6. Clean up the stale `"Run OWL-EL classification (ELK reasoner)"` tooltip in `admin/OntologyTable.tsx`.

## Architecture (four layers, built in dependency order)

### Layer 1 — rustdl `v0.3.22`
Add `render_manchester(path: str) -> list[str]` to `crates/owl-dl-py` (`explain.rs` or a new `render.rs`): `load::load_path(path)`, map the existing internal `render(ax)` (`ax.as_manchester_with_prefixes(&PrefixMapping::default())`) over the ontology's components/axioms, return the Manchester strings (skip declarations/annotations if noise — return logical axioms). Register in `lib.rs`. Add a Rust unit test + a Python test. Tag `v0.3.22`; the release-python.yml workflow publishes the manylinux wheels to PyPI.

### Layer 2 — reasoner-service
- Bump `rustdl==0.3.22` in `docker/reasoner-service/Dockerfile`.
- In the justification endpoint / whelk+rdflib backends: after computing the N-Triple justification axiom sets, render each set to Manchester via `rustdl.render_manchester` (materialize the set's axioms to a temp `.rdf`, call it), and return `format: "manchester"`. rustdl's own justify path is unchanged (already Manchester). So `POST /classify/{v}/justification` always returns `format: "manchester"`.
- The whelk `Backend.justify` in `registry.py` returns `(sets, "manchester")` after rendering. (rdflib gains justify only if trivial via this path; otherwise it stays non-justify — decide during planning; SP1 had rdflib as non-justify, keep that unless the Manchester path makes it free.)

### Layer 3 — app (ontoexplorer)
- The sync `get_justification` GET endpoint: since the client now always returns `format: "manchester"`, drop the `format`-branching added in SP2 and the N-Triples→AST `_render_justification` path; return the Manchester strings uniformly `{justifications: [[str,...]], format: "manchester", reasoning_available: true, timed_out: ...}`. Keep the `reasoning_available: false` (no-justify) handling. Keep the Oxigraph BFS fallback but return its output as Manchester-ish strings (or plain `sub ⊑ sup` strings) — a last-resort path.
- `_render_justification` (N-Triples→AST) is removed if nothing else uses it (grep first).

### Layer 4 — frontend
- **API client** (`lib/api.ts`): add `reasoners.list() -> ReasonerInfo[]` (`GET /reasoners`); add an optional `reasoner` arg to `submitByIri/Url/File/Content`; change `JustificationResult` to carry `justifications: string[][]` + `format: "manchester"` + `reasoning_available: boolean` (replacing the `JustificationAxiom[][]` AST type).
- **Add-ontology** (`Dashboard.tsx`): Advanced disclosure + reasoner `<select>` (options from `reasoners.list()`, default = app default; the endpoint validates too). Pass the chosen reasoner into the submit call.
- **Explain UI** (`components/TermPanel.tsx`): `JustificationDisplay` renders each justification as a list of Manchester axiom strings (monospace; shorten IRIs to labels where the label map is already available). The "inference" button is disabled when the ontology's reasoner (known from the ontology/version data + `reasoners.list()` capabilities) lacks `justify`, with a tooltip ("Konclude does not produce explanations").
- **Ontology detail** (`OntologyPage.tsx`): `Reasoner: <name>` badge (reasoner comes from the version data — SP2 exposes it on the version; confirm the version API serializes `reasoner`, add it if missing).
- Remove the stale ELK tooltip in `admin/OntologyTable.tsx`.

## Data flow

```
Add ontology: Dashboard advanced <select> (reasoners.list) → submitBy*(…, reasoner)
              → POST /api/v1/ontologies {reasoner} (SP2 validates+persists)
Explain:      TermPanel inference button (enabled iff version.reasoner has justify cap)
              → GET /ontologies/{o}/{v}/justification
              → app → reasoner-service (renders via rustdl.render_manchester)
              → {format:"manchester", justifications:[[str,…]]}
              → JustificationDisplay renders strings
Detail:       OntologyPage badge ← version.reasoner
```

## Non-goals (SP3)

- No typed re-parse of Manchester into an interactive AST (strings are displayed as-is).
- No "possibly incomplete" surfacing; no re-classify-with-different-reasoner UI.
- No changes to classification/term-inference display (SP2 already routes those).

## Testing

- **rustdl:** Rust unit test that `render_manchester` on a small ontology returns the expected Manchester axiom strings; Python test via the built wheel.
- **reasoner-service:** whelk justification now returns `format: "manchester"` with real Manchester strings for a fixture entailment (needs the engine — validate in-container as SP1 did); registry/contract tests updated for the uniform format.
- **app:** `get_justification` returns `format: "manchester"` for whelk and rustdl versions; no-justify (konclude) still `reasoning_available: false`; `_render_justification` removal doesn't break imports.
- **frontend:** `Dashboard` shows the reasoner select under Advanced and passes it to submit (RTL test mocking the api client); `JustificationDisplay` renders Manchester strings; the explain button is disabled for a no-justify reasoner; `OntologyPage` shows the reasoner badge. Follow the repo's existing Vitest/RTL patterns (`*.test.tsx`).

## Risks / open items

- **rustdl `v0.3.22` release + wheel availability.** Layer 2 can't proceed until the wheel is on PyPI (the release workflow runs on the tag). Mitigation: build the wheel locally for the image if PyPI lag is an issue (as SP1 did before the tag existed), but prefer the published wheel.
- **`render_manchester` axiom selection.** Rendering ALL components (incl. declarations/annotations) would be noisy; render logical axioms only. Confirm which `Component` variants to include during Layer 1.
- **Whelk justification → temp-file round-trip per request** (NT set → `.rdf` → `render_manchester`). Acceptable for on-demand justification; matches rustdl's own justify file round-trip.
- **Frontend type change** (`JustificationAxiom[][]` → `string[][]`) touches any other consumer of `JustificationResult` — grep the frontend before changing the type.
- **Version API exposing `reasoner`.** The detail badge needs the version's `reasoner` in the API response; if SP2 didn't add it to the serializer, SP3 does.

## Forward pointer

This completes the pluggable-reasoners feature (SP1 engine + SP2 app + SP3 UI/Manchester). Future ideas (not planned): typed interactive Manchester, per-inference reasoner comparison, rustdl `diagnose`/`repair` surfaced in the UI.
