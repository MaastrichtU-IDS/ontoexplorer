# SPARQL Cross-Version Diff Query Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Single↔Diff toggle to the SPARQL page so users can run a single SELECT query against two `(version, reasoning mode)` tuples in parallel and see a unified row-level diff with status badges.

**Architecture:** Frontend-only. The scope toolbar grows a mode toggle; in Diff mode it shows two graph-picker rows (each: ontology + version + reasoning mode). The page subscribes to Yasqe's `query` event — in Diff mode it aborts the default fetch and fires two parallel scoped POSTs to `/sparql/content`, then computes set-diff over the JSON bindings client-side. A new `DiffQueryView` component renders the unified table with `Only From / Only To / Both` status badges; the native Yasr result pane is hidden via `display: none` while in Diff mode.

**Tech Stack:** React 18 + TypeScript, Vitest + jsdom, @testing-library/react, @triply/yasgui v4. Backend untouched.

**Spec:** [`docs/superpowers/specs/2026-05-21-sparql-diff-query-mode-design.md`](../specs/2026-05-21-sparql-diff-query-mode-design.md)

---

## File Map

| Path | Role |
|---|---|
| `frontend/src/components/sparql/scopeUrls.ts` | Add `endpointForVersion(version, mode): string` helper. |
| `frontend/src/components/sparql/scopeUrls.test.ts` | Tests for the new helper. |
| `frontend/src/components/sparql/diffBindings.ts` | Pure helpers: `canonicalRow`, `diffBindings`. |
| `frontend/src/components/sparql/diffBindings.test.ts` | Unit tests. |
| `frontend/src/components/sparql/DiffQueryView.tsx` | Unified-table component with filter pills + sort + status badges + error banners. |
| `frontend/src/components/sparql/DiffQueryView.test.tsx` | Component tests. |
| `frontend/src/components/sparql/ScopeToolbar.tsx` | Add `Single ↔ Diff` toggle, diff pickers (version + mode per side), `onDiffScopeChange` callback. |
| `frontend/src/components/sparql/ScopeToolbar.test.tsx` | New tests for Diff-mode UI. |
| `frontend/src/pages/Sparql.tsx` | Subscribe to `yasqe.on('query', ...)`, run two fetches in Diff mode, mount `DiffQueryView`, hide Yasr `.yasr` element. |
| `frontend/src/pages/Sparql.test.tsx` | One integration test: Diff mode + Run → two fetches → diff renders. |

---

## Task 1: `endpointForVersion` helper

Small pure addition to the existing `scopeUrls.ts`. Builds a `/api/v1/sparql/content?…` URL with `default-graph-uri` + `named-graph-uri` parameters for a single `(version, mode)` tuple.

**Files:**
- Modify: `frontend/src/components/sparql/scopeUrls.ts`
- Modify: `frontend/src/components/sparql/scopeUrls.test.ts`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/scopeUrls.test.ts`:

```typescript
import { endpointForVersion } from './scopeUrls'
import type { OntologyVersion } from '../../lib/api'

const V1: OntologyVersion = {
  id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
  version_iri: null, sha256: '', triple_count: 0, download_url: '', created_at: '',
}

