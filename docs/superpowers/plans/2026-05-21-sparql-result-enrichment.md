# SPARQL Result Enrichment + IRI Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking IRI cells in SPARQL results navigates to OntoExplorer's term page; an opt-in "labels" toggle appends `rdfs:label` after each IRI cell.

**Architecture:** Frontend-only. Event-delegation click handler on the Yasgui container resolves IRIs via longest-prefix match against the scope toolbar's ontologies (with `/api/v1/search` as fallback) and uses React Router `navigate`. Label enrichment runs a follow-up VALUES-based SPARQL query against the same scoped endpoint Yasgui uses, then walks the DOM to append `<span class="iri-label">` after each `a.iri`. Re-applied on every Yasr `drawn` event.

**Tech Stack:** React 18 + TypeScript, Vitest + jsdom, @testing-library/react, @triply/yasgui v4, React Router v6.

**Spec:** [`docs/superpowers/specs/2026-05-21-sparql-result-enrichment-design.md`](../specs/2026-05-21-sparql-result-enrichment-design.md)

---

## File Map

| Path | Role |
|---|---|
| `frontend/src/components/sparql/iriResolver.ts` | Pure helpers: longest-prefix match across ontologies; term-page URL builder. |
| `frontend/src/components/sparql/iriResolver.test.ts` | Unit tests. |
| `frontend/src/components/sparql/labelEnricher.ts` | DOM helpers: collect IRIs from a container, build a VALUES SPARQL query, apply/remove label spans. |
| `frontend/src/components/sparql/labelEnricher.test.ts` | Unit tests (jsdom). |
| `frontend/src/components/sparql/iriClickHandler.ts` | Event-delegated click installer; uses iriResolver + fetch fallback + React-Router navigate. |
| `frontend/src/components/sparql/iriClickHandler.test.ts` | Tests with synthetic clicks. |
| `frontend/src/components/sparql/ScopeToolbar.tsx` | Add `📑` labels toggle button + optional `onLabelsToggle?: (enabled: boolean) => void` prop. |
| `frontend/src/components/sparql/ScopeToolbar.test.tsx` | One new test verifying the toggle. |
| `frontend/src/pages/Sparql.tsx` | Install the click handler on mount; manage `labelsOn` state; subscribe to Yasr's `drawn` event for re-applying labels. |
| `frontend/src/pages/Sparql.test.tsx` | Two integration tests: click navigates; toggle injects spans. |

---

## Task 1: `iriResolver` — longest-prefix match + term-page URL

Pure helpers.

**Files:**
- Create: `frontend/src/components/sparql/iriResolver.ts`
- Test: `frontend/src/components/sparql/iriResolver.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/iriResolver.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { findOwningOntology, termPageUrl } from './iriResolver'
import type { Ontology } from '../../lib/api'

const PIZZA: Ontology = {
  id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
  title: 'Pizza', created_at: '2024-01-01',
  latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
} as any

const OBO: Ontology = {
  id: 'O2', iri: 'http://purl.obolibrary.org/obo/', shortname: 'obo',
  title: 'OBO', created_at: '2024-01-01',
  latest_version: { id: 'V2', ontology_id: 'O2', status: 'ready' } as any,
} as any

const CHEBI: Ontology = {
  id: 'O3', iri: 'http://purl.obolibrary.org/obo/chebi/', shortname: 'chebi',
  title: 'ChEBI', created_at: '2024-01-01',
  latest_version: { id: 'V3', ontology_id: 'O3', status: 'ready' } as any,
} as any

describe('findOwningOntology', () => {
  it('returns null when no ontology matches', () => {
    expect(findOwningOntology('http://example.org/Foo', [PIZZA])).toBeNull()
  })

  it('returns the ontology when iri starts with its base', () => {
    expect(findOwningOntology('https://w3id.org/ontostart/pizza/Margherita', [PIZZA]))
      .toBe(PIZZA)
  })

  it('picks the longest-prefix match when multiple ontologies match', () => {
    // CHEBI's base is a longer prefix of obo:chebi/12345 than OBO's
    const iri = 'http://purl.obolibrary.org/obo/chebi/12345'
    expect(findOwningOntology(iri, [OBO, CHEBI])).toBe(CHEBI)
  })

  it('normalises ontology IRIs without trailing terminator', () => {
    // Ontology IRI lacks a trailing slash; the iri lookup still works
    const o: Ontology = { ...PIZZA, iri: 'https://w3id.org/ontostart/pizza' } as any
    expect(findOwningOntology('https://w3id.org/ontostart/pizza/Foo', [o])).toBe(o)
  })

  it('returns null when ontology has no latest_version', () => {
    const stale: Ontology = { ...PIZZA, latest_version: null } as any
    expect(findOwningOntology('https://w3id.org/ontostart/pizza/Foo', [stale])).toBeNull()
  })
})

describe('termPageUrl', () => {
  it('builds /ontologies/<shortname>?term=<encoded-iri>', () => {
    expect(termPageUrl('pizza', 'https://w3id.org/ontostart/pizza/Margherita'))
      .toBe('/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita')
  })

  it('encodes hash fragments in the IRI', () => {
    expect(termPageUrl('owl', 'http://www.w3.org/2002/07/owl#Class'))
      .toBe('/ontologies/owl?term=http%3A%2F%2Fwww.w3.org%2F2002%2F07%2Fowl%23Class')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/iriResolver.test.ts --reporter=basic`

Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/sparql/iriResolver.ts`:

```typescript
import type { Ontology } from '../../lib/api'
import { extractBaseIri } from './prefixUtils'

