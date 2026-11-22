import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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

  // ONE cross-ontology request. The server pre-filters to ontologies whose
  // entity_index contains the query's terms and only evaluates already-reasoned
  // versions (replacing the old per-ontology fan-out that fired one request per
  // ontology — up to ~500, nearly all erroring). `warnings` tells us how many
  // matching ontologies were skipped because they aren't reasoned yet.
  const { data, isFetching, error } = useQuery({
    queryKey: ['mos-global', normalizedQuery, effectiveRelation, direct, selectedOids],
    queryFn: () => api.globalSearch.expression(normalizedQuery, {
      relation: effectiveRelation, direct, ontologyIds: selectedOids, limit: 50,
    }),
    enabled: normalizedQuery.length >= 2,
    staleTime: 10_000,
    retry: false,
  })

  const isSearching = mosQuery.length >= 2 && isFetching
  const warnings = data?.warnings ?? []
  const skipped = warnings.find(w => w.type === 'versions_skipped_unclassified')?.count ?? 0

  // Re-rank: exact label → prefix → substring, then alpha. Extract the bare term
  // from MOS syntax ("'cell'" / "'cell" → "cell").
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
  const dedupedResults: SearchResult[] = [...(data?.results ?? [])]
  if (_bareQuery) {
    dedupedResults.sort((a, b) => {
      const [ra, la] = _rank(a.label ?? '')
      const [rb, lb] = _rank(b.label ?? '')
      return ra !== rb ? ra - rb : la.localeCompare(lb)
    })
  }

  // A real failure of the single request (parse error, bad relation, transport).
  const errBody = (error as (Error & { body?: { error?: string; message?: string; detail?: string } }) | null)?.body
  const errorMsg = !error ? null
    : errBody?.error === 'parse_error' ? `Invalid expression: ${errBody.message ?? ''}`.trim()
    : errBody?.error === 'relation_requires_named_class' ? `"${effectiveRelation}" needs a single named class.`
    : (errBody?.detail ?? errBody?.message ?? errBody?.error ?? (error as Error).message)

  // Resolve ontology_id → shortname from the (already-loaded) catalogue so each
  // result links to a clean slug and shows the source-ontology badge. The server
  // returns version_id/ontology_id; ontology_id alone still resolves server-side.
  const shortnameById = new Map<string, string>(
    ontologies.flatMap(o => (o.shortname ? [[o.id, o.shortname] as [string, string]] : [])),
  )
  function pathFor(r: SearchResult): string | null {
    if (!r.version_id) return null
    const slug = (r.ontology_id && shortnameById.get(r.ontology_id)) || r.ontology_shortname || r.ontology_id
    if (!slug) return null
    return `/ontologies/${encodeURIComponent(slug)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }
  function ontologyNameFor(r: SearchResult): string | null {
    return (r.ontology_id && shortnameById.get(r.ontology_id)) || r.ontology_shortname || null
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
          {skipped > 0 && (
            <><br /><span style={{ fontSize: 11 }}>
              {skipped} matching ontolog{skipped > 1 ? 'ies are' : 'y is'} not reasoned yet, so {skipped > 1 ? 'they were' : 'it was'} skipped.
            </span></>
          )}
        </p>
      )}
      {/* Honest aggregate note (replaces the old misleading per-ontology
          "'<q>' not found in this ontology's index"): when the term matched
          ontologies that simply aren't reasoned yet, say so. */}
      {mosQuery && !errorMsg && !isSearching && dedupedResults.length > 0 && skipped > 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 11, textAlign: 'center', margin: '8px 0 0' }}>
          {skipped} more matching ontolog{skipped > 1 ? 'ies' : 'y'} not shown — not reasoned yet.
        </p>
      )}
      <ResultList results={dedupedResults} pathFor={pathFor} ontologyNameFor={ontologyNameFor} />
    </>
  )
}