describe('endpointForVersion', () => {
  const BASE = '/api/v1/sparql/content'

  it('asserted mode emits both default and named graph params for the asserted URI', () => {
    const url = endpointForVersion(V1, 'asserted')
    const enc = encodeURIComponent('urn:ontology:O1:V1')
    expect(url).toBe(`${BASE}?default-graph-uri=${enc}&named-graph-uri=${enc}`)
  })

  it('inferred mode uses the :inferred suffix', () => {
    const url = endpointForVersion(V1, 'inferred')
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1:inferred'))
    expect(url).not.toContain(encodeURIComponent('urn:ontology:O1:V1&'))
  })

  it('both mode emits four params (asserted + inferred)', () => {
    const url = endpointForVersion(V1, 'both')
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1'))
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1:inferred'))
    // Count: 4 params (2 URIs × default+named)
    expect((url.match(/default-graph-uri=/g) ?? []).length).toBe(2)
    expect((url.match(/named-graph-uri=/g) ?? []).length).toBe(2)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx vitest run src/components/sparql/scopeUrls.test.ts --reporter=basic
```

Expected: FAIL — `endpointForVersion` doesn't exist.

- [ ] **Step 3: Add the helper**

Append to `frontend/src/components/sparql/scopeUrls.ts` (after the existing exports):

```typescript
import type { OntologyVersion } from '../../lib/api'

const BASE_ENDPOINT = '/api/v1/sparql/content'

/**
 * Build a scoped /sparql/content endpoint URL for a single (version, mode)
 * tuple. Convenience over `buildScopedEndpoint` for callers that already have
 * the OntologyVersion in hand (e.g. the diff-mode toolbar).
 */
export function endpointForVersion(version: OntologyVersion, mode: ReasoningMode): string {
  const iris: string[] = []
  if (mode === 'asserted' || mode === 'both') {
    iris.push(assertedGraphIri(version.ontology_id, version.id))
  }
  if (mode === 'inferred' || mode === 'both') {
    iris.push(inferredGraphIri(version.ontology_id, version.id))
  }
  return buildScopedEndpoint(BASE_ENDPOINT, iris)
}
```

(If `BASE_ENDPOINT` is already declared as a top-level const in this file, don't redeclare it — reuse the existing constant.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
npx vitest run src/components/sparql/scopeUrls.test.ts --reporter=basic
```

Expected: PASS — both pre-existing tests AND the 3 new ones.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/scopeUrls.ts frontend/src/components/sparql/scopeUrls.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): endpointForVersion helper for diff-mode URL construction

Small wrapper over the existing assertedGraphIri / inferredGraphIri
/ buildScopedEndpoint pipeline that takes a single (version, mode)
tuple — convenience for the diff-mode toolbar that owns two such
tuples (From / To) and needs to build the matching scoped endpoint
URLs without going through the set-based selection model.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `diffBindings` — canonical row + set-diff helpers

Pure module that computes the row-level diff over two SPARQL JSON binding sets.

**Files:**
- Create: `frontend/src/components/sparql/diffBindings.ts`
- Create: `frontend/src/components/sparql/diffBindings.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/diffBindings.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { canonicalRow, diffBindings, BindingRow, BindingValue } from './diffBindings'

const uri = (v: string): BindingValue => ({ type: 'uri', value: v })
const lit = (v: string, lang?: string, datatype?: string): BindingValue =>
  ({ type: 'literal', value: v, ...(lang ? { 'xml:lang': lang } : {}), ...(datatype ? { datatype } : {}) })

describe('canonicalRow', () => {
  it('produces the same string regardless of insertion order', () => {
    const a: BindingRow = { x: uri('http://a/'), y: lit('foo') }
    const b: BindingRow = { y: lit('foo'), x: uri('http://a/') }
    expect(canonicalRow(a)).toBe(canonicalRow(b))
  })

  it('distinguishes URI from literal with the same value', () => {
    expect(canonicalRow({ x: uri('foo') })).not.toBe(canonicalRow({ x: lit('foo') }))
  })

  it('distinguishes literals with different language tags', () => {
    expect(canonicalRow({ x: lit('foo', 'en') })).not.toBe(canonicalRow({ x: lit('foo', 'de') }))
  })

  it('distinguishes literals with different datatypes', () => {
    expect(canonicalRow({ x: lit('1', undefined, 'http://www.w3.org/2001/XMLSchema#integer') }))
      .not.toBe(canonicalRow({ x: lit('1') }))
  })

  it('treats a missing variable as different from a present-but-empty one', () => {
    expect(canonicalRow({ x: uri('a') })).not.toBe(canonicalRow({ x: uri('a'), y: lit('') }))
  })
})

describe('diffBindings', () => {
  it('returns all-Both when sides are identical', () => {
    const rows: BindingRow[] = [{ x: uri('a') }, { x: uri('b') }]
    const result = diffBindings(rows, rows)
    expect(result.onlyFrom).toEqual([])
    expect(result.onlyTo).toEqual([])
    expect(result.both).toHaveLength(2)
  })

  it('returns all-onlyFrom + all-onlyTo when sides are disjoint', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    const to: BindingRow[] = [{ x: uri('b') }]
    const result = diffBindings(from, to)
    expect(result.onlyFrom).toEqual(from)
    expect(result.onlyTo).toEqual(to)
    expect(result.both).toEqual([])
  })

  it('partitions correctly for overlapping sides', () => {
    const from: BindingRow[] = [{ x: uri('a') }, { x: uri('b') }, { x: uri('c') }]
    const to:   BindingRow[] = [{ x: uri('b') }, { x: uri('c') }, { x: uri('d') }]
    const result = diffBindings(from, to)
    expect(result.onlyFrom).toEqual([{ x: uri('a') }])
    expect(result.onlyTo).toEqual([{ x: uri('d') }])
    expect(result.both).toHaveLength(2)
  })

  it('preserves From-side ordering for Both rows', () => {
    const from: BindingRow[] = [{ x: uri('c') }, { x: uri('a') }, { x: uri('b') }]
    const to:   BindingRow[] = [{ x: uri('a') }, { x: uri('b') }, { x: uri('c') }]
    const { both } = diffBindings(from, to)
    expect(both.map(r => (r.x as { value: string }).value)).toEqual(['c', 'a', 'b'])
  })

  it('returns the union of variable names in vars', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    const to:   BindingRow[] = [{ y: uri('b') }]
    const result = diffBindings(from, to)
    expect(new Set(result.vars)).toEqual(new Set(['x', 'y']))
  })

  it('handles empty sides', () => {
    expect(diffBindings([], [])).toEqual({ onlyFrom: [], onlyTo: [], both: [], vars: [] })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npx vitest run src/components/sparql/diffBindings.test.ts --reporter=basic
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/sparql/diffBindings.ts`:

```typescript
/** A single binding value as returned in SPARQL Protocol JSON results. */
export interface BindingValue {
  type: 'uri' | 'literal' | 'bnode'
  value: string
  'xml:lang'?: string
  datatype?: string
}

/** One row of SPARQL bindings — a map from variable name to value. */
export type BindingRow = Record<string, BindingValue>

export interface DiffResult {
  onlyFrom: BindingRow[]
  onlyTo: BindingRow[]
  both: BindingRow[]
  vars: string[]
}

/**
 * Produce a stable string key for a binding row. Two rows with the same
 * bindings (modulo variable insertion order) yield the same key. Different
 * types / langs / datatypes produce different keys even when `value` matches.
 *
 * Note: a missing variable is distinguishable from a present binding because
 * variable names are part of the canonical key.
 */
export function canonicalRow(row: BindingRow): string {
  const keys = Object.keys(row).sort()
  const parts = keys.map(k => {
    const v = row[k]
    const lang = v['xml:lang'] ?? ''
    const dt = v.datatype ?? ''
    return `${k}\x01${v.type}\x02${v.value}\x03${lang}\x04${dt}`
  })
  return parts.join('\x1f')
}

/**
 * Set-diff two SPARQL binding lists. Returns three buckets (only-on-from-side,
 * only-on-to-side, present-on-both) plus the union of variable names.
 *
 * Order preservation:
 *   - `both` preserves From-side order (so the user sees them as they appeared
 *     in the From-side response).
 *   - `onlyFrom` / `onlyTo` preserve their respective side's order.
 */
export function diffBindings(from: BindingRow[], to: BindingRow[]): DiffResult {
  const fromKeys = new Set(from.map(canonicalRow))
  const toKeys = new Set(to.map(canonicalRow))

  const onlyFrom: BindingRow[] = []
  const both: BindingRow[] = []
  for (const r of from) {
    if (toKeys.has(canonicalRow(r))) both.push(r)
    else onlyFrom.push(r)
  }

  const onlyTo: BindingRow[] = []
  for (const r of to) {
    if (!fromKeys.has(canonicalRow(r))) onlyTo.push(r)
  }

  const varSet = new Set<string>()
  for (const r of from) for (const k of Object.keys(r)) varSet.add(k)
  for (const r of to) for (const k of Object.keys(r)) varSet.add(k)

  return { onlyFrom, onlyTo, both, vars: Array.from(varSet).sort() }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npx vitest run src/components/sparql/diffBindings.test.ts --reporter=basic
```

Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/diffBindings.ts frontend/src/components/sparql/diffBindings.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): row-level diff helpers for SPARQL binding sets

canonicalRow produces a stable key per row that distinguishes URI
vs literal vs bnode, language tags, and datatypes. diffBindings
partitions two binding lists into { onlyFrom, onlyTo, both, vars }
preserving each side's input order; both[] uses From-side ordering.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `DiffQueryView` — unified table with status badges

A self-contained component that takes two binding lists + their query metadata and renders the unified diff table.

**Files:**
- Create: `frontend/src/components/sparql/DiffQueryView.tsx`
- Create: `frontend/src/components/sparql/DiffQueryView.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/DiffQueryView.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { DiffQueryView } from './DiffQueryView'
import type { BindingRow } from './diffBindings'

const uri = (v: string) => ({ type: 'uri' as const, value: v })

describe('DiffQueryView', () => {
  it('renders status badges for onlyFrom / onlyTo / both', () => {
    const from: BindingRow[] = [{ x: uri('http://a') }, { x: uri('http://b') }]
    const to:   BindingRow[] = [{ x: uri('http://b') }, { x: uri('http://c') }]
    render(<DiffQueryView from={from} to={to} fromError={null} toError={null} />)
    expect(screen.getByText('Only From')).toBeInTheDocument()
    expect(screen.getByText('Only To')).toBeInTheDocument()
    expect(screen.getByText('Both')).toBeInTheDocument()
  })

  it('filter pills show counts', () => {
    const from: BindingRow[] = [{ x: uri('a') }, { x: uri('b') }, { x: uri('c') }]
    const to:   BindingRow[] = [{ x: uri('b') }, { x: uri('c') }, { x: uri('d') }]
    render(<DiffQueryView from={from} to={to} fromError={null} toError={null} />)
    // pills: All (4), Only From (1), Only To (1), Both (2)
    expect(screen.getByText(/All \(4\)/)).toBeInTheDocument()
    expect(screen.getByText(/Only From \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Only To \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Both \(2\)/)).toBeInTheDocument()
  })

  it('filter pill narrows to one bucket', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    const to:   BindingRow[] = [{ x: uri('b') }]
    render(<DiffQueryView from={from} to={to} fromError={null} toError={null} />)
    fireEvent.click(screen.getByRole('button', { name: /Only From \(1\)/ }))
    // After filtering, the To-row is hidden
    expect(screen.queryByText('http://b')).not.toBeInTheDocument()
    expect(screen.getByText('http://a')).toBeInTheDocument()
  })

  it('shows banner when one side errored', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    render(<DiffQueryView from={from} to={[]} fromError={null} toError="boom" />)
    expect(screen.getByText(/To side failed/i)).toBeInTheDocument()
  })

  it('shows empty-results message when both sides empty and no errors', () => {
    render(<DiffQueryView from={[]} to={[]} fromError={null} toError={null} />)
    expect(screen.getByText(/no results on either side/i)).toBeInTheDocument()
  })

  it('renders IRI cells as a.iri so the page-level click handler can intercept', () => {
    const from: BindingRow[] = [{ x: uri('http://example.org/X') }]
    const { container } = render(<DiffQueryView from={from} to={[]} fromError={null} toError={null} />)
    const anchor = container.querySelector('a.iri')
    expect(anchor).not.toBeNull()
    expect(anchor?.getAttribute('href')).toBe('http://example.org/X')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npx vitest run src/components/sparql/DiffQueryView.test.tsx --reporter=basic
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/sparql/DiffQueryView.tsx`:

```tsx
import { useMemo, useState } from 'react'
import { BindingRow, BindingValue, diffBindings } from './diffBindings'

type Status = 'onlyFrom' | 'onlyTo' | 'both'
type Filter = 'all' | Status

interface Props {
  from: BindingRow[]
  to: BindingRow[]
  fromError: string | null
  toError: string | null
}

const STATUS_LABEL: Record<Status, string> = {
  onlyFrom: 'Only From',
  onlyTo: 'Only To',
  both: 'Both',
}

const STATUS_COLOR: Record<Status, { bg: string; border: string; color: string }> = {
  onlyFrom: { bg: 'rgba(248,81,73,0.10)',  border: 'rgba(248,81,73,0.35)',  color: '#f85149' },
  onlyTo:   { bg: 'rgba(63,185,80,0.10)',  border: 'rgba(63,185,80,0.35)',  color: '#3fb950' },
  both:     { bg: 'rgba(125,133,144,0.10)', border: 'rgba(125,133,144,0.35)', color: 'var(--text-dim)' },
}

function renderValue(v: BindingValue) {
  if (v.type === 'uri') {
    return <a className="iri" href={v.value}>{v.value}</a>
  }
  if (v.type === 'bnode') {
    return <span style={{ fontFamily: 'monospace', color: 'var(--text-dim)' }}>_:{v.value}</span>
  }
  // literal
  const lang = v['xml:lang']
  return (
    <span>
      <span>{v.value}</span>
      {lang && <span style={{ color: 'var(--text-dim)', fontSize: 10, marginLeft: 4 }}>@{lang}</span>}
    </span>
  )
}

export function DiffQueryView({ from, to, fromError, toError }: Props) {
  const { onlyFrom, onlyTo, both, vars } = useMemo(() => diffBindings(from, to), [from, to])
  const [filter, setFilter] = useState<Filter>('all')

  const allRows: Array<{ status: Status; row: BindingRow }> = useMemo(() => {
    return [
      ...onlyFrom.map(row => ({ status: 'onlyFrom' as const, row })),
      ...onlyTo.map(row => ({ status: 'onlyTo' as const, row })),
      ...both.map(row => ({ status: 'both' as const, row })),
    ]
  }, [onlyFrom, onlyTo, both])

  const visible = useMemo(() => {
    if (filter === 'all') return allRows
    return allRows.filter(r => r.status === filter)
  }, [allRows, filter])

  const totalCount = allRows.length
  const empty = totalCount === 0 && !fromError && !toError

  const banner = (() => {
    if (fromError && toError) {
      return `Both sides failed: From — ${fromError} · To — ${toError}`
    }
    if (fromError) return `From side failed: ${fromError}`
    if (toError) return `To side failed: ${toError}`
    return null
  })()

  return (
    <div style={{ padding: '1rem', overflowY: 'auto', height: '100%', boxSizing: 'border-box' }}>
      {banner && (
        <div style={{
          background: 'rgba(248,81,73,0.10)', border: '1px solid rgba(248,81,73,0.35)',
          color: '#f85149', borderRadius: 4, padding: '6px 10px', fontSize: 12, marginBottom: 8,
        }}>
          {banner}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {[
          { k: 'all'      as const, n: totalCount },
          { k: 'onlyFrom' as const, n: onlyFrom.length },
          { k: 'onlyTo'   as const, n: onlyTo.length },
          { k: 'both'     as const, n: both.length },
        ].map(({ k, n }) => {
          const active = filter === k
          const label = k === 'all' ? 'All' : STATUS_LABEL[k as Status]
          return (
            <button
              key={k}
              onClick={() => setFilter(k)}
              style={{
                fontSize: 11, padding: '3px 10px', borderRadius: 12,
                border: '1px solid', borderColor: active ? 'var(--accent)' : 'var(--border)',
                background: active ? 'rgba(88,166,255,0.10)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >{label} ({n})</button>
          )
        })}
      </div>

      {empty && (
        <div style={{ color: 'var(--text-dim)', fontSize: 12, padding: 12 }}>
          No results on either side.
        </div>
      )}

      {!empty && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>
                  Status
                </th>
                {vars.map(v => (
                  <th key={v} style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>
                    {v}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map(({ status, row }, i) => {
                const c = STATUS_COLOR[status]
                return (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <td style={{ padding: '4px 8px' }}>
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 10,
                        background: c.bg, border: `1px solid ${c.border}`,
                        color: c.color, fontWeight: 600, letterSpacing: 0.3, whiteSpace: 'nowrap',
                      }}>
                        {STATUS_LABEL[status]}
                      </span>
                    </td>
                    {vars.map(v => (
                      <td key={v} style={{ padding: '4px 8px', verticalAlign: 'top' }}>
                        {row[v] ? renderValue(row[v]) : <span style={{ color: 'var(--text-dim)' }}>—</span>}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npx vitest run src/components/sparql/DiffQueryView.test.tsx --reporter=basic
```

Expected: PASS, 6 tests.

- [ ] **Step 5: TS check**

```bash
npx tsc --noEmit 2>&1 | grep "DiffQueryView\|diffBindings" | grep -v "\.test\."
```

Expected: empty.

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/DiffQueryView.tsx frontend/src/components/sparql/DiffQueryView.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): DiffQueryView component for cross-version row-diff display

Unified table with a Status column per row (Only From / Only To /
Both) and a filter pill strip showing counts. IRI cells render as
<a class="iri"> so the existing page-level iri-click handler still
navigates in-app. Error banner aggregates per-side failures.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ScopeToolbar — `Single ↔ Diff` toggle + diff pickers

Add the mode toggle and the two graph-picker rows to the existing toolbar. Emit `onDiffScopeChange` whenever the diff selection completes or the mode exits.

**Files:**
- Modify: `frontend/src/components/sparql/ScopeToolbar.tsx`
- Modify: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
describe('ScopeToolbar — Diff mode', () => {
  const SAMPLE_ONTS_WITH_VERSIONS = [
    {
      id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
      created_at: '2024-01-01',
      latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } as any,
    } as any,
  ]

  // Stub api.ontologies.versions for the version dropdown
  vi.doMock('../../lib/api', async () => {
    const actual = await vi.importActual<any>('../../lib/api')
    return {
      ...actual,
      api: {
        ...actual.api,
        ontologies: {
          ...actual.api?.ontologies,
          list: vi.fn().mockResolvedValue({ ontologies: SAMPLE_ONTS_WITH_VERSIONS }),
          versions: vi.fn().mockResolvedValue({
            versions: [
              { id: 'V2', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: null, sha256: '', triple_count: 0, download_url: '', created_at: '2026-05-20' },
              { id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: null, sha256: '', triple_count: 0, download_url: '', created_at: '2024-01-01' },
            ],
          }),
        },
      },
    }
  })

  it('renders the Single ↔ Diff mode toggle', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    expect(screen.getByRole('button', { name: /single/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^diff$/i })).toBeInTheDocument()
  })

  it('clicking Diff reveals From and To picker rows', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /^diff$/i }))
    expect(await screen.findByText(/from:/i)).toBeInTheDocument()
    expect(screen.getByText(/to:/i)).toBeInTheDocument()
  })

  it('selecting both sides fires onDiffScopeChange with the selection', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onDiff = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onDiffScopeChange={onDiff} />))
    fireEvent.click(screen.getByRole('button', { name: /^diff$/i }))
    // Both sides default to envo's latest two versions: To=V2, From=V1
    await waitFor(() => expect(onDiff).toHaveBeenCalled())
    const last = onDiff.mock.calls.at(-1)?.[0]
    expect(last.from.version.id).toBe('V1')
    expect(last.from.version.ontology_id).toBe('O1')
    expect(last.to.version.id).toBe('V2')
    expect(last.to.version.ontology_id).toBe('O1')
    expect(last.from.mode).toBe('asserted')
    expect(last.to.mode).toBe('asserted')
  })

  it('toggling back to Single fires onDiffScopeChange(null)', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onDiff = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onDiffScopeChange={onDiff} />))
    fireEvent.click(screen.getByRole('button', { name: /^diff$/i }))
    onDiff.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /single/i }))
    expect(onDiff).toHaveBeenCalledWith(null)
  })
})
```

The `wait` helpers (`waitFor`) require importing if not already available — the existing test file's imports include `waitFor` if needed. If `vi.doMock` for `../../lib/api` collides with the existing `useOntologies` mock, prefer extending the existing `useOntologies` mock to include a `versions` stub.

Inspect the existing imports/mocks first:

```bash
head -50 /home/micheldumontier/code/ontoexplorer/frontend/src/components/sparql/ScopeToolbar.test.tsx
```

Adapt the new tests to match the existing module-mock pattern. The key behaviours to test are: (1) toggle renders, (2) From/To rows appear in Diff mode, (3) `onDiffScopeChange` fires with the correct shape, (4) returning to Single fires `null`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic
```