/**
 * Find the ontology whose base IRI is a prefix of `iri`. If multiple match,
 * the one with the longest base IRI wins (more specific match). Ontologies
 * without a `latest_version` are ignored.
 */
export function findOwningOntology(iri: string, ontologies: Ontology[]): Ontology | null {
  let best: Ontology | null = null
  let bestLen = 0
  for (const o of ontologies) {
    if (!o.latest_version) continue
    const base = extractBaseIri(o.iri)
    if (iri.startsWith(base) && base.length > bestLen) {
      best = o
      bestLen = base.length
    }
  }
  return best
}

/**
 * Build the OntoExplorer term-page URL for an IRI inside an ontology.
 */
export function termPageUrl(shortname: string, iri: string): string {
  return `/ontologies/${shortname}?term=${encodeURIComponent(iri)}`
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/iriResolver.test.ts --reporter=basic`

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/iriResolver.ts frontend/src/components/sparql/iriResolver.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): iriResolver helpers for term-page navigation

Pure functions: findOwningOntology does a longest-prefix match
across a list of ontologies, using extractBaseIri (from prefixUtils)
to normalise terminators. termPageUrl encodes IRIs for the
?term= query param. Used by the click handler in Task 3.
EOF
)"
```

---

## Task 2: `labelEnricher` — collect, build query, apply, remove

DOM-aware pure helpers. Operate on any container element with `a.iri` descendants. No React, no Yasgui.

**Files:**
- Create: `frontend/src/components/sparql/labelEnricher.ts`
- Test: `frontend/src/components/sparql/labelEnricher.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/labelEnricher.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { collectIris, buildLabelsQuery, applyLabels, removeLabels } from './labelEnricher'

function makeTable(hrefs: string[]): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = `
    <table>
      <tbody>
        ${hrefs.map(h => `<tr><td><span><a class="iri" href="${h}">${h}</a></span></td></tr>`).join('')}
      </tbody>
    </table>
  `
  return root
}

describe('collectIris', () => {
  it('returns empty array when no a.iri present', () => {
    const root = document.createElement('div')
    expect(collectIris(root)).toEqual([])
  })

  it('extracts hrefs from a.iri elements', () => {
    const root = makeTable(['http://a/', 'http://b/'])
    expect(collectIris(root)).toEqual(['http://a/', 'http://b/'])
  })

  it('deduplicates repeated IRIs', () => {
    const root = makeTable(['http://a/', 'http://a/', 'http://b/'])
    expect(collectIris(root)).toEqual(['http://a/', 'http://b/'])
  })

  it('ignores anchors without the iri class', () => {
    const root = document.createElement('div')
    root.innerHTML = `<a href="http://x/">x</a><a class="iri" href="http://y/">y</a>`
    expect(collectIris(root)).toEqual(['http://y/'])
  })
})

describe('buildLabelsQuery', () => {
  it('returns empty string for empty list', () => {
    expect(buildLabelsQuery([])).toBe('')
  })

  it('builds a VALUES + rdfs:label SELECT for one IRI', () => {
    expect(buildLabelsQuery(['http://a/foo'])).toBe(
      'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n' +
      'SELECT ?iri ?label WHERE {\n' +
      '  VALUES ?iri { <http://a/foo> }\n' +
      '  ?iri rdfs:label ?label .\n' +
      '}'
    )
  })

  it('joins multiple IRIs in the VALUES block', () => {
    const q = buildLabelsQuery(['http://a/', 'http://b/'])
    expect(q).toContain('VALUES ?iri { <http://a/> <http://b/> }')
  })
})

describe('applyLabels', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('appends an iri-label span after each matching a.iri', () => {
    const root = makeTable(['http://a/', 'http://b/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha'], ['http://b/', 'Beta']]))
    const spans = root.querySelectorAll('.iri-label')
    expect(spans.length).toBe(2)
    expect(spans[0].textContent).toBe(' · Alpha')
    expect(spans[1].textContent).toBe(' · Beta')
  })

  it('skips IRIs absent from the label map', () => {
    const root = makeTable(['http://a/', 'http://nolabel/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha']]))
    expect(root.querySelectorAll('.iri-label').length).toBe(1)
  })

  it('does not duplicate spans on repeated calls', () => {
    const root = makeTable(['http://a/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha']]))
    applyLabels(root, new Map([['http://a/', 'Alpha']]))
    expect(root.querySelectorAll('.iri-label').length).toBe(1)
  })
})

describe('removeLabels', () => {
  it('removes every .iri-label span', () => {
    const root = makeTable(['http://a/', 'http://b/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha'], ['http://b/', 'Beta']]))
    expect(root.querySelectorAll('.iri-label').length).toBe(2)
    removeLabels(root)
    expect(root.querySelectorAll('.iri-label').length).toBe(0)
  })

  it('is a no-op when no labels are present', () => {
    const root = makeTable(['http://a/'])
    document.body.appendChild(root)
    expect(() => removeLabels(root)).not.toThrow()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/labelEnricher.test.ts --reporter=basic`

Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/sparql/labelEnricher.ts`:

```typescript
/**
 * Collect unique hrefs from every `a.iri` descendant of `root`.
 */
export function collectIris(root: HTMLElement): string[] {
  const seen = new Set<string>()
  root.querySelectorAll<HTMLAnchorElement>('a.iri').forEach(a => {
    const href = a.getAttribute('href')
    if (href) seen.add(href)
  })
  return Array.from(seen)
}

/**
 * Build a VALUES-based SPARQL query that asks for rdfs:label for the given IRIs.
 * Returns the empty string when iris is empty.
 */
export function buildLabelsQuery(iris: string[]): string {
  if (iris.length === 0) return ''
  const values = iris.map(iri => `<${iri}>`).join(' ')
  return (
    'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n' +
    'SELECT ?iri ?label WHERE {\n' +
    `  VALUES ?iri { ${values} }\n` +
    '  ?iri rdfs:label ?label .\n' +
    '}'
  )
}

/**
 * For each `a.iri` whose href is a key in `labels`, append a `<span class="iri-label">`
 * immediately after the anchor showing the label. Idempotent: re-applying with the
 * same data doesn't duplicate spans.
 */
export function applyLabels(root: HTMLElement, labels: Map<string, string>): void {
  root.querySelectorAll<HTMLAnchorElement>('a.iri').forEach(a => {
    const href = a.getAttribute('href') ?? ''
    const label = labels.get(href)
    if (!label) return
    // Skip if the next sibling is already our injected label span
    const next = a.nextElementSibling
    if (next && next.classList.contains('iri-label')) return
    const span = document.createElement('span')
    span.className = 'iri-label'
    span.style.color = 'var(--text-dim)'
    span.style.marginLeft = '4px'
    span.textContent = ` · ${label}`
    a.insertAdjacentElement('afterend', span)
  })
}

/**
 * Remove every `.iri-label` span beneath `root`.
 */
export function removeLabels(root: HTMLElement): void {
  root.querySelectorAll('.iri-label').forEach(el => el.remove())
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/labelEnricher.test.ts --reporter=basic`

Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/labelEnricher.ts frontend/src/components/sparql/labelEnricher.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): labelEnricher for SPARQL result rdfs:label decoration

Four pure DOM helpers: collectIris walks a container for unique
a.iri hrefs; buildLabelsQuery emits a VALUES-based SELECT;
applyLabels inserts a dimmed iri-label span after each matching
anchor (idempotent); removeLabels strips them all.
EOF
)"
```

---

## Task 3: `iriClickHandler` — event delegation + fetch fallback

Installs a single click listener on the Yasgui container. Resolves the click target's IRI via `iriResolver`. Falls back to `/api/v1/search` on miss.

**Files:**
- Create: `frontend/src/components/sparql/iriClickHandler.ts`
- Test: `frontend/src/components/sparql/iriClickHandler.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/iriClickHandler.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { installIriClickHandler } from './iriClickHandler'
import type { Ontology } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: { globalSearch: { search: vi.fn() } },
}))
import { api } from '../../lib/api'
const mockSearch = api.globalSearch.search as ReturnType<typeof vi.fn>

const PIZZA: Ontology = {
  id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
  title: 'Pizza', created_at: '2024-01-01',
  latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
} as any

beforeEach(() => {
  document.body.innerHTML = ''
  mockSearch.mockReset()
})

function makeAnchor(href: string): { root: HTMLElement; anchor: HTMLAnchorElement } {
  const root = document.createElement('div')
  root.innerHTML = `<a class="iri" href="${href}">${href}</a>`
  document.body.appendChild(root)
  return { root, anchor: root.querySelector('a')! }
}

function dispatchClick(target: HTMLElement, opts: Partial<MouseEventInit> = {}) {
  const ev = new MouseEvent('click', { bubbles: true, cancelable: true, ...opts })
  target.dispatchEvent(ev)
  return ev
}

describe('installIriClickHandler', () => {
  it('navigates to the term page when the IRI is in scope', () => {
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('https://w3id.org/ontostart/pizza/Margherita')
    installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    const ev = dispatchClick(anchor)
    expect(navigate).toHaveBeenCalledWith(
      '/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita'
    )
    expect(ev.defaultPrevented).toBe(true)
  })

  it('does not navigate on modified clicks (ctrlKey)', () => {
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('https://w3id.org/ontostart/pizza/Margherita')
    installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    const ev = dispatchClick(anchor, { ctrlKey: true })
    expect(navigate).not.toHaveBeenCalled()
    expect(ev.defaultPrevented).toBe(false)
  })

  it('falls back to /api/v1/search when no scope ontology matches and navigates on result', async () => {
    mockSearch.mockResolvedValue({
      results: [{ iri: 'http://outside/Foo', ontology_id: 'O1', label: 'Foo', short: 'Foo', type: 'class', version_id: 'V1' }],
      count: 1, truncated: false,
    })
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('http://outside/Foo')
    installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    const ev = dispatchClick(anchor)
    // preventDefault fires synchronously
    expect(ev.defaultPrevented).toBe(true)
    // navigate happens after the fetch resolves
    await new Promise(r => setTimeout(r, 0))
    expect(mockSearch).toHaveBeenCalledWith('http://outside/Foo', 1)
    expect(navigate).toHaveBeenCalledWith(
      '/ontologies/pizza?term=http%3A%2F%2Foutside%2FFoo'
    )
  })

  it('opens raw IRI in new tab when search returns empty', async () => {
    mockSearch.mockResolvedValue({ results: [], count: 0, truncated: false })
    const navigate = vi.fn()
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { root, anchor } = makeAnchor('http://nothing/Foo')
    installIriClickHandler(root, { getOntologies: () => [], navigate })
    dispatchClick(anchor)
    await new Promise(r => setTimeout(r, 0))
    expect(navigate).not.toHaveBeenCalled()
    expect(openSpy).toHaveBeenCalledWith('http://nothing/Foo', '_blank')
    openSpy.mockRestore()
  })

  it('opens raw IRI when fetch rejects', async () => {
    mockSearch.mockRejectedValue(new Error('boom'))
    const navigate = vi.fn()
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { root, anchor } = makeAnchor('http://nothing/Foo')
    installIriClickHandler(root, { getOntologies: () => [], navigate })
    dispatchClick(anchor)
    await new Promise(r => setTimeout(r, 0))
    expect(openSpy).toHaveBeenCalledWith('http://nothing/Foo', '_blank')
    openSpy.mockRestore()
  })

  it('teardown removes the listener', () => {
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('https://w3id.org/ontostart/pizza/Foo')
    const teardown = installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    teardown()
    dispatchClick(anchor)
    expect(navigate).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/iriClickHandler.test.ts --reporter=basic`

Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/sparql/iriClickHandler.ts`:

```typescript
import { api, Ontology } from '../../lib/api'
import { findOwningOntology, termPageUrl } from './iriResolver'

interface InstallDeps {
  getOntologies: () => Ontology[]
  navigate: (path: string) => void
}

/**
 * Attach a single delegated click listener to `rootEl` that intercepts clicks
 * on `<a class="iri">` elements (rendered by Yasr's table plugin). The handler:
 *
 * 1. Skips modified clicks (Ctrl, Cmd, Shift, middle-mouse) so users keep
 *    "open in new tab" affordances.
 * 2. Tries a longest-prefix match against the current ontology selection.
 * 3. Falls back to `/api/v1/search?q=<iri>&mode=entity&limit=1` if no
 *    in-scope ontology matches.
 * 4. On miss / network error, calls `window.open(iri, '_blank')` so the user
 *    still reaches the raw IRI.
 *
 * Returns a teardown function that removes the listener.
 */
export function installIriClickHandler(rootEl: HTMLElement, deps: InstallDeps): () => void {
  function handler(event: MouseEvent) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return

    const target = event.target as Element | null
    if (!target) return
    const anchor = target.closest('a.iri') as HTMLAnchorElement | null
    if (!anchor) return

    const iri = anchor.getAttribute('href')
    if (!iri) return

    // Try in-scope prefix match first
    const owning = findOwningOntology(iri, deps.getOntologies())
    if (owning && owning.shortname) {
      event.preventDefault()
      deps.navigate(termPageUrl(owning.shortname, iri))
      return
    }

    // Fall back to search API
    event.preventDefault()
    api.globalSearch.search(iri, 1).then(
      resp => {
        const hit = resp.results?.[0]
        if (hit?.ontology_id) {
          const found = deps.getOntologies().find(o => o.id === hit.ontology_id)
          if (found?.shortname) {
            deps.navigate(termPageUrl(found.shortname, iri))
            return
          }
        }
        window.open(iri, '_blank')
      },
      () => {
        window.open(iri, '_blank')
      },
    )
  }

  rootEl.addEventListener('click', handler)
  return () => rootEl.removeEventListener('click', handler)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/iriClickHandler.test.ts --reporter=basic`

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/iriClickHandler.ts frontend/src/components/sparql/iriClickHandler.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): event-delegated IRI click handler

installIriClickHandler attaches a single click listener to the
Yasgui container that intercepts clicks on a.iri anchors. Resolves
the target IRI via iriResolver (in-scope prefix match) with a
/api/v1/search fallback for IRIs outside scope. Modified clicks
(Ctrl, Cmd, Shift, middle-mouse) pass through unchanged so users
keep 'open in new tab' affordances.
EOF
)"
```

---

## Task 4: `ScopeToolbar` — labels toggle button

Add a 📑 button to the toolbar that emits an `onLabelsToggle(enabled: boolean)` callback. Visual active state when on.

**Files:**
- Modify: `frontend/src/components/sparql/ScopeToolbar.tsx`
- Modify: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
describe('ScopeToolbar — labels toggle', () => {
  it('renders a labels toggle button', () => {
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    expect(screen.getByRole('button', { name: /toggle result labels/i })).toBeInTheDocument()
  })

  it('fires onLabelsToggle(true) on first click and (false) on second click', () => {
    const onToggle = vi.fn()
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} onLabelsToggle={onToggle} />))
    const btn = screen.getByRole('button', { name: /toggle result labels/i })
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenLastCalledWith(true)
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenLastCalledWith(false)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: FAIL on the two new tests — no labels button exists yet.

- [ ] **Step 3: Modify `ScopeToolbar.tsx`**

Open `frontend/src/components/sparql/ScopeToolbar.tsx`. Make three edits:

1. **Extend the props interface:**

```tsx
export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
  onOntologyAdded?: (ontologyId: string) => void
  onSelectionChange?: (ontologyIds: string[]) => void
  onLabelsToggle?: (enabled: boolean) => void
}
```

2. **Destructure the new prop:**

```tsx
export function ScopeToolbar({ onScopeChange, onCopy, onOntologyAdded, onSelectionChange, onLabelsToggle }: ScopeToolbarProps) {
```

3. **Add `labelsOn` state and a labels button next to the copy button.** Add the state near the other `useState` calls:

```tsx
const [labelsOn, setLabelsOn] = useState(false)
```

Find the existing `📋` copy button JSX (it has `aria-label="Copy query with scope"`). Insert this new button **immediately before** the copy button:

```tsx
<button
  onClick={() => {
    const next = !labelsOn
    setLabelsOn(next)
    onLabelsToggle?.(next)
  }}
  aria-label="Toggle result labels"
  title="Append rdfs:label to IRI cells in result table"
  style={{
    fontSize: 14, padding: '2px 8px',
    border: `1px solid ${labelsOn ? 'var(--accent)' : 'var(--border)'}`,
    borderRadius: 4, background: labelsOn ? 'rgba(88,166,255,0.1)' : 'transparent',
    color: labelsOn ? 'var(--accent)' : 'var(--text-dim)',
    cursor: 'pointer',
  }}
>
  📑
</button>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: PASS, 19 tests total (17 pre-existing + 2 new).

- [ ] **Step 5: TS check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep "ScopeToolbar\.tsx" | grep -v "\.test\."`

Expected: empty.

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/sparql/ScopeToolbar.tsx frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): labels toggle button on ScopeToolbar

A 📑 button sits next to the copy icon and emits onLabelsToggle
(boolean) when clicked. Active-state styling (accent border + tint)
shows whether labels are currently on. State is owned by the toolbar
so toggling persists across re-renders of the Sparql page.
EOF
)"
```

---

## Task 5: `Sparql.tsx` — wire the click handler and labels enrichment

Install the IRI click handler on mount; wire the labels toggle to fetch + apply labels via the existing Yasgui endpoint; re-apply on Yasr's `drawn` event.

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`
- Modify: `frontend/src/pages/Sparql.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append two new tests inside the existing top-level `describe` block in `frontend/src/pages/Sparql.test.tsx`:

```tsx
it('navigates to the term page when an IRI cell is clicked', async () => {
  vi.resetModules()
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => '') }),
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
          latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } },
      ],
      isLoading: false,
    }),
  }))
  // Stub navigate to capture calls
  const navigateMock = vi.fn()
  vi.doMock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
    return { ...actual, useNavigate: () => navigateMock }
  })

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )

  const yasguiHost = screen.getByTestId('yasgui-container')
  const a = document.createElement('a')
  a.className = 'iri'
  a.href = 'https://w3id.org/ontostart/pizza/Margherita'
  a.textContent = 'Margherita'
  yasguiHost.appendChild(a)

  fireEvent.click(a)
  await waitFor(() => {
    expect(navigateMock).toHaveBeenCalledWith(
      '/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita'
    )
  })
})

