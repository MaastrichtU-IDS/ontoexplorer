# SPARQL Page — Cross-Version Diff Query Mode

## Context

Sub-project F of six in the SPARQL-page improvement plan. Sub-projects A (scope toolbar), C (IRI autocomplete + prefix autoload), D (starter query library), and E (result enrichment) have shipped.

This sub-project adds an on-demand, query-driven version comparison. The user writes an arbitrary SPARQL SELECT query and runs it against two graph endpoints (typically two versions of the same ontology). The frontend computes a row-level set diff over the result tuples and presents a unified table with status badges per row.

The existing precomputed *structural* diff (entities/axioms via the `compute_diff` Celery task and the Compare page on `/ontologies?tab=compare`) is unchanged and complementary — this feature is exploratory ("which classes added in V2 have `rdfs:subClassOf SomePizza`?"), the existing one is comprehensive ("what changed structurally").

Frontend-only. No backend changes.

## Goal

Let users:

1. Toggle the SPARQL page into "Diff" mode.
2. Pick two (ontology, version, reasoning mode) tuples — `From` and `To`.
3. Write a SPARQL SELECT query in the editor as usual.
4. Click Run.
5. See a unified table with one extra column: a `Only From` / `Only To` / `Both` status badge per row. Filter pills above the table narrow to each subset.

Common UX: pick the same ontology on both sides with different versions to compare version-over-version. Less common but supported: different ontologies, or same version on both sides with different reasoning modes ("what does inference add?").

## Approach

### Mode toggle on the scope toolbar

The existing toolbar grows a `Single ↔ Diff` segmented control. In Single mode (default) it behaves exactly as today.

In Diff mode the chip strip is hidden and replaced by two graph-picker rows:

```
Scope: [ Single | Diff ]
   From: [ ontology ▾ ] [ version ▾ ] [ Asserted | Inferred | Both ]
   To:   [ ontology ▾ ] [ version ▾ ] [ Asserted | Inferred | Both ]
```

The ontology dropdown is the same data source as the existing Single-mode picker (filtered to `latest_version.status` ∉ `{pending, failed, deprecated}`). The version dropdown shows `/api/v1/ontologies/{id}/versions` sorted newest-first.