Expected: FAIL on the new tests.

- [ ] **Step 3: Modify `ScopeToolbar.tsx`**

Open `frontend/src/components/sparql/ScopeToolbar.tsx`. Make these edits:

1. **Extend the props interface:**

```tsx
import type { OntologyVersion } from '../../lib/api'

export interface DiffScope {
  from: { version: OntologyVersion; mode: ReasoningMode }
  to:   { version: OntologyVersion; mode: ReasoningMode }
}

export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
  onOntologyAdded?: (ontologyId: string) => void
  onSelectionChange?: (ontologyIds: string[]) => void
  onLabelsToggle?: (enabled: boolean) => void
  onDiffScopeChange?: (scope: DiffScope | null) => void
}
```

2. **Destructure the new prop:**

```tsx
export function ScopeToolbar({ onScopeChange, onCopy, onOntologyAdded, onSelectionChange, onLabelsToggle, onDiffScopeChange }: ScopeToolbarProps) {
```

3. **Add mode + diff-side state:**

```tsx
type ToolbarMode = 'single' | 'diff'
const [toolbarMode, setToolbarMode] = useState<ToolbarMode>('single')

const [fromOntologyId, setFromOntologyId] = useState<string>('')
const [fromVersionId, setFromVersionId] = useState<string>('')
const [fromMode, setFromMode] = useState<ReasoningMode>('asserted')
const [toOntologyId, setToOntologyId] = useState<string>('')
const [toVersionId, setToVersionId] = useState<string>('')
const [toMode, setToMode] = useState<ReasoningMode>('asserted')

const [fromVersions, setFromVersions] = useState<OntologyVersion[]>([])
const [toVersions, setToVersions] = useState<OntologyVersion[]>([])
```

