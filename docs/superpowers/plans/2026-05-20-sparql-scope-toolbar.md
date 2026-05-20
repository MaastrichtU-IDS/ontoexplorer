# SPARQL Scope Toolbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let SPARQL-page users pick a set of ontologies and a reasoning mode (Asserted · Inferred · Both) so that every Yasgui request is auto-scoped to the right named graphs, without modifying the visible query text.

**Architecture:** Frontend-only. A new `ScopeToolbar` component above the Yasgui editor maintains `(selected ontology ids, reasoning mode)` state, computes graph URIs (`urn:ontology:O:V` and/or `urn:ontology:O:V:inferred`), and updates the Yasgui request endpoint via `tab.setEndpoint(...)` with `default-graph-uri` + `named-graph-uri` URL parameters appended. A copy icon materializes the equivalent `FROM` / `FROM NAMED` lines to clipboard on demand. The existing inline `GraphsPanel` is removed.

**Tech Stack:** React 18 + TypeScript, Vitest + jsdom, @testing-library/react, @triply/yasgui v4, @tanstack/react-query.

**Spec:** [`docs/superpowers/specs/2026-05-20-sparql-scope-toolbar-design.md`](../specs/2026-05-20-sparql-scope-toolbar-design.md)

---

## File Map

| Path | Role |
|---|---|
| `frontend/src/components/sparql/scopeUrls.ts` | Pure helpers: graph-IRI construction, endpoint URL builder, FROM-clause formatter |
| `frontend/src/components/sparql/scopeUrls.test.ts` | Unit tests for the helpers |
| `frontend/src/components/sparql/ScopeToolbar.tsx` | UI strip: chip multi-select, reasoning segmented control, copy icon |
| `frontend/src/components/sparql/ScopeToolbar.test.tsx` | Component tests (jsdom, Yasgui untouched) |
| `frontend/src/pages/Sparql.tsx` | Modified: remove inline `GraphsPanel`, mount `ScopeToolbar`, wire `setEndpoint` + clipboard copy |
| `frontend/src/pages/Sparql.test.tsx` | Modified: update mocks so `getTab()` exposes `setEndpoint` and `getValue` |

---

## Task 1: Graph IRI helpers and selection resolver

Pure functions that derive the graph URIs from a selection + mode. No DOM, no React, no Yasgui — easy to test first.

**Files:**
- Create: `frontend/src/components/sparql/scopeUrls.ts`
- Test: `frontend/src/components/sparql/scopeUrls.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/scopeUrls.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { assertedGraphIri, inferredGraphIri, selectedGraphIris, ReasoningMode } from './scopeUrls'
import type { Ontology } from '../../lib/api'

const ONTS: Ontology[] = [
  {
    id: 'O1', iri: 'http://example.org/o1', shortname: 'o1', title: null,
    created_at: '2024-01-01', latest_version: {
      id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
      version_iri: null, sha256: '',
    } as any,
  } as any,
  {
    id: 'O2', iri: 'http://example.org/o2', shortname: 'o2', title: null,
    created_at: '2024-01-01', latest_version: {
      id: 'V2', ontology_id: 'O2', status: 'ready', format: 'owl',
      version_iri: null, sha256: '',
    } as any,
  } as any,
]

describe('assertedGraphIri', () => {
  it('builds urn:ontology:O:V', () => {
    expect(assertedGraphIri('O1', 'V1')).toBe('urn:ontology:O1:V1')
  })
})

describe('inferredGraphIri', () => {
  it('builds urn:ontology:O:V:inferred', () => {
    expect(inferredGraphIri('O1', 'V1')).toBe('urn:ontology:O1:V1:inferred')
  })
})

describe('selectedGraphIris', () => {
  it('returns [] for empty selection regardless of mode', () => {
    expect(selectedGraphIris(new Set(), 'asserted', ONTS)).toEqual([])
    expect(selectedGraphIris(new Set(), 'inferred', ONTS)).toEqual([])
    expect(selectedGraphIris(new Set(), 'both', ONTS)).toEqual([])
  })

  it('returns asserted URI for mode=asserted', () => {
    expect(selectedGraphIris(new Set(['O1']), 'asserted', ONTS))
      .toEqual(['urn:ontology:O1:V1'])
  })

  it('returns inferred URI for mode=inferred', () => {
    expect(selectedGraphIris(new Set(['O1']), 'inferred', ONTS))
      .toEqual(['urn:ontology:O1:V1:inferred'])
  })

  it('returns asserted then inferred for mode=both, per ontology', () => {
    expect(selectedGraphIris(new Set(['O1']), 'both', ONTS))
      .toEqual(['urn:ontology:O1:V1', 'urn:ontology:O1:V1:inferred'])
  })

  it('preserves ontology order from the input list', () => {
    expect(selectedGraphIris(new Set(['O1', 'O2']), 'asserted', ONTS))
      .toEqual(['urn:ontology:O1:V1', 'urn:ontology:O2:V2'])
  })

  it('skips selected ids not present in the ontologies list', () => {
    expect(selectedGraphIris(new Set(['O1', 'OXX']), 'asserted', ONTS))
      .toEqual(['urn:ontology:O1:V1'])
  })

  it('skips ontologies missing latest_version', () => {
    const noVer = [{ ...ONTS[0], latest_version: null } as any]
    expect(selectedGraphIris(new Set(['O1']), 'asserted', noVer)).toEqual([])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/sparql/scopeUrls.test.ts --reporter=basic`

