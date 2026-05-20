# SPARQL Page — Ontology + Reasoning Scope Toolbar

## Context

The SPARQL page ([frontend/src/pages/Sparql.tsx](../../../frontend/src/pages/Sparql.tsx)) is a thin wrapper around Yasgui. Today it exposes only one workflow: querying the entire Oxigraph content store at `/api/v1/sparql/content`, with a *Graphs* disclosure panel that lists named-graph URIs the user can copy-paste into `GRAPH`/`FROM NAMED` clauses by hand.

Two things are missing:

1. **Ontology scoping.** Users have to memorize the `urn:ontology:<ontologyId>:<versionId>` convention and hand-paste URIs.
2. **Reasoning visibility.** ELK-inferred triples are already materialized in the same Oxigraph store under the parallel URI `urn:ontology:<O>:<V>:inferred` (see [oxigraph.py:48-50](../../../ontoexplorer/clients/oxigraph.py#L48-L50), populated by the reasoning task at [tasks.py:444-447](../../../ontoexplorer/modules/jobs/tasks.py#L444-L447), already consumed by the diff pipeline). The SPARQL UI never surfaces them.

This is sub-project **A** of six in a broader plan to improve the SPARQL page. The other sub-projects (term-aware autocomplete, embedded starter-query rail, result enrichment, cross-version diff) are out of scope for this design.

## Goal

Let a user say *"query these ontologies, with this reasoning mode"* via UI, and have every Yasgui-issued request automatically scoped to the right graphs — without modifying the visible query text.

## Approach

The SPARQL 1.1 Protocol [§2.1](https://www.w3.org/TR/sparql11-protocol/#query-operation) defines two URL parameters that act exactly like `FROM` / `FROM NAMED` clauses:

- `default-graph-uri=<X>` (repeatable) is equivalent to `FROM <X>`.
- `named-graph-uri=<X>` (repeatable) is equivalent to `FROM NAMED <X>`.

Oxigraph honours both. We use them to scope every request out-of-band. The Yasgui editor contents are never touched.

Both parameters are sent for each selected graph, so both query styles work transparently:

| Query style | What it needs to see triples |
|---|---|
| `SELECT * WHERE { ?s ?p ?o }` (no GRAPH) | `default-graph-uri` |
| `SELECT * WHERE { GRAPH ?g { ?s ?p ?o } }` | `named-graph-uri` |

The two parameters are not redundant — they're complementary. Sending both means the user never has to think about which form to use.

## UI

A new strip — `ScopeToolbar` — sits between the page header and the Yasgui editor, **replacing** the current `GraphsPanel` disclosure.

```
┌────────────────────────────────────────────────────────────────────┐
│ SPARQL · Query the full ontology graph · read-only · SPARQL 1.1    │
├────────────────────────────────────────────────────────────────────┤
│ Scope: [ENVO ✕] [CHEBI ✕] [+ add ontology…]   ⌜Asserted⌝ Inferred Both    📋 │
│        2 ontologies · asserted · 2 graphs scoped                            │
├────────────────────────────────────────────────────────────────────┤
│  [Yasgui editor — query text unchanged]                            │
│  [Yasgui results pane]                                             │
└────────────────────────────────────────────────────────────────────┘
```

**Controls:**

- **Ontology multi-select**: chip strip with `+ add ontology…` opening a filterable popover (same data source as today's `GraphsPanel`). Clicking the `✕` on a chip removes it. Filterable list mirrors the ontology list endpoint.
- **Reasoning segmented control**: three pills `Asserted · Inferred · Both`. Default `Asserted`. Disabled (greyed out, unchanged on click) while no ontology is selected; the segmented control's value still persists so it reactivates when the user picks an ontology.
- **Copy icon** (📋): one-click copies the **materialized** query text — i.e. the editor's current query with the equivalent `FROM` / `FROM NAMED` lines prepended — to the clipboard. The editor itself is not modified; the icon flashes a brief "copied" confirmation. This is the only place the user ever sees the materialized clauses.
- **Summary line**: one-line status, e.g. `2 ontologies · asserted · 2 graphs scoped`. Or `No scope selected · whole store queryable` when empty.

**Empty state** (no ontology selected): no protocol parameters are sent. The endpoint behaves exactly as today — the whole Oxigraph store is queryable. Reasoning control is disabled but retains its state.

**Saved-query loading** (`?q=<id>`): the toolbar resets to "no selection" and we do not parse the saved query for existing `FROM` / `FROM NAMED` lines. If the saved query has its own `FROM` clauses they remain untouched; if the user then picks ontologies, the protocol-parameter scope is unioned with whatever the saved query already declares (SPARQL spec behaviour).

## Mechanism

```
ScopeToolbar
   ├─ selected: Set<ontologyId>
   └─ mode: 'asserted' | 'inferred' | 'both'
        │
        ▼ on change
   buildScopedEndpoint(baseUrl, selected, mode, ontologies) → endpointUrl
        │
        ▼
   yasguiRef.current.getTab().setRequestConfig({ endpoint: endpointUrl })
```

The page already constructs Yasgui once and holds it in a ref. To make the endpoint dynamic, we call Yasgui's per-tab `setRequestConfig` whenever scope changes. (`setRequestConfig` is the supported way to update Yasgui's POST target after construction — verified against Yasgui v4 API.)

For the copy icon, a parallel pure helper:

```
formatScopeAsFromClauses(selected, mode, ontologies) → string
  # FROM <urn:ontology:O1:V1>
  # FROM NAMED <urn:ontology:O1:V1>
  …
```

is prepended to the current Yasgui query text and written to `navigator.clipboard`.

## URI construction

A selected ontology `o` with `latest_version.id = V` and `ontology.id = O` produces graph URIs identically to [oxigraph.py:48-50](../../../ontoexplorer/clients/oxigraph.py#L48-L50):

- asserted: `urn:ontology:O:V`
- inferred: `urn:ontology:O:V:inferred`

For each selected `o` and chosen `mode`:

- `mode === 'asserted'` → emit asserted URI
- `mode === 'inferred'` → emit inferred URI
- `mode === 'both'` → emit both URIs

For each emitted URI, send both `default-graph-uri=<uri>` and `named-graph-uri=<uri>` as URL params (URI-encoded).

Ontologies whose `latest_version.status` ∈ `{pending, failed, deprecated}` are excluded from the selectable list (same filter as today's `GraphsPanel`).

## Edge cases

| Case | Behaviour |
|---|---|
| Empty selection | No URL params; endpoint reverts to base `/api/v1/sparql/content`. |
| User selects ontology that has no inferred graph yet | The inferred URI is still added when mode is *Inferred* or *Both*; queries against it simply return no rows. We do **not** filter, because reasoning is an async job and "not yet inferred" is a transient state; filtering would silently change scope. Acceptable: zero results signal that reasoning hasn't run. |
| User edits the editor query manually | No interaction with scope. Query text is the source of truth for query content; scope toolbar is the source of truth for graph URIs. |
| User loads `?q=<savedQueryId>` | Scope resets to empty; saved query text untouched. |
| User clicks copy with empty selection | Copies the editor's current query verbatim (no `FROM` block prepended). |
| Endpoint URL exceeds reasonable length (e.g. >50 ontologies × 2 modes × 2 params = 200 params) | Acceptable; URLs of this length are well within HTTP and Oxigraph limits. Yasgui POSTs the body, so the URL only carries the params. |

## Backend

**No changes.** `/api/v1/sparql/content` already serves both asserted and inferred named graphs. Oxigraph already honours `default-graph-uri` / `named-graph-uri` query parameters per SPARQL Protocol.

## Files

- **New** `frontend/src/components/sparql/scopeUrls.ts` — pure helpers:
  - `assertedGraphIri(ontologyId, versionId): string`
  - `inferredGraphIri(ontologyId, versionId): string`
  - `selectedGraphIris(selected, mode, ontologies): string[]`
  - `buildScopedEndpoint(baseUrl, graphIris): string`
  - `formatScopeAsFromClauses(graphIris): string`
- **New** `frontend/src/components/sparql/scopeUrls.test.ts` — unit tests for all helpers.
- **New** `frontend/src/components/sparql/ScopeToolbar.tsx` — the UI strip; consumes ontologies via `useOntologies()`, owns `selected` / `mode` state, calls an `onChange` callback with the computed endpoint URL and the current materialized FROM string.
- **New** `frontend/src/components/sparql/ScopeToolbar.test.tsx` — component-level tests with Yasgui mocked at the page boundary.
- **Modified** `frontend/src/pages/Sparql.tsx`:
  - Remove the inline `GraphsPanel` component and its references.
  - Render `<ScopeToolbar onScopeChange={...} onCopyMaterialized={...} />` in its place.
  - On `onScopeChange`, call `yasguiRef.current?.getTab()?.setRequestConfig({ endpoint })`.
  - On `onCopyMaterialized`, read current Yasgui query text via `yasguiRef.current?.getTab()?.getYasqe()?.getValue()`, prepend the `FROM` block, and write to clipboard.

The `GraphsPanel` deletion is in scope because its responsibilities are entirely subsumed by the new toolbar.

## Testing

**Pure-helper unit tests** (`scopeUrls.test.ts`):

- `assertedGraphIri('O', 'V')` returns `'urn:ontology:O:V'`.
- `inferredGraphIri('O', 'V')` returns `'urn:ontology:O:V:inferred'`.
- `selectedGraphIris(empty, *, *)` returns `[]`.
- `selectedGraphIris({O1}, 'asserted', [{id:O1, latest_version:{id:V1}}])` returns `['urn:ontology:O1:V1']`.
- `selectedGraphIris({O1}, 'inferred', …)` returns `['urn:ontology:O1:V1:inferred']`.
- `selectedGraphIris({O1}, 'both', …)` returns both URIs in deterministic order (asserted first).
- `selectedGraphIris({O1, O2}, 'asserted', …)` preserves selection iteration order.
- `buildScopedEndpoint('/api/v1/sparql/content', [])` returns the base URL unchanged.
- `buildScopedEndpoint(base, ['urn:ontology:O:V'])` returns `'/api/v1/sparql/content?default-graph-uri=urn%3Aontology%3AO%3AV&named-graph-uri=urn%3Aontology%3AO%3AV'`.
- `buildScopedEndpoint(base, ['a', 'b'])` emits 4 params total, both `default-graph-uri` and `named-graph-uri` for each.
- `formatScopeAsFromClauses([])` returns `''`.
- `formatScopeAsFromClauses(['urn:a'])` returns `'FROM <urn:a>\nFROM NAMED <urn:a>\n'`.
- `formatScopeAsFromClauses(['urn:a', 'urn:b'])` returns the four lines in order.

**Component tests** (`ScopeToolbar.test.tsx`, jsdom):

- Initial render: chip strip empty, reasoning control disabled, summary reads "No scope selected".
- Adding an ontology chip enables the reasoning control and calls `onScopeChange` with a URL that includes the asserted URI.
- Switching reasoning to *Inferred* calls `onScopeChange` with an inferred URI.
- Switching to *Both* calls `onScopeChange` with both URIs.
- Removing the last chip calls `onScopeChange` with the base URL (no params) and disables the reasoning control.
- Clicking the copy icon calls `onCopyMaterialized` with the expected FROM block (mock clipboard).

**No backend tests** required — backend is unchanged.

## Out of scope (deferred to later sub-projects)

- Term/IRI autocomplete inside the editor (sub-project C)
- Embedded starter-query rail (sub-project D)
- Result-pane enrichment / clickable IRIs (sub-project E)
- Side-by-side cross-version diff (sub-project F)
- Persisting scope across page loads — explicit non-goal for v1 (default is "no scope")
- Detecting and reflecting `FROM` clauses already present in saved queries — explicit non-goal; saved queries' own clauses pass through untouched
- Switching the QLever metadata endpoint (`/api/v1/sparql`) vs the content endpoint — explicit non-goal; rare use case, can be added later as a third toggle if anyone wants it

## Open questions

None. The design is fully specified.
