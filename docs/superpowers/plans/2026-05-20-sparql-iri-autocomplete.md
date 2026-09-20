# SPARQL IRI Autocomplete + Prefix Autoload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Yasqe editor term-aware: typing a partial label inside `<...>` or after a known prefix offers IRI suggestions; adding an ontology to the scope toolbar auto-prepends its `PREFIX` declaration to the editor.

**Architecture:** Frontend-only. Register a custom Yasqe autocompleter via `Yasqe.registerAutocompleter(...)` that classifies the cursor position (IRI literal vs prefixed-name), queries the existing `/api/v1/autocomplete` endpoint, and inserts the right form. A separate prefix-injection step runs when `ScopeToolbar` fires a new `onOntologyAdded` callback — additive-only, never removes.

**Tech Stack:** React 18 + TypeScript, Vitest + jsdom, @testing-library/react, @triply/yasgui v4 (CodeMirror-based), existing `api.search.autocomplete` client.

**Spec:** [`docs/superpowers/specs/2026-05-20-sparql-iri-autocomplete-design.md`](../specs/2026-05-20-sparql-iri-autocomplete-design.md)

---

## File Map

| Path | Role |
|---|---|
| `frontend/src/components/sparql/prefixUtils.ts` | Pure helpers: derive base IRI from an ontology, detect existing PREFIX, prepend a PREFIX line. |
| `frontend/src/components/sparql/prefixUtils.test.ts` | Unit tests for the helpers. |
| `frontend/src/components/sparql/positionUtils.ts` | Pure helper: classify a Yasqe token + cursor position as `iri` / `curie` / `none`, extract the partial-text the user is typing and the bound prefix IRI if any. |
| `frontend/src/components/sparql/positionUtils.test.ts` | Unit tests. |
| `frontend/src/components/sparql/ontoCompleter.ts` | `buildOntoCompleter(getSelectedOntologyIds, getOntologies)` returns a Yasqe `CompleterConfig`. Reuses `prefixUtils` + `positionUtils`; calls `api.search.autocomplete`. |
| `frontend/src/components/sparql/ontoCompleter.test.ts` | Unit tests (mocked fetch + stubbed Yasqe). |
| `frontend/src/components/sparql/ScopeToolbar.tsx` | Add optional `onOntologyAdded?: (ontologyId: string) => void` prop. Fire on add (popover-click + chip toggle add), NOT on remove. |
| `frontend/src/components/sparql/ScopeToolbar.test.tsx` | Extend "selecting ontologies" describe block with two new tests. |
| `frontend/src/pages/Sparql.tsx` | At mount: `Yasqe.registerAutocompleter(buildOntoCompleter(...))`. Add `handleOntologyAdded(ontologyId)` that injects the PREFIX into the editor. |
| `frontend/src/pages/Sparql.test.tsx` | One new integration test: adding an ontology triggers `setValue` with the PREFIX prepended; same-name PREFIX is not duplicated. |

---

## Task 1: Pure prefix helpers

`extractBaseIri`, `hasPrefix`, `prependPrefix` — no React, no DOM, no fetch.

