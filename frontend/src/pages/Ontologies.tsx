import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useOntologySearch } from '../hooks/useOntologySearch'
import { Ontology, slugFromIri } from '../lib/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCount(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

function displayName(o: Ontology): string {
  if (o.shortname) return o.shortname
  const last = o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? o.iri
  return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
}

function IriChip({ iri }: { iri: string }) {
  const [copied, setCopied] = useState(false)
  function copy(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    navigator.clipboard.writeText(iri).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={copy}
      title={iri}
      style={{
        fontSize: 10, padding: '1px 7px', borderRadius: 3,
        border: '1px solid var(--border)',
        background: copied ? 'rgba(100,200,100,0.1)' : 'transparent',
        color: copied ? 'var(--accent)' : 'var(--text-dim)',
        cursor: 'pointer', fontFamily: 'monospace', flexShrink: 0,
      }}
    >
      {copied ? '✓ copied' : 'IRI'}
    </button>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function OntologyRow({ o }: { o: Ontology }) {
  const navigate = useNavigate()
  const latest = o.latest_version
  const hasStats = o.class_count != null || o.property_count != null || o.triple_count != null

  return (
    <tr
      onClick={() => latest && navigate(`/ontologies/${o.shortname ?? slugFromIri(o.iri)}`)}
      style={{ cursor: latest ? 'pointer' : 'default', borderBottom: '1px solid var(--border)' }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
      onMouseLeave={e => (e.currentTarget.style.background = '')}
    >
      {/* Name */}
      <td style={{ padding: '10px 12px' }}>
        <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{displayName(o)}</span>
      </td>

      {/* IRI chip */}
      <td style={{ padding: '10px 12px' }}>
        <IriChip iri={o.iri} />
      </td>

      {/* Status */}
      <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
        {latest ? (
          <span style={{
            background: latest.status === 'ingested' ? 'rgba(80,200,120,0.12)' : 'var(--bg-secondary)',
            color: latest.status === 'ingested' ? '#50c878' : 'var(--text-dim)',
            borderRadius: 3, padding: '2px 7px', fontSize: 10,
          }}>
            {latest.status}
          </span>
        ) : (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>—</span>
        )}
      </td>

      {/* Classes · props · axioms */}
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {hasStats ? (
          <>
            {fmtCount(o.class_count)} cls
            <span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>
            {fmtCount(o.property_count)} props
            <span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>
            {fmtCount(o.triple_count)} axioms
          </>
        ) : '—'}
      </td>

      {/* Added */}
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap' }}>
        {new Date(o.created_at).toLocaleDateString()}
      </td>
    </tr>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Ontologies() {
  const [query, setQuery] = useState('')
  const { data, isLoading } = useOntologySearch(query)
  const ontologies = data?.ontologies ?? []

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, marginBottom: '1.5rem' }}>
        Ontologies
      </h1>

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
              {['Name', 'IRI', 'Status', 'Stats', 'Added'].map(h => (
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