it('fetches and applies labels when the labels toggle is enabled', async () => {
  vi.resetModules()
  const setEndpointMock = vi.fn()
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => '') }),
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: setEndpointMock,
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
      }),
      destroy: vi.fn(),
    })),
  }))
  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({ ontologies: [], isLoading: false }),
  }))
  // Stub fetch for the labels SPARQL call
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      results: { bindings: [
        { iri: { type: 'uri', value: 'http://a/' }, label: { type: 'literal', value: 'Alpha' } },
      ] },
    }),
  }) as any

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )

  // Pre-populate one a.iri inside the Yasgui host
  const yasguiHost = screen.getByTestId('yasgui-container')
  const a = document.createElement('a')
  a.className = 'iri'
  a.href = 'http://a/'
  a.textContent = 'http://a/'
  yasguiHost.appendChild(a)

  // Click the labels toggle
  fireEvent.click(screen.getByRole('button', { name: /toggle result labels/i }))

  await waitFor(() => {
    const span = yasguiHost.querySelector('.iri-label')
    expect(span).not.toBeNull()
    expect(span?.textContent).toBe(' · Alpha')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx --reporter=basic`

Expected: FAIL — the click handler and labels-toggle wiring don't exist in `Sparql.tsx` yet.

- [ ] **Step 3: Modify `frontend/src/pages/Sparql.tsx`**

Read the file first to understand the existing structure. Then make these edits in order:

1. **Add imports** alongside the existing ones at the top:

```tsx
import { useNavigate } from 'react-router-dom'
import { installIriClickHandler } from '../components/sparql/iriClickHandler'
import { collectIris, buildLabelsQuery, applyLabels, removeLabels } from '../components/sparql/labelEnricher'
```

(`useLocation` is already imported from `react-router-dom`; extend the import to include `useNavigate`.)

2. **Add a navigate hook** inside the `Sparql` component, near the other top-of-component hooks:

```tsx
const navigate = useNavigate()
```

3. **Install the click handler when Yasgui mounts.** Inside the existing Yasgui-mount `useEffect`, AFTER `yasguiRef.current = new Yasgui(...)`, before the `qId` handling, add:

```tsx
const teardownClickHandler = containerRef.current
  ? installIriClickHandler(containerRef.current, {
      getOntologies: () => ontologiesRef.current,
      navigate,
    })
  : () => {}
```

Then extend the existing cleanup return inside that `useEffect` to also call `teardownClickHandler()`:

```tsx
return () => {
  teardownClickHandler()
  if (yasguiRef.current) {
    if (typeof yasguiRef.current.destroy === 'function') {
      yasguiRef.current.destroy()
    } else if (containerRef.current) {
      containerRef.current.innerHTML = ''
    }
    yasguiRef.current = null
  }
}
```

4. **Add labels-toggle state + apply/remove helpers.** Add a `useState` near the other handlers:

```tsx
const [labelsOn, setLabelsOn] = useState(false)
```

Then add a stable `runLabelEnrichment` callback that does the fetch + apply:

```tsx
const runLabelEnrichment = useCallback(async () => {
  const root = containerRef.current
  if (!root) return
  const iris = collectIris(root)
  if (iris.length === 0) return
  const endpoint = (() => {
    const cfg = yasguiRef.current?.getTab()?.getRequestConfig()
    const raw = cfg?.endpoint
    if (typeof raw === 'string') return raw
    return '/api/v1/sparql/content'
  })()
  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/sparql-results+json',
      },
      body: `query=${encodeURIComponent(buildLabelsQuery(iris))}`,
    })
    if (!resp.ok) return
    const data = await resp.json()
    const labels = new Map<string, string>()
    for (const b of data?.results?.bindings ?? []) {
      const iri = b?.iri?.value
      const lbl = b?.label?.value
      if (iri && lbl && !labels.has(iri)) labels.set(iri, lbl)
    }
    if (containerRef.current) applyLabels(containerRef.current, labels)
  } catch {
    // Silent fallback: labels aren't critical
  }
}, [])
```

Then add the toggle handler:

```tsx
const handleLabelsToggle = useCallback((enabled: boolean) => {
  setLabelsOn(enabled)
  if (!containerRef.current) return
  if (enabled) {
    runLabelEnrichment()
  } else {
    removeLabels(containerRef.current)
  }
}, [runLabelEnrichment])
```

5. **Subscribe to Yasr's `drawn` event so labels re-apply after re-renders.** Inside the same Yasgui-mount `useEffect`, AFTER the click handler install:

```tsx
const yasr = yasguiRef.current?.getTab()?.getYasr()
if (yasr && typeof yasr.on === 'function') {
  yasr.on('drawn', () => {
    if (labelsOnRef.current) runLabelEnrichment()
  })
}
```

To read `labelsOn` inside that closure without re-registering, add a ref:

```tsx
const labelsOnRef = useRef(false)
useEffect(() => { labelsOnRef.current = labelsOn }, [labelsOn])
```

6. **Pass the toggle callback to ScopeToolbar:**

```tsx
<ScopeToolbar
  onScopeChange={handleScopeChange}
  onCopy={handleCopy}
  onOntologyAdded={handleOntologyAdded}
  onSelectionChange={handleSelectionChange}
  onLabelsToggle={handleLabelsToggle}