4. **Default selection when entering Diff mode** — when `toolbarMode` flips to `'diff'`, populate the pickers from the first selected ontology in Single mode (if any):

```tsx
useEffect(() => {
  if (toolbarMode !== 'diff') return
  const first = Array.from(selected)[0]
  if (first && !fromOntologyId && !toOntologyId) {
    setFromOntologyId(first)
    setToOntologyId(first)
  }
}, [toolbarMode]) // eslint-disable-line react-hooks/exhaustive-deps
```

5. **Fetch versions for each side** when its ontology is picked:

```tsx
useEffect(() => {
  if (!fromOntologyId) { setFromVersions([]); return }
  api.ontologies.versions(fromOntologyId)
    .then(r => {
      const sorted = [...r.versions].sort((a, b) =>
        (b.created_at ?? '').localeCompare(a.created_at ?? '')
      )
      setFromVersions(sorted)
      // Default From to second-newest, To to newest (if both still empty for this ontology)
      if (sorted.length > 0 && !fromVersionId) setFromVersionId(sorted[1]?.id ?? sorted[0].id)
    })
    .catch(() => setFromVersions([]))
}, [fromOntologyId])  // eslint-disable-line react-hooks/exhaustive-deps

useEffect(() => {
  if (!toOntologyId) { setToVersions([]); return }
  api.ontologies.versions(toOntologyId)
    .then(r => {
      const sorted = [...r.versions].sort((a, b) =>
        (b.created_at ?? '').localeCompare(a.created_at ?? '')
      )
      setToVersions(sorted)
      if (sorted.length > 0 && !toVersionId) setToVersionId(sorted[0].id)
    })
    .catch(() => setToVersions([]))
}, [toOntologyId])  // eslint-disable-line react-hooks/exhaustive-deps
```