Expected: FAIL with "Failed to resolve import" or "module not found" — the file doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/sparql/scopeUrls.ts`:

```typescript
import type { Ontology } from '../../lib/api'

export type ReasoningMode = 'asserted' | 'inferred' | 'both'

export function assertedGraphIri(ontologyId: string, versionId: string): string {
  return `urn:ontology:${ontologyId}:${versionId}`
}

export function inferredGraphIri(ontologyId: string, versionId: string): string {
  return `urn:ontology:${ontologyId}:${versionId}:inferred`
}

export function selectedGraphIris(
  selected: Set<string>,
  mode: ReasoningMode,
  ontologies: Ontology[],
): string[] {
  const out: string[] = []
  for (const o of ontologies) {
    if (!selected.has(o.id)) continue
    if (!o.latest_version) continue
    const vid = o.latest_version.id
    if (mode === 'asserted' || mode === 'both') {
      out.push(assertedGraphIri(o.id, vid))
    }
    if (mode === 'inferred' || mode === 'both') {
      out.push(inferredGraphIri(o.id, vid))
    }
  }
  return out
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/scopeUrls.test.ts --reporter=basic`

Expected: PASS with 7 passing tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sparql/scopeUrls.ts frontend/src/components/sparql/scopeUrls.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): graph-IRI helpers for scope toolbar

Pure functions: build asserted/inferred named-graph URIs and
resolve a (selected, mode, ontologies) tuple to the list of
URIs that should be scoped. Mode 'both' emits asserted first,
then inferred, per ontology, preserving input order.
EOF
)"
```

---

## Task 2: Endpoint URL builder and FROM-clause formatter

Two more pure helpers that consume the URI list from Task 1.

**Files:**
- Modify: `frontend/src/components/sparql/scopeUrls.ts`
- Modify: `frontend/src/components/sparql/scopeUrls.test.ts`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/scopeUrls.test.ts`:

```typescript
import { buildScopedEndpoint, formatScopeAsFromClauses } from './scopeUrls'

describe('buildScopedEndpoint', () => {
  const BASE = '/api/v1/sparql/content'

  it('returns the base URL unchanged when no URIs', () => {
    expect(buildScopedEndpoint(BASE, [])).toBe(BASE)
  })

  it('appends default-graph-uri + named-graph-uri for one URI', () => {
    expect(buildScopedEndpoint(BASE, ['urn:ontology:O1:V1']))
      .toBe(`${BASE}?default-graph-uri=urn%3Aontology%3AO1%3AV1&named-graph-uri=urn%3Aontology%3AO1%3AV1`)
  })

  it('appends both params for each URI in order', () => {
    expect(buildScopedEndpoint(BASE, ['urn:a', 'urn:b']))
      .toBe(`${BASE}?default-graph-uri=urn%3Aa&named-graph-uri=urn%3Aa&default-graph-uri=urn%3Ab&named-graph-uri=urn%3Ab`)
  })
})

describe('formatScopeAsFromClauses', () => {
  it('returns empty string for empty list', () => {
    expect(formatScopeAsFromClauses([])).toBe('')
  })

  it('returns FROM + FROM NAMED for one URI', () => {
    expect(formatScopeAsFromClauses(['urn:a']))
      .toBe('FROM <urn:a>\nFROM NAMED <urn:a>\n')
  })

  it('returns four lines for two URIs in order', () => {
    expect(formatScopeAsFromClauses(['urn:a', 'urn:b']))
      .toBe('FROM <urn:a>\nFROM NAMED <urn:a>\nFROM <urn:b>\nFROM NAMED <urn:b>\n')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/scopeUrls.test.ts --reporter=basic`

Expected: FAIL — `buildScopedEndpoint` and `formatScopeAsFromClauses` not exported.

- [ ] **Step 3: Add implementations**

Append to `frontend/src/components/sparql/scopeUrls.ts`:

```typescript
export function buildScopedEndpoint(baseUrl: string, graphIris: string[]): string {
  if (graphIris.length === 0) return baseUrl
  const params: string[] = []
  for (const uri of graphIris) {
    const enc = encodeURIComponent(uri)
    params.push(`default-graph-uri=${enc}`)
    params.push(`named-graph-uri=${enc}`)
  }
  return `${baseUrl}?${params.join('&')}`
}

export function formatScopeAsFromClauses(graphIris: string[]): string {
  return graphIris.map(uri => `FROM <${uri}>\nFROM NAMED <${uri}>\n`).join('')
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/scopeUrls.test.ts --reporter=basic`

Expected: PASS, total 13 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sparql/scopeUrls.ts frontend/src/components/sparql/scopeUrls.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): scoped-endpoint URL + FROM-clause formatter

buildScopedEndpoint produces a /sparql URL with default-graph-uri
and named-graph-uri SPARQL Protocol parameters per graph URI, both
URI-encoded. formatScopeAsFromClauses renders the equivalent FROM
+ FROM NAMED lines for the clipboard-copy action.
EOF
)"
```

---

## Task 3: ScopeToolbar skeleton — empty state

Build the visual shell of the toolbar with no ontologies selected. Reasoning control is disabled. Summary line shows "No scope selected · whole store queryable". The copy icon is visible but does nothing yet (placeholder handler).

**Files:**
- Create: `frontend/src/components/sparql/ScopeToolbar.tsx`
- Create: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ScopeToolbar } from './ScopeToolbar'

vi.mock('../../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [],
    isLoading: false,
  }),
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('ScopeToolbar — empty state', () => {
  it('shows the "No scope" summary when nothing is selected', () => {
    render(wrap(
      <ScopeToolbar
        onScopeChange={vi.fn()}
        onCopy={vi.fn()}
      />
    ))
    expect(screen.getByText(/No scope selected/i)).toBeInTheDocument()
  })

  it('renders three reasoning options, all disabled', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    const asserted = screen.getByRole('button', { name: /asserted/i })
    const inferred = screen.getByRole('button', { name: /inferred/i })
    const both = screen.getByRole('button', { name: /both/i })
    expect(asserted).toBeDisabled()
    expect(inferred).toBeDisabled()
    expect(both).toBeDisabled()
  })

  it('renders an "add ontology" button', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    expect(screen.getByRole('button', { name: /add ontology/i })).toBeInTheDocument()
  })

  it('renders a copy button', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    expect(screen.getByRole('button', { name: /copy query with scope/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: FAIL — "Failed to resolve import './ScopeToolbar'".

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/sparql/ScopeToolbar.tsx`:

```tsx
import { useMemo, useState } from 'react'
import { useOntologies } from '../../hooks/useOntologies'
import {
  ReasoningMode,
  buildScopedEndpoint,
  formatScopeAsFromClauses,
  selectedGraphIris,
} from './scopeUrls'

const BASE_ENDPOINT = '/api/v1/sparql/content'

export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
}

export function ScopeToolbar({ onScopeChange, onCopy }: ScopeToolbarProps) {
  const { ontologies } = useOntologies()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mode, setMode] = useState<ReasoningMode>('asserted')

  const graphIris = useMemo(
    () => selectedGraphIris(selected, mode, ontologies),
    [selected, mode, ontologies],
  )
  const hasSelection = selected.size > 0

  function handleCopy() {
    onCopy(formatScopeAsFromClauses(graphIris))
  }

  const summary = hasSelection
    ? `${selected.size} ontolog${selected.size === 1 ? 'y' : 'ies'} · ${mode} · ${graphIris.length} graph${graphIris.length === 1 ? '' : 's'} scoped`
    : 'No scope selected · whole store queryable'

  return (
    <div
      style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>Scope:</span>
      <button
        style={{
          fontSize: 11, padding: '2px 8px', border: '1px dashed var(--border)',
          borderRadius: 12, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        + add ontology…
      </button>
      <div style={{ display: 'flex', gap: 4 }}>
        {(['asserted', 'inferred', 'both'] as ReasoningMode[]).map(m => (
          <button
            key={m}
            disabled={!hasSelection}
            onClick={() => setMode(m)}
            style={{
              fontSize: 11, padding: '2px 10px', borderRadius: 12,
              border: '1px solid',
              borderColor: mode === m && hasSelection ? 'var(--accent)' : 'var(--border)',
              background: mode === m && hasSelection ? 'rgba(88,166,255,0.1)' : 'transparent',
              color: !hasSelection ? 'var(--text-dim)' : mode === m ? 'var(--accent)' : 'var(--text)',
              opacity: hasSelection ? 1 : 0.45,
              cursor: hasSelection ? 'pointer' : 'not-allowed',
              textTransform: 'capitalize',
            }}
          >
            {m}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, minWidth: 80, fontSize: 11, color: 'var(--text-dim)' }}>
        {summary}
      </div>
      <button
        onClick={handleCopy}
        aria-label="Copy query with scope"
        title="Copy editor query with FROM/FROM NAMED clauses prepended"
        style={{
          fontSize: 14, padding: '2px 8px', border: '1px solid var(--border)',
          borderRadius: 4, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        📋
      </button>
    </div>
  )
}
```

Note: the `onScopeChange` callback is wired up here but only fires once selection/mode change. Since this skeleton has neither yet, `onScopeChange` stays unused until Task 4 / Task 5. The selection setter only exists on the `setSelected` state hook for Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sparql/ScopeToolbar.tsx frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): ScopeToolbar skeleton with empty state

Renders the visual frame: 'Scope:' label, an inert '+ add ontology…'
button, three disabled reasoning pills, summary line, and the copy
icon. No selection logic yet — Task 4 wires the popover and chips.
EOF
)"
```

---

## Task 4: Ontology popover, chip add/remove, and `onScopeChange` wiring

Clicking `+ add ontology…` opens a filterable popover listing every ontology with a ready `latest_version`. Clicking an ontology adds it as a chip; clicking the chip's `✕` removes it. Each add/remove fires `onScopeChange` with the freshly-computed scoped endpoint URL.

**Files:**
- Modify: `frontend/src/components/sparql/ScopeToolbar.tsx`
- Modify: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
import { fireEvent } from '@testing-library/react'

const SAMPLE_ONTS = [
  {
    id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
    created_at: '2024-01-01',
    latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
  } as any,
  {
    id: 'O2', iri: 'http://x/o2', shortname: 'chebi', title: 'ChEBI',
    created_at: '2024-01-01',
    latest_version: { id: 'V2', ontology_id: 'O2', status: 'ready' } as any,
  } as any,
]

vi.doMock('../../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: SAMPLE_ONTS, isLoading: false }),
}))

describe('ScopeToolbar — selecting ontologies', () => {
  it('lists ontologies in the popover when opened', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    expect(screen.getByText('envo')).toBeInTheDocument()
    expect(screen.getByText('chebi')).toBeInTheDocument()
  })

  it('adds a chip on click and calls onScopeChange with the scoped URL', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(onScope).toHaveBeenLastCalledWith(
      '/api/v1/sparql/content?default-graph-uri=urn%3Aontology%3AO1%3AV1&named-graph-uri=urn%3Aontology%3AO1%3AV1'
    )
    expect(screen.getByRole('button', { name: /envo ✕/i })).toBeInTheDocument()
  })

  it('removes a chip and calls onScopeChange with the base URL', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /envo ✕/i }))
    expect(onScope).toHaveBeenLastCalledWith('/api/v1/sparql/content')
  })

  it('filters the popover list', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    const input = screen.getByPlaceholderText(/filter/i)
    fireEvent.change(input, { target: { value: 'che' } })
    expect(screen.queryByText('envo')).not.toBeInTheDocument()
    expect(screen.getByText('chebi')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: FAIL on the four new tests — popover doesn't exist, chips don't render, callback never fires.

- [ ] **Step 3: Implement popover, chip rendering, and onScopeChange wiring**

Replace `frontend/src/components/sparql/ScopeToolbar.tsx` with:

```tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { useOntologies } from '../../hooks/useOntologies'
import {
  ReasoningMode,
  buildScopedEndpoint,
  formatScopeAsFromClauses,
  selectedGraphIris,
} from './scopeUrls'
import type { Ontology } from '../../lib/api'

const BASE_ENDPOINT = '/api/v1/sparql/content'

export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
}

function ontologyLabel(o: Ontology): string {
  return (
    o.shortname
    || o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
    || o.iri
  )
}

function isSelectable(o: Ontology): boolean {
  if (!o.latest_version) return false
  return !['pending', 'failed', 'deprecated'].includes(o.latest_version.status)
}

export function ScopeToolbar({ onScopeChange, onCopy }: ScopeToolbarProps) {
  const { ontologies } = useOntologies()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mode, setMode] = useState<ReasoningMode>('asserted')
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)

  const selectableOntologies = useMemo(() => ontologies.filter(isSelectable), [ontologies])

  const graphIris = useMemo(
    () => selectedGraphIris(selected, mode, selectableOntologies),
    [selected, mode, selectableOntologies],
  )
  const hasSelection = selected.size > 0
  const endpoint = useMemo(() => buildScopedEndpoint(BASE_ENDPOINT, graphIris), [graphIris])

  // Notify the parent on any change to the computed endpoint.
  useEffect(() => {
    onScopeChange(endpoint)
  }, [endpoint, onScopeChange])

  // Close popover on outside click.
  useEffect(() => {
    if (!popoverOpen) return
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setPopoverOpen(false)
        setFilter('')
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [popoverOpen])

  function toggleOntology(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function removeChip(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  function handleCopy() {
    onCopy(formatScopeAsFromClauses(graphIris))
  }

  const q = filter.trim().toLowerCase()
  const popoverList = q
    ? selectableOntologies.filter(o => ontologyLabel(o).toLowerCase().includes(q))
    : selectableOntologies

  const summary = hasSelection
    ? `${selected.size} ontolog${selected.size === 1 ? 'y' : 'ies'} · ${mode} · ${graphIris.length} graph${graphIris.length === 1 ? '' : 's'} scoped`
    : 'No scope selected · whole store queryable'

  const selectedOntologies = selectableOntologies.filter(o => selected.has(o.id))

  return (
    <div
      ref={rootRef}
      style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        position: 'relative',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>Scope:</span>

      {selectedOntologies.map(o => (
        <button
          key={o.id}
          onClick={() => removeChip(o.id)}
          aria-label={`${ontologyLabel(o)} ✕`}
          style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 12,
            border: '1px solid var(--accent)',
            background: 'rgba(88,166,255,0.1)', color: 'var(--accent)',
            cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4,
          }}
        >
          {ontologyLabel(o)} <span style={{ fontSize: 10 }}>✕</span>
        </button>
      ))}

      <button
        onClick={() => setPopoverOpen(v => !v)}
        style={{
          fontSize: 11, padding: '2px 8px', border: '1px dashed var(--border)',
          borderRadius: 12, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        + add ontology…
      </button>

      {popoverOpen && (
        <div
          style={{
            position: 'absolute', top: 'calc(100% + 2px)', left: '1.5rem',
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 4, zIndex: 50, minWidth: 220, maxHeight: 280, overflowY: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            display: 'flex', flexDirection: 'column',
          }}
        >
          <div style={{ padding: 6, borderBottom: '1px solid var(--border)' }}>
            <input
              autoFocus
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Filter ontologies…"
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '4px 8px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 4, color: 'var(--text)', outline: 'none',
              }}
            />
          </div>
          <div>
            {popoverList.length === 0 ? (
              <div style={{ padding: 8, fontSize: 12, color: 'var(--text-dim)' }}>No matches</div>
            ) : (
              popoverList.map(o => {
                const isSelected = selected.has(o.id)
                return (
                  <button
                    key={o.id}
                    onClick={() => toggleOntology(o.id)}
                    style={{
                      display: 'block', width: '100%', textAlign: 'left',
                      padding: '6px 10px', background: 'none', border: 'none',
                      color: isSelected ? 'var(--accent)' : 'var(--text)',
                      fontSize: 12, cursor: 'pointer',
                    }}
                  >
                    {isSelected ? '✓ ' : '  '}{ontologyLabel(o)}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 4 }}>
        {(['asserted', 'inferred', 'both'] as ReasoningMode[]).map(m => (
          <button
            key={m}
            disabled={!hasSelection}
            onClick={() => setMode(m)}
            style={{
              fontSize: 11, padding: '2px 10px', borderRadius: 12,
              border: '1px solid',
              borderColor: mode === m && hasSelection ? 'var(--accent)' : 'var(--border)',
              background: mode === m && hasSelection ? 'rgba(88,166,255,0.1)' : 'transparent',
              color: !hasSelection ? 'var(--text-dim)' : mode === m ? 'var(--accent)' : 'var(--text)',
              opacity: hasSelection ? 1 : 0.45,
              cursor: hasSelection ? 'pointer' : 'not-allowed',
              textTransform: 'capitalize',
            }}
          >
            {m}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, minWidth: 80, fontSize: 11, color: 'var(--text-dim)' }}>
        {summary}
      </div>

      <button
        onClick={handleCopy}
        aria-label="Copy query with scope"
        title="Copy editor query with FROM/FROM NAMED clauses prepended"
        style={{
          fontSize: 14, padding: '2px 8px', border: '1px solid var(--border)',
          borderRadius: 4, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        📋
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: PASS, 8 tests total. (The empty-state tests from Task 3 still pass because the empty default keeps the toolbar in its previous state.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sparql/ScopeToolbar.tsx frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): ScopeToolbar ontology popover, chips, and scope callback

Clicking '+ add ontology…' opens a filterable popover of every
ontology with a ready latest_version. Selecting one adds a chip;
clicking the chip removes it. Every change recomputes the scoped
endpoint URL via buildScopedEndpoint and emits it via onScopeChange.
EOF
)"
```

---

## Task 5: Reasoning mode change fires `onScopeChange`

The mode buttons are already wired to local state; they need to additionally trigger the `onScopeChange` callback when the active mode changes. This is already covered by the `useEffect([endpoint])` from Task 4 — every mode change recomputes `graphIris`, which recomputes `endpoint`, which fires the effect. But we need an explicit test to lock this in, and a test that the segmented control becomes active once a chip is added.

**Files:**
- Modify: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
describe('ScopeToolbar — reasoning mode', () => {
  it('reasoning controls become enabled after first selection', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(screen.getByRole('button', { name: /asserted/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /inferred/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /both/i })).not.toBeDisabled()
  })

  it('switching to Inferred re-emits the endpoint with the inferred URI', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /inferred/i }))
    expect(onScope).toHaveBeenLastCalledWith(
      '/api/v1/sparql/content?default-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred&named-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred'
    )
  })

  it('switching to Both emits four URL params per ontology', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /both/i }))
    const url = onScope.mock.calls.at(-1)?.[0] as string
    expect(url).toContain('default-graph-uri=urn%3Aontology%3AO1%3AV1&')
    expect(url).toContain('named-graph-uri=urn%3Aontology%3AO1%3AV1&')
    expect(url).toContain('default-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred')
    expect(url).toContain('named-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred')
  })
})
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: PASS — these are behavioural assertions over Task 4's code; no new implementation needed. 11 tests total.

