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

function StatCard({ label, value, subtitle, to }: { label: string; value: number | string; subtitle?: string; to?: string }) {
  const inner = (
    <>
      <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
      {subtitle && (
        <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3, opacity: 0.7 }}>
          {subtitle}
        </div>
      )}
    </>
  )
  const base: React.CSSProperties = {
    flex: 1, textAlign: 'center',
    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius)', padding: '16px 12px',
    display: 'block', textDecoration: 'none',
  }
  return to ? (
    <Link to={to} style={base}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)' }}
    >
      {inner}
    </Link>
  ) : (
    <div style={base}>{inner}</div>
  )
}

function ResultList({ results, pathFor, ontologyNameFor }: {
  results: SearchResult[]
  pathFor: (r: SearchResult) => string | null
  ontologyNameFor?: (r: SearchResult) => string | null
}) {
  if (results.length === 0) return null
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {results.map(r => {
        const path = pathFor(r)
        const isInd = r.type === 'individual'
        const ontName = ontologyNameFor?.(r) ?? null
        const inner = (
          <>
            <span style={{ color: 'var(--accent)', fontWeight: 500, flexShrink: 0 }}>{r.label}</span>
            {isInd && (
              <span style={{
                fontSize: 9, padding: '1px 5px', borderRadius: 3,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                color: 'var(--accent-blue, #61afef)', flexShrink: 0, fontWeight: 600,
              }}>ind</span>
            )}
            {r.source && <SourceBadge source={r.source} />}
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
            {ontName && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0, fontWeight: 500,
              }}>{ontName}</span>
            )}
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
  const { data, isFetching } = useGlobalSearch(submitted, submitted.length >= 3)
  const results = data?.results ?? []
  const semanticResults = data?.semantic_results ?? []

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitted(query.trim())
  }

  function pathFor(r: SearchResult): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }

  function ontologyNameFor(r: SearchResult): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont) return null
    if (ont.shortname) return ont.shortname
    const last = ont.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? ont.iri
    return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
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

      {submitted && isFetching && results.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          Searching…
        </p>
      )}
      {submitted && !isFetching && results.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          No results for "{submitted}"
        </p>
      )}
      <ResultList results={results} pathFor={pathFor} ontologyNameFor={ontologyNameFor} />
      {semanticResults.length > 0 && (
        <>
          <div style={{
            margin: '1.25rem 0 0.5rem',
            fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase',
            letterSpacing: 0.8, display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
            Semantically similar
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
          </div>
          <ul style={{ listStyle: 'none', marginTop: 0 }}>
            {semanticResults.map(r => {
              const path = pathFor(r)
              const alreadyInResults = results.some(p => p.iri === r.iri)
              const semOntName = ontologyNameFor(r)
              const inner = (
                <>
                  <span style={{
                    color: alreadyInResults ? 'var(--text-dim)' : 'var(--accent)',
                    fontWeight: 500, flexShrink: 0,
                  }}>{r.label}</span>
                  {r.source && <SourceBadge source={r.source} />}
                  <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
                  {semOntName && (
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 3,
                      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                      color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0, fontWeight: 500,
                    }}>{semOntName}</span>
                  )}
                  <span style={{
                    fontSize: 10, padding: '1px 5px', borderRadius: 3,
                    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                    color: 'var(--text-dim)', flexShrink: 0,
                  }}>{r.score?.toFixed(2)}</span>
                </>
              )
              const sharedStyle: React.CSSProperties = {
                padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                display: 'flex', gap: 10, alignItems: 'baseline',
                borderBottom: '1px solid var(--border)',
                textDecoration: 'none',
                opacity: alreadyInResults ? 0.5 : 1,
              }
              return path ? (
                <li key={r.iri}>
                  <Link to={path} style={sharedStyle}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >{inner}</Link>
                </li>
              ) : (
                <li key={r.iri} style={{ ...sharedStyle, color: 'var(--text-dim)' }}>{inner}</li>
              )
            })}
          </ul>
        </>
      )}
    </>
  )
}

// ── Query tab (MOS) ───────────────────────────────────────────────────────────