`api.ontologies.versions(oid)` returns `{ versions: OntologyVersion[] }` (see `frontend/src/lib/api.ts` around line 981).

6. **Emit `onDiffScopeChange`** when the diff selection is complete or the mode exits. The callback emits the full `OntologyVersion` objects so the page can build scoped endpoint URLs without doing its own version lookups:

```tsx
useEffect(() => {
  if (toolbarMode !== 'diff') {
    onDiffScopeChange?.(null)
    return
  }
  const fromV = fromVersions.find(v => v.id === fromVersionId)
  const toV = toVersions.find(v => v.id === toVersionId)
  if (fromV && toV) {
    onDiffScopeChange?.({
      from: { version: fromV, mode: fromMode },
      to:   { version: toV,   mode: toMode },
    })
  } else {
    onDiffScopeChange?.(null)
  }
}, [toolbarMode, fromVersions, fromVersionId, fromMode, toVersions, toVersionId, toMode, onDiffScopeChange])
```

7. **Render the mode toggle** at the very top of the toolbar's return JSX. Find the existing return statement and add this right after the `<div ref={rootRef} …>` opening:

```tsx
<div style={{ display: 'flex', gap: 4, alignItems: 'center', marginRight: 8 }}>
  <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Mode:</span>
  {(['single', 'diff'] as const).map(m => {
    const active = toolbarMode === m
    return (
      <button
        key={m}
        onClick={() => setToolbarMode(m)}
        style={{
          fontSize: 11, padding: '2px 10px', borderRadius: 12,
          border: '1px solid',
          borderColor: active ? 'var(--accent)' : 'var(--border)',
          background: active ? 'rgba(88,166,255,0.10)' : 'transparent',
          color: active ? 'var(--accent)' : 'var(--text-dim)',
          cursor: 'pointer', textTransform: 'capitalize',
        }}
      >
        {m === 'single' ? 'Single' : 'Diff'}
      </button>
    )
  })}
</div>
```