If any fail, fix the toolbar logic in `ScopeToolbar.tsx` until they pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
test(sparql): cover reasoning mode transitions in ScopeToolbar

Locks in behaviour: reasoning pills become active after first chip;
switching to Inferred emits the inferred URI; switching to Both
emits four URL params per ontology (default+named × asserted+inferred).
EOF
)"
```

---

## Task 6: Copy icon emits the materialized FROM block

The toolbar's copy icon already calls `onCopy(formatScopeAsFromClauses(graphIris))`. Add tests for: empty selection → empty string; one ontology + Both mode → four lines.

**Files:**
- Modify: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
describe('ScopeToolbar — copy icon', () => {
  it('emits empty string when no ontologies selected', () => {
    const onCopy = vi.fn()
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={onCopy} />))
    fireEvent.click(screen.getByRole('button', { name: /copy query with scope/i }))
    expect(onCopy).toHaveBeenCalledWith('')
  })

  it('emits FROM + FROM NAMED lines for a selected ontology in Both mode', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onCopy = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={onCopy} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    fireEvent.click(screen.getByRole('button', { name: /both/i }))
    fireEvent.click(screen.getByRole('button', { name: /copy query with scope/i }))
    expect(onCopy).toHaveBeenLastCalledWith(
      'FROM <urn:ontology:O1:V1>\nFROM NAMED <urn:ontology:O1:V1>\n' +
      'FROM <urn:ontology:O1:V1:inferred>\nFROM NAMED <urn:ontology:O1:V1:inferred>\n'
    )
  })
})
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: PASS, 13 tests total.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
test(sparql): cover copy icon FROM-block materialization

Empty selection emits ''; one ontology in Both mode emits the
four FROM/FROM NAMED lines for asserted + inferred graphs.
EOF
)"
```