/>
```

7. **Add a `data-testid` to the Yasgui container div** so the integration tests can locate it. Find the existing line:

```tsx
<div ref={containerRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto' }} />
```

Change it to:

```tsx
<div ref={containerRef} data-testid="yasgui-container" style={{ flex: 1, minHeight: 0, overflowY: 'auto' }} />
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx src/components/sparql/ --reporter=basic`

Expected: PASS — both new Sparql tests pass; all other tests (19 ScopeToolbar + 13 prefixUtils + 10 positionUtils + 9 ontoCompleter + 15 scopeUrls + 7 iriResolver + 12 labelEnricher + 6 iriClickHandler = 91 plus the prior Sparql tests still pass).

- [ ] **Step 5: TS check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "Sparql\.tsx|ScopeToolbar|iriResolver|iriClickHandler|labelEnricher" | grep -v "\.test\."`

Expected: empty.

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/Sparql.tsx frontend/src/pages/Sparql.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): wire IRI click handler and labels-toggle enrichment

At Sparql page mount, installs the IRI click handler on the Yasgui
container so clicks on a.iri elements navigate to the term page via
React Router. Subscribes to Yasr's drawn event so labels re-apply
after every re-render when the labels toggle is on. The labels
fetch uses the same scoped endpoint Yasgui currently posts to.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: End-to-end sweep

