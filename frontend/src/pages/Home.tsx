import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useOntologies } from '../hooks/useOntologies'
import { useVersions } from '../hooks/useVersions'
import { useGlobalSearch, useSearch } from '../hooks/useSearch'
import { slugFromIri, SearchResult, api } from '../lib/api'
import SearchBar from '../components/SearchBar'

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

function ResultList({ results, onSelect }: {
  results: SearchResult[]
  onSelect: (r: SearchResult) => void
}) {
  if (results.length === 0) return null
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {results.map(r => (
        <li
          key={r.iri}
          onClick={() => onSelect(r)}
          style={{
            padding: '8px 10px', borderRadius: 'var(--radius-sm)',
            cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'baseline',
            borderBottom: '1px solid var(--border)',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
          onMouseLeave={e => (e.currentTarget.style.background = '')}
        >
          <span style={{ color: 'var(--accent)', fontWeight: 500, flexShrink: 0 }}>{r.label}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
        </li>
      ))}
    </ul>
  )
}

// ── Search tab ────────────────────────────────────────────────────────────────

function KeywordSearch({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const { ontologies } = useOntologies()
  const { data } = useGlobalSearch(submitted)
  const results = data?.results ?? []

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitted(query.trim())
  }

  function handleSelect(r: SearchResult) {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return
    onNavigate(`/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`)
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
      <ResultList results={results} onSelect={handleSelect} />
    </>
  )
}

// ── Query tab (MOS) ───────────────────────────────────────────────────────────

function MOSQuery({ onNavigate }: { onNavigate: (path: string) => void }) {
  const { ontologies } = useOntologies()
  const [selectedOid, setSelectedOid] = useState<string>(ontologies[0]?.id ?? '')
  const { data: versionsData } = useVersions(selectedOid || undefined)
  const vid = versionsData?.versions[0]?.id ?? null
  const [mosQuery, setMosQuery] = useState('')
  const { data } = useSearch(selectedOid || null, vid, mosQuery)
  const results = data?.results ?? []

  const activeOid = selectedOid || ontologies[0]?.id || null

  function handleSelect(r: SearchResult) {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return
    onNavigate(`/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`)
  }

  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <select
          value={selectedOid}
          onChange={e => setSelectedOid(e.target.value)}
          style={{
            width: '100%', padding: '8px 12px', fontSize: 14,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)',
          }}
        >
          {ontologies.map(o => (
            <option key={o.id} value={o.id}>{slugFromIri(o.iri).toUpperCase()} — {o.iri}</option>
          ))}
        </select>
      </div>

      <SearchBar
        ontologyId={activeOid}
        versionId={vid}
        onSearch={setMosQuery}
        placeholder="Enter MOS expression, e.g. 'cell' and 'nucleus'"
      />

      <p style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 6, marginBottom: 8 }}>
        Manchester OWL Syntax — use class names, <code>and</code>, <code>or</code>, <code>not</code>, <code>some</code>, <code>only</code>
      </p>

      {mosQuery && results.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          No results for "{mosQuery}"
        </p>
      )}
      <ResultList results={results} onSelect={handleSelect} />
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const [mode, setMode] = useState<Mode>('search')
  const navigate = useNavigate()

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
            {m === 'search' ? 'Search' : 'Query (MOS)'}
          </button>
        ))}
      </div>

      {mode === 'search'
        ? <KeywordSearch onNavigate={navigate} />
        : <MOSQuery onNavigate={navigate} />
      }
    </div>
  )
}