**Files:**
- Create: `frontend/src/components/sparql/prefixUtils.ts`
- Test: `frontend/src/components/sparql/prefixUtils.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/prefixUtils.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { extractBaseIri, hasPrefix, prependPrefix } from './prefixUtils'

describe('extractBaseIri', () => {
  it('keeps slash-terminated IRIs as-is', () => {
    expect(extractBaseIri('http://example.org/foo/')).toBe('http://example.org/foo/')
  })

  it('keeps hash-terminated IRIs as-is', () => {
    expect(extractBaseIri('http://example.org/foo#')).toBe('http://example.org/foo#')
  })

  it('appends / when neither terminator is present', () => {
    expect(extractBaseIri('http://example.org/foo')).toBe('http://example.org/foo/')
  })

  it('handles IRIs with empty path', () => {
    expect(extractBaseIri('http://example.org')).toBe('http://example.org/')
  })
})

describe('hasPrefix', () => {
  it('returns true for an exact PREFIX line', () => {
    expect(hasPrefix('PREFIX pizza: <http://x>\nSELECT * WHERE { ?s ?p ?o }', 'pizza')).toBe(true)
  })

  it('returns true ignoring case of PREFIX keyword', () => {
    expect(hasPrefix('prefix pizza: <http://x>\n', 'pizza')).toBe(true)
  })

  it('returns true with extra whitespace', () => {
    expect(hasPrefix('  PREFIX   pizza:   <http://x>\n', 'pizza')).toBe(true)
  })

  it('returns false when prefix name differs', () => {
    expect(hasPrefix('PREFIX other: <http://x>\n', 'pizza')).toBe(false)
  })

  it('returns false when no PREFIX line at all', () => {
    expect(hasPrefix('SELECT * WHERE { ?s ?p ?o }', 'pizza')).toBe(false)
  })

  it('matches in a multi-line query', () => {
    const q = 'PREFIX owl: <http://www.w3.org/2002/07/owl#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT * WHERE { }'
    expect(hasPrefix(q, 'rdfs')).toBe(true)
    expect(hasPrefix(q, 'owl')).toBe(true)
    expect(hasPrefix(q, 'missing')).toBe(false)
  })
})

describe('prependPrefix', () => {
  it('prepends to an empty query', () => {
    expect(prependPrefix('', 'pizza', 'http://x/')).toBe('PREFIX pizza: <http://x/>\n')
  })

  it('prepends above existing content', () => {
    expect(prependPrefix('SELECT * WHERE { ?s ?p ?o }', 'pizza', 'http://x/'))
      .toBe('PREFIX pizza: <http://x/>\nSELECT * WHERE { ?s ?p ?o }')
  })

  it('preserves existing PREFIX lines from being touched', () => {
    const before = 'PREFIX owl: <http://www.w3.org/2002/07/owl#>\nSELECT * WHERE { ?s ?p ?o }'
    expect(prependPrefix(before, 'pizza', 'http://x/'))
      .toBe('PREFIX pizza: <http://x/>\nPREFIX owl: <http://www.w3.org/2002/07/owl#>\nSELECT * WHERE { ?s ?p ?o }')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/prefixUtils.test.ts --reporter=basic`

Expected: FAIL — `prefixUtils.ts` doesn't exist.

- [ ] **Step 3: Implement helpers**

Create `frontend/src/components/sparql/prefixUtils.ts`:

```typescript
/**
 * Normalise an ontology IRI to a usable base for prefix declarations.
 * If it already ends in `/` or `#`, return as-is; otherwise append `/`.
 */
export function extractBaseIri(ontologyIri: string): string {
  if (ontologyIri.endsWith('/') || ontologyIri.endsWith('#')) return ontologyIri
  return `${ontologyIri}/`
}

/**
 * True if the query text already contains a PREFIX declaration for the given
 * shortname. Case-insensitive on the PREFIX keyword; whitespace-tolerant.
 */
export function hasPrefix(queryText: string, shortname: string): boolean {
  const escaped = shortname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`^\\s*PREFIX\\s+${escaped}\\s*:\\s*<`, 'im')
  return re.test(queryText)
}

/**
 * Prepend `PREFIX <shortname>: <baseIri>\n` to the query text. Does not check
 * for duplicates — callers should `hasPrefix(...)` first.
 */
