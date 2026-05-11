import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import OntologySelector from '../components/OntologySelector'
import SearchBar from '../components/SearchBar'
import { useSearch } from '../hooks/useSearch'
import { useVersions } from '../hooks/useVersions'

export default function Search() {
  const [selectedOid, setSelectedOid] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState('')
  const navigate = useNavigate()

  const { data: versionsData } = useVersions(selectedOid ?? undefined)
  const vid = versionsData?.versions[0]?.id ?? null

  const { data: results, isLoading, error } = useSearch(selectedOid, vid, submitted)

  function handleSearch(q: string) {
    if (!selectedOid) return
    setSubmitted(q)
  }

  const badgeColor = (type: string) =>
    type === 'elk' ? 'var(--accent)'
    : type === 'sparql' ? 'var(--accent-blue)'
    : 'var(--text-dim)'

  const apiError = error as any
  const is422 = apiError?.status === 422
  const is503 = apiError?.status === 503

  return (
    <div style={{ padding: '2rem 1.5rem', maxWidth: 900, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 18, fontWeight: 700, marginBottom: '1.5rem' }}>
        MOS Expression Search
      </h1>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: '1.5rem', alignItems: 'center' }}>
        <OntologySelector value={selectedOid} onChange={setSelectedOid} required placeholder="Select ontology…" />
        <div style={{ flex: 1 }}>
          <SearchBar
            ontologyId={selectedOid}
            versionId={vid}
            onSearch={handleSearch}
            placeholder="Enter MOS expression or entity label…"
          />
        </div>
      </div>

      {!selectedOid && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Select an ontology to search within. MOS expressions require OWL-EL classification.
        </p>
      )}

      {/* Error states */}
      {is422 && (
        <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem', marginBottom: '1rem' }}>
          <p style={{ color: 'var(--text)', marginBottom: 8 }}>Ambiguous label — did you mean:</p>
          {apiError.body?.candidates?.map((c: string) => (
            <button
              key={c}
              onClick={() => setSubmitted(c)}
              style={{ color: 'var(--accent)', marginRight: 8, fontSize: 'var(--font-size-sm)' }}
            >
              {c}
            </button>
          ))}
        </div>
      )}
      {is503 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
          Ontology is not yet classified. Check job status.
        </p>
      )}

      {/* Results */}
      {isLoading && <p style={{ color: 'var(--text-dim)' }}>Searching…</p>}
      {results && results.results.length === 0 && submitted && (
        <p style={{ color: 'var(--text-dim)' }}>No results for "{submitted}"</p>
      )}
      {results && results.results.length > 0 && (
        <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {results.results.map(r => (
            <li
              key={r.iri}
              onClick={() => navigate(`/browse/${selectedOid}/${vid}/term/${encodeURIComponent(r.iri)}`)}
              style={{
                padding: '8px 12px', borderRadius: 'var(--radius-sm)',
                cursor: 'pointer', background: 'var(--bg-secondary)',
                display: 'flex', gap: 10, alignItems: 'center',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'var(--bg-secondary)')}
            >
              <span style={{ color: 'var(--accent)', fontWeight: 500, flex: 1 }}>{r.label}</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
              <span style={{
                fontSize: 10, background: 'var(--bg)', color: badgeColor(r.match_type),
                borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
              }}>{r.match_type}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
