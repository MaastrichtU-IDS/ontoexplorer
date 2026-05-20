# SPARQL Page — IRI Autocomplete + Prefix Autoload

## Context

Sub-project C of six in the broader SPARQL-page improvement plan. Sub-project A (scope toolbar) shipped on 2026-05-20 and now exposes `(selected ontology ids, reasoning mode)` state. This sub-project makes the Yasqe editor *term-aware*: typing a label in an IRI position offers IRI completions; selecting an ontology auto-injects its `PREFIX` declaration.

The pain this addresses: today, writing `<https://w3id.org/ontostart/pizza/Margherita>` by hand is the worst remaining friction on `/sparql`. We have all the data needed to fix it — `/api/v1/autocomplete` returns labels, synonyms, multilingual variants, and cross-ontology disambiguation — but the editor doesn't tap into it.

Frontend-only. No backend changes.

## Goal

When the user is writing SPARQL in the Yasgui editor:

1. **Inside `<...>`** — typing a partial label (or IRI fragment) auto-shows IRI suggestions, scoped to the toolbar's selected ontologies (or fleet-wide if none). Selecting a suggestion inserts the full IRI.
2. **After `prefix:`** in a prefixed-name position — typing a partial label scoped to the namespace bound to that prefix shows local-name suggestions; selecting one inserts the CURIE.
3. **On scope add** — the selected ontology's `PREFIX <shortname>: <base-iri>` line is prepended to the editor *if not already present*; deselection leaves the line untouched (additive-only policy).

Synonyms and cross-language matches are surfaced automatically because the backend's `/autocomplete` endpoint already returns them; the frontend doesn't filter.

## Approach

### Completer

Register a custom Yasqe autocompleter via `Yasqe.registerAutocompleter(...)`. The completer's three callbacks are:

- `isValidCompletionPosition(yasqe)` — returns `true` when the cursor is inside an IRI literal (`token.type` is one of the Yasqe SPARQL-mode IRI-token types) or in a prefixed-name position, and the token's string is non-empty. Returns `false` for variables (`?x`), string literals, and SPARQL keywords.
- `get(yasqe, token)` — calls `GET /api/v1/autocomplete?q=<partial>&ontology_ids=<selected>&limit=20`, transforms each completion into a Yasqe suggestion, returns the list.
- `postProcessSuggestion(yasqe, token, suggested)` — wraps with `<>` for IRI position; keeps `prefix:LocalName` for CURIE position.

The completer holds a closure over `getSelectedOntologyIds: () => string[]` so the scope toolbar's current selection is read on every keystroke without re-registration. Empty selection → no `ontology_ids` param → fleet-wide suggestions.

`autoShow: true` so the dropdown appears as the user types (matches Yasqe's built-in prefixes completer pattern). The backend autocomplete endpoint is Redis-backed and fast enough for keystroke-rate calls.

### Prefix injection

When `ScopeToolbar` adds an ontology to the selection (popover click or chip toggle), it fires a new `onOntologyAdded(ontologyId)` callback in addition to the existing `onScopeChange`. `Sparql.tsx` handles this callback by:

1. Reading the ontology's `iri` field.
2. Deriving the namespace base: strip a trailing `/` or `#`, then re-append the same terminator. If the IRI ends in neither, append `/`. (Same logic as `slugFromIri`.)
3. Reading the ontology's `shortname` (fall back to the IRI's last segment if absent).
4. Reading the editor's current query via `yasqe.getValue()`.
5. If a `PREFIX <shortname>:` line (case-insensitive) is already present, do nothing.
6. Otherwise prepend `PREFIX <shortname>: <base-iri>\n` to the query and call `yasqe.setValue(newQuery)`.

The standard W3C prefixes (`owl`, `rdf`, `rdfs`, `xsd`) are already in the default starter query — we don't manage them.

Removing an ontology from scope does **not** remove its `PREFIX` line. Users who have already typed `pizza:Margherita` somewhere in the query body would lose query validity if we did. The policy mirrors how Yasgui's own prefixes plugin works: additive on use, never removed automatically.

### Prefix → ontology resolution (for the CURIE completion path)

When the cursor is in a `prefixed-name` token like `pizza:Marg`, the completer needs to know *which ontology* to filter by. Yasqe exposes `yasqe.getPrefixesFromQuery()` which returns the prefix map parsed from the editor's current `PREFIX` declarations (e.g. `{ pizza: "https://w3id.org/ontostart/pizza/" }`). The completer:

1. Reads the token's prefix segment (`pizza`).
2. Looks it up in `yasqe.getPrefixesFromQuery()` → base IRI.
3. Searches the toolbar's selected ontologies (via `useOntologies()` data) for one whose `iri`, after normalisation via `extractBaseIri`, matches the base IRI.
4. If found, calls `/autocomplete?q=<local-part>&ontology_ids=<found-id>&limit=20`.
5. If not found (user has typed a prefix bound to an IRI we don't know), falls back to fleet-wide search using only `q=<local-part>`.

The match in step 3 is exact-string after normalisation. We don't try to fuzzy-match.

### Position detection

Yasqe's SPARQL mode tokenizer tags tokens with `style` strings. From the `sparql11Mode` source the relevant types are:
- `iri-ref` — inside `<...>` IRI literal
- `prefixed-name` (with sub-styles `prefixed-name-ns` for the prefix and `prefixed-name-local` for the local name) — `foo:bar` form
- `variable-1` / `variable-2` — `?x` / `$x`
- `string-1` / `string-2` — quoted literals

`isValidCompletionPosition` returns `true` only when `token.type` matches one of the IRI / prefixed-name types and the token's text is non-empty. Everything else short-circuits to `false` so we don't pollute the keyword/variable/literal contexts.

### Backend

Unchanged. `/api/v1/autocomplete` already returns the shape we need:

```json
{
  "completions": [
    {"text": "Pizza", "type": "class", "iri": "https://w3id.org/...", "short": "Pizza",
     "insert": "Pizza", "lang": "en", "cross_language": false,
     "ontology_shortname": "pizza"}
  ],
  "context": "name",
  "replace_from": 12,
  "replace_to": 16
}
```

We use `text` (label) for the dropdown, `iri` for IRI-position insertion, `short`/`iri` for CURIE-position insertion (build CURIE = `<existing-prefix>:<local-name>` where local-name is extracted from `iri` by trimming the matched base). The `ontology_shortname` field is shown as secondary text in the dropdown for disambiguation.

## UI

The autocomplete dropdown is Yasqe-native — its built-in styling — populated with two columns:

```
┌────────────────────────────────────────────────────────────┐
│  Pizza                              pizza · class          │
│  Pizza Topping                      pizza · class          │
│  Pizza Order #001                   pizza · individual     │
│  Pizza dough                        food · class           │
└────────────────────────────────────────────────────────────┘
```

Primary text: the entry's label. Secondary (right-aligned): `<ontology-shortname> · <type>`. No separate widget on the toolbar — the autocomplete is silently active.

The PREFIX injection has no UI signal of its own beyond the visible PREFIX line itself.

## Edge cases

| Case | Behaviour |
|---|---|
| User selects an ontology with no `shortname` | Synthesise from the IRI's last path segment (same fallback the rest of the UI uses). Acceptable: shortnames are rare to be missing for ingested ontologies. |
| User selects an ontology whose `latest_version` is `pending/failed/deprecated` | `ScopeToolbar.isSelectable` already filters these out, so they never reach `onOntologyAdded`. |
| User has the same `PREFIX shortname:` in the editor already, bound to a *different* IRI | Do nothing. We don't second-guess the user's manual edits. |
| Autocomplete returns nothing | Yasqe shows no dropdown. Normal Yasqe behaviour. |
| `/api/v1/autocomplete` returns an HTTP error | Completer returns an empty list (silent fail). Error logged to console for dev debugging. |
| User types inside `<...>` but the partial text contains characters disallowed in IRIs | Backend handles encoding; frontend sends `q` as-is. |
| Cursor sits at `prefix:` (no local name yet) | Completer fires with empty local-name query, fetches suggestions whose `iri` starts with the prefix's bound base, returns local-name list. |
| Selected ontologies change while a dropdown is open | The next character typed refetches with the new selection; in-flight requests are abandoned by Yasqe's debouncer (built-in). |
| `getSelectedOntologyIds()` is read inside `get(yasqe, token)` (not at registration) | Confirmed pattern; the closure reads fresh state on every call. |

## Files

- **New** `frontend/src/components/sparql/prefixUtils.ts` — pure helpers: `extractBaseIri`, `hasPrefix`, `prependPrefix`, plus the `OntologyForPrefix` shape needed by the page.
- **New** `frontend/src/components/sparql/prefixUtils.test.ts` — unit tests for the three helpers.
- **New** `frontend/src/components/sparql/ontoCompleter.ts` — `buildOntoCompleter(getSelectedOntologyIds)` returns a `CompleterConfig`. Imports the `/api/v1/autocomplete` fetcher (a new method on `api.search` in `lib/api.ts`) and the position-detection helpers.
- **New** `frontend/src/components/sparql/ontoCompleter.test.ts` — unit tests with a stubbed Yasqe / token shape, mocked fetch, covering all three positions and edge cases.
- **Modified** `frontend/src/lib/api.ts` — add a typed wrapper `api.search.autocomplete(q, options): Promise<AutocompleteResponse>` if not already present.
- **Modified** `frontend/src/components/sparql/ScopeToolbar.tsx` — add optional `onOntologyAdded?: (ontologyId: string) => void` prop; fire it on chip add (popover-click) but **not** on chip remove.
- **Modified** `frontend/src/components/sparql/ScopeToolbar.test.tsx` — extend the existing "selecting ontologies" describe block to cover `onOntologyAdded` fires on add and not on remove.
- **Modified** `frontend/src/pages/Sparql.tsx` — at mount, call `Yasqe.registerAutocompleter(buildOntoCompleter(() => getSelectedOntologyIds()))` (with a ref-backed closure if needed). Add `handleOntologyAdded(ontologyId)` that reads the ontology metadata via the `useOntologies()` hook (or via a ref to its result) and calls the prefix injector.
- **Modified** `frontend/src/pages/Sparql.test.tsx` — add a test that adding an ontology results in `setValue` being called with a `PREFIX <shortname>:` line prepended.

## Testing

**Pure helpers (`prefixUtils.test.ts`):**

- `extractBaseIri` — handles `http://example.org/foo/` (returns as-is), `http://example.org/foo` (appends `/`), `http://example.org/foo#` (returns as-is), URLs with paths and queries (uses last path segment trimming).
- `hasPrefix` — detects `PREFIX foo: <bar>` exact, with extra whitespace, mixed case (`prefix Foo:`), and the trailing newline; returns false for absent or different-name prefixes.
- `prependPrefix` — inserts at the top, preserves existing content, doesn't duplicate when called twice with the same shortname (smoke test for idempotency under repeated calls).

**Completer (`ontoCompleter.test.ts`):**

- `isValidCompletionPosition` returns `true` for an `iri-ref` token, `true` for a `prefixed-name-local` token, `false` for `variable-1`, `false` for `string-1`, `false` for an empty token.
- `get(yasqe, token)` for an IRI-position token calls fetch with the partial text (extracted between `<` and cursor) and returns suggestions wrapped in `<...>`.
- `get(yasqe, token)` for a prefixed-name token calls fetch with the local-name partial and returns suggestions as `<existing-prefix>:LocalName`.
- `get` filters by `getSelectedOntologyIds()` when selection is non-empty; sends no `ontology_ids` when selection is empty.
- `get` returns `[]` on fetch failure (no throw).

**Component tests (`ScopeToolbar.test.tsx`):**

- Calling `onOntologyAdded` with the chip's id fires when an ontology is added via popover.
- `onOntologyAdded` is not called when a chip is removed.
- `onOntologyAdded` is not called for the initial render with empty selection.

**Integration (`Sparql.test.tsx`):**

- Mount `<Sparql>`, simulate adding an ontology through `ScopeToolbar` (mocked), assert `yasqe.setValue` was called with a query starting with `PREFIX <shortname>: <base-iri>\n` followed by the original query text.
- If the original query already contains `PREFIX <shortname>:`, adding the same ontology does not call `setValue` again.

## Out of scope

- Live editing the prefix mapping itself (custom shortnames per user) — explicit non-goal.
- Removing PREFIX lines when ontologies are deselected — explicit non-goal per the additive-only policy.
- Standard W3C prefix management — the default starter query already declares them.
- Snippet-style insertions (e.g. inserting a SPARQL query template after picking a class) — too speculative; revisit in sub-project D.
- Two-column "label + short" view inside the dropdown — Yasqe's hint widget supports custom HTML rendering but adding it bloats the spec; the single-line "label (ontology · type)" format covers the disambiguation case.
- Per-keystroke client-side caching beyond React Query defaults — backend is fast enough.

## Open questions

None. Ready for implementation planning.