export function prependPrefix(queryText: string, shortname: string, baseIri: string): string {
  return `PREFIX ${shortname}: <${baseIri}>\n${queryText}`
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/prefixUtils.test.ts --reporter=basic`

Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/sparql/prefixUtils.ts frontend/src/components/sparql/prefixUtils.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): prefix helpers for IRI autocomplete

Pure functions: extractBaseIri normalises an ontology IRI to a
slash/hash-terminated namespace; hasPrefix is a case-insensitive
PREFIX-line detector; prependPrefix inserts a PREFIX line at the
top of an existing query.
EOF
)"
```

---

## Task 2: Position-classification helper

Given a Yasqe token at the cursor and the editor's current prefix map, decide whether the cursor is in an IRI literal, a prefixed-name (CURIE), or neither. Return the partial text the user is typing and (for CURIE) the bound prefix's base IRI.

**Files:**
- Create: `frontend/src/components/sparql/positionUtils.ts`
- Test: `frontend/src/components/sparql/positionUtils.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/positionUtils.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { classifyPosition } from './positionUtils'

const NO_PREFIXES = {}
const PREFIXES = { pizza: 'https://w3id.org/ontostart/pizza/', owl: 'http://www.w3.org/2002/07/owl#' }

describe('classifyPosition', () => {
  it('returns iri for a token starting with <', () => {
    expect(classifyPosition({ string: '<http://example.org/Marg', type: null }, NO_PREFIXES))
      .toEqual({ kind: 'iri', partial: 'http://example.org/Marg' })
  })

  it('returns iri for a bare < token (cursor just after <)', () => {
    expect(classifyPosition({ string: '<', type: null }, NO_PREFIXES))
      .toEqual({ kind: 'iri', partial: '' })
  })

  it('returns curie when token is prefix:local with known prefix', () => {
    expect(classifyPosition({ string: 'pizza:Marg', type: 'string-2' }, PREFIXES))
      .toEqual({ kind: 'curie', partial: 'Marg', prefix: 'pizza', baseIri: 'https://w3id.org/ontostart/pizza/' })
  })

  it('returns curie when token is just prefix: (empty local part)', () => {
    expect(classifyPosition({ string: 'pizza:', type: 'string-2' }, PREFIXES))
      .toEqual({ kind: 'curie', partial: '', prefix: 'pizza', baseIri: 'https://w3id.org/ontostart/pizza/' })
  })

  it('returns curie with no baseIri when prefix is unknown', () => {
    expect(classifyPosition({ string: 'unknown:Foo', type: 'string-2' }, PREFIXES))
      .toEqual({ kind: 'curie', partial: 'Foo', prefix: 'unknown' })
  })

  it('returns none for a variable token', () => {
    expect(classifyPosition({ string: '?x', type: null }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for a dollar-variable', () => {
    expect(classifyPosition({ string: '$x', type: null }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for a string literal token', () => {
    expect(classifyPosition({ string: '"hello', type: 'string' }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for an empty token', () => {
    expect(classifyPosition({ string: '', type: null }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for keywords without prefix:', () => {
    expect(classifyPosition({ string: 'SELECT', type: 'keyword' }, PREFIXES))
      .toEqual({ kind: 'none' })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/positionUtils.test.ts --reporter=basic`

Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Implement helper**

Create `frontend/src/components/sparql/positionUtils.ts`:

```typescript
export type Position =
  | { kind: 'none' }
  | { kind: 'iri'; partial: string }
  | { kind: 'curie'; partial: string; prefix: string; baseIri?: string }

interface MinimalToken {
  string: string
  type: string | null
}

/**
 * Classify what kind of completion is appropriate at the cursor token.
 *
 * - `iri`   : cursor is inside `<...>`. Suggest matching IRIs.
 * - `curie` : cursor is in a `prefix:local` token. Suggest local names.
 * - `none`  : variable, literal, keyword, empty — no suggestions.
 *
 * @param token         { string, type } from yasqe.getCompleteToken() / getTokenAt()
 * @param queryPrefixes prefix-name → base-iri map (from yasqe.getPrefixesFromQuery())
 */
export function classifyPosition(token: MinimalToken, queryPrefixes: Record<string, string>): Position {
  const s = token.string
  if (!s) return { kind: 'none' }
  if (s.startsWith('?') || s.startsWith('$')) return { kind: 'none' }
  if (token.type === 'string') return { kind: 'none' }
  if (token.type === 'keyword') return { kind: 'none' }

  if (s.startsWith('<')) {
    return { kind: 'iri', partial: s.slice(1) }
  }

  const colonIdx = s.indexOf(':')
  if (colonIdx > 0) {
    const prefix = s.slice(0, colonIdx)
    const partial = s.slice(colonIdx + 1)
    const baseIri = queryPrefixes[prefix]
    return baseIri
      ? { kind: 'curie', partial, prefix, baseIri }
      : { kind: 'curie', partial, prefix }
  }

  return { kind: 'none' }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/positionUtils.test.ts --reporter=basic`

Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/sparql/positionUtils.ts frontend/src/components/sparql/positionUtils.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): cursor-position classifier for IRI autocomplete

Pure helper that decides whether the cursor is in an IRI literal,
a CURIE, or neither. Returns the partial text the user is typing
plus (for CURIE) the resolved prefix → base-iri mapping when known.
Distinguishes variables and string literals so the completer doesn't
fire in non-IRI positions.
EOF
)"
```

---

## Task 3: Yasqe completer

`buildOntoCompleter(getSelectedOntologyIds, getOntologies)` returns a `CompleterConfig` that Yasqe calls per keystroke. Encapsulates the position classification, the fetch, the per-position formatting.

**Files:**
- Create: `frontend/src/components/sparql/ontoCompleter.ts`
- Test: `frontend/src/components/sparql/ontoCompleter.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/sparql/ontoCompleter.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { buildOntoCompleter } from './ontoCompleter'
import type { Ontology } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: {
    search: {
      autocomplete: vi.fn(),
    },
  },
}))

import { api } from '../../lib/api'
const mockAutocomplete = api.search.autocomplete as ReturnType<typeof vi.fn>

