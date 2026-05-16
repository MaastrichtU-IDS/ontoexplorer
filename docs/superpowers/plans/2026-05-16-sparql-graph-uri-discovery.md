# SPARQL Graph URI Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsible "Graphs" panel above the YASGUI editor and YASQE named-graph autocomplete so users can discover and copy `urn:ontology:{id}:{version_id}` graph URIs for use in `GRAPH` / `FROM NAMED` clauses.

**Architecture:** A `GraphsPanel` component (defined in `Sparql.tsx`) receives a derived list of `{ name, graphUri }` entries from the existing `useOntologies` hook. The `Sparql` component also passes the URI list to YASGUI via the `yasqe.namedGraphs` config, using a ref so it stays current after the async load without re-initialising YASGUI.

**Tech Stack:** React 18 (functional components, hooks), TypeScript, `@triply/yasgui` v4, Vitest + jsdom + @testing-library/react.

---

## File map

| File | Action |
|------|--------|
| `frontend/src/pages/Sparql.tsx` | Add `iriSlug`, `toEntries`, `GraphsPanel`; wire `useOntologies`, `namedGraphsRef`, `GraphsPanel` into `Sparql` |
| `frontend/src/pages/Sparql.test.tsx` | Create — tests for panel toggle, filter, copy, empty state |

---

## Task 1: Write failing tests

**Files:**
- Create: `frontend/src/pages/Sparql.test.tsx`

- [ ] **Step 1: Create the test file**

```typescript
// frontend/src/pages/Sparql.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sparql from './Sparql'

vi.mock('@triply/yasgui', () => ({
  default: vi.fn().mockImplementation(() => ({
    getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }),
    destroy: vi.fn(),
  })),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: vi.fn(),
}))

import { useOntologies } from '../hooks/useOntologies'

const ONTOLOGIES = [
  {
    id: 'abc1',
    iri: 'http://purl.obolibrary.org/obo/go.owl',
    shortname: 'go',
    title: 'Gene Ontology',
    created_at: '2024-01-01',
    latest_version: {
      id: 'v1', ontology_id: 'abc1', status: 'ready',
      format: 'owl', version_iri: null, sha256: '',
    },
  },
  {
    id: 'abc2',
    iri: 'http://purl.obolibrary.org/obo/mondo.owl',
    shortname: null,
    title: 'Mondo',
    created_at: '2024-01-01',
    latest_version: {
      id: 'v2', ontology_id: 'abc2', status: 'ready',
      format: 'owl', version_iri: null, sha256: '',
    },
  },
  {
    id: 'abc3',
    iri: 'http://example.org/pending.owl',
    shortname: 'pending-ont',
    title: 'Pending',
    created_at: '2024-01-01',
    latest_version: {
      id: 'v3', ontology_id: 'abc3', status: 'pending',
      format: 'owl', version_iri: null, sha256: '',
    },
  },
]

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(useOntologies).mockReturnValue({ ontologies: ONTOLOGIES, isLoading: false })
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

test('shows Graphs toggle with count of ready ontologies, panel collapsed by default', () => {
  wrap(<Sparql />)
  // Only 2 ready ontologies (pending one excluded)
  expect(screen.getByRole('button', { name: /Graphs \(2\)/i })).toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Filter ontologies…')).not.toBeInTheDocument()
})

test('clicking toggle expands panel showing filter input and ontology rows', () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  expect(screen.getByPlaceholderText('Filter ontologies…')).toBeInTheDocument()
  expect(screen.getByText('go')).toBeInTheDocument()      // shortname used
  expect(screen.getByText('mondo')).toBeInTheDocument()   // iri slug used (no shortname)
  expect(screen.queryByText('pending-ont')).not.toBeInTheDocument() // excluded (status pending)
})

test('filter input narrows rows by name', () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  fireEvent.change(screen.getByPlaceholderText('Filter ontologies…'), { target: { value: 'go' } })
  expect(screen.getByText('go')).toBeInTheDocument()
  expect(screen.queryByText('mondo')).not.toBeInTheDocument()
})

test('shows empty message when filter matches nothing', () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  fireEvent.change(screen.getByPlaceholderText('Filter ontologies…'), { target: { value: 'zzz' } })
  expect(screen.getByText('No matching ontologies')).toBeInTheDocument()
})

test('copy button writes correct graph URI to clipboard', async () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  const copyBtns = screen.getAllByRole('button', { name: 'Copy' })
  fireEvent.click(copyBtns[0])
  await waitFor(() => {
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('urn:ontology:abc1:v1')
  })
  expect(screen.getByText('✓')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
cd frontend && npx vitest run src/pages/Sparql.test.tsx
```

Expected: 5 failures — `GraphsPanel` does not exist yet.

---

## Task 2: Implement GraphsPanel and wire Sparql

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`

- [ ] **Step 3: Replace `Sparql.tsx` with the full implementation**

```typescript
// frontend/src/pages/Sparql.tsx
import { useEffect, useRef, useState } from 'react'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'
import './Sparql.css'
import { useOntologies } from '../hooks/useOntologies'
import type { Ontology } from '../lib/api'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

# All triples are stored in named graphs (one per ontology version).
# Use GRAPH ?g { ... } to query across all ontologies, or bind ?g to
# a specific graph IRI to query a single ontology version.