8. **Conditionally render the diff pickers vs the single-mode chip strip.** Wrap the existing chip-strip + reasoning-pills + summary in `{toolbarMode === 'single' && (...)}` and add a new block for `'diff'`:

```tsx
{toolbarMode === 'diff' && (
  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
    {(['from', 'to'] as const).map(side => {
      const ontId = side === 'from' ? fromOntologyId : toOntologyId
      const setOntId = side === 'from' ? setFromOntologyId : setToOntologyId
      const versions = side === 'from' ? fromVersions : toVersions
      const vid = side === 'from' ? fromVersionId : toVersionId
      const setVid = side === 'from' ? setFromVersionId : setToVersionId
      const mode = side === 'from' ? fromMode : toMode
      const setMode = side === 'from' ? setFromMode : setToMode

      return (
        <div key={side} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)', minWidth: 36 }}>
            {side === 'from' ? 'From:' : 'To:'}
          </span>
          <select
            value={ontId}
            onChange={e => { setOntId(e.target.value); setVid('') }}
            style={{ fontSize: 11, padding: '2px 6px', background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }}
          >
            <option value="">Pick ontology…</option>
            {selectableOntologies.map(o => (
              <option key={o.id} value={o.id}>{ontologyLabel(o)}</option>
            ))}
          </select>
          <select
            value={vid}
            onChange={e => setVid(e.target.value)}
            disabled={!versions.length}
            style={{ fontSize: 11, padding: '2px 6px', background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }}
          >
            <option value="">Pick version…</option>
            {versions.map(v => (
              <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
            ))}
          </select>
          <div style={{ display: 'flex', gap: 2 }}>
            {(['asserted', 'inferred', 'both'] as ReasoningMode[]).map(m => {
              const active = mode === m
              return (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  style={{
                    fontSize: 10, padding: '1px 8px', borderRadius: 10,
                    border: '1px solid',
                    borderColor: active ? 'var(--accent)' : 'var(--border)',
                    background: active ? 'rgba(88,166,255,0.10)' : 'transparent',
                    color: active ? 'var(--accent)' : 'var(--text-dim)',
                    cursor: 'pointer', textTransform: 'capitalize',
                  }}
                >{m}</button>
              )
            })}
          </div>
        </div>
      )
    })}
  </div>
)}
```

9. **Reset existing single-mode behaviour when in Diff mode** — emit `onScopeChange(BASE_ENDPOINT)` (no params) so the page's normal Yasr path doesn't see stale URL params. Wrap the existing endpoint-change effect:

```tsx
useEffect(() => {
  if (toolbarMode === 'diff') {
    onScopeChange(BASE_ENDPOINT)
    return
  }
  onScopeChange(endpoint)
}, [toolbarMode, endpoint, onScopeChange])
```

Replace the existing `useEffect(() => { onScopeChange(endpoint) }, [endpoint, onScopeChange])` with the version above.

- [ ] **Step 4: Run tests**

```bash
npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic
```

Expected: PASS — pre-existing tests + 4 new Diff-mode tests.

- [ ] **Step 5: TS check**

```bash
npx tsc --noEmit 2>&1 | grep "ScopeToolbar\.tsx" | grep -v "\.test\."
```

Expected: empty.

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/ScopeToolbar.tsx frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): Single↔Diff mode toggle on ScopeToolbar with From/To pickers

In Diff mode the chip strip is replaced by two graph-picker rows
(each: ontology + version + reasoning mode). Defaults populate from
the first single-mode selection if any. The toolbar emits a new
onDiffScopeChange(DiffScope | null) callback; in Diff mode it also
zeros out the single-mode endpoint so the page's regular Yasr
path doesn't see stale URL params.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Sparql page — Yasqe `query` event intercept + DiffQueryView mount