---

## Task 7: Wire ScopeToolbar into Sparql page; remove GraphsPanel

Replace the inline `GraphsPanel` with the new `ScopeToolbar`. On `onScopeChange`, call `tab.setEndpoint(endpoint)` on the active Yasgui tab so subsequent queries POST to the scoped URL.

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`
- Modify: `frontend/src/pages/Sparql.test.tsx`

- [ ] **Step 1: Update the Sparql page tests to expect ScopeToolbar (replacing the GraphsPanel assertions)**

Open `frontend/src/pages/Sparql.test.tsx`. The current mock returns `{ getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }) }`. Extend the Yasgui mock so `getTab()` also exposes `setEndpoint` and so `getYasqe()` exposes `getValue`:

```tsx
vi.mock('@triply/yasgui', () => ({
  default: vi.fn().mockImplementation(() => ({
    getTab: () => ({
      getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => 'SELECT * WHERE { ?s ?p ?o }') }),
      setEndpoint: vi.fn(),
    }),
    destroy: vi.fn(),
  })),
}))
```

Locate any assertion that references the old `Graphs (n)` disclosure (search the test file for the text `Graphs`) and replace it with an assertion on the new toolbar, e.g.:

```tsx
expect(await screen.findByText(/No scope selected/i)).toBeInTheDocument()
```

- [ ] **Step 2: Run the existing Sparql page tests to confirm they fail**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx --reporter=basic`

