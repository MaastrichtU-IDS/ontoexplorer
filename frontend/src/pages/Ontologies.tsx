import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useOntologySearch } from '../hooks/useOntologySearch'
import { useVersions } from '../hooks/useVersions'
import { Ontology, slugFromIri } from '../lib/api'

function OntologyRow({ o }: { o: Ontology }) {
  const navigate = useNavigate()
  const { data: versionsData } = useVersions(o.id)
  const versions = versionsData?.versions ?? []
  const latest = versions[0]
  const shortName = o.shortname ?? o.iri.split(/[/#]/).filter(Boolean).pop() ?? o.iri

  return (
    <tr
      onClick={() => latest && navigate(`/ontologies/${slugFromIri(o.iri)}`)}
      style={{ cursor: latest ? 'pointer' : 'default' }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
      onMouseLeave={e => (e.currentTarget.style.background = '')}
    >
      <td style={{ padding: '10px 12px', color: 'var(--accent)', fontWeight: 500 }}>
        {shortName}
      </td>
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', wordBreak: 'break-all' }}>
        {o.iri}
      </td>
      <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap' }}>
        {versions.length > 0 ? (
          <span style={{
            background: latest?.status === 'ingested' ? 'rgba(80,200,120,0.12)' : 'var(--bg-secondary)',
            color: latest?.status === 'ingested' ? '#50c878' : 'var(--text-dim)',
            borderRadius: 3, padding: '2px 7px', fontSize: 10,
          }}>
            {latest?.status ?? '—'}
          </span>
        ) : (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>—</span>
        )}
      </td>
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap' }}>
        {versions.length}
      </td>
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap' }}>
        {latest?.format?.toUpperCase() ?? '—'}
      </td>
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap' }}>
        {new Date(o.created_at).toLocaleDateString()}
      </td>
    </tr>
  )
}

export default function Ontologies() {
  const [query, setQuery] = useState('')
  const { data, isLoading } = useOntologySearch(query)
  const ontologies = data?.ontologies ?? []

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, marginBottom: '1.5rem' }}>
        Ontologies
      </h1>

      {/* Search bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', padding: '8px 12px', marginBottom: '1.5rem',
      }}>
        <span style={{ color: 'var(--text-dim)' }}>⌕</span>
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Filter by IRI or name…"
          style={{
            flex: 1, background: 'none', border: 'none',
            color: 'var(--text)', fontSize: 'var(--font-size-base)', outline: 'none',
          }}
        />
        {query && (
          <button
            onClick={() => setQuery('')}
            style={{ color: 'var(--text-dim)', fontSize: 12, padding: '2px 6px' }}
          >
            ✕
          </button>
        )}
      </div>

      {isLoading ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</p>
      ) : ontologies.length === 0 ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          {query ? 'No ontologies match your filter.' : 'No ontologies loaded yet.'}
        </p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Name', 'IRI', 'Status', 'Versions', 'Format', 'Added'].map(h => (
                <th key={h} style={{
                  padding: '8px 12px', textAlign: 'left',
                  color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
                  fontWeight: 500,
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ontologies.map(o => <OntologyRow key={o.id} o={o} />)}
          </tbody>
        </table>
      )}

      <p style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: '1rem' }}>
        {ontologies.length} ontolog{ontologies.length === 1 ? 'y' : 'ies'}
        {query && ' matching filter'}
      </p>
    </div>
  )
}
