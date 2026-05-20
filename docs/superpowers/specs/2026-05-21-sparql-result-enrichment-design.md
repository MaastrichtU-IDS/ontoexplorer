# SPARQL Page — Result Enrichment + IRI Drilldown

## Context

Sub-project E of six in the SPARQL-page improvement plan. Sub-projects A (scope toolbar, 2026-05-20) and C (IRI autocomplete + prefix autoload, 2026-05-20) have shipped. This sub-project improves the **result pane** of the Yasgui editor.

Two related improvements:

1. **IRI cells become clickable in-app links** — clicking an IRI in a SPARQL result row navigates to OntoExplorer's term page rather than dereferencing the raw IRI.
2. **Labels toggle** — when on, a follow-up SPARQL query fetches `rdfs:label` for every IRI in the result set and appends the label to each cell.

Manchester-syntax rendering for bnode/anonymous-class results is **out of scope**: it would require backend work to reconstruct class expressions from the store. Defer to a later sub-project.

Frontend-only.

## Goal

Make SPARQL result tables more useful to ontology users without changing the editor experience or adding to the backend surface:

- Clicking `<https://w3id.org/ontostart/pizza/Margherita>` in a result opens `/ontologies/pizza?term=…` in the same tab.
- Toggling **📑 Labels** appends `· Margherita Pizza` after each IRI cell using the labels available in the same scoped store.

## Approach

### IRI cells → in-app navigation

Yasr's built-in table plugin renders IRI cells as `<a class="iri" href="<full-iri>" target="_self">…</a>`. We intercept clicks via a single delegated `click` listener on the Yasgui container element. The handler:

1. Walks up from the click target until it finds an `<a class="iri">` ancestor (or returns).
2. Reads `href` to get the IRI.
3. Tries a **longest-prefix match** against the scope toolbar's selected ontologies' base IRIs. The match uses `extractBaseIri(o.iri)` (already implemented in `prefixUtils.ts` for sub-project C) as the namespace key and `iri.startsWith(baseIri)` as the predicate. Among matches, the one with the longest `baseIri` wins.
4. If matched, calls `event.preventDefault()` and React Router's `navigate(termPageUrl(shortname, iri))`.
5. If no match, fires `GET /api/v1/search?q=<iri>&mode=entity&limit=1` asynchronously. While the fetch is in flight, also calls `event.preventDefault()` so the default browser navigation doesn't fire. When the response returns:
   - If it has a result with an `ontology_id` → look up that ontology's shortname in the client cache and navigate.
   - If empty or error → call `window.open(iri, '_blank')` so the user still gets to the IRI's home (the original behaviour, just delayed).
6. Modified-key clicks (Ctrl/Cmd/Shift/middle-mouse) skip all of the above and let the browser handle them — users expecting "open in new tab" still get it.

### Labels toggle

A new `📑` icon button on `ScopeToolbar`, next to the existing `📋` copy icon. Internal toolbar state, optional `onLabelsToggle(enabled: boolean)` callback so the page can react.

Behaviour when toggled **on**:

1. `Sparql.tsx` reads all unique IRI strings from `a.iri` elements within the Yasgui container.
2. If the set is non-empty, builds a SPARQL query:
   ```sparql
   SELECT ?iri ?label WHERE {
     VALUES ?iri { <iri1> <iri2> … }
     ?iri rdfs:label ?label .
   }
   ```
