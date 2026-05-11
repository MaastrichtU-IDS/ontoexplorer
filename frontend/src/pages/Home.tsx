import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchBar from '../components/SearchBar'
import OntologyPicker from '../components/OntologyPicker'
import { useGlobalSearch } from '../hooks/useSearch'
import { useOntologySearch } from '../hooks/useOntologySearch'

export default function Home() {
  const [selectedOids, setSelectedOids] = useState<string[]>([])
  const [submittedQuery, setSubmittedQuery] = useState('')
  const navigate = useNavigate()

  const { data: searchData } = useGlobalSearch(submittedQuery)
  const { data: ontologyData } = useOntologySearch('')
  const ontologies = ontologyData?.ontologies ?? []

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '3rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 24, fontWeight: 700, marginBottom: '0.5rem', textAlign: 'center' }}>
        OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', textAlign: 'center', marginBottom: '2rem' }}>
        FAIR ontology repository — search terms, ontologies, and MOS expressions
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: '1.5rem', alignItems: 'flex-start' }}>
        <OntologyPicker
          value={selectedOids}
          onChange={setSelectedOids}
          placeholder="Filter by ontology…"
        />
        <div style={{ flex: 1 }}>
          <SearchBar
            ontologyId={selectedOids[0] ?? ontologies[0]?.id ?? null}
            versionId={null}
            onSearch={setSubmittedQuery}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Terms panel */}
        <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius)', padding: '1rem' }}>
          <h2 style={{ color: 'var(--accent-purple)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, marginBottom: '0.75rem' }}>
            Terms
          </h2>
          {!submittedQuery ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
              Search to find terms across all ontologies
            </p>
          ) : (searchData?.results ?? []).length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No terms found</p>
          ) : (
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(searchData?.results ?? []).map(r => (
                <li
                  key={r.iri}
                  onClick={() =>
                    r.ontology_id && r.version_id &&
                    navigate(`/browse/${r.ontology_id}/${r.version_id}?term=${encodeURIComponent(r.iri)}`)
                  }
                  style={{
                    padding: '6px 8px', borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'baseline',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}
                >
                  <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{r.label}</span>
                  <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Ontologies panel */}
        <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius)', padding: '1rem' }}>
          <h2 style={{ color: 'var(--accent-blue)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, marginBottom: '0.75rem' }}>
            Ontologies
          </h2>
          {ontologies.length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No ontologies</p>
          ) : (
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {ontologies.slice(0, 10).map(o => (
                <li
                  key={o.id}
                  onClick={() => navigate(`/browse/${o.id}/latest`)}
                  style={{
                    padding: '6px 8px', borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}
                >
                  <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{o.id}</span>
                  <span style={{ color: 'var(--text-dim)', fontSize: 11, wordBreak: 'break-all' }}>{o.iri}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