const PIZZA: Ontology = {
  id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
  title: 'Pizza', created_at: '2024-01-01',
  latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
} as any

function stubYasqe(tokenString: string, prefixes: Record<string, string> = {}) {
  return {
    getCompleteToken: () => ({ string: tokenString, type: null }),
    getPrefixesFromQuery: () => prefixes,
  } as any
}

beforeEach(() => {
  mockAutocomplete.mockReset()
})

describe('buildOntoCompleter — isValidCompletionPosition', () => {
  const completer = buildOntoCompleter(() => [], () => [])

  it('returns true inside <...>', () => {
    expect(completer.isValidCompletionPosition(stubYasqe('<http://example.org/Marg'))).toBe(true)
  })

  it('returns true for a CURIE-like token', () => {
    expect(completer.isValidCompletionPosition(stubYasqe('pizza:Marg'))).toBe(true)
  })

  it('returns false for a variable', () => {
    expect(completer.isValidCompletionPosition(stubYasqe('?x'))).toBe(false)
  })

  it('returns false for an empty token', () => {
    expect(completer.isValidCompletionPosition(stubYasqe(''))).toBe(false)
  })
})

describe('buildOntoCompleter — get', () => {
  it('fetches with the IRI partial when inside <...>', async () => {
    mockAutocomplete.mockResolvedValue({
      completions: [{ text: 'Pizza', iri: 'https://w3id.org/ontostart/pizza/Pizza', type: 'class',
                     short: 'Pizza', insert: 'Pizza', lang: 'en', cross_language: false,
                     ontology_shortname: 'pizza' }],
      context: 'name', replace_from: 0, replace_to: 4,
    })
    const completer = buildOntoCompleter(() => ['O1'], () => [PIZZA])
    const result = await completer.get(stubYasqe('<Marg'), { string: '<Marg', type: null } as any)
    expect(mockAutocomplete).toHaveBeenCalledWith('Marg', -1, ['O1'])
    expect(result).toEqual(['<https://w3id.org/ontostart/pizza/Pizza>'])
  })

  it('fetches with the local-name partial and filters by matching ontology for a known CURIE', async () => {
    mockAutocomplete.mockResolvedValue({
      completions: [{ text: 'Margherita', iri: 'https://w3id.org/ontostart/pizza/Margherita', type: 'class',
                     short: 'Margherita', insert: 'Margherita', lang: 'en', cross_language: false,
                     ontology_shortname: 'pizza' }],
      context: 'name', replace_from: 0, replace_to: 10,
    })
    const completer = buildOntoCompleter(() => ['O1', 'O2'], () => [PIZZA])
    const result = await completer.get(
      stubYasqe('pizza:Marg', { pizza: 'https://w3id.org/ontostart/pizza/' }),
      { string: 'pizza:Marg', type: 'string-2' } as any,
    )
    expect(mockAutocomplete).toHaveBeenCalledWith('Marg', -1, ['O1'])
    expect(result).toEqual(['pizza:Margherita'])
  })

  it('falls back to fleet-wide when CURIE prefix is unbound in the editor', async () => {
    mockAutocomplete.mockResolvedValue({ completions: [], context: 'name', replace_from: 0, replace_to: 0 })
    const completer = buildOntoCompleter(() => ['O1'], () => [PIZZA])
    await completer.get(
      stubYasqe('unknown:Foo'),
      { string: 'unknown:Foo', type: 'string-2' } as any,
    )
    expect(mockAutocomplete).toHaveBeenCalledWith('Foo', -1, [])
  })

  it('passes empty ontology_ids when scope selection is empty', async () => {
    mockAutocomplete.mockResolvedValue({ completions: [], context: 'name', replace_from: 0, replace_to: 0 })
    const completer = buildOntoCompleter(() => [], () => [PIZZA])
    await completer.get(stubYasqe('<Marg'), { string: '<Marg', type: null } as any)
    expect(mockAutocomplete).toHaveBeenCalledWith('Marg', -1, [])
  })

  it('returns an empty list on fetch error', async () => {
    mockAutocomplete.mockRejectedValue(new Error('boom'))
    const completer = buildOntoCompleter(() => [], () => [])
    const result = await completer.get(stubYasqe('<x'), { string: '<x', type: null } as any)
    expect(result).toEqual([])
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/ontoCompleter.test.ts --reporter=basic`

Expected: FAIL — `ontoCompleter.ts` doesn't exist.

- [ ] **Step 3: Implement completer**

Create `frontend/src/components/sparql/ontoCompleter.ts`:

```typescript
import { api, Ontology } from '../../lib/api'
import { extractBaseIri } from './prefixUtils'
import { classifyPosition } from './positionUtils'

interface YasqeLike {
  getCompleteToken: () => { string: string; type: string | null }
  getPrefixesFromQuery: () => Record<string, string>
}

interface CompleterConfig {
  name: string
  bulk: boolean
  autoShow: boolean
  isValidCompletionPosition: (yasqe: YasqeLike) => boolean
  get: (yasqe: YasqeLike, token: { string: string; type: string | null }) => Promise<string[]>
}

/**
 * Build a Yasqe autocompleter that suggests IRIs/CURIEs from OntoExplorer's
 * search backend, scoped to the user's current ontology selection.
 *
 * @param getSelectedOntologyIds  closure read on each keystroke — returns the
 *                                ScopeToolbar's current selection.
 * @param getOntologies           closure that returns the full ontology list
 *                                (needed to map prefix → ontology id for
 *                                CURIE-position scoping).
 */
export function buildOntoCompleter(
  getSelectedOntologyIds: () => string[],
  getOntologies: () => Ontology[],
): CompleterConfig {
  return {
    name: 'ontoexplorer',
    bulk: false,
    autoShow: true,

    isValidCompletionPosition(yasqe) {
      const token = yasqe.getCompleteToken()
      const pos = classifyPosition(token, yasqe.getPrefixesFromQuery())
      return pos.kind !== 'none'
    },

    async get(yasqe, _token) {
      const token = yasqe.getCompleteToken()
      const prefixes = yasqe.getPrefixesFromQuery()
      const pos = classifyPosition(token, prefixes)
      if (pos.kind === 'none') return []

      const selected = getSelectedOntologyIds()
      let ontologyIds: string[] = selected
      let partial = pos.partial

      if (pos.kind === 'curie' && pos.baseIri) {
        // Restrict to the ontology that owns this prefix's base IRI, if known.
        const match = getOntologies().find(o => extractBaseIri(o.iri) === pos.baseIri)
        ontologyIds = match ? [match.id] : []
      } else if (pos.kind === 'curie' && !pos.baseIri) {
        // Unknown prefix in the editor — fall back to fleet-wide.
        ontologyIds = []
      }

      try {
        const resp = await api.search.autocomplete(partial, -1, ontologyIds)
        return resp.completions
          .filter(c => c.iri)
          .map(c => formatInsertion(c.iri as string, pos, prefixes, getOntologies()))
      } catch {
        return []
      }
    },
  }
}

/**
 * Format an IRI suggestion for insertion based on cursor position.
 * - `iri`   → `<full-iri>`
 * - `curie` → `prefix:LocalName` (using the prefix that was already typed)
 */
function formatInsertion(
  iri: string,
  pos: ReturnType<typeof classifyPosition>,
  _prefixes: Record<string, string>,
  _ontologies: Ontology[],
): string {
  if (pos.kind === 'iri') {
    return `<${iri}>`
  }
  if (pos.kind === 'curie' && pos.baseIri && iri.startsWith(pos.baseIri)) {
    const localName = iri.slice(pos.baseIri.length)
    return `${pos.prefix}:${localName}`
  }
  // Fallback: wrap in <> if we can't compose a CURIE
  return `<${iri}>`
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ontoCompleter.test.ts --reporter=basic`

Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/sparql/ontoCompleter.ts frontend/src/components/sparql/ontoCompleter.test.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): Yasqe autocompleter for IRI / CURIE completion

buildOntoCompleter returns a Yasqe CompleterConfig that classifies
the cursor position (IRI literal vs prefixed-name), queries the
existing /api/v1/autocomplete endpoint with the right partial text
and ontology filter, then formats suggestions for insertion. The
ontology filter follows the ScopeToolbar's selection; CURIE position
narrows further to the ontology whose base IRI matches the bound
prefix.
EOF
)"
```

---

## Task 4: ScopeToolbar — fire `onOntologyAdded` on add

Extend `ScopeToolbar` to emit a callback when an ontology is added to the selection. Removal does NOT fire it.

**Files:**
- Modify: `frontend/src/components/sparql/ScopeToolbar.tsx`
- Modify: `frontend/src/components/sparql/ScopeToolbar.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/sparql/ScopeToolbar.test.tsx`:

```tsx
describe('ScopeToolbar — onOntologyAdded callback', () => {
  it('fires with the ontology id on chip add', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onAdded = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onOntologyAdded={onAdded} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(onAdded).toHaveBeenCalledWith('O1')
  })

  it('does not fire on chip remove', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onAdded = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onOntologyAdded={onAdded} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onAdded.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /remove envo/i }))
    expect(onAdded).not.toHaveBeenCalled()
  })

  it('does not fire on initial render with empty selection', () => {
    const onAdded = vi.fn()
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} onOntologyAdded={onAdded} />))
    expect(onAdded).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: FAIL — `onOntologyAdded` is not in the props.

- [ ] **Step 3: Modify `ScopeToolbar.tsx`**

Open `frontend/src/components/sparql/ScopeToolbar.tsx`. Make three edits:

1. Extend the props interface:

```tsx
export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
  onOntologyAdded?: (ontologyId: string) => void
}
```

2. Destructure the new prop in the component signature:

```tsx
export function ScopeToolbar({ onScopeChange, onCopy, onOntologyAdded }: ScopeToolbarProps) {
```

3. Modify `toggleOntology` to fire the callback only on the add path:

```tsx
function toggleOntology(id: string) {
  setSelected(prev => {
    const next = new Set(prev)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
      onOntologyAdded?.(id)
    }
    return next
  })
}
```

The chip-remove handler (`removeChip`) is unchanged — it only removes, never adds, so it doesn't need to fire `onOntologyAdded`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/sparql/ScopeToolbar.test.tsx --reporter=basic`

Expected: PASS, 16 tests (13 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/sparql/ScopeToolbar.tsx frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): ScopeToolbar emits onOntologyAdded on chip add

Optional callback fires when an ontology is added to the selection
(popover click). Removal explicitly does not fire it — the page uses
this signal to inject a PREFIX line into the editor, and we want the
PREFIX to stick around even after the ontology is deselected from
scope (additive-only policy).
EOF
)"
```

---

## Task 5: Sparql page — wire prefix injection

Hook `ScopeToolbar`'s new callback to the editor: when an ontology is added, prepend its PREFIX line if not already present.

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`
- Modify: `frontend/src/pages/Sparql.test.tsx`

- [ ] **Step 1: Add the failing test**

Append to `frontend/src/pages/Sparql.test.tsx` (within the existing `describe` block):

```tsx
it('prepends a PREFIX line when an ontology is added to scope', async () => {
  vi.resetModules()
  const setValueMock = vi.fn()
  const getValueMock = vi.fn(() => 'SELECT * WHERE { ?s ?p ?o }')
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: setValueMock, getValue: getValueMock }),
        setEndpoint: vi.fn(),
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

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
  fireEvent.click(screen.getByText('pizza'))

  // setValue is called with PREFIX prepended
  await waitFor(() => {
    expect(setValueMock).toHaveBeenCalledWith(
      'PREFIX pizza: <https://w3id.org/ontostart/pizza/>\nSELECT * WHERE { ?s ?p ?o }'
    )
  })
})

it('does not duplicate PREFIX when the same shortname is already in the query', async () => {
  vi.resetModules()
  const setValueMock = vi.fn()
  const getValueMock = vi.fn(() => 'PREFIX pizza: <https://w3id.org/ontostart/pizza/>\nSELECT * WHERE { ?s ?p ?o }')
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: setValueMock, getValue: getValueMock }),
        setEndpoint: vi.fn(),
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

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
  fireEvent.click(screen.getByText('pizza'))

  // setValue is NOT called because the PREFIX is already present
  await new Promise(resolve => setTimeout(resolve, 50))
  expect(setValueMock).not.toHaveBeenCalled()
})
```

If `waitFor` or `fireEvent` are not yet imported at the top of `Sparql.test.tsx`, add them to the existing import line from `@testing-library/react`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx --reporter=basic`

Expected: FAIL on the two new tests — the PREFIX-injection wiring doesn't exist yet.

- [ ] **Step 3: Modify `frontend/src/pages/Sparql.tsx`**

Make four edits:

1. Add imports at the top:

```tsx
import { hasPrefix, prependPrefix, extractBaseIri } from '../components/sparql/prefixUtils'
import { useOntologies } from '../hooks/useOntologies'
```

2. Read `ontologies` inside the `Sparql` component (just after the existing `useLocation()`, `useState`, `useRef` lines):

```tsx
const { ontologies } = useOntologies()
```

3. Add a stable handler:

```tsx
const handleOntologyAdded = useCallback((ontologyId: string) => {
  const onto = ontologies.find(o => o.id === ontologyId)
  if (!onto) return
  const shortname = onto.shortname || onto.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() || 'ns'
  const baseIri = extractBaseIri(onto.iri)
  const yasqe = yasguiRef.current?.getTab()?.getYasqe()
  if (!yasqe) return
  const current = yasqe.getValue() ?? ''
  if (hasPrefix(current, shortname)) return
  yasqe.setValue(prependPrefix(current, shortname, baseIri))
}, [ontologies])
```

4. Pass it through:

```tsx
<ScopeToolbar
  onScopeChange={handleScopeChange}
  onCopy={handleCopy}
  onOntologyAdded={handleOntologyAdded}
/>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx src/components/sparql/ --reporter=basic`

Expected: PASS — both new Sparql page tests pass, all 16 ScopeToolbar tests still pass, all 14 prefixUtils tests still pass, all 10 positionUtils tests still pass, all 9 ontoCompleter tests still pass, all 15 scopeUrls tests still pass.

- [ ] **Step 5: TS check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "Sparql\.tsx|ScopeToolbar|prefixUtils|positionUtils|ontoCompleter" | grep -v "\.test\."`

Expected: no output.

- [ ] **Step 6: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/pages/Sparql.tsx frontend/src/pages/Sparql.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): auto-prepend PREFIX line when ontology added to scope

When the ScopeToolbar fires onOntologyAdded, the Sparql page reads
the ontology's IRI, normalises it to a base, and prepends a PREFIX
declaration to the editor (if not already present). Additive-only:
removing an ontology from scope does not remove its PREFIX line.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Sparql page — register the Yasqe autocompleter

Wire `buildOntoCompleter` into Yasgui at mount time so the editor starts offering term-aware suggestions.

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`

- [ ] **Step 1: Modify `frontend/src/pages/Sparql.tsx`**

Make four edits:

1. Add the import at the top of the file:

```tsx
import { buildOntoCompleter } from '../components/sparql/ontoCompleter'
```

2. Add a ref for the selected ontology ids near the other refs:

```tsx
const selectedOntologyIdsRef = useRef<string[]>([])
const ontologiesRef = useRef<Ontology[]>([])
```

(Also import `Ontology` from `../lib/api` if not already imported, in the same line as `api` or via a new `import type` line.)

3. Keep the refs synced with the toolbar state by intercepting `handleScopeChange` and storing the latest selection. Simpler approach: extend ScopeToolbar's `onScopeChange` payload OR keep a separate ref synced via a new ScopeToolbar callback. Easiest path: hold the ref in this file and update it whenever `ontologies` changes (just an init) plus when the toolbar reports a scope change. But the cleanest hookup is:

   Replace `handleScopeChange` to also update the ref. Since `onScopeChange` only receives the endpoint URL string, we cannot derive the selection from it. Add another callback. Edit `ScopeToolbarProps` and the toolbar's effect to also emit the ids.

   Simpler: in `ScopeToolbar.tsx`, after the existing `useEffect([endpoint, onScopeChange])`, add a second effect that calls a new optional `onSelectionChange?: (ids: string[]) => void` whenever `selected` changes:

   Add to `ScopeToolbarProps` in `ScopeToolbar.tsx`:

   ```tsx
   onSelectionChange?: (ontologyIds: string[]) => void
   ```

   Add to the destructure:

   ```tsx
   export function ScopeToolbar({ onScopeChange, onCopy, onOntologyAdded, onSelectionChange }: ScopeToolbarProps) {
   ```

   Add a `useEffect` near the existing one:

   ```tsx
   useEffect(() => {
     onSelectionChange?.(Array.from(selected))
   }, [selected, onSelectionChange])
   ```

4. In `Sparql.tsx`, hook the new callback and update both refs:

```tsx
const handleSelectionChange = useCallback((ids: string[]) => {
  selectedOntologyIdsRef.current = ids
}, [])

useEffect(() => {
  ontologiesRef.current = ontologies
}, [ontologies])
```

5. Register the completer once at first Yasgui construction. Inside the existing `useEffect` that creates `new Yasgui(...)`, BEFORE the constructor call, add:

```tsx
// inside the useEffect, before `yasguiRef.current = new Yasgui(...)`:
const Yasqe = (Yasgui as any).Yasqe
if (Yasqe?.registerAutocompleter) {
  Yasqe.registerAutocompleter(
    buildOntoCompleter(
      () => selectedOntologyIdsRef.current,
      () => ontologiesRef.current,
    ),
  )
}
```

The guard skips the call cleanly when Yasgui is mocked in tests (the mock returns a plain object without a `Yasqe` static). The `(Yasgui as any).Yasqe` access is needed because Yasgui's runtime exposes the Yasqe constructor as a static but its TypeScript declarations don't.

6. Pass `onSelectionChange` to the `<ScopeToolbar>`:

```tsx
<ScopeToolbar
  onScopeChange={handleScopeChange}
  onCopy={handleCopy}
  onOntologyAdded={handleOntologyAdded}
  onSelectionChange={handleSelectionChange}
/>
```

- [ ] **Step 2: Smoke-test that the existing tests still pass**

Run: `cd frontend && npx vitest run src/pages/Sparql.test.tsx src/components/sparql/ --reporter=basic`

Expected: PASS — no regression. The `if (Yasqe?.registerAutocompleter)` guard added in Step 1 sub-edit 5 skips the call when Yasgui is mocked.

- [ ] **Step 3: Manual smoke test (skip in CI; run during local development)**

Open `/sparql`. Type `<piz` inside angle brackets — the Yasqe dropdown should show entries with "Pizza" matches. Add the pizza ontology to scope; type `<` again — suggestions are now narrower (pizza only). Type `pizza:Marg` — suggestions show Pizza ontology classes; selecting one inserts `pizza:Margherita`.

- [ ] **Step 4: TS check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "Sparql\.tsx|ScopeToolbar|prefixUtils|positionUtils|ontoCompleter" | grep -v "\.test\."`

Expected: no output.

- [ ] **Step 5: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/pages/Sparql.tsx frontend/src/components/sparql/ScopeToolbar.tsx frontend/src/components/sparql/ScopeToolbar.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): register Yasqe autocompleter for IRI completion

At Sparql page mount, Yasqe is taught to call the OntoExplorer
autocomplete API whenever the cursor sits inside <...> or at a
prefixed-name. The completer reads the ScopeToolbar's current
selection via a ref (kept in sync via a new onSelectionChange
callback) so scope changes affect future suggestions immediately.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: End-to-end sweep

Run the full frontend test suite and tsc to confirm nothing regressed.

- [ ] **Step 1: Full frontend test run**

Run: `cd frontend && npx vitest run --reporter=basic 2>&1 | tail -20`

Expected: all feature tests pass (15 scopeUrls + 14 prefixUtils + 10 positionUtils + 9 ontoCompleter + 16 ScopeToolbar + 3 Sparql page = 67 new/extended for this feature). Pre-existing failures elsewhere (unrelated test files) are out of scope.

- [ ] **Step 2: Full project TypeScript check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "(Sparql\.tsx|ScopeToolbar|prefixUtils|positionUtils|ontoCompleter)" | grep -v "\.test\."`

Expected: empty output.

- [ ] **Step 3: Verify file inventory**

Run: `git log --stat --since="3 hours ago" -- frontend/src/components/sparql/ frontend/src/pages/Sparql.tsx | head -60`

Confirm the commits touched only the expected files (the seven listed in the File Map above).

- [ ] **Step 4 (optional): Manual UAT**

Visit `/sparql` in the running dev environment. Walk through:

1. Default starter query (with PREFIX owl, PREFIX rdfs already declared). Confirm autocomplete dropdown doesn't appear over keywords.
2. Position cursor inside `<...>`, type `piz` — dropdown should appear, suggestions ranked by label.
3. Add pizza to scope via toolbar. Confirm `PREFIX pizza: <https://w3id.org/ontostart/pizza/>` is prepended to the query text.
4. Type `pizza:Marg` somewhere — dropdown should show Margherita and related entries, all from the pizza ontology.
5. Select a suggestion — the CURIE form `pizza:Margherita` is inserted at the cursor.
6. Remove pizza from scope. The `PREFIX pizza:` line stays. Add pizza back — `PREFIX pizza:` is not duplicated.

- [ ] **Step 5: Final commit (only if any fixes were needed)**

```bash
cd /path/to/ontoexplorer
git add -A
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(sparql): post-merge cleanup for IRI autocomplete

Fix-ups discovered during the end-to-end sweep.
EOF
)"
```

If nothing changed, no commit.

---

## Out of scope (deferred to other sub-projects per the spec)

- Removing PREFIX lines on deselect — explicit non-goal (additive-only).
- Two-column custom dropdown rendering — Yasqe's default suffices.
- Per-keystroke client-side caching beyond React Query — backend is fast.
- Snippet-style insertions (insert a SPARQL query template after picking a class) — defer to D.
- Standard W3C prefix management (`rdf`, `rdfs`, `owl`, `xsd`) — already in the default query template.
- Custom user-defined shortnames — explicit non-goal.