SELECT ?class ?label WHERE {
  GRAPH ?g {
    ?class a owl:Class .
    OPTIONAL { ?class rdfs:label ?label }
  }
}
LIMIT 100`

// ── Helpers ──────────────────────────────────────────────────────────────────

function iriSlug(iri: string): string {
  return (
    iri.replace(/[/#]+$/, '').split(/[/#]/).pop()
      ?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '') ?? iri
  )
}

interface GraphEntry { name: string; graphUri: string }

function toEntries(ontologies: Ontology[]): GraphEntry[] {
  return ontologies
    .filter(o =>
      o.latest_version &&
      !['pending', 'failed', 'deprecated'].includes(o.latest_version.status)
    )
    .map(o => ({
      name: o.shortname ?? iriSlug(o.iri),
      graphUri: `urn:ontology:${o.id}:${o.latest_version!.id}`,
    }))
}

// ── GraphsPanel ───────────────────────────────────────────────────────────────

function GraphsPanel({ entries }: { entries: GraphEntry[] }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [copied, setCopied] = useState<string | null>(null)

  const q = filter.trim().toLowerCase()
  const visible = q
    ? entries.filter(e =>
        e.name.toLowerCase().includes(q) || e.graphUri.toLowerCase().includes(q)
      )
    : entries

  function copyUri(uri: string) {
    navigator.clipboard.writeText(uri)
    setCopied(uri)
    setTimeout(() => setCopied(null), 1500)
  }

  return (
    <div style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0 }}>
      <div style={{
        padding: '0 1.5rem', height: 32,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <button
          onClick={() => setOpen(v => !v)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', padding: 0,
          }}
        >
          Graphs ({entries.length}) {open ? '▴' : '▾'}
        </button>
        {!open && (
          <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
            browse named graph URIs for GRAPH / FROM NAMED clauses
          </span>
        )}
      </div>
      {open && (
        <div style={{ padding: '0 1.5rem 0.75rem' }}>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Filter ontologies…"
            style={{
              width: '100%', boxSizing: 'border-box',
              padding: '4px 8px', fontSize: 12,
              background: 'var(--bg)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text)',
              outline: 'none', marginBottom: 6,
            }}
          />
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {visible.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 12, padding: '8px 0' }}>
                No matching ontologies
              </div>
            ) : (
              visible.map(e => (
                <div key={e.graphUri} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0' }}>
                  <span style={{ fontSize: 12, color: 'var(--text)', flexShrink: 0, minWidth: 80 }}>
                    {e.name}
                  </span>
                  <span style={{
                    fontSize: 11, color: 'var(--text-dim)', fontFamily: 'monospace',
                    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {e.graphUri}
                  </span>
                  <button
                    onClick={() => copyUri(e.graphUri)}
                    style={{
                      background: 'none', border: '1px solid var(--border)',
                      borderRadius: 3, padding: '1px 7px', fontSize: 11,
                      color: copied === e.graphUri ? 'var(--accent-green, #3fb950)' : 'var(--text-dim)',
                      cursor: 'pointer', flexShrink: 0,
                    }}
                  >
                    {copied === e.graphUri ? '✓' : 'Copy'}
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<InstanceType<typeof Yasgui> | null>(null)
  const namedGraphsRef = useRef<string[]>([])
  const { ontologies } = useOntologies()

  const entries = toEntries(ontologies)

  useEffect(() => {
    namedGraphsRef.current = entries.map(e => e.graphUri)
  }, [entries])

  useEffect(() => {
    if (!containerRef.current || yasguiRef.current) return

    yasguiRef.current = new Yasgui(containerRef.current, {
      persistenceId: null,
      yasqe: {
        namedGraphs: () => namedGraphsRef.current,
      },
      requestConfig: {
        endpoint: '/api/v1/sparql/content',
        method: 'POST',
        acceptHeaderSelect: 'application/sparql-results+json',
        acceptHeaderGraph: 'text/turtle',
      },
      endpointCatalogueOptions: {
        getData: () => [
          { endpoint: '/api/v1/sparql/content', title: 'OntoExplorer — Ontology Content' },
        ],
      },
    })
    yasguiRef.current.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)

    return () => {
      if (yasguiRef.current) {
        if (typeof yasguiRef.current.destroy === 'function') {
          yasguiRef.current.destroy()
        } else if (containerRef.current) {
          containerRef.current.innerHTML = ''
        }
        yasguiRef.current = null
      }
    }
  }, [])

  return (
    <div style={{
      height: 'calc(100vh - var(--nav-height))',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: 'var(--bg)',
    }}>
      <div style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'baseline',
        gap: '0.75rem',
      }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text)' }}>
          SPARQL
        </h1>
        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
          Query the full ontology graph · read-only · SPARQL 1.1
        </span>
      </div>
      <GraphsPanel entries={entries} />
      <div ref={containerRef} style={{ flex: 1, minHeight: 0 }} />
    </div>
  )
}
```

- [ ] **Step 4: Run tests to confirm all pass**

```bash
cd frontend && npx vitest run src/pages/Sparql.test.tsx
```

Expected output:
```
 ✓ src/pages/Sparql.test.tsx (5)
   ✓ shows Graphs toggle with count of ready ontologies, panel collapsed by default
   ✓ clicking toggle expands panel showing filter input and ontology rows
   ✓ filter input narrows rows by name
   ✓ shows empty message when filter matches nothing
   ✓ copy button writes correct graph URI to clipboard

 Test Files  1 passed (1)
 Tests       5 passed (5)
```

If the `namedGraphs` option causes a TypeScript error because YASGUI's config type doesn't expose `yasqe` at the top level, cast it:

```typescript
yasguiRef.current = new Yasgui(containerRef.current, {
  persistenceId: null,
  yasqe: {
    namedGraphs: () => namedGraphsRef.current,
  },
  // ...
} as any)
```

- [ ] **Step 5: Run the full frontend test suite to confirm no regressions**

```bash
cd frontend && npx vitest run
```

Expected: all pre-existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Sparql.tsx frontend/src/pages/Sparql.test.tsx
git commit -m "feat(sparql): add graph URI discovery panel and YASQE namedGraphs autocomplete"
```
