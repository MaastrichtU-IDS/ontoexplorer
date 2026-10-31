import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { useOntologies } from '../hooks/useOntologies'
import { SearchResult, api } from '../lib/api'
import SearchBar from './SearchBar'
import OntologyPicker from './OntologyPicker'
import { ResultList } from './ResultList'

export type MosRelation = 'subclasses' | 'superclasses' | 'equivalent'

const RELATION_FACETS: { value: MosRelation; label: string; namedClassOnly: boolean }[] = [
  { value: 'subclasses', label: 'Subclasses', namedClassOnly: false },
  { value: 'superclasses', label: 'Superclasses', namedClassOnly: true },
  { value: 'equivalent', label: 'Equivalent', namedClassOnly: true },
]

// MOS reserved words. A bare token equal to one of these makes a query a real
// expression rather than a label.
const MOS_KEYWORDS = new Set([
  'and', 'or', 'not', 'some', 'only', 'value', 'min', 'max', 'exactly', 'self', 'that',
])

// A bare multi-word label typed without quotes (e.g. `catalytic activity`) is a
// single named class, but the MOS parser only accepts it quoted. Wrap it so it
// parses as one NamedClass — unless it already carries MOS syntax (a quote or a
// paren) or a reserved operator token, in which case it's a genuine expression
// and is left untouched. Single tokens and CURIEs need no quoting.
export function normalizeMos(q: string): string {
  const t = q.trim()
  if (!t) return t
  if (t.includes("'") || t.includes('(') || t.includes(')')) return t
  const tokens = t.split(/\s+/)
  if (tokens.length <= 1) return t
  if (tokens.some(tok => MOS_KEYWORDS.has(tok.toLowerCase()))) return t
  return `'${t}'`
}

// A MOS query is a single named class (so super/equivalent are answerable) when
// it's one bare token (word or CURIE) or a single quoted phrase — i.e. no
// boolean/restriction operators. Anything with whitespace outside quotes is a
// complex expression. Callers pass the normalized query so a bare multi-word
// label counts as a named class.
export function isNamedClassQuery(q: string): boolean {
  const t = q.trim()
  if (!t) return false
  if (/^'[^']*'$/.test(t)) return true
  return !/\s/.test(t)
}

function RelationChips({ selected, onChange, namedClass }: {
  selected: MosRelation
  onChange: (next: MosRelation) => void
  namedClass: boolean
}) {
  const chipStyle = (active: boolean, disabled: boolean): React.CSSProperties => ({
    fontSize: 12, padding: '3px 10px', borderRadius: 12,
    background: active ? 'var(--accent)' : 'var(--bg-secondary)',
    border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border)'),
    color: disabled ? 'var(--text-dim)' : active ? 'var(--on-accent)' : 'var(--text-muted)',
    cursor: disabled ? 'not-allowed' : 'pointer', fontWeight: active ? 600 : 400,
    opacity: disabled ? 0.45 : 1,
  })
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: '0.75rem' }}>
      {RELATION_FACETS.map(f => {
        const disabled = f.namedClassOnly && !namedClass
        return (
          <button
            key={f.value}
            type="button"
            disabled={disabled}
            title={disabled ? 'Available for a single named class' : undefined}
            onClick={() => !disabled && onChange(f.value)}
            style={chipStyle(selected === f.value, disabled)}
          >
            {f.label}
          </button>
        )
      })}
    </div>
  )
}

function useMOSFanout(pairs: { oid: string; vid: string }[], query: string, direct: boolean, relation: MosRelation) {
  return useQueries({
    queries: pairs.map(({ oid, vid }) => ({
      queryKey: ['mos-search', oid, vid, query, direct, relation],
      queryFn: () => api.ontologies.search(oid, vid, query, 'expression', undefined, false, direct, relation),
      staleTime: 10_000,
      enabled: query.length >= 2,
      retry: false,
    })),
  })
}

