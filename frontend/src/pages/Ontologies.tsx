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

const GROUP_LABELS: Record<string, string> = {
  upper:       'Upper Ontology',
  sulo_family: 'SULO Family',
  metadata:    'Metadata',
  obo:         'OBO Foundry',
  biomedical:  'Biomedical',
}

const GROUP_COLORS: Record<string, { bg: string; border: string; color: string }> = {
  upper:       { bg: 'rgba(97,175,239,0.12)',  border: 'rgba(97,175,239,0.4)',  color: '#61afef' },
  sulo_family: { bg: 'rgba(229,192,123,0.12)', border: 'rgba(229,192,123,0.4)', color: '#e5c07b' },
  metadata:    { bg: 'rgba(198,120,221,0.12)', border: 'rgba(198,120,221,0.4)', color: '#c678dd' },
  obo:         { bg: 'rgba(152,195,121,0.12)', border: 'rgba(152,195,121,0.4)', color: '#98c379' },
  biomedical:  { bg: 'rgba(224,108,117,0.12)', border: 'rgba(224,108,117,0.4)', color: '#e06c75' },
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
  const [descExpanded, setDescExpanded] = useState(false)
  const latest = o.latest_version
  const hasStats = o.class_count != null || o.property_count != null || o.triple_count != null || o.individual_count != null
  const knownGroups = (o.groups ?? []).filter(g => g in GROUP_LABELS)

  return (
    <tr
      onClick={() => latest && navigate(`/ontologies/${o.shortname ?? slugFromIri(o.iri)}`)}
      style={{ cursor: latest ? 'pointer' : 'default', borderBottom: '1px solid var(--border)' }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
      onMouseLeave={e => (e.currentTarget.style.background = '')}
    >
      {/* Name · IRI chip · group badges · description */}
      <td style={{ padding: '10px 12px' }}>
        {o.label && (
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', marginBottom: 2 }}>
            {o.label}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{displayName(o)}</span>
          <IriChip iri={o.iri} />
          {knownGroups.map(g => {
            const c = GROUP_COLORS[g]
            return (
              <span key={g} style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 10,
                background: c.bg, border: `1px solid ${c.border}`,
                color: c.color, fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
              }}>
                {GROUP_LABELS[g]}
              </span>
            )
          })}
        </div>
        {o.description && (
          <div style={{ marginTop: 3, maxWidth: 520 }}>
            <div style={{
              color: 'var(--text-dim)', fontSize: 11, lineHeight: 1.4,
              ...(!descExpanded && {
                display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
              }),
            }}>
              {o.description}
            </div>
            {(descExpanded || o.description.length > 200) && (
              <button
                onClick={e => { e.stopPropagation(); setDescExpanded(v => !v) }}
                style={{
                  fontSize: 10, color: 'var(--accent)', background: 'none',
                  border: 'none', padding: '2px 0', cursor: 'pointer',
                }}
              >
                {descExpanded ? 'less' : 'more…'}
              </button>
            )}
          </div>
        )}
      </td>

      {/* Classes · props · axioms */}
      <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {hasStats ? (
          <>
            {fmtCount(o.class_count)} cls
            <span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>
            {fmtCount(o.property_count)} props
            {o.individual_count != null && o.individual_count > 0 && (
              <><span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>{fmtCount(o.individual_count)} ind</>
            )}
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

// ── Group filter ─────────────────────────────────────────────────────────────

const GROUPS: { value: string; label: string }[] = [
  { value: '',            label: 'All' },
  { value: 'upper',       label: 'Upper Ontology' },
  { value: 'sulo_family', label: 'SULO Family' },
  { value: 'metadata',    label: 'Metadata' },
  { value: 'obo',         label: 'OBO Foundry' },
  { value: 'biomedical',  label: 'Biomedical' },
]

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Ontologies() {
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState('')
  const { data, isLoading } = useOntologySearch(query, group || undefined)
  const ontologies = data?.ontologies ?? []

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, marginBottom: '1.5rem' }}>
        Ontologies
      </h1>

      {/* Group filter chips */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: '1rem' }}>
        {GROUPS.map(g => (
          <button
            key={g.value}
            onClick={() => setGroup(g.value)}
            style={{
              fontSize: 12, padding: '4px 12px', borderRadius: 20,
              border: '1px solid var(--border)', cursor: 'pointer',
              background: group === g.value ? 'var(--accent)' : 'var(--bg-secondary)',
              color: group === g.value ? '#000' : 'var(--text-dim)',
              fontWeight: group === g.value ? 600 : 400,
            }}
          >
            {g.label}
          </button>
        ))}
      </div>

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
          placeholder="Filter by name, IRI, or description…"
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
          {(query || group) ? 'No ontologies match your filter.' : 'No ontologies loaded yet.'}
        </p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Name', 'Stats', 'Added'].map(h => (
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
        {(query || group) && ' matching filter'}
      </p>
    </div>
  )
}