Expected: FAIL — the page still renders `GraphsPanel`; the new "No scope selected" string is absent.

- [ ] **Step 3: Modify `frontend/src/pages/Sparql.tsx`**

Make these edits, in order:

1. Add the import at the top of the file:

```tsx
import { ScopeToolbar } from '../components/sparql/ScopeToolbar'
```

2. Delete the entire `GraphsPanel` function (currently around lines 47-140) and the inline `toEntries` / `GraphEntry` / `iriSlug` helpers that are no longer referenced.

3. Inside the `Sparql` component, remove these no-longer-used pieces:
- The `namedGraphsRef`, the `entries = useMemo(...)`, the `useEffect` that syncs `namedGraphsRef.current`, and the `namedGraphs: () => namedGraphsRef.current` line inside the Yasgui constructor's `yasqe` config.
- The `<GraphsPanel entries={entries} />` JSX element.
- The `useOntologies` import and call (the new toolbar fetches its own data via its own `useOntologies` call).

4. Add a scope-change handler that calls `setEndpoint` on the active Yasgui tab, and a copy handler that prepends the FROM block to the current editor text:

```tsx
function handleScopeChange(endpoint: string) {
  yasguiRef.current?.getTab()?.setEndpoint(endpoint)
}

function handleCopy(fromBlock: string) {
  const current = yasguiRef.current?.getTab()?.getYasqe()?.getValue() ?? ''
  const text = fromBlock ? `${fromBlock}${current}` : current
  navigator.clipboard?.writeText(text).catch(() => {})
}
```

