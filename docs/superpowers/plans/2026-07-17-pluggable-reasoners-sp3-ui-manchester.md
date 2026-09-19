# Pluggable Reasoners — SP3 (Admin/UI + Manchester Unification) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish pluggable reasoners for users — reasoner selection in the add-ontology UI, capability-driven explain, a reasoner badge — and unify all justification rendering on horned-owl Manchester syntax via a new rustdl `render_manchester` API.

**Architecture:** Four layers built in dependency order. rustdl `v0.3.22` exposes `render_manchester(path)`; the reasoner-service routes whelk/rdflib N-Triple justifications through it so every justification response is `format:"manchester"`; the app stops rendering the typed AST and passes Manchester strings through; the frontend adds the reasoner selector, renders Manchester strings, disables explain for no-justify reasoners, and shows a reasoner badge.

**Tech Stack:** Rust + PyO3/maturin (rustdl), Python/FastAPI (reasoner-service, app), React/TypeScript + Vitest/RTL (frontend), Docker.

## Global Constraints

- Branch `feat/pluggable-reasoners-sp3` off `feat/pluggable-reasoners-sp2` (SP2). rustdl work happens in the separate repo `~/code/rustdl` (remote MaastrichtU-IDS/rustdl).
- Reasoner names: whelk, rdflib, rustdl, konclude; app default whelk.
- Every justification response after this work has `format: "manchester"`; a no-justify reasoner (Konclude) yields `reasoning_available: false` (never a 500).
- Non-standard env: `python` not on PATH, `uv run` fails. Python tests: `/Users/micheldumontier/code/ontoexplorer/.venv/bin/python -m pytest`. reasoner-service in-container validation via `docker compose exec -T reasoner-service`. Frontend tests: from `frontend/`, use the repo's configured runner (check `frontend/package.json` — likely `npm run test` / `vitest`); if node deps aren't installed, `npm ci` in `frontend/` first.
- Commits use `git -c user.email=admin@example.org` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. (rustdl repo commits use the same identity.)
- rustdl release: tag `v0.3.22`; the `release-python.yml` workflow publishes manylinux wheels to PyPI on the tag. Layer 2 must not proceed until the `v0.3.22` wheel is installable (`pip index versions rustdl` shows it) OR a locally-built linux wheel is vendored as an interim.

---

## File Structure
- rustdl: `crates/owl-dl-py/src/explain.rs` (add `render_manchester` + register), a Rust test, `crates/owl-dl-py/python/rustdl/__init__.pyi` (type stub), CHANGELOG/version bump.
- `docker/reasoner-service/Dockerfile` (rustdl==0.3.22), `docker/reasoner-service/registry.py` (whelk justify → Manchester), `docker/reasoner-service/main.py` (uniform format), tests.
- `ontoexplorer/api/ontologies.py` (get_justification uniform Manchester; version serializer exposes `reasoner`), remove/trim `_render_justification`.
- `frontend/src/lib/api.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/TermPanel.tsx`, `frontend/src/pages/OntologyPage.tsx`, `frontend/src/components/admin/OntologyTable.tsx`, plus `*.test.tsx`.

---

## Task 1: rustdl `render_manchester` + v0.3.22 release  (repo: ~/code/rustdl)

**Files:**
- Modify: `crates/owl-dl-py/src/explain.rs`, `crates/owl-dl-py/python/rustdl/__init__.pyi`, `CHANGELOG.md`
- Test: a Rust `#[test]` in explain.rs (or tests/), and a Python test under the rustdl repo's python tests

**Interfaces:**
- Produces: `rustdl.render_manchester(path: str) -> list[str]` — each logical axiom of the ontology at `path` as a Manchester string.

- [ ] **Step 1: Write the Rust unit test (RED)**