export function MOSQuery() {
  const [relation, onRelationChange] = useState<MosRelation>('subclasses')
  const { ontologies } = useOntologies()
  const [selectedOids, setSelectedOids] = useState<string[]>([])
  const [mosQuery, setMosQuery] = useState('')
  const [direct, setDirect] = useState(false)

  // Auto-quote a bare multi-word label so it's treated as a single named class
  // (both for the chip gate and for the actual query the backend parses).
  const normalizedQuery = normalizeMos(mosQuery)

  // Super/equivalent are only answerable for a single named class. When the
  // query is a complex expression, force the relation back to subclasses
  // (the chips for the others render disabled).
  const namedClass = isNamedClassQuery(normalizedQuery)
  const effectiveRelation: MosRelation = namedClass ? relation : 'subclasses'

  // latest_version is now returned inline by the list endpoint — no extra calls needed
  const allPairs: { oid: string; vid: string }[] = ontologies.flatMap(o => {
    const vid = o.latest_version?.id
    return vid ? [{ oid: o.id, vid }] : []
  })

  // Scope: selected ontologies, or all if none selected
  const scopePairs = selectedOids.length > 0
    ? allPairs.filter(p => selectedOids.includes(p.oid))
    : allPairs

  // Fan-out MOS search across scoped ontologies (normalized so a bare
  // multi-word label parses as one named class instead of erroring).
  const searchResults = useMOSFanout(scopePairs, normalizedQuery, direct, effectiveRelation)
  // Tag each result with the oid/vid of the ontology it came from
  const allResults: SearchResult[] = searchResults.flatMap((r, i) =>
    (r.data?.results ?? []).map(res => ({
      ...res,
      ontology_id: scopePairs[i]?.oid,
      version_id: scopePairs[i]?.vid,
    }))
  )

  // Re-rank merged results globally: exact label → prefix → substring, then alpha.
  // Extract bare term from MOS syntax: "'cell'" or "'cell" (open quote) → "cell".
  const _bareQuery = (() => {
    const closed = mosQuery.match(/'([^']+)'/)
    if (closed) return closed[1].toLowerCase().trim()
    const open = mosQuery.match(/^'(.+)/)
    if (open) return open[1].toLowerCase().trim()
    return mosQuery.toLowerCase().trim()
  })()
  const _rank = (lbl: string): [number, string] => {
    const l = lbl.toLowerCase()
    if (l === _bareQuery) return [0, l]
    if (l.startsWith(_bareQuery)) return [1, l]
    return [2, l]
  }
  if (_bareQuery) {
    allResults.sort((a, b) => {
      const [ra, la] = _rank(a.label ?? '')
      const [rb, lb] = _rank(b.label ?? '')
      return ra !== rb ? ra - rb : la.localeCompare(lb)
    })
  }

  // Deduplicate by IRI — same class can appear in multiple ontologies. The
  // relationship facet is chosen server-side via `relation`, so no client-side
  // type filtering is needed here.
  const dedupedResults: SearchResult[] = []
  const _seenIris = new Set<string>()
  for (const r of allResults) {
    if (_seenIris.has(r.iri)) continue
    _seenIris.add(r.iri)
    dedupedResults.push(r)
  }

  const isSearching = mosQuery.length >= 2 && searchResults.some(r => r.isFetching)

  // Surface error message only when all queries failed (no results at all)
  const firstError = searchResults.find(r => r.error)?.error as (Error & { status?: number; body?: { error?: string; detail?: string } }) | undefined
  const allNotClassified = mosQuery.length >= 2 && searchResults.length > 0 && searchResults.every(r => (r.error as (Error & { body?: { error?: string } }) | undefined)?.body?.error === 'not_classified')
  const errorMsg = dedupedResults.length === 0 && firstError
    ? allNotClassified
      ? 'Ontology classification is not ready yet — reasoning is still running. Try again in a few minutes.'
      : (firstError.body?.detail ?? firstError.body?.error ?? firstError.message)
    : null

  // Build the term link from the result itself (shortname → clean slug, else the
  // ontology_id, which the term page resolves server-side). This works for every
  // result regardless of catalogue size — the old lookup against the page-capped
  // ontology list left results from ontologies past the cap un-clickable.
  function pathFor(r: SearchResult): string | null {
    if (!r.version_id) return null
    const slug = r.ontology_shortname || r.ontology_id
    if (!slug) return null
    return `/ontologies/${encodeURIComponent(slug)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }

  function ontologyNameFor(r: SearchResult): string | null {
    return r.ontology_shortname || null
  }

  return (
    <>
      <RelationChips selected={effectiveRelation} onChange={onRelationChange} namedClass={namedClass} />

      <div style={{ marginBottom: 8 }}>
        <OntologyPicker
          value={selectedOids}
          onChange={setSelectedOids}
          placeholder="Filter ontologies… (leave empty to search all)"
        />
      </div>

      <SearchBar
        ontologyId={null}
        versionId={null}
        onSearch={setMosQuery}
        placeholder="MOS expression, e.g. cell, 'cell death', GO:0008150"
        scopeOntologyIds={selectedOids}
      />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6, marginBottom: 8 }}>
        <p style={{ color: 'var(--text-dim)', fontSize: 11, margin: 0 }}>
          Use <code>and</code>, <code>or</code>, <code>not</code>, <code>some</code>, <code>only</code> · quote multi-word names: <code>'cell death'</code> ·{' '}
          {selectedOids.length > 0
            ? `searching ${selectedOids.length} selected ontolog${selectedOids.length > 1 ? 'ies' : 'y'}`
            : 'searching all ontologies'}
        </p>
        {effectiveRelation !== 'equivalent' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', flexShrink: 0, marginLeft: 12 }}>
            <input
              type="checkbox"
              checked={direct}
              onChange={e => setDirect(e.target.checked)}
              style={{ cursor: 'pointer', accentColor: 'var(--accent)' }}
            />
            <span style={{ fontSize: 11, color: direct ? 'var(--text)' : 'var(--text-dim)', whiteSpace: 'nowrap' }}>
              {effectiveRelation === 'superclasses' ? 'Direct parents only' : 'Direct only'}
            </span>
          </label>
        )}
      </div>

      {mosQuery && errorMsg && (
        <p style={{ color: 'var(--error)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          {errorMsg}
        </p>
      )}
      {mosQuery && !errorMsg && isSearching && dedupedResults.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          Searching…
        </p>
      )}
      {mosQuery && !errorMsg && !isSearching && dedupedResults.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          {effectiveRelation === 'equivalent'
            ? `No classes equivalent to "${mosQuery}"`
            : effectiveRelation === 'superclasses'
              ? `No superclasses for "${mosQuery}"`
              : `No results for "${mosQuery}"`}
        </p>
      )}
      <ResultList results={dedupedResults} pathFor={pathFor} ontologyNameFor={ontologyNameFor} />
    </>
  )
}