- [ ] **Step 1: Full frontend test run**

Run: `cd frontend && npx vitest run --reporter=basic 2>&1 | tail -20`

Expected: all feature tests pass (counts per Task 5 Step 4 + every other test file). Note any failure and determine whether it's caused by this feature (touched files: `iriResolver`, `iriClickHandler`, `labelEnricher`, `ScopeToolbar`, `Sparql.tsx`) or pre-existing.

- [ ] **Step 2: Full project TypeScript check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "(Sparql\.tsx|ScopeToolbar|iriResolver|iriClickHandler|labelEnricher)" | grep -v "\.test\."`

Expected: empty.

- [ ] **Step 3: Verify file inventory**

Run: `git log --since="2 hours ago" --stat | head -80`

Confirm only the expected files were touched.

- [ ] **Step 4: Manual smoke test (optional)**

Open `/sparql` in the dev server:

1. Run the default starter query. Confirm the result table has IRI cells styled as links.
2. Add the pizza ontology to scope. Run a query like `SELECT * WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 5`.
3. Click an IRI from the pizza ontology. Confirm the URL changes to `/ontologies/pizza?term=<iri>` (in-app navigation, not a new tab).
4. Ctrl-click an IRI. Confirm it opens in a new tab (raw IRI).
5. Click the 📑 toggle. Confirm `· <label>` spans appear after each IRI that has an `rdfs:label`.
6. Click the toggle again. Confirm labels disappear.
7. Run a new query (re-trigger Yasgui). With the toggle still on, confirm labels re-appear on the new results.

- [ ] **Step 5: Optional post-merge cleanup commit**

If anything was tweaked during the sweep:

```bash
cd /home/micheldumontier/code/ontoexplorer
git add -A
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(sparql): post-merge cleanup for result enrichment

Fix-ups discovered during the end-to-end sweep.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If nothing changed, no commit.

---

## Out of scope

Per the spec, these are explicit non-goals for this plan:

- Manchester rendering for bnode / anonymous-class results — backend work needed; deferred.
- Per-row expand/inspect UI — Yasr's own row UI; not touched.
- Preferred-language filter for labels — v1 shows whatever label is returned first.
- Client-side caching of label lookups across queries — React Query is enough.
- IRI → CURIE display in cells — Yasr already does this when a PREFIX is declared (free with sub-project C).
- Toggle persistence across page loads — off by default each visit.
- Labels in non-tabular result formats (Turtle CONSTRUCT, raw JSON view) — v1 only enriches the table.