3. Sends the query as a POST to the **same endpoint URL the Yasgui editor currently uses** (i.e. respecting the scope toolbar's `default-graph-uri` / `named-graph-uri` parameters). Reads it via `yasguiRef.current.getTab().getRequestConfig().endpoint`. Falls back to the bare `/api/v1/sparql/content` if unavailable.
4. Builds an `iri → label` `Map`. If an IRI has multiple labels (different languages, multiple `rdfs:label` properties), keeps the first one encountered.
5. Walks the table once more and appends `<span class="iri-label"> · label</span>` immediately after each `<a class="iri">` whose `href` has a known label. Skips IRIs that didn't get a label.

Behaviour when toggled **off**: walks the table and removes every `.iri-label` span.

Behaviour on **table re-draw** (Yasr emits `drawn` after sort, paginate, or new query): if the labels toggle is on, re-collect IRIs and re-apply. Subscribe via the Yasr instance's event API.

### URLs

| Path | Constructed by | Where |
|---|---|---|
| `/ontologies/<shortname>?term=<encoded-iri>` | `termPageUrl(shortname, iri)` | iriResolver.ts |
| `/api/v1/search?q=<iri>&mode=entity&limit=1` | existing `api.globalSearch.search(q, 1)` | reuse |

## UI

The toolbar grows one button. The copy icon (📋) is unchanged; the labels icon (📑) sits to its left:

```
… Scope: [pizza ✕] [+ add ontology…] Asserted Inferred Both    … 📑 📋
```

When on, the button shows an active border (using `var(--accent)`) to indicate state. Aria-label `Toggle result labels`.

In the result table, each enriched cell looks like:

```
<https://w3id.org/ontostart/pizza/Margherita>  · Margherita Pizza
```

The dimmed label span uses `color: var(--text-dim)` and a leading `· ` separator.

## Files

| Path | Role |
|---|---|
| `frontend/src/components/sparql/iriResolver.ts` | Pure helpers: `findOwningOntology(iri, ontologies): Ontology \| null` (longest-prefix), `termPageUrl(shortname, iri): string`. |
| `frontend/src/components/sparql/iriResolver.test.ts` | Unit tests for both helpers. |
| `frontend/src/components/sparql/iriClickHandler.ts` | `installIriClickHandler(rootEl, { getOntologies, navigate })` returns a teardown fn. Attaches the click listener; uses iriResolver + a fetch fallback via `api.globalSearch.search`. |
| `frontend/src/components/sparql/iriClickHandler.test.ts` | jsdom test: synthetic click on `a.iri`, navigate called with correct URL; modified clicks pass through; fetch-fallback path tested. |
| `frontend/src/components/sparql/labelEnricher.ts` | Pure helpers: `collectIris(rootEl)`, `buildLabelsQuery(iris)`, `applyLabels(rootEl, labels)`, `removeLabels(rootEl)`. |
| `frontend/src/components/sparql/labelEnricher.test.ts` | Unit tests with jsdom-built fake tables. |
| `frontend/src/components/sparql/ScopeToolbar.tsx` | Add a labels toggle button + optional `onLabelsToggle?: (enabled: boolean) => void` prop. |
| `frontend/src/components/sparql/ScopeToolbar.test.tsx` | One new test verifying the toggle fires the callback with the right boolean. |
| `frontend/src/pages/Sparql.tsx` | Mount `installIriClickHandler` (and tear down on unmount). State for `labelsOn`. On toggle change, run label enrichment. Subscribe to Yasr's `drawn` event for re-application after re-renders. |
| `frontend/src/pages/Sparql.test.tsx` | Integration test: simulate render of an `a.iri` with a scoped ontology → click navigates to `/ontologies/<shortname>?term=<iri>`. Second test: labels toggle + mocked SPARQL fetch + DOM contains injected `<span class="iri-label">`. |

## Edge cases

| Case | Behaviour |
|---|---|
| Click on `a.iri` outside any scope ontology, but matching a search result | Fetch path runs; navigates to that ontology page. |
| Click matches no scope, no search result, no network | `window.open(iri, '_blank')` — original IRI URL fetched directly. |
| Search fetch errors out | Same: `window.open(iri, '_blank')`. |
| Modified click (Ctrl, Cmd, Shift, middle-mouse) | Let the browser handle natively. Don't preventDefault. |
| Same `a.iri` element clicked twice rapidly | Both clicks trigger; the first navigate wins; the second is harmless. |
| Labels toggle on, but result is empty | No-op. |
| Labels toggle on, result has 500 unique IRIs | One SPARQL query with `VALUES` block of 500 IRIs. Oxigraph handles this. If responses exceed timeouts, label rendering silently fails (the rest of the page is unaffected). No artificial client-side cap in v1. |
| Labels query returns multiple labels per IRI (different langs) | Keep the first one encountered. (Future improvement: prefer user's preferred language.) |
| Labels toggle off while a label fetch is in flight | AbortController cancels the fetch; if the response arrives anyway, the `applyLabels` step is a no-op because the toggle state is off. |
| Yasr re-draws (sort/paginate/new query) while toggle is on | `drawn` listener re-runs label enrichment. |
| Yasr re-draws while toggle is off | No-op. |
| IRI has no `rdfs:label` in the store | No label span is appended for that cell. |
| Result column shows a literal that happens to contain `<...>` text | Not affected — Yasr only adds `class="iri"` to actual IRI bindings. |

## Backend

**No changes.** `/api/v1/search?mode=entity` already supports IRI lookup. `/api/v1/sparql/content` already accepts arbitrary SPARQL.

## Testing

**Pure helpers** (`iriResolver.test.ts`):

- `findOwningOntology` — exact-base match, longest-prefix match (e.g. two ontologies, one whose base is a prefix of the other), no match returns null.
- `termPageUrl` — encodes IRI correctly; `#` becomes `%23`.

**Pure helpers** (`labelEnricher.test.ts`):

- `collectIris` — extracts hrefs from `a.iri` elements; ignores `a` without that class; deduplicates.
- `buildLabelsQuery` — wraps IRIs in `<>`, builds VALUES block; empty input returns empty string.
- `applyLabels` — appends `<span class="iri-label">` after each `a.iri` whose href matches; skips unmatched.
- `removeLabels` — strips all `.iri-label` spans cleanly.

**Click handler** (`iriClickHandler.test.ts`):

- Synthetic click on `a.iri` → navigate called with `/ontologies/<shortname>?term=<iri>` for in-scope IRI.
- Modified click (Ctrl-click) → navigate NOT called.
- Unmatched IRI + successful search → fetch called, navigate called with the right URL.
- Unmatched IRI + empty search → `window.open` called with the raw IRI.
- Teardown removes the listener.

**Component** (`ScopeToolbar.test.tsx`): toggle button click fires `onLabelsToggle(true)`, then again with `false`.

**Integration** (`Sparql.test.tsx`):

- Mount, simulate Yasgui rendering an `<a class="iri">` element; click; assert navigate was called.
- Mount, toggle labels on, mock the fetch SPARQL response, assert `<span class="iri-label">` was injected.

## Out of scope

- Manchester rendering for bnode/anonymous-class results — deferred (backend work).
- Per-row expand/inspect — Yasr has its own row UI; not touching.
- Preferred-language filter for labels — v1 shows whatever label comes first.
- Client-side caching of label lookups across queries — React Query is enough for v1.
- IRI → CURIE display — Yasr already does this when a `PREFIX` is declared (free with sub-project C's prefix-autoload).
- Toggle persistence across page loads — explicit non-goal for v1 (off by default).
- Labels in result formats other than `application/sparql-results+json` (e.g. Turtle for CONSTRUCT) — v1 only enriches the JSON-bindings table view.

## Open questions

None. Ready for implementation planning.
