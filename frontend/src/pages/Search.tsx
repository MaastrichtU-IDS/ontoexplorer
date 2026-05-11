import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import OntologyPicker from '../components/OntologyPicker'
import SearchBar from '../components/SearchBar'
import { useSearch } from '../hooks/useSearch'
import { useVersions } from '../hooks/useVersions'

function OntologySearchPane({ oid, submitted, navigate }: { oid: string; submitted: string; navigate: (p: string) => void }) {
  const { data: versionsData } = useVersions(oid)
  const vid = versionsData?.versions[0]?.id ?? null
  const { data: results, isLoading, error } = useSearch(oid, vid, submitted)

  const apiError = error as any
  const badgeColor = (type: string) =>
    type === 'elk' ? 'var(--accent)' : type === 'sparql' ? 'var(--accent-blue)' : 'var(--text-dim)'

  if (isLoading) return <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Searching {oid}…</p>
  if (apiError?.status === 503) return (
    <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
      {oid}: not yet classified.
    </p>
  )
  if (!results?.results.length) return null

  return (
    <>
      {results.results.map(r => (
        <li
          key={`${oid}:${r.iri}`}
          onClick={() => vid && navigate(`/browse/${oid}/${vid}/term/${encodeURIComponent(r.iri)}`)}
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
          <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>{oid}</span>
          <span style={{
            fontSize: 10, background: 'var(--bg)', color: badgeColor(r.match_type),
            borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
          }}>{r.match_type}</span>
        </li>
      ))}
    </>
  )
}

export default function Search() {
  const [selectedOids, setSelectedOids] = useState<string[]>([])
  const [submitted, setSubmitted] = useState('')
  const navigate = useNavigate()

  const firstOid = selectedOids[0] ?? null
  const { data: versionsData } = useVersions(firstOid ?? undefined)
  const firstVid = versionsData?.versions[0]?.id ?? null

  function handleSearch(q: string) {
    if (selectedOids.length === 0) return
    setSubmitted(q)
  }

  return (
    <div style={{ padding: '2rem 1.5rem', maxWidth: 900, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 18, fontWeight: 700, marginBottom: '1.5rem' }}>
        MOS Expression Search
      </h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: '1.5rem', alignItems: 'flex-start' }}>
        <OntologyPicker
          value={selectedOids}
          onChange={setSelectedOids}
          placeholder="Select ontologies…"
        />
        <div style={{ flex: 1 }}>
          <SearchBar
            ontologyId={firstOid}
            versionId={firstVid}
            onSearch={handleSearch}
            placeholder="Enter MOS expression or entity label…"
          />
        </div>
      </div>

      {selectedOids.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Select one or more ontologies to search within. MOS expressions require OWL-EL classification.
        </p>
      )}

      {submitted && selectedOids.length > 0 && (
        <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {selectedOids.map(oid => (
            <OntologySearchPane key={oid} oid={oid} submitted={submitted} navigate={navigate} />
          ))}
        </ul>
      )}
    </div>
  )
}
