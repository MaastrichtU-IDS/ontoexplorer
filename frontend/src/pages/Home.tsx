import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueries } from '@tanstack/react-query'
import { useOntologies } from '../hooks/useOntologies'
import { useGlobalSearch } from '../hooks/useSearch'
import { slugFromIri, SearchResult, api } from '../lib/api'
import SearchBar from '../components/SearchBar'
import OntologyPicker from '../components/OntologyPicker'
import SourceBadge from '../components/SourceBadge'

const EXAMPLES = ['cell death', 'apoptosis', 'protein binding', 'nucleus', 'membrane']

type Mode = 'search' | 'query'

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div style={{
      flex: 1, textAlign: 'center',
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '16px 12px',
    }}>
      <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
    </div>
  )
}

function ResultList({ results, pathFor }: {
  results: SearchResult[]
  pathFor: (r: SearchResult) => string | null
}) {
  if (results.length === 0) return null
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {results.map(r => {
        const path = pathFor(r)
        const inner = (
          <>
            <span style={{ color: 'var(--accent)', fontWeight: 500, flexShrink: 0 }}>{r.label}</span>
            {r.source && <SourceBadge source={r.source} />}
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
          </>
        )
        const sharedStyle: React.CSSProperties = {
          padding: '8px 10px', borderRadius: 'var(--radius-sm)',
          display: 'flex', gap: 10, alignItems: 'baseline',
          borderBottom: '1px solid var(--border)',
          textDecoration: 'none',
        }
        return path ? (
          <li key={r.iri}>
            <Link
              to={path}
              style={sharedStyle}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              {inner}
            </Link>
          </li>
        ) : (
          <li key={r.iri} style={{ ...sharedStyle, color: 'var(--text-dim)' }}>
            {inner}
          </li>
        )
      })}
    </ul>
  )
}

// ── Search tab ────────────────────────────────────────────────────────────────

function KeywordSearch() {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const { ontologies } = useOntologies()
  const { data } = useGlobalSearch(submitted)
  const results = data?.results ?? []

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitted(query.trim())
  }

  function pathFor(r: SearchResult): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }

  return (
    <>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8, marginBottom: '0.75rem' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search classes, properties, individuals…"
          style={{
            flex: 1, padding: '10px 14px', fontSize: 15,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)', outline: 'none',
          }}
          onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
          onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
        />
        <button type="submit" style={{
          padding: '10px 20px', background: 'var(--accent)', color: '#000',
          border: 'none', borderRadius: 'var(--radius)', fontWeight: 600, fontSize: 14, cursor: 'pointer',
        }}>
          Search
        </button>
      </form>

      {!submitted && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>Try:</span>
          {EXAMPLES.map(ex => (
            <button key={ex} onClick={() => { setQuery(ex); setSubmitted(ex) }} style={{
              fontSize: 12, padding: '3px 10px', borderRadius: 12,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >{ex}</button>
          ))}
        </div>
      )}

      {submitted && results.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          No results for "{submitted}"
        </p>
      )}
      <ResultList results={results} pathFor={pathFor} />
    </>
  )
}

// ── Query tab (MOS) ───────────────────────────────────────────────────────────

function useMOSFanout(pairs: { oid: string; vid: string }[], query: string) {
  return useQueries({
    queries: pairs.map(({ oid, vid }) => ({
      queryKey: ['mos-search', oid, vid, query],
      queryFn: () => api.ontologies.search(oid, vid, query),
      staleTime: 10_000,
      enabled: query.length >= 2,
      retry: false,
    })),
  })
}