**Default selection.** When entering Diff mode for the first time:
- If at least one ontology is currently in Single-mode scope, both pickers preset to that ontology. `To` selects the newest version; `From` selects the second-newest (or remains empty if there's only one version).
- If no ontology is in scope yet, both pickers start empty.

Default reasoning mode for both sides: `Asserted`.

The toolbar emits a new optional callback `onDiffScopeChange(scope: DiffScope | null)`:

```ts
interface DiffScope {
  from: { version: OntologyVersion; mode: ReasoningMode }
  to:   { version: OntologyVersion; mode: ReasoningMode }
}
```

The toolbar carries the full `OntologyVersion` object (not just an id) because the page-level diff orchestrator needs both `id` and `ontology_id` to build the scoped endpoint URL via `endpointForVersion(version, mode)`. The toolbar already fetched the version list in order to populate its dropdowns, so it has the full objects in hand.

`null` is emitted whenever the toolbar exits Diff mode or the selection is incomplete. The page treats `null` as "no diff possible".

### Query execution intercept

`Sparql.tsx` subscribes to Yasqe's `query` event:

```ts
yasqe.on('query', (req, _config) => {
  if (diffScopeRef.current) {
    req.abort()
    void runDiffQuery(yasqe.getValue(), diffScopeRef.current)
  }
})
```

`req.abort()` cancels the default single-graph Yasr render path. `runDiffQuery` fires two parallel `fetch()` calls against `/api/v1/sparql/content`, each scoped via `default-graph-uri` + `named-graph-uri` URL parameters built from the side's `(versionId, mode)` using the existing `buildScopedEndpoint` helper (sub-project A) — generalised to take a version id directly rather than going through the toolbar's `Set<string>` selection.

Both fetches use `application/x-www-form-urlencoded` body with `query=<encoded>`, matching the SPARQL Protocol. `Accept: application/sparql-results+json` so the response is always JSON bindings.

The two responses are passed to `DiffQueryView` as `{ from: bindings[], to: bindings[] }`. The native Yasr result pane is hidden via inline `display: none` while in Diff mode.

### Diff semantics

Row identity = JSON-canonical tuple of all bindings, where each binding value is serialised as `{ type, value, lang?, datatype? }` (the same shape SPARQL Protocol returns). The variable names are sorted alphabetically so column-order doesn't affect identity.

Set operations:
- `onlyFrom = fromRows \ toRows`
- `onlyTo   = toRows \ fromRows`
- `both     = fromRows ∩ toRows`

`Both` rows preserve the From-side ordering (so the user sees them as they appeared in the From-side query result). `Only From` / `Only To` preserve their side's order.

### UI — `DiffQueryView`

A new unified table component:

| Status | var1 | var2 | … |
|---|---|---|---|
| Only From | … | … | … |
| Both | … | … | … |
| Only To | … | … | … |

Status column has coloured badges: green-ish for `Only To` (additions), red-ish for `Only From` (removals), grey for `Both`.

**Above the table** — filter pills with counts:

```
[ All (1234) ] [ Only From (45) ] [ Only To (67) ] [ Both (1122) ]
```

Click a pill to filter; default is `All` with the changes (`Only From` + `Only To`) sorted to the top.

**Sortable columns** — click any column header to sort. Status is the default sort key.

**Clickable IRIs** — cells with IRI values render as `<a class="iri" href="<iri>">…</a>` so the existing `installIriClickHandler` (sub-project E) handles in-app navigation. The label-enrichment toggle (also sub-project E) also still works because it walks `a.iri` elements in the result pane.

### Edge cases

| Case | Behaviour |
|---|---|
| Non-SELECT query (ASK/CONSTRUCT/DESCRIBE) | Detect via response Accept-mismatch or the absence of `head.vars`. Show banner: "Diff mode supports SELECT queries only." Hide DiffQueryView. Re-show Yasr native pane with whatever the From side returned. |
| One side errors (4xx/5xx, timeout, network) | The other side's rows render with the appropriate `Only From` or `Only To` badge. Banner shows the failing side's error. |
| Both sides error | Banner with both messages; empty table. |
| Both sides return zero rows | Empty table with "No results on either side." |
| Result variables differ between sides (rare; e.g. OPTIONAL resolution differs) | Use the union of variable names. Missing values render as `—`. Diff still works on the canonical tuple (missing binding ≠ explicit binding). |
| Both sides return >5000 rows | No cap; rendering uses memoised row computation. Stutters above ~10k. Document as a future polish issue. |
| User toggles back to Single mode while a diff render is on screen | DiffQueryView unmounts; Yasr native pane re-shown; diff state dropped. |
| User edits query while diff is rendered | Stale diff stays visible until next Run; no auto-rerun. |
| User cancels mid-run | `AbortController` cancels both in-flight fetches. |
| `From` and `To` are exactly the same `(versionId, mode)` | Toolbar allows it (no validation); the diff will be all `Both`. We don't block — it's a useful sanity-check workflow. |
| Default starter query is loaded | Works fine; it's a SELECT. |
| User picks a `?q=savedQueryId` URL | Saved query loads into editor as today; if user enters Diff mode and Runs, diff fires. |

### Files

| Path | Role |
|---|---|
| `frontend/src/components/sparql/diffBindings.ts` | Pure helpers: `canonicalRow(row)`, `diffBindings(from, to)` returning `{ onlyFrom, onlyTo, both, vars }`. |
| `frontend/src/components/sparql/diffBindings.test.ts` | Unit tests. |
| `frontend/src/components/sparql/DiffQueryView.tsx` | The unified-table component (filter pills, sort, status badges, error banner). |
| `frontend/src/components/sparql/DiffQueryView.test.tsx` | Component tests. |
| `frontend/src/components/sparql/ScopeToolbar.tsx` | Add `mode: 'single' \| 'diff'` state, diff pickers, `onDiffScopeChange` callback. |
| `frontend/src/components/sparql/ScopeToolbar.test.tsx` | New tests for the diff-mode UI. |
| `frontend/src/pages/Sparql.tsx` | Subscribe to `yasqe.on('query', ...)`, run two fetches in Diff mode, mount `DiffQueryView`, hide Yasr native pane via `display: none`. |
| `frontend/src/pages/Sparql.test.tsx` | One integration test: Diff mode + Run → two fetches → diff renders. |

`buildScopedEndpoint` from sub-project A is generalised slightly: a new export `endpointForGraphTuple(versionId, mode, ontologies): string` builds the URL with `default-graph-uri` + `named-graph-uri` params for a single `(versionId, mode)` pair (deriving the ontology id from the version via the ontologies list). This avoids duplicating URL-construction logic in `Sparql.tsx`.

### Backend

**No changes.**

## Testing

**Pure helpers (`diffBindings.test.ts`):**
- `canonicalRow` produces a stable string for the same binding regardless of variable insertion order in the source object.
- `canonicalRow` distinguishes URI vs literal vs blank-node with the same `value`.
- `canonicalRow` includes `lang` and `datatype` so `"foo"@en` ≠ `"foo"@de`.
- `diffBindings` over identical sides yields all `Both`.
- `diffBindings` over disjoint sides yields all-`Only From` + all-`Only To`.
- `diffBindings` over overlapping sides yields correct partition; counts match cardinality of each set.
- `diffBindings` preserves From-side order for `Both`.
- `diffBindings` returns the union of variable names in `vars`.

**Component (`DiffQueryView.test.tsx`):**
- Renders the unified table with status badges.
- Filter pills narrow correctly; counts shown.
- Sorting by a column header works.
- Banner shown when one side errored.
- "Diff mode supports SELECT queries only" banner shown when one side returned a non-bindings shape.

**Toolbar (`ScopeToolbar.test.tsx`):**
- `Single ↔ Diff` toggle is present.
- In Diff mode, both graph-picker rows render.
- Picking versions + modes fires `onDiffScopeChange` with the expected `DiffScope`.
- Toggling back to Single fires `onDiffScopeChange(null)`.
- Default version selection populates correctly when entering Diff mode with an existing scope.

**Integration (`Sparql.test.tsx`):**
- Mount, switch to Diff mode, select versions, simulate Yasqe `query` event → assert two `fetch` calls were made with the right URLs.
- Mocked responses → assert `DiffQueryView` shows the expected rows with badges.

## Out of scope

- Diffing CONSTRUCT/DESCRIBE result graphs (RDF-level diff is a different problem; see the existing Compare page).
- Diffing ASK booleans (just two booleans — could add later but trivial).
- Three-way diff (A vs B vs C).
- Side caching across re-runs (`React Query` keys could fix this in a polish round).
- Persisting diff results into saved queries.
- Cell-level visual diff within `Both` rows.
- Diff over per-row inferred-vs-asserted within the same version *automatically* (the user can achieve it by picking the same version on both sides with different modes).
- Server-side diff endpoint (kept in frontend for v1 — no backend change).

## Known deferred from v1

(All v1 deferred items have shipped: sortable column headers and the non-SELECT
spec-compliant path that re-shows Yasr's native pane.)

## Open questions

None. Ready for implementation planning.