5. Replace the `<GraphsPanel ... />` JSX with:

```tsx
<ScopeToolbar onScopeChange={handleScopeChange} onCopy={handleCopy} />
```

The expected final shape of the return statement:

```tsx
return (
  <div style={{
    height: 'calc(100vh - var(--nav-height))',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
    background: 'var(--bg)',
  }}>
    <div style={{
      padding: '0.6rem 1.5rem', borderBottom: '1px solid var(--border)',
      background: 'var(--bg-secondary)', flexShrink: 0,
      display: 'flex', alignItems: 'baseline', gap: '0.75rem',
    }}>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text)' }}>SPARQL</h1>
      <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
        Query the full ontology graph · read-only · SPARQL 1.1
      </span>
    </div>
    <ScopeToolbar onScopeChange={handleScopeChange} onCopy={handleCopy} />
    {queryError && (
      <div style={{
        padding: '0.4rem 1.5rem', background: 'rgba(239,68,68,0.1)',
        borderBottom: '1px solid rgba(239,68,68,0.3)',
        color: '#f87171', fontSize: 'var(--font-size-sm)', flexShrink: 0,
      }}>{queryError}</div>
    )}
    <div style={{ flex: 1, display: 'flex', flexDirection: 'row', overflow: 'hidden', minHeight: 0 }}>
      <QuerySidebar yasguiRef={yasguiRef} />
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto' }} />
    </div>
  </div>
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx src/components/sparql/ --reporter=basic`