function MOSQuery() {
  const { ontologies } = useOntologies()
  const [selectedOids, setSelectedOids] = useState<string[]>([])
  const [mosQuery, setMosQuery] = useState('')

  // latest_version is now returned inline by the list endpoint — no extra calls needed
  const allPairs: { oid: string; vid: string }[] = ontologies.flatMap(o => {
    const vid = o.latest_version?.id
    return vid ? [{ oid: o.id, vid }] : []
  })

  // Scope: selected ontologies, or all if none selected
  const scopePairs = selectedOids.length > 0
    ? allPairs.filter(p => selectedOids.includes(p.oid))
    : allPairs

  // Autocomplete context: use ontologyId only (autocompleteLatest endpoint),
  // so it works immediately without waiting for version queries to resolve.
  const acOid = (selectedOids.length > 0 ? selectedOids[0] : ontologies[0]?.id) ?? null

  // Fan-out MOS search across scoped ontologies
  const searchResults = useMOSFanout(scopePairs, mosQuery)
  // Tag each result with the oid/vid of the ontology it came from
  const allResults: SearchResult[] = searchResults.flatMap((r, i) =>
    (r.data?.results ?? []).map(res => ({
      ...res,
      ontology_id: scopePairs[i]?.oid,
      version_id: scopePairs[i]?.vid,
    }))
  )

  // Surface error message only when all queries failed (no results at all)
  const firstError = searchResults.find(r => r.error)?.error as (Error & { status?: number; body?: { error?: string; detail?: string } }) | undefined
  const allNotClassified = mosQuery.length >= 2 && searchResults.length > 0 && searchResults.every(r => (r.error as (Error & { body?: { error?: string } }) | undefined)?.body?.error === 'not_classified')
  const errorMsg = allResults.length === 0 && firstError
    ? allNotClassified
      ? 'Ontology classification is not ready yet — reasoning is still running. Try again in a few minutes.'
      : (firstError.body?.detail ?? firstError.body?.error ?? firstError.message)
    : null

  function pathFor(r: SearchResult): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }

  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <OntologyPicker
          value={selectedOids}
          onChange={setSelectedOids}
          placeholder="Filter ontologies… (leave empty to search all)"
        />
      </div>

      <SearchBar
        ontologyId={acOid}
        versionId={null}
        onSearch={setMosQuery}
        placeholder="MOS expression, e.g. 'cell' and 'nucleus'"
      />

      <p style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 6, marginBottom: 8 }}>
        Use <code>and</code>, <code>or</code>, <code>not</code>, <code>some</code>, <code>only</code> · quote names with spaces: <code>'has part'</code> ·{' '}
        {selectedOids.length > 0
          ? `searching ${selectedOids.length} selected ontolog${selectedOids.length > 1 ? 'ies' : 'y'}`
          : 'searching all ontologies'}
      </p>

      {mosQuery && errorMsg && (
        <p style={{ color: 'var(--error, #e06c75)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          {errorMsg}
        </p>
      )}
      {mosQuery && !errorMsg && allResults.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          No results for "{mosQuery}"
        </p>
      )}
      <ResultList results={allResults} pathFor={pathFor} />
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const [mode, setMode] = useState<Mode>('search')

  const { data: publicStats } = useQuery({
    queryKey: ['public-stats'],
    queryFn: () => api.stats.public(),
    staleTime: 300_000,
  })

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '5rem 1.5rem 3rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 28, fontWeight: 700, marginBottom: '0.5rem', textAlign: 'center' }}>
        OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', textAlign: 'center', marginBottom: '2rem' }}>
        FAIR ontology repository — search and query across all ontologies
      </p>

      {publicStats && (
        <div style={{ display: 'flex', gap: 12, marginBottom: '2rem' }}>
          <StatCard label="Ontologies" value={publicStats.total_ontologies} />
          <StatCard label="Classes" value={publicStats.total_classes} />
          <StatCard label="Properties" value={publicStats.total_properties} />
        </div>
      )}

      {/* Mode toggle */}
      <div style={{ display: 'flex', borderRadius: 'var(--radius)', overflow: 'hidden', border: '1px solid var(--border)', marginBottom: 12, width: 'fit-content' }}>
        {(['search', 'query'] as Mode[]).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              padding: '7px 22px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 500,
              background: mode === m ? 'var(--accent)' : 'transparent',
              color: mode === m ? '#000' : 'var(--text-dim)',
              textTransform: 'capitalize',
            }}
          >
            {m === 'search' ? 'Keyword Search' : 'Structured Query'}
          </button>
        ))}
      </div>

      {mode === 'search'
        ? <KeywordSearch />
        : <MOSQuery />
      }
    </div>
  )
}