function useMOSFanout(pairs: { oid: string; vid: string }[], query: string, direct: boolean) {
  return useQueries({
    queries: pairs.map(({ oid, vid }) => ({
      queryKey: ['mos-search', oid, vid, query, direct],
      queryFn: () => api.ontologies.search(oid, vid, query, 'expression', undefined, false, direct),
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
  const [direct, setDirect] = useState(false)

  // latest_version is now returned inline by the list endpoint — no extra calls needed
  const allPairs: { oid: string; vid: string }[] = ontologies.flatMap(o => {
    const vid = o.latest_version?.id
    return vid ? [{ oid: o.id, vid }] : []
  })

  // Scope: selected ontologies, or all if none selected
  const scopePairs = selectedOids.length > 0
    ? allPairs.filter(p => selectedOids.includes(p.oid))
    : allPairs

  // Fan-out MOS search across scoped ontologies
  const searchResults = useMOSFanout(scopePairs, mosQuery, direct)
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

  // Deduplicate by IRI — same class can appear in multiple ontologies
  const dedupedResults: SearchResult[] = []
  const _seenIris = new Set<string>()
  for (const r of allResults) {
    if (!_seenIris.has(r.iri)) {
      _seenIris.add(r.iri)
      dedupedResults.push(r)
    }
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

  function pathFor(r: SearchResult): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }

  function ontologyNameFor(r: SearchResult): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont) return null
    if (ont.shortname) return ont.shortname
    const last = ont.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? ont.iri
    return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
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
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', flexShrink: 0, marginLeft: 12 }}>
          <input
            type="checkbox"
            checked={direct}
            onChange={e => setDirect(e.target.checked)}
            style={{ cursor: 'pointer', accentColor: 'var(--accent)' }}
          />
          <span style={{ fontSize: 11, color: direct ? 'var(--text)' : 'var(--text-dim)', whiteSpace: 'nowrap' }}>
            Direct only
          </span>
        </label>
      </div>

      {mosQuery && errorMsg && (
        <p style={{ color: 'var(--error, #e06c75)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
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
          No results for "{mosQuery}"
        </p>
      )}
      <ResultList results={dedupedResults} pathFor={pathFor} ontologyNameFor={ontologyNameFor} />
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
        <div style={{ display: 'flex', gap: 12, marginBottom: '2rem', flexWrap: 'wrap' }}>
          <StatCard label="Ontologies" value={publicStats.total_ontologies} to="/ontologies" />
          <StatCard label="Classes" value={publicStats.total_classes}
            subtitle={publicStats.unique_classes != null ? `${publicStats.unique_classes.toLocaleString()} unique` : undefined}
            to="/ontologies" />
          {publicStats.total_object_properties > 0 && (
            <StatCard label="Object Properties" value={publicStats.total_object_properties}
              subtitle={publicStats.unique_object_properties != null ? `${publicStats.unique_object_properties.toLocaleString()} unique` : undefined}
              to="/ontologies" />
          )}
          {publicStats.total_data_properties > 0 && (
            <StatCard label="Data Properties" value={publicStats.total_data_properties}
              subtitle={publicStats.unique_data_properties != null ? `${publicStats.unique_data_properties.toLocaleString()} unique` : undefined}
              to="/ontologies" />
          )}
          {publicStats.total_annotation_properties > 0 && (
            <StatCard label="Annotation Properties" value={publicStats.total_annotation_properties}
              subtitle={publicStats.unique_annotation_properties != null ? `${publicStats.unique_annotation_properties.toLocaleString()} unique` : undefined}
              to="/ontologies" />
          )}
          {publicStats.total_individuals > 0 && (
            <StatCard label="Individuals" value={publicStats.total_individuals}
              subtitle={publicStats.unique_individuals != null ? `${publicStats.unique_individuals.toLocaleString()} unique` : undefined}
              to="/ontologies" />
          )}
          {publicStats.total_axioms > 0 && (
            <StatCard label="Axioms" value={publicStats.total_axioms} to="/ontologies" />
          )}
        </div>
      )}

      {/* Mode toggle */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
      <div style={{ display: 'flex', borderRadius: 'var(--radius)', overflow: 'hidden', border: '1px solid var(--border)' }}>
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
      </div>

      {mode === 'search'
        ? <KeywordSearch />
        : <MOSQuery />
      }
    </div>
  )
}
