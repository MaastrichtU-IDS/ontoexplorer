import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const selected = ontologies.find(o => o.id === value)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return ontologies
    return ontologies.filter(o =>
      ontologyDisplayName(o).toLowerCase().includes(q) ||
      o.iri.toLowerCase().includes(q) ||
      (o.title ?? '').toLowerCase().includes(q)
    )
  }, [ontologies, query])

  // Close when clicking outside.
  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  // Auto-focus the filter input when the dropdown opens.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  function pick(id: string) {
    onChange(id)
    setOpen(false)
    setQuery('')
  }

  return (
    <div ref={rootRef} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {side === 'from' ? 'From ontology' : 'To ontology'}
      </label>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '6px 10px', color: selected ? 'var(--text)' : 'var(--text-dim)',
          fontSize: 12, textAlign: 'left', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
          fontFamily: 'inherit',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected
            ? `${ontologyDisplayName(selected)}${selected.title ? ` — ${selected.title}` : ''}`
            : 'Select an ontology…'}
        </span>
        <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div
          style={{
            position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4, zIndex: 50,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 4, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            display: 'flex', flexDirection: 'column',
          }}
        >
          <div style={{ padding: 6, borderBottom: '1px solid var(--border)' }}>
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search ontologies…"
              style={{
                width: '100%', boxSizing: 'border-box',
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 4, padding: '5px 8px', color: 'var(--text)', fontSize: 12, outline: 'none',
              }}
            />
          </div>
          <div style={{ maxHeight: 280, overflowY: 'auto' }}>
            {filtered.length === 0 && (
              <div style={{ padding: 10, color: 'var(--text-dim)', fontSize: 12 }}>No matches</div>
            )}
            {filtered.map(o => {
              const isDisabled = o.id === disabledId
              const isSelected = o.id === value
              return (
                <button
                  key={o.id}
                  type="button"
                  disabled={isDisabled}
                  onClick={() => pick(o.id)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '6px 10px',
                    background: isSelected ? 'rgba(97,175,239,0.08)' : 'transparent',
                    border: 'none',
                    borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
                    color: isDisabled ? 'var(--text-dim)' : 'var(--text)',
                    fontSize: 12, cursor: isDisabled ? 'not-allowed' : 'pointer',
                    opacity: isDisabled ? 0.5 : 1,
                  }}
                  title={isDisabled ? 'Already selected on the other side' : o.iri}
                >
                  <div style={{ fontFamily: 'monospace' }}>{ontologyDisplayName(o)}</div>
                  {o.title && (
                    <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 1 }}>{o.title}</div>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
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
    if (versions.length === 0) return
    // Reset to latest when value is empty OR when current value isn't a valid
    // version of the loaded ontology. The latter catches a subtle bug where
    // changing the ontology in OntologyPicker left a stale version ID from
    // the previous ontology (or from URL params seeded before the user
    // picked any ontology), causing the wrong comparison to be triggered.
    const isValid = versions.some(v => v.id === value)
    if (!value || !isValid) onChange(versions[0].id)
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

  // Smart default: when the user picks the same ontology on both sides and
  // both VersionPickers default to the latest version (so fromVid === toVid),
  // demote the From side to the previous version so the comparison is
  // meaningful by default. Uses the React Query cache populated by
  // VersionPicker's own fetch.
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!fromOnt || fromOnt !== toOnt) return
    if (!fromVid || !toVid || fromVid !== toVid) return
    const data = queryClient.getQueryData<{ versions: OntologyVersion[] }>(
      ['versions', fromOnt],
    )
    if (!data) return
    const versions = data.versions.filter(v => v.status !== 'deprecated')
    if (versions.length < 2) return
    // versions are returned sorted by created_at DESC by the backend;
    // versions[1] is the previous non-deprecated version.
    setFromVid(versions[1].id)
  }, [fromOnt, toOnt, fromVid, toVid, queryClient])

  const canCompare = !!fromVid && !!toVid && fromVid !== toVid

  function handleCompare() {
    navigate(`/compare?from=${encodeURIComponent(fromVid)}&to=${encodeURIComponent(toVid)}`, { replace: true })
    trigger.mutate({ fromVid, toVid })
  }

  // Prefer the picker state. Fall back to the comparison response so that
  // URL-driven loads (where fromOnt/toOnt aren't selected in the picker)
  // still get the correct ontology labels.
  const fromOntFromCompare = comparison && comparison.status === 'ready'
    ? ontologies.find(o => o.id === comparison.from_ontology_id)
    : undefined
  const toOntFromCompare = comparison && comparison.status === 'ready'
    ? ontologies.find(o => o.id === comparison.to_ontology_id)
    : undefined
  const fromOntObj = ontologies.find(o => o.id === fromOnt) ?? fromOntFromCompare
  const toOntObj   = ontologies.find(o => o.id === toOnt)   ?? toOntFromCompare

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem 2rem', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>Compare ontologies</h1>
      <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
        Pick any two ontologies (or the same ontology twice to compare versions).
        Entities are aligned by exact IRI match.
      </div>

      <div style={{ display: 'flex', gap: 16 }}>
        <OntologyPicker
          ontologies={ontologies}
          value={fromOnt}
          onChange={setFromOnt}
          side="from"
        />
        <OntologyPicker
          ontologies={ontologies}
          value={toOnt}
          onChange={setToOnt}
          side="to"
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

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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
        {fromVid && toVid && fromVid === toVid && (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            Pick a different version on each side to compare.
          </span>
        )}
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