Expected: PASS — Sparql page tests find "No scope selected"; all ScopeToolbar tests still pass.

If the Sparql page tests assert on `Graphs (n)` text or `setValue` invocation patterns that no longer match, update them to match the new toolbar's behaviour.

- [ ] **Step 5: TypeScript sanity check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "Sparql\.tsx|ScopeToolbar|scopeUrls" | grep -v "\.test\."`

Expected: no output (no TS errors in the modified files).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Sparql.tsx frontend/src/pages/Sparql.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): wire ScopeToolbar into Sparql page; remove GraphsPanel

Replace the read-only GraphsPanel disclosure with the new
ScopeToolbar. Scope changes call tab.setEndpoint() so every
subsequent Yasgui request POSTs to a scoped URL with
default-graph-uri + named-graph-uri parameters. The copy icon
prepends the equivalent FROM/FROM NAMED block to the editor's
current query text and writes it to clipboard.
EOF
)"
```

---

## Task 8: Final end-to-end sweep

Run the whole frontend test suite and tsc to catch anything else that referenced the old `GraphsPanel` or stale Yasgui mock shape.

**Files:**
- (no source changes expected; fix only if a regression turns up)

- [ ] **Step 1: Full frontend test run**

Run: `cd frontend && npx vitest run --reporter=basic 2>&1 | tail -25`

