import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, Ontology, OntologyVersion } from '../lib/api'
import { useArbitraryComparison, useTriggerComparison } from '../hooks/useCompare'
import DiffResultView from '../components/DiffResultView'

function ontologyDisplayName(o: Ontology): string {
  return (
    o.shortname
    || o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
    || o.iri
  )
}

function OntologyPicker({
  ontologies,
  value,
  onChange,
  side,
  disabledId,
}: {
  ontologies: Ontology[]
  value: string
  onChange: (id: string) => void
  side: 'from' | 'to'
  disabledId?: string
}) {
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return ontologies
    return ontologies.filter(o =>
      ontologyDisplayName(o).toLowerCase().includes(q) ||
      o.iri.toLowerCase().includes(q) ||
      (o.title ?? '').toLowerCase().includes(q)
    )
  }, [ontologies, query])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {side === 'from' ? 'From ontology' : 'To ontology'}
      </label>
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Filter ontologies…"
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '6px 10px', color: 'var(--text)', fontSize: 12,
        }}
      />
      <select
        size={Math.min(8, Math.max(3, filtered.length))}
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '4px 6px', color: 'var(--text)', fontSize: 12,
          fontFamily: 'monospace', minHeight: 90,
        }}
      >
        {filtered.map(o => (
          <option key={o.id} value={o.id} disabled={o.id === disabledId}>
            {ontologyDisplayName(o)}{o.title ? ` — ${o.title}` : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function VersionPicker({
  ontologyId,
  value,
  onChange,
  side,
}: {
  ontologyId: string
  value: string
  onChange: (vid: string) => void
  side: 'from' | 'to'
}) {
  const { data } = useQuery({
    queryKey: ['versions', ontologyId],
    queryFn: () => api.ontologies.versions(ontologyId),
    enabled: !!ontologyId,
  })

  const versions: OntologyVersion[] = useMemo(
    () => (data?.versions ?? []).filter(v => v.status !== 'deprecated'),
    [data],
  )

  useEffect(() => {
    if (!value && versions.length > 0) onChange(versions[0].id)
  }, [versions, value, onChange])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {side === 'from' ? 'From version' : 'To version'}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '6px 10px', color: 'var(--text)', fontSize: 12,
          fontFamily: 'monospace',
        }}
      >
        {versions.map(v => (
          <option key={v.id} value={v.id}>
            {v.version_iri ?? `${v.id.slice(0, 8)} · ${new Date(v.created_at).toLocaleDateString()}`}
          </option>
        ))}
      </select>
    </div>
  )
}

export default function Compare() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const urlFrom = params.get('from')
  const urlTo = params.get('to')

  const [fromOnt, setFromOnt] = useState('')
  const [toOnt,   setToOnt]   = useState('')
  const [fromVid, setFromVid] = useState(urlFrom ?? '')
  const [toVid,   setToVid]   = useState(urlTo ?? '')

  const { data: onts } = useQuery({
    queryKey: ['ontologies', 'all'],
    queryFn: () => api.ontologies.list(),
  })
  const ontologies: Ontology[] = onts?.ontologies ?? []

  const trigger = useTriggerComparison()
  const { data: comparison } = useArbitraryComparison(
    fromVid || null, toVid || null
  )

  useEffect(() => {
    if (urlFrom && urlTo && urlFrom !== urlTo && !trigger.isPending) {
      trigger.mutate({ fromVid: urlFrom, toVid: urlTo })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canCompare = !!fromVid && !!toVid && fromVid !== toVid

  function handleCompare() {
    navigate(`/compare?from=${encodeURIComponent(fromVid)}&to=${encodeURIComponent(toVid)}`, { replace: true })
    trigger.mutate({ fromVid, toVid })
  }

  const fromOntObj = ontologies.find(o => o.id === fromOnt)
  const toOntObj   = ontologies.find(o => o.id === toOnt)

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem 2rem', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>Compare ontologies</h1>
      <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
        Pick any two ontologies. The comparison aligns entities by exact IRI match.
      </div>

      <div style={{ display: 'flex', gap: 16 }}>
        <OntologyPicker
          ontologies={ontologies}
          value={fromOnt}
          onChange={setFromOnt}
          side="from"
          disabledId={toOnt}
        />
        <OntologyPicker
          ontologies={ontologies}
          value={toOnt}
          onChange={setToOnt}
          side="to"
          disabledId={fromOnt}
        />
      </div>

      {(fromOnt || toOnt) && (
        <div style={{ display: 'flex', gap: 16 }}>
          {fromOnt ? (
            <VersionPicker ontologyId={fromOnt} value={fromVid} onChange={setFromVid} side="from" />
          ) : <div style={{ flex: 1 }} />}
          {toOnt ? (
            <VersionPicker ontologyId={toOnt} value={toVid} onChange={setToVid} side="to" />
          ) : <div style={{ flex: 1 }} />}
        </div>
      )}

      <div>
        <button
          onClick={handleCompare}
          disabled={!canCompare || trigger.isPending}
          style={{
            background: canCompare ? 'var(--accent)' : 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 6, padding: '8px 18px',
            color: canCompare ? '#0f172a' : 'var(--text-dim)',
            fontSize: 13, fontWeight: 600,
            cursor: canCompare && !trigger.isPending ? 'pointer' : 'default',
          }}
        >
          {trigger.isPending ? 'Queuing…' : 'Compare'}
        </button>
      </div>

      {fromVid && toVid && fromVid !== toVid && comparison && (
        <>
          {comparison.status === 'pending' && (
            <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
              Computing comparison… this can take up to a minute for large ontologies.
            </div>
          )}
          {comparison.status === 'failed' && (
            <div style={{ padding: '1rem', color: '#f85149', fontSize: 12 }}>
              Comparison failed. Click Compare to retry.
            </div>
          )}
          {comparison.status === 'ready' && 'diff_data' in comparison && comparison.diff_data && (
            <DiffResultView
              data={comparison.diff_data}
              summary={comparison.summary}
              variant="cross-compare"
              fromLabel={fromOntObj ? ontologyDisplayName(fromOntObj) : 'A'}
              toLabel={toOntObj ? ontologyDisplayName(toOntObj) : 'B'}
            />
          )}
        </>
      )}
    </div>
  )
}
