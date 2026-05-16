# SPARQL Graph URI Discovery

**Date:** 2026-05-16
**Status:** Approved

## Goal

Users writing SPARQL queries need to know the `urn:ontology:{ontology_id}:{version_id}` graph URI for a specific ontology in order to use `GRAPH <...>` or `FROM NAMED <...>` clauses. Currently there is no in-app way to discover these URIs. This feature provides:

1. Inline editor autocomplete in YASQE for named graph URIs.
2. A searchable, collapsible panel above the YASGUI editor listing all indexed ontologies with their graph URIs and a copy-to-clipboard button.

## Data layer

No new API endpoints. `useOntologies()` (existing hook at `frontend/src/hooks/useOntologies.ts`) fetches all ontologies including `latest_version`. From each ontology we derive:

- **Display name**: `shortname ?? iriSlug(iri)` — strip trailing `/#`, take the last path segment, strip file extensions (`.owl`, `.ttl`, `.rdf`, `.obo`, `.json`, `.xml`, `.nt`).
- **Graph URI**: `urn:ontology:{id}:{latest_version.id}`

**Filter**: only include ontologies where `latest_version` exists and its `status` is not `"pending"`, `"failed"`, or `"deprecated"` (i.e., the ontology has a usable index).

## YASQE inline autocomplete

YASGUI accepts a `yasqe` config block that is passed to YASQE at init time. YASQE's `namedGraphs` option accepts `string[] | ((yasqe) => string[])`.

Implementation:
- Declare a `namedGraphsRef = useRef<string[]>([])` in the `Sparql` component.
- Pass `yasqe: { namedGraphs: () => namedGraphsRef.current }` to the `Yasgui` constructor.
- In a `useEffect` that watches the `ontologies` array, recompute and write the filtered graph URI list to `namedGraphsRef.current`.

This gives autocomplete in both `GRAPH <…> { }` and `FROM NAMED <…>` positions with no extra work, and stays current after the async ontology load without re-initialising YASGUI.

## `GraphsPanel` component

A self-contained component defined in `Sparql.tsx` (no new file needed given the small scope).

### Props

```ts
interface GraphsPanelProps {
  ontologies: Ontology[]   // filtered to indexed only, passed from Sparql
}
```

### Collapsed state (default)

A slim bar (~32 px tall), styled consistently with the existing page header:

```
[ Graphs (N) ▾ ]    browse named graph URIs for GRAPH / FROM NAMED clauses
```

- Left: toggle button `"Graphs ({count}) ▾/▴"` — `font-size: var(--font-size-sm)`, `color: var(--text-dim)`.
- Right: hint text `"browse named graph URIs …"` — `font-size: var(--font-size-sm)`, `color: var(--text-dim)`.
- `borderBottom: 1px solid var(--border)`, `background: var(--bg-secondary)`.

### Expanded state

Below the bar, a section with `maxHeight: 260px`, `overflow: hidden` (panel) containing:

1. **Search input** — filters the list by display name or graph URI substring (case-insensitive). Placeholder `"Filter ontologies…"`. Styled to match existing search inputs in the codebase.
2. **Scrollable list** — `overflowY: auto`, `maxHeight: ~220px` (panel height minus input). Each row:
   - Display name (`color: var(--text)`, `fontSize: 12`, left-aligned, `minWidth: 0`, `flexShrink: 0`).
   - Graph URI in monospace (`fontSize: 11`, `color: var(--text-dim)`, `overflow: hidden`, `textOverflow: ellipsis`, `whiteSpace: nowrap`, `flex: 1`).
   - Copy button — icon or "Copy" text; on click: copies URI to clipboard, changes to "✓" for 1500 ms then resets.
3. **Empty state** — if filter matches nothing: `"No matching ontologies"` centered, `color: var(--text-dim)`.

### Interaction

- Toggle open/closed via `useState<boolean>` (`open`, default `false`).
- Copy state per row via `useState<string | null>` holding the URI that was last copied (resets after timeout).
- No debounce needed on the filter input (list is small, all client-side).

## Layout integration

`Sparql.tsx` outer structure becomes:

```
<div flex-column full-height>
  <header>          ← existing header bar (title + subtitle)
  <GraphsPanel>     ← new, inserted here
  <div ref yasgui>  ← existing, flex:1 minHeight:0 (unchanged)
</div>
```

YASGUI already has `flex: 1; minHeight: 0`, so it correctly fills remaining height when the panel expands or collapses. No changes to YASGUI sizing.

## File changes

| File | Change |
|------|--------|
| `frontend/src/pages/Sparql.tsx` | Add `GraphsPanel` component; wire `useOntologies`, `namedGraphsRef`, and `yasqe.namedGraphs` |
| No other files | `useOntologies` hook and `Ontology` type already exist and are sufficient |

## Out of scope

- Persisting the open/closed state across page loads.
- Showing multiple versions per ontology (only latest indexed version is shown).
- Any backend changes.