Expected: all tests pass. If a test outside `src/components/sparql/` or `src/pages/Sparql.test.tsx` fails because it referenced the old toolbar text or relied on the `Graphs (n)` disclosure, fix it minimally to match the new toolbar UI.

- [ ] **Step 2: Full project tsc check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules/@tanstack" | grep -v "OwlProfileSection" | grep -v "OwlProfile\.test\.tsx" | grep -v "Sparql\.test\.tsx.*TS2322" | head -20`

Expected: no new errors in `Sparql.tsx`, `ScopeToolbar.tsx`, or `scopeUrls.ts`. Pre-existing errors in unrelated files (e.g. `OwlProfileSection`, react-query private identifiers) are not caused by this change and remain ignored.

- [ ] **Step 3: Manual smoke test**

Open the dev server (Vite should already be running on port 5173):
1. Navigate to `/sparql`.
2. Verify the new toolbar appears in place of the old `Graphs (n)` disclosure.
3. Click `+ add ontology…`; verify the popover lists ready ontologies; pick one. Chip appears.
4. Verify the reasoning pills became enabled. Switch to `Inferred`. Run the default query — it should now query only that ontology's inferred graph.
5. Click the copy icon. Paste into a text editor. Confirm the materialized `FROM` / `FROM NAMED` lines appear above the original query.
6. Remove the chip. Verify reasoning pills disable and the endpoint reverts to the unparameterized base.

- [ ] **Step 4: Final commit (only if any fixes were needed)**

If Step 1, 2, or 3 surfaced anything that required a code change, commit it:

```bash
git add -A
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(sparql): post-merge cleanup for ScopeToolbar rollout

Fix-ups discovered during the end-to-end sweep after replacing
GraphsPanel with ScopeToolbar.
EOF
)"
```

If nothing changed, this task ends without a commit.

---

## Out of scope

Per the spec, these are explicit non-goals for this plan and belong to later sub-projects:

- Term/IRI autocomplete in the editor (sub-project C)
- Embedded starter-query rail (sub-project D)
- Result-pane enrichment (sub-project E)
- Cross-version diff mode (sub-project F)
- Persisting scope across page loads
- Parsing existing `FROM` clauses out of saved queries
- Adding a QLever metadata endpoint toggle
