import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useOntologies } from '../hooks/useOntologies'
import { useGlobalSearch } from '../hooks/useSearch'
import { slugFromIri } from '../lib/api'

export default function Home() {
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const navigate = useNavigate()

  const { data: searchData } = useGlobalSearch(submittedQuery)
  const { ontologies } = useOntologies()

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setSubmittedQuery(query.trim())
  }

  function handleResultClick(ontologyId: string | undefined, versionId: string | undefined, iri: string) {
    if (!ontologyId || !versionId) return
    const ont = ontologies.find(o => o.id === ontologyId)
    if (!ont) return
    navigate(`/ontologies/${slugFromIri(ont.iri)}/${versionId}?term=${encodeURIComponent(iri)}`)
  }

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '6rem 1.5rem 3rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 28, fontWeight: 700, marginBottom: '0.5rem', textAlign: 'center' }}>
        OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', textAlign: 'center', marginBottom: '2.5rem' }}>
        FAIR ontology repository — search terms across all ontologies
      </p>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8 }}>
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
        <button
          type="submit"
          style={{
            padding: '10px 20px', background: 'var(--accent)', color: '#000',
            border: 'none', borderRadius: 'var(--radius)', fontWeight: 600,
            fontSize: 14, cursor: 'pointer',
          }}
        >
          Search
        </button>
      </form>

      {submittedQuery && (
        <div style={{ marginTop: '1.5rem' }}>
          {(searchData?.results ?? []).length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
              No results for "{submittedQuery}"
            </p>
          ) : (
            <ul style={{ listStyle: 'none' }}>
              {(searchData?.results ?? []).map(r => (
                <li
                  key={r.iri}
                  onClick={() => handleResultClick(r.ontology_id, r.version_id, r.iri)}
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
          )}
        </div>
      )}
    </div>
  )
}