In `crates/owl-dl-py/src/explain.rs` (or the crate's test module), add a test that loads a tiny ontology fixture (A⊑B, B⊑C) and asserts `render_manchester` returns Manchester strings containing the subclass axioms. Use the existing test fixtures pattern in the crate (grep `#[cfg(test)]` in owl-dl-py/owl-dl-reasoner for the load helper).

- [ ] **Step 2: Run it → fails (function absent)**

Run: `cd ~/code/rustdl && RUSTUP_TOOLCHAIN=1.96.0 cargo test -p owl-dl-py render_manchester 2>&1 | tail`
Expected: compile error / no such fn. (This repo pins toolchain 1.95.0 which lacks cargo locally; override to 1.96.0 as established.)

- [ ] **Step 3: Implement `render_manchester`**

In `crates/owl-dl-py/src/explain.rs`, add (reusing the existing private `render` and imports `use horned_owl::io::omn::AsManchester;`, `PrefixMapping`, `load`):

```rust
/// Every logical axiom of the ontology at `path`, rendered as Manchester
/// syntax strings (declarations, imports, and ontology annotations are
/// skipped as non-logical noise). Same renderer `justify` uses.
#[pyfunction]
pub(crate) fn render_manchester(path: &str) -> PyResult<Vec<String>> {
    let onto = load::load_path(path)?;
    let pm = PrefixMapping::default();
    Ok(onto
        .iter()
        .map(|ac| &ac.component)
        .filter(|c| is_logical_axiom(c))
        .map(|c| c.as_manchester_with_prefixes(&pm).to_string())
        .collect())
}

fn is_logical_axiom(c: &horned_owl::model::Component<RcStr>) -> bool {
    use horned_owl::model::Component::*;
    // Exclude declarations, imports, and ontology-level annotations; keep the
    // class/property/individual axioms that carry entailment meaning.
    !matches!(
        c,
        OntologyID(_) | DocIRI(_) | Import(_) | OntologyAnnotation(_)
            | DeclareClass(_) | DeclareObjectProperty(_) | DeclareAnnotationProperty(_)
            | DeclareDataProperty(_) | DeclareNamedIndividual(_) | DeclareDatatype(_)
            | AnnotationAssertion(_)
    )
}
```

(Confirm the exact `Component` variant names against the horned-owl version in `Cargo.lock` — the match arms must compile. If a variant name differs, adjust. `RcStr` is already imported in explain.rs.)

Register it in `crates/owl-dl-py/src/explain.rs`'s `register(...)` alongside `justify`/`justify_all`/`diagnose`/`repair`:
```rust
    m.add_function(wrap_pyfunction!(render_manchester, m)?)?;
```

- [ ] **Step 4: Run the Rust test → passes**

Run: `cd ~/code/rustdl && RUSTUP_TOOLCHAIN=1.96.0 cargo test -p owl-dl-py render_manchester 2>&1 | tail`
Expected: PASS.

- [ ] **Step 5: Update the type stub + CHANGELOG + version**

Add to `crates/owl-dl-py/python/rustdl/__init__.pyi`:
```python
def render_manchester(path: str) -> list[str]:
    """Every logical axiom of the ontology at `path` as Manchester strings."""
    ...
```
Add a `CHANGELOG.md` entry for `0.3.22` (new `render_manchester`). The workspace version is set via `version.workspace`; bump the workspace `version` in the root `Cargo.toml` to `0.3.22`.

- [ ] **Step 6: Build the wheel locally + Python smoke test**

```bash
cd ~/code/rustdl
RUSTUP_TOOLCHAIN=1.96.0 /Users/micheldumontier/code/ontoexplorer/.venv/bin/maturin build --release -m crates/owl-dl-py/Cargo.toml --out /tmp/rustdl-wheels
/Users/micheldumontier/code/ontoexplorer/.venv/bin/python -m pip install --force-reinstall /tmp/rustdl-wheels/rustdl-0.3.22-*.whl 2>/dev/null || \
  /Users/micheldumontier/code/ontoexplorer/.venv/bin/python -m pip install --force-reinstall /tmp/rustdl-wheels/rustdl-0.3.22-*.whl
```
Then smoke-test: write A⊑B⊑C to a temp `.rdf` (RDF/XML) and assert `rustdl.render_manchester(path)` returns non-empty Manchester strings mentioning A/B/C. (`pip` may be absent in the venv — if so use `uv pip install --force-reinstall`.)

- [ ] **Step 7: Commit + tag + push (rustdl repo)**

```bash
cd ~/code/rustdl
git add -A
git -c user.email=admin@example.org commit -m "feat(py): render_manchester — render an ontology's axioms as Manchester

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git tag v0.3.22
git push origin HEAD --tags
```
Then wait for the `release-python.yml` GitHub Action to publish the `v0.3.22` manylinux wheels to PyPI (check: `curl -s https://pypi.org/pypi/rustdl/0.3.22/json | python3 -c 'import sys,json;print([f["filename"] for f in json.load(sys.stdin)["urls"]])'` shows a `manylinux_2_17_x86_64` wheel). If the Action lags, Layer 2 can use the locally-built wheel as an interim (vendor it in the image build context) — note this in the report.

---

## Task 2: reasoner-service renders whelk/rdflib justifications to Manchester

**Files:**
- Modify: `docker/reasoner-service/Dockerfile` (rustdl==0.3.22), `docker/reasoner-service/registry.py` (whelk `justify`), possibly `docker/reasoner-service/main.py`
- Test: `docker/reasoner-service/test_manchester_justification.py`

**Interfaces:**
- Consumes: `rustdl.render_manchester` (Task 1).
- Produces: `_WhelkBackend.justify(...)` returns `(list_of_manchester_axiom_sets, "manchester")`; `POST /classify/{v}/justification` always returns `format:"manchester"`.

- [ ] **Step 1: Bump rustdl in the Dockerfile**

In `docker/reasoner-service/Dockerfile`, change `"rustdl==0.3.21"` → `"rustdl==0.3.22"`.

- [ ] **Step 2: Write the test (RED)**

Create `docker/reasoner-service/test_manchester_justification.py` — skips unless `pywhelk`/`rustdl` importable (they're absent on the mac host; this validates in-container). Fixture A⊑B⊑C, call `registry.get_backend("whelk").justify(nt, A, C, 1)`; assert the returned tuple's format is `"manchester"` and the axiom set is non-empty Manchester strings (contain "SubClassOf" or the class names, not N-Triple `<...>` angle-bracket triples).

- [ ] **Step 3: Implement whelk→Manchester in `registry.py`**

In `_WhelkBackend.justify` (which currently classifies then calls `compute_justifications` returning N-Triple axiom sets and returns `(sets, "ntriples")`), after getting the N-Triple `sets`, render each set to Manchester via rustdl:

```python
    def justify(self, ntriples, sub, sup, max_justifications):
        import io, os, tempfile
        import pyoxigraph, rustdl
        from justification import compute_justifications
        result = self.classify_ntriples(ntriples, "_justify")
        g = rdflib.Graph(); g.parse(io.StringIO(ntriples), format="nt")
        nt_sets = compute_justifications(g, result, sub, sup, max_justifications)
        manchester_sets = []
        for nt_axioms in nt_sets:
            # Each nt_axioms is a list of N-Triple axiom strings; materialise
            # to RDF/XML and render via rustdl's horned-owl Manchester renderer.
            store = pyoxigraph.Store()
            store.bulk_load(io.BytesIO("\n".join(nt_axioms).encode()),
                            format=pyoxigraph.RdfFormat.N_TRIPLES)
            rdfxml = pyoxigraph.serialize(
                (q.triple for q in store.quads_for_pattern(None, None, None, None)),
                format=pyoxigraph.RdfFormat.RDF_XML)
            fd, path = tempfile.mkstemp(suffix=".rdf")
            try:
                with os.fdopen(fd, "wb") as fh: fh.write(rdfxml)
                manchester_sets.append(rustdl.render_manchester(path))
            finally:
                os.unlink(path)
        return manchester_sets, "manchester"
```

Update `_WhelkBackend.info.capabilities` unchanged (still has `justify`). If `compute_justifications` returns axiom sets that don't round-trip cleanly through pyoxigraph (e.g. blank nodes), fall back to returning the N-Triple set for that entry with a logged warning — but prefer Manchester.

- [ ] **Step 4: Build the image + in-container validation (GREEN)**

```bash
cd ~/code/ontoexplorer && docker compose build reasoner-service && docker compose up -d reasoner-service && sleep 8
```
Then POST a fresh classify for a small A⊑B⊑C with `reasoner=whelk`, then POST its justification (sub=A, sup=C) and assert the response `format` is `"manchester"` and `justifications` are Manchester strings. Also re-confirm rustdl justification still returns `manchester`. (Use a Python smoke script hitting `http://localhost:8001` as SP1 did.)

- [ ] **Step 5: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/Dockerfile docker/reasoner-service/registry.py docker/reasoner-service/test_manchester_justification.py
git -c user.email=admin@example.org commit -m "feat(reasoner-service): render whelk/rdflib justifications to Manchester via rustdl

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: app returns uniform Manchester + version exposes reasoner

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` (`get_justification`; version serializer)
- Test: `tests/test_justification_uniform_manchester.py`, extend a version-serialization test

**Interfaces:**
- Produces: `GET /ontologies/{o}/{v}/justification` returns `{justifications: [[str,...]], format:"manchester", reasoning_available: true, timed_out}` for whelk AND rustdl; no-justify → `reasoning_available:false`. Version API responses include `reasoner`.

- [ ] **Step 1: Write the tests (RED)**

Create `tests/test_justification_uniform_manchester.py` — using the conftest `client` + inline version creation (mirror SP2's tests): a whelk version and a rustdl version both return `format:"manchester"` (mock `elk_request_justification` to return manchester payloads for each); a konclude version returns `reasoning_available:false`. Also add/extend a test asserting the version serialization (whatever endpoint returns version detail — grep for the version response model) includes `reasoner`.

- [ ] **Step 2: Run → fails**

Run: `.venv/bin/python -m pytest tests/test_justification_uniform_manchester.py -q` → FAIL.

- [ ] **Step 3: Simplify `get_justification` to uniform Manchester**

In `ontoexplorer/api/ontologies.py` `get_justification`: keep the version load + `reasoner=version.reasoner` pass-through (SP2). Since the client now always returns `format:"manchester"`, replace the SP2 format-branching + the N-Triples→AST render loop with a single passthrough: if `reasoning_available is False` → return that; else return `{"justifications": elk_result.get("justifications", []), "format": "manchester", "timed_out": bool(elk_result.get("timed_out")), "reasoning_available": True}`. Keep the Oxigraph BFS fallback ONLY for the empty-result case, returning its edges as plain `"<sub> SubClassOf <sup>"`-style strings (a `_bfs_as_manchester` tiny helper) so the shape stays `string[][]`.

- [ ] **Step 4: Remove the now-dead `_render_justification`**

Grep `_render_justification` across the repo; if only `get_justification` used it, delete the function (and unused imports it pulled). If other code uses it, leave it.

- [ ] **Step 5: Expose `reasoner` on the version serializer**

Find the version response model/serialization (grep the version detail endpoint + any Pydantic `VersionOut`/dict build in `api/ontologies.py`); add `reasoner` to it (`version.reasoner`).

- [ ] **Step 6: Run tests → pass**

Run: `.venv/bin/python -m pytest tests/test_justification_uniform_manchester.py -q` → PASS. Then broader: `.venv/bin/python -m pytest tests/ -q -k "justif or version or ontolog"` → report new vs pre-existing failures.

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/api/ontologies.py tests/test_justification_uniform_manchester.py
git -c user.email=admin@example.org commit -m "feat(app): uniform Manchester justifications; expose reasoner on version

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: frontend API client — reasoners list, reasoner on submit, Manchester result type

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts` (if the repo tests the client; else covered via component tests)

**Interfaces:**
- Produces: `api.reasoners.list(): Promise<ReasonerInfo[]>`; `submitByIri(iri, reasoner?)`, `submitByUrl(url, reasoner?)`, `submitFile(file, reasoner?)`, `submitByContent(content, format?, reasoner?)`; `JustificationResult { justifications: string[][]; format: string; reasoning_available: boolean; timed_out: boolean }`; `interface ReasonerInfo { name: string; profile: string; capabilities: string[]; available: boolean }`.

- [ ] **Step 1: Change the types**

In `frontend/src/lib/api.ts`: replace `JustificationResult.justifications: JustificationAxiom[][]` with `justifications: string[][]` and add `format: string`. Add `export interface ReasonerInfo { name: string; profile: string; capabilities: string[]; available: boolean }`. (Leave `JustificationAxiom`/`ClassExprNode` types if other code references them; grep first — if now unused, remove.)

- [ ] **Step 2: Add reasoners.list + reasoner on submit**

Add a `reasoners` client group: `list: () => request<ReasonerInfo[]>('/reasoners')` — NOTE: `GET /reasoners` is a reasoner-service route, but the app proxies reasoning via its own API; confirm whether the app exposes `/reasoners` (SP2/SP3 may need an app passthrough endpoint). If the app has no `/reasoners`, add a tiny app GET `/api/v1/reasoners` that calls `reasoning.list_reasoners()` (SP2 helper) — do this in Task 3's file if missing, and here just consume it. Thread `reasoner` into the submit bodies: `submitByIri: (iri, reasoner?) => ... body: JSON.stringify({ iri, ...(reasoner ? {reasoner} : {}) })` (same for url/content; for `submitFile`, `fd.append('reasoner', reasoner)` when provided).

- [ ] **Step 3: Build/type-check → passes**

Run: `cd frontend && npm run build 2>&1 | tail` (or `npx tsc --noEmit`). Expected: no type errors. Fix any consumer broken by the `JustificationResult` type change (Task 6 handles TermPanel; here just make the client compile).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git -c user.email=admin@example.org commit -m "feat(ui): api client — reasoners.list, reasoner on submit, Manchester result type

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(If Step 2 revealed the app lacks `/api/v1/reasoners`, add that endpoint in `ontoexplorer/api/ontologies.py` — `@router.get("/reasoners")` returning `await reasoning.list_reasoners()` — and a test; fold into Task 3's commit or a small dedicated commit.)

---

## Task 5: Add-ontology reasoner selector (Advanced disclosure)

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/pages/Dashboard.test.tsx`

**Interfaces:**
- Consumes: `api.reasoners.list()`, the `reasoner`-accepting submit fns (Task 4).

- [ ] **Step 1: Write the RTL test (RED)**

In `Dashboard.test.tsx` (mock the api client): the form has a collapsed "Advanced" control; expanding it shows a reasoner `<select>` whose options come from a mocked `reasoners.list()`; submitting with a chosen reasoner (e.g. `rustdl`) calls `submitByIri` with `rustdl`; default (unexpanded) submit calls it with no reasoner (or the app default). Mirror existing `Dashboard.test.tsx` patterns.

- [ ] **Step 2: Run → fails**

Run: `cd frontend && npm run test -- Dashboard 2>&1 | tail` → FAIL.

- [ ] **Step 3: Implement the disclosure + select**

In `Dashboard.tsx`: add state `const [showAdvanced, setShowAdvanced] = useState(false)` and `const [reasoner, setReasoner] = useState<string | undefined>()`; fetch `reasoners.list()` (React Query or effect) filtered to `available`; render an "Advanced" toggle that reveals a labeled `<select>` (default option = "(default)"/unset). Pass `reasoner` into each submit call. Keep the existing submit UX otherwise unchanged.

- [ ] **Step 4: Run → passes**

Run: `cd frontend && npm run test -- Dashboard 2>&1 | tail` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.test.tsx
git -c user.email=admin@example.org commit -m "feat(ui): reasoner selector under Advanced on add-ontology

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Explain UI — render Manchester + capability-driven disable

**Files:**
- Modify: `frontend/src/components/TermPanel.tsx`
- Test: `frontend/src/components/TermPanel.test.tsx` (create if absent)

**Interfaces:**
- Consumes: `JustificationResult` (now `string[][]` + `format`, Task 4); the version's `reasoner` + `api.reasoners.list()` capabilities.

- [ ] **Step 1: Write the RTL test (RED)**

Test `JustificationDisplay` (or TermPanel): given a `JustificationResult` with `justifications: [["A SubClassOf B", "B SubClassOf C"]]`, it renders those strings (monospace list). Given the ontology's reasoner is `konclude` (no `justify` capability), the "inference" button is rendered disabled with a tooltip. Given `whelk`/`rustdl`, it's enabled.

- [ ] **Step 2: Run → fails**

Run: `cd frontend && npm run test -- TermPanel 2>&1 | tail` → FAIL.

- [ ] **Step 3: Implement**

In `TermPanel.tsx`: replace `JustificationDisplay`'s AST rendering (it currently maps `JustificationAxiom` → `ExprNode` with `⊑/≡/⊥`) with rendering each justification as a list of its Manchester strings (`<code>`/monospace, one per line; optionally shorten known IRIs via the existing label map). Determine the reasoner's justify capability: the component knows the ontology/version; get `version.reasoner` and look it up in `reasoners.list()` capabilities (pass caps in as a prop or fetch). Disable the "inference" toggle button (and show a `title` tooltip "This reasoner does not produce explanations") when `justify` is not in the reasoner's capabilities. Remove now-unused `ExprNode`/AST rendering code if nothing else uses it.

- [ ] **Step 4: Run → passes**

Run: `cd frontend && npm run test -- TermPanel 2>&1 | tail` → PASS. Then `cd frontend && npm run build` to confirm no type errors from the `JustificationResult` change.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TermPanel.tsx frontend/src/components/TermPanel.test.tsx
git -c user.email=admin@example.org commit -m "feat(ui): render Manchester justifications; disable explain for no-justify reasoners

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Reasoner badge on detail + stale-tooltip cleanup

**Files:**
- Modify: `frontend/src/pages/OntologyPage.tsx`, `frontend/src/components/admin/OntologyTable.tsx`
- Test: `frontend/src/pages/OntologyPage.test.tsx` (extend if present)

**Interfaces:**
- Consumes: the version's `reasoner` field (Task 3 exposes it).

- [ ] **Step 1: Write/extend the RTL test (RED)**

`OntologyPage.test.tsx`: given version data with `reasoner: "rustdl"`, the page shows a "Reasoner: rustdl" badge. Mock the api as the existing test does.

- [ ] **Step 2: Run → fails**

Run: `cd frontend && npm run test -- OntologyPage 2>&1 | tail` → FAIL.

- [ ] **Step 3: Implement the badge + cleanup**

In `OntologyPage.tsx`: render a small badge `Reasoner: {version.reasoner}` near the version metadata (match existing badge styling). In `frontend/src/components/admin/OntologyTable.tsx:251`: change the stale `title="Run OWL-EL classification (ELK reasoner)"` to `title="Run classification"` (or "Run reasoning").

- [ ] **Step 4: Run → passes**

Run: `cd frontend && npm run test -- OntologyPage 2>&1 | tail` → PASS. Then `cd frontend && npm run build` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OntologyPage.tsx frontend/src/pages/OntologyPage.test.tsx frontend/src/components/admin/OntologyTable.tsx
git -c user.email=admin@example.org commit -m "feat(ui): reasoner badge on ontology detail; drop stale ELK tooltip

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** rustdl render_manchester + v0.3.22 → T1; reasoner-service Manchester unification → T2; app uniform Manchester + retire typed AST + version.reasoner → T3; api client (reasoners.list, reasoner on submit, Manchester type) → T4; add-ontology Advanced selector → T5; Manchester render + capability-driven explain → T6; reasoner badge + stale tooltip → T7. All spec sections covered.

**Placeholder scan:** No TBD/TODO. Real codebase-lookups flagged in-step (not placeholders): exact horned-owl `Component` variant names (T1 — must compile against Cargo.lock); whether the app already exposes `/reasoners` (T4 — add if missing); the version serializer location (T3); frontend test runner command (Global Constraints — check package.json). Each names the lookup + fallback.

**Type consistency:** `render_manchester(path) -> list[str]` used identically T1→T2. `JustificationResult.justifications: string[][]` + `format` consistent T3 (producer) → T4 (type) → T6 (consumer). `ReasonerInfo {name, profile, capabilities, available}` consistent T4→T5→T6. Reasoner passed as an optional trailing arg on submit fns T4→T5.

**Cross-repo note:** T1 is in `~/code/rustdl` (separate repo/remote); T2 depends on its published (or locally-built) `v0.3.22` wheel — the hard ordering dependency in this plan. T2–T7 are in the ontoexplorer repo on `feat/pluggable-reasoners-sp3`.