Wire the page-level diff orchestration: in Diff mode, intercept the Yasqe `query` event, abort the default request, fire two parallel scoped POSTs, hand the bindings to `DiffQueryView`, hide the native Yasr pane.

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`
- Modify: `frontend/src/pages/Sparql.test.tsx`

- [ ] **Step 1: Add the failing test**

Append to `frontend/src/pages/Sparql.test.tsx` inside the existing top-level `describe`:

```tsx
it('runs two parallel fetches in Diff mode and renders DiffQueryView', async () => {
  vi.resetModules()

  const queryHandlers: Array<(req: any, cfg: any) => void> = []
  const fakeYasqe = {
    setValue: vi.fn(),
    getValue: vi.fn(() => 'SELECT ?x WHERE { ?x ?p ?o }'),
    on: vi.fn((evt: string, cb: any) => {
      if (evt === 'query') queryHandlers.push(cb)
    }),
  }
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => fakeYasqe,
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: vi.fn(),
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
      }),
      destroy: vi.fn(),
    })),
  }))

  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({
      ontologies: [
        { id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
          title: 'Pizza', created_at: '2024-01-01',
          latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } },
      ],
      isLoading: false,
    }),
  }))

  // Mock api.ontologies.versions for the toolbar
  vi.doMock('../lib/api', async () => {
    const actual = await vi.importActual<any>('../lib/api')
    return {
      ...actual,
      api: {
        ...actual.api,
        ontologies: {
          ...actual.api.ontologies,
          versions: vi.fn().mockResolvedValue({
            versions: [
              { id: 'V2', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: 'pizza-2.0', sha256: '', triple_count: 0, download_url: '', created_at: '2026-05-20' },
              { id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: 'pizza-1.0', sha256: '', triple_count: 0, download_url: '', created_at: '2024-01-01' },
            ],
          }),
        },
      },
    }
  })

  // Stub the global fetch to return two distinct binding sets for the two URLs
  global.fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.includes('urn%3Aontology%3AO1%3AV1')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          head: { vars: ['x'] },
          results: { bindings: [{ x: { type: 'uri', value: 'http://example.org/A' } }] },
        }),
      } as Response
    }
    if (url.includes('urn%3Aontology%3AO1%3AV2')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          head: { vars: ['x'] },
          results: { bindings: [{ x: { type: 'uri', value: 'http://example.org/B' } }] },
        }),
      } as Response
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response
  }) as any

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )

  // Switch to Diff mode (defaults to envo's V1 / V2 from the mocked versions list)
  fireEvent.click(await screen.findByRole('button', { name: /^diff$/i }))

  // Wait for the diff scope to settle so the query handler will fire two fetches
  await waitFor(() => expect(queryHandlers.length).toBeGreaterThan(0))

  // Fire Yasqe's query event manually
  const abortMock = vi.fn()
  queryHandlers[0]({ abort: abortMock }, { endpoint: '/api/v1/sparql/content' })

  // Assert preventDefault analogue: the request was aborted
  expect(abortMock).toHaveBeenCalled()

  // The two binding sets render as DiffQueryView's "Only From" and "Only To" rows.
  await waitFor(() => {
    expect(screen.getByText('http://example.org/A')).toBeInTheDocument()
    expect(screen.getByText('http://example.org/B')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run src/pages/Sparql.test.tsx --reporter=basic
```

Expected: FAIL — the page doesn't yet subscribe to `query` events or render `DiffQueryView`.

- [ ] **Step 3: Modify `frontend/src/pages/Sparql.tsx`**

Make these edits in order:

1. **Add imports** near the existing top-of-file imports:

```tsx
import { DiffQueryView } from '../components/sparql/DiffQueryView'
import { endpointForVersion } from '../components/sparql/scopeUrls'
import type { BindingRow } from '../components/sparql/diffBindings'
import type { DiffScope } from '../components/sparql/ScopeToolbar'
```

2. **Add diff state and refs** inside the `Sparql` component, next to the existing state:

```tsx
const [diffScope, setDiffScope] = useState<DiffScope | null>(null)
const diffScopeRef = useRef<DiffScope | null>(null)
useEffect(() => { diffScopeRef.current = diffScope }, [diffScope])

const [diffResult, setDiffResult] = useState<{
  from: BindingRow[]
  to: BindingRow[]
  fromError: string | null
  toError: string | null
} | null>(null)
const diffAbortRef = useRef<AbortController | null>(null)
```

3. **Add the diff-run handler** (stable `useCallback`):

```tsx
const runDiffQuery = useCallback(async (query: string, scope: DiffScope) => {
  // Cancel any in-flight diff
  if (diffAbortRef.current) diffAbortRef.current.abort()
  const ac = new AbortController()
  diffAbortRef.current = ac

  async function fetchSide(side: { version: OntologyVersion; mode: ReasoningMode }): Promise<{ bindings: BindingRow[]; error: string | null }> {
    try {
      const resp = await fetch(endpointForVersion(side.version, side.mode), {
        method: 'POST',
        signal: ac.signal,
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/sparql-results+json',
        },
        body: `query=${encodeURIComponent(query)}`,
      })
      if (!resp.ok) return { bindings: [], error: `HTTP ${resp.status}` }
      const data = await resp.json()
      if (!data?.head?.vars) {
        return { bindings: [], error: 'Diff mode supports SELECT queries only' }
      }
      return { bindings: data.results?.bindings ?? [], error: null }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return { bindings: [], error: 'aborted' }
      return { bindings: [], error: e instanceof Error ? e.message : 'fetch failed' }
    }
  }

  const [fromResp, toResp] = await Promise.all([
    fetchSide(scope.from),
    fetchSide(scope.to),
  ])

  if (ac.signal.aborted) return

  setDiffResult({
    from: fromResp.bindings,
    to: toResp.bindings,
    fromError: fromResp.error,
    toError: toResp.error,
  })
}, [])
```

The handler is fully self-contained because `DiffScope` carries the full `OntologyVersion` objects (with both `id` and `ontology_id`), so `endpointForVersion(side.version, side.mode)` builds the scoped URL directly — no need to resolve version-id → ontology-id from the surrounding state.

4. **Subscribe to the Yasqe `query` event** inside the existing Yasgui-mount `useEffect`. Locate the line after `yasguiRef.current = new Yasgui(...)` and the existing `installIriClickHandler` call. Add this just before the cleanup `return`:

```tsx
const yasqe = yasguiRef.current?.getTab()?.getYasqe()
if (yasqe && typeof (yasqe as any).on === 'function') {
  (yasqe as any).on('query', (req: any) => {
    const scope = diffScopeRef.current
    if (!scope) return
    try { req?.abort?.() } catch { /* superagent abort can be noisy */ }
    void runDiffQuery(yasqe.getValue() ?? '', scope)
  })
}
```

5. **Pass `onDiffScopeChange` to ScopeToolbar:**

```tsx
<ScopeToolbar
  onScopeChange={handleScopeChange}
  onCopy={handleCopy}
  onOntologyAdded={handleOntologyAdded}
  onSelectionChange={handleSelectionChange}
  onLabelsToggle={handleLabelsToggle}
  onDiffScopeChange={setDiffScope}
/>
```

6. **Render the diff view** when `diffScope` is set; hide the Yasr `.yasr` element. Inside the existing layout JSX, replace the `<div ref={containerRef} data-testid="yasgui-container" .../>` line with a wrapping container that renders either Yasgui's `.yasr` (default) or the `DiffQueryView` overlay:

```tsx
<div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
  <div ref={containerRef} data-testid="yasgui-container" style={{
    height: '100%', overflowY: 'auto',
    // Hide Yasr's rendered result pane while in Diff mode by hiding its child.
    // (Yasgui draws .yasqe and .yasr under the container; in Diff mode we want
    // Yasqe visible and Yasr hidden.)
  }} />
  {diffScope && diffResult && (
    <div style={{
      position: 'absolute', left: 0, right: 0, bottom: 0,
      top: '50%',  // editor takes top half, diff view bottom half
      background: 'var(--bg)', borderTop: '2px solid var(--border)',
      overflow: 'hidden',
    }}>
      <DiffQueryView
        from={diffResult.from}
        to={diffResult.to}
        fromError={diffResult.fromError}
        toError={diffResult.toError}
      />
    </div>
  )}
</div>
```

This is the simplest layout: the editor pane stays in its container; in Diff mode the bottom-half is overlaid with `DiffQueryView`. The native Yasr result pane is still in the container but hidden behind the overlay. (More precise: add a side effect that toggles `.yasr` display when `diffScope` changes — see Step 7.)

7. **Toggle `.yasr` visibility** to keep the native pane clean while in Diff mode. Add a `useEffect`:

```tsx
useEffect(() => {
  const yasrEl = containerRef.current?.querySelector('.yasr') as HTMLElement | null
  if (yasrEl) yasrEl.style.display = diffScope ? 'none' : ''
}, [diffScope])
```

8. **Clear `diffResult` on Diff exit**:

```tsx
useEffect(() => {
  if (!diffScope) setDiffResult(null)
}, [diffScope])
```

- [ ] **Step 4: Run the integration test**

```bash
npx vitest run src/pages/Sparql.test.tsx src/components/sparql/ --reporter=basic
```

Expected: PASS for the new diff test + all pre-existing tests still pass.

- [ ] **Step 5: TS check on touched files**

```bash
npx tsc --noEmit 2>&1 | grep -E "Sparql\.tsx|ScopeToolbar|DiffQueryView|diffBindings|scopeUrls" | grep -v "\.test\."
```

Expected: empty.

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/Sparql.tsx frontend/src/pages/Sparql.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): wire diff-mode query intercept + DiffQueryView mount

The page subscribes to Yasqe's 'query' event. When diff scope is
set, the handler aborts the default request and instead fires two
parallel POSTs to /sparql/content (one per side, scoped by the
toolbar's From/To picks). Bindings are passed to DiffQueryView.
The native Yasr result pane is hidden via display:none while in
Diff mode.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: End-to-end sweep

- [ ] **Step 1: Full frontend test run**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx vitest run --reporter=basic 2>&1 | tail -25
```

Expected: all PASS. Pre-existing `OwlProfileSection.*` failures are unrelated and may persist.

- [ ] **Step 2: Full TypeScript check**

```bash
npx tsc --noEmit 2>&1 | grep -E "(Sparql\.tsx|ScopeToolbar|DiffQueryView|diffBindings|scopeUrls)" | grep -v "\.test\." | grep -v node_modules
```

Expected: empty.

- [ ] **Step 3: File inventory**

```bash
cd /home/micheldumontier/code/ontoexplorer
git log --oneline e37d205..HEAD | head
```

Confirm the 5 task commits are present in order.

- [ ] **Step 4 (optional): Manual smoke test**

If the dev server is running, open `/sparql`:

1. Confirm the scope toolbar shows the new `Mode: Single | Diff` toggle.
2. Pick the pizza ontology in Single mode → confirm normal scope still works.
3. Click `Diff` → confirm two graph-picker rows appear, pre-populated with pizza's latest two versions.
4. Run the default starter query — confirm the result pane is replaced by `DiffQueryView` with filter pills and status badges.
5. Switch the To-side reasoning mode to `Inferred` — confirm a fresh Run produces a different diff.
6. Click `Single` to return — confirm the standard Yasr table reappears.

- [ ] **Step 5: Optional post-merge cleanup commit**

If anything was tweaked during the sweep:

```bash
git add -A
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(sparql): post-merge cleanup for diff query mode

Fix-ups discovered during the end-to-end sweep.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If nothing changed, no commit.

---

## Out of scope

Per the spec:

- CONSTRUCT/DESCRIBE result diffing.
- ASK boolean diffing.
- Three-way diff (A vs B vs C).
- Side caching across re-runs.
- Persisting diff sessions into saved queries.
- Visual cell-level diff for `Both` rows.
- A server-side diff endpoint (kept frontend-only for v1).
