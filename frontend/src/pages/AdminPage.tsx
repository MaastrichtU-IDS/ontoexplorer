import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { useAdminOverview } from '../hooks/useAdminOverview'
import { AdminOntologyEntry, AdminJobEntry, WorkerTask, api } from '../lib/api'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTriples(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function fmtAge(iso: string | null): string {
  if (!iso) return '—'
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function fmtDuration(started: string | null, finished: string | null): string {
  if (!started) return '—'
  const end = finished ? new Date(finished).getTime() : Date.now()
  const secs = Math.floor((end - new Date(started).getTime()) / 1000)
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusDot({ status, label }: { status: string; label?: string }) {
  const text = label ?? status
  if (status === 'ok' || status === 'ingested' || status === 'done' || status === 'ready') {
    return <span style={{ color: 'var(--accent-green, #3fb950)', fontSize: 11 }}>● {text}</span>
  }
  if (status === 'running') {
    return <span style={{ color: 'var(--accent-blue, #58a6ff)', fontSize: 11 }}>⟳ {text}</span>
  }
  if (status === 'pending' || status === 'queued') {
    return <span style={{ color: '#d29922', fontSize: 11 }}>⏳ {text}</span>
  }
  if (status === 'not_started') {
    return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>— {text}</span>
  }
  if (status === 'failed' || status.startsWith('error')) {
    return <span style={{ color: '#f85149', fontSize: 11 }}>✕ {text}</span>
  }
  return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{text}</span>
}

// ── Section heading ───────────────────────────────────────────────────────────

function SectionLabel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase',
      letterSpacing: '.8px', marginBottom: 6, ...style,
    }}>
      {children}
    </div>
  )
}

// ── Service Health ────────────────────────────────────────────────────────────

function ServiceCard({ name, status }: { name: string; status: string | number }) {
  const isOk = status === 'ok'
  const isNum = typeof status === 'number'
  const color = isNum
    ? (status > 0 ? '#f0883e' : 'var(--accent-green, #3fb950)')
    : (isOk ? 'var(--accent-green, #3fb950)' : '#f85149')
  return (
    <div style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 6, padding: '10px 12px', textAlign: 'center', minWidth: 90,
    }}>
      <div style={{ color, fontSize: 11, marginBottom: 3, fontWeight: 500 }}>
        {isNum ? `▶ ${status} queued` : (isOk ? '● ok' : '✕ error')}
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
        {name}
      </div>
    </div>
  )
}

// ── Ontology Pipeline ─────────────────────────────────────────────────────────

const REASONING_ORDER: Record<string, number> = { not_started: 0, running: 1, ready: 2 }

type UpdateState = 'idle' | 'queued' | 'error'
type SortCol = 'ontology' | 'triples' | 'ingestion' | 'indexed' | 'embeddings' | 'reasoning' | 'updated'

function ontologyDisplayName(row: AdminOntologyEntry): string {
  return row.shortname
    || row.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
    || row.iri
}

function UpdateButton({
  ontologyId,
  sourceUrl,
  iri,
  state,
  onUpdate,
}: {
  ontologyId: string
  sourceUrl: string | null
  iri: string
  state: UpdateState
  onUpdate: (id: string) => void
}) {
  const hasSource = !!(sourceUrl || iri)
  if (!hasSource) {
    return <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>—</span>
  }
  if (state === 'queued') {
    return <span style={{ color: '#ffa657', fontSize: 10 }}>↑ queued</span>
  }
  const method = sourceUrl ? 'url' : 'iri'
  const isError = state === 'error'
  return (
    <button
      onClick={() => onUpdate(ontologyId)}
      title={method === 'url' ? `Re-ingest via URL: ${sourceUrl}` : `Re-ingest via IRI (content negotiation): ${iri}`}
      style={{
        background: isError ? 'rgba(248,81,73,0.1)' : 'none',
        border: `1px solid ${isError ? 'rgba(248,81,73,0.3)' : 'var(--border)'}`,
        borderRadius: 4, cursor: 'pointer',
        color: isError ? '#f85149' : 'var(--text-dim)',
        fontSize: 10, padding: '2px 8px',
      }}
    >
      {isError ? '✕ retry' : `↑ ${method}`}
    </button>
  )
}

const PAGE_SIZE = 25

function OntologyTable({
  rows,
  updateStates,
  onUpdate,
  reindexStates,
  onReindex,
}: {
  rows: AdminOntologyEntry[]
  updateStates: Record<string, UpdateState>
  onUpdate: (id: string) => void
  reindexStates: Record<string, UpdateState>
  onReindex: (id: string) => void
}) {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' }>({ col: 'ontology', dir: 'asc' })
  const [page, setPage] = useState(0)

  function toggleSort(col: SortCol) {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' })
    setPage(0)
  }

  function handleSearch(q: string) {
    setSearch(q)
    setPage(0)
  }

  const filtered = rows.filter(r => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      ontologyDisplayName(r).toLowerCase().includes(q) ||
      r.iri.toLowerCase().includes(q) ||
      (r.label ?? '').toLowerCase().includes(q) ||
      (r.shortname ?? '').toLowerCase().includes(q)
    )
  })

  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0
    switch (sort.col) {
      case 'ontology':   cmp = ontologyDisplayName(a).localeCompare(ontologyDisplayName(b)); break
      case 'triples':    cmp = (a.triple_count ?? -1) - (b.triple_count ?? -1); break
      case 'ingestion':  cmp = a.ingestion_status.localeCompare(b.ingestion_status); break
      case 'indexed':    cmp = (a.indexed ? 1 : 0) - (b.indexed ? 1 : 0); break
      case 'embeddings': cmp = a.embed_count - b.embed_count; break
      case 'reasoning':  cmp = (REASONING_ORDER[a.reasoning_status] ?? 0) - (REASONING_ORDER[b.reasoning_status] ?? 0); break
      case 'updated':    cmp = (a.version_created_at ?? '').localeCompare(b.version_created_at ?? ''); break
    }
    return sort.dir === 'asc' ? cmp : -cmp
  })

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const thBase: React.CSSProperties = {
    padding: '7px 10px', fontWeight: 500, fontSize: 10,
    textTransform: 'uppercase', letterSpacing: .5,
    cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
  }

  function SortTh({ col, label, align = 'center' }: { col: SortCol; label: string; align?: React.CSSProperties['textAlign'] }) {
    const active = sort.col === col
    return (
      <th onClick={() => toggleSort(col)} style={{ ...thBase, textAlign: align, color: active ? 'var(--text)' : 'var(--text-dim)' }}>
        {label} <span style={{ opacity: active ? 1 : 0.25 }}>{active && sort.dir === 'desc' ? '▼' : '▲'}</span>
      </th>
    )
  }

  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    background: 'none', border: '1px solid var(--border)', borderRadius: 4,
    color: disabled ? 'var(--text-dim)' : 'var(--text)',
    fontSize: 11, padding: '2px 10px', cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.4 : 1,
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <input
          value={search}
          onChange={e => handleSearch(e.target.value)}
          placeholder="Search ontologies…"
          style={{
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 6, padding: '5px 10px', color: 'var(--text)',
            fontSize: 12, outline: 'none', width: 240,
          }}
        />
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          {filtered.length !== rows.length ? `${filtered.length} of ${rows.length}` : `${rows.length} total`}
        </span>
      </div>

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
              <SortTh col="ontology"   label="Ontology"    align="left" />
              <SortTh col="triples"    label="Triples" />
              <SortTh col="ingestion"  label="Ingestion" />
              <SortTh col="indexed"    label="Indexed" />
              <SortTh col="embeddings" label="Embeddings" />
              <SortTh col="reasoning"  label="Reasoning" />
              <SortTh col="updated"    label="Updated" />
              <th style={{ ...thBase, textAlign: 'center', cursor: 'default', color: 'var(--text-dim)' }}>Ingest</th>
              <th style={{ ...thBase, textAlign: 'center', cursor: 'default', color: 'var(--text-dim)' }}>Index</th>
            </tr>
          </thead>
          <tbody>
            {paged.map(row => (
              <tr key={row.version_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                  <div>{ontologyDisplayName(row)}</div>
                  {row.label && row.label !== ontologyDisplayName(row) && (
                    <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>{row.label}</div>
                  )}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  {fmtTriples(row.triple_count)}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <StatusDot status={row.ingestion_status} />
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <StatusDot status={row.indexed ? 'done' : 'not_started'} label={row.indexed ? 'yes' : 'no'} />
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: row.embed_count > 0 ? 'var(--accent-green, #3fb950)' : 'var(--text-dim)', fontSize: 11 }}>
                  {row.embed_count > 0 ? fmtTriples(row.embed_count) : '—'}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <StatusDot status={row.reasoning_status} label={row.reasoning_status.replace('_', ' ')} />
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                  {fmtAge(row.version_created_at)}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <UpdateButton
                    ontologyId={row.id}
                    sourceUrl={row.source_url}
                    iri={row.iri}
                    state={updateStates[row.id] ?? 'idle'}
                    onUpdate={onUpdate}
                  />
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  {row.ingestion_status !== 'deprecated' && row.ingestion_status !== 'pending' ? (
                    reindexStates[row.id] === 'queued'
                      ? <span style={{ color: '#ffa657', fontSize: 10 }}>↑ queued</span>
                      : <button
                          onClick={() => onReindex(row.id)}
                          title="Re-index search (updates deprecated term filter, labels, synonyms)"
                          style={{
                            background: reindexStates[row.id] === 'error' ? 'rgba(248,81,73,0.1)' : 'none',
                            border: `1px solid ${reindexStates[row.id] === 'error' ? 'rgba(248,81,73,0.3)' : 'var(--border)'}`,
                            borderRadius: 4, cursor: 'pointer',
                            color: reindexStates[row.id] === 'error' ? '#f85149' : 'var(--text-dim)',
                            fontSize: 10, padding: '2px 8px',
                          }}
                        >
                          {reindexStates[row.id] === 'error' ? '✕ retry' : '↺ index'}
                        </button>
                  ) : (
                    <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>—</span>
                  )}
                </td>
              </tr>
            ))}
            {paged.length === 0 && (
              <tr>
                <td colSpan={9} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                  {search ? 'No matching ontologies' : 'No ontologies'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <button onClick={() => setPage(p => p - 1)} disabled={page === 0} style={btnStyle(page === 0)}>
            ‹ Prev
          </button>
          <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1} style={btnStyle(page >= totalPages - 1)}>
            Next ›
          </button>
        </div>
      )}
    </div>
  )
}

// ── Recent Jobs ───────────────────────────────────────────────────────────────

const JOB_TYPE_COLOR: Record<string, string> = {
  ingest: '#d2a8ff',
  ingestion: '#d2a8ff',
  index: '#79c0ff',
  indexing: '#79c0ff',
  reason: '#56d364',
  reasoning: '#56d364',
  embedding: '#ffa657',
}

function JobsTable({ jobs }: { jobs: AdminJobEntry[] }) {
  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            {['Type', 'Ontology', 'Status', 'Duration', 'Started'].map(h => (
              <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Type' || h === 'Ontology' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {jobs.map(job => (
            <tr key={job.id} style={{
              borderBottom: '1px solid rgba(255,255,255,0.04)',
              background: job.status === 'failed' ? 'rgba(248,81,73,0.06)' : undefined,
            }}>
              <td style={{ padding: '6px 10px', color: JOB_TYPE_COLOR[job.type] ?? 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>
                {job.type}
              </td>
              <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                {job.ontology_shortname ?? job.ontology_iri?.split(/[/#]/).pop() ?? '—'}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <StatusDot status={job.status} />
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                {fmtDuration(job.started_at, job.finished_at)}
                {job.status === 'running' && <span style={{ color: 'var(--text-dim)' }}>…</span>}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                {fmtAge(job.started_at)}
              </td>
            </tr>
          ))}
          {jobs.length === 0 && (
            <tr>
              <td colSpan={5} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                No jobs yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ── Workers panel ─────────────────────────────────────────────────────────────

const TASK_SHORT: Record<string, string> = {
  'ontoexplorer.ingest_ontology':    'ingest',
  'ontoexplorer.embed_ontology':     'embed',
  'ontoexplorer.index_ontology':     'index',
  'ontoexplorer.reason_ontology':    'reason',
  'ontoexplorer.detect_profile':     'profile',
  'ontoexplorer.detect_meta_profile':'meta',
  'ontoexplorer.compute_diff':       'diff',
  'ontoexplorer.poll_for_updates':   'poll',
}

function taskLabel(name: string): string {
  return TASK_SHORT[name] ?? name.split('.').pop() ?? name
}

function taskDetail(t: WorkerTask, versionMap: Record<string, string>): string {
  const kw = t.kwargs
  if (kw.version_id) {
    const name = versionMap[String(kw.version_id)]
    return name ?? String(kw.version_id).slice(0, 8) + '…'
  }
  if (kw.iri) return String(kw.iri).replace(/^https?:\/\//, '').slice(0, 48)
  if (kw.url) return String(kw.url).replace(/^https?:\/\//, '').slice(0, 48)
  return '—'
}

function WorkersPanel({ versionMap }: { versionMap: Record<string, string> }) {
  const qc = useQueryClient()
  const [revoking, setRevoking] = useState<Set<string>>(new Set())

  const { data, isFetching } = useQuery({
    queryKey: ['admin-workers'],
    queryFn: () => api.admin.workers(),
    refetchInterval: 5000,
  })

  async function handleRevoke(t: WorkerTask) {
    setRevoking(s => new Set(s).add(t.id))
    try {
      const versionId = t.kwargs.version_id ? String(t.kwargs.version_id) : undefined
      await api.admin.revokeWorker(t.id, versionId)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['admin-workers'] }), 800)
    } finally {
      setRevoking(s => { const n = new Set(s); n.delete(t.id); return n })
    }
  }

  const tasks = data?.tasks ?? []

  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            {['Task', 'Ontology', 'Worker', 'State', 'Running', ''].map(h => (
              <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Task' || h === 'Ontology' || h === 'Worker' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map(t => (
            <tr key={t.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '6px 10px' }}>
                <div style={{ color: JOB_TYPE_COLOR[taskLabel(t.name)] ?? '#79c0ff', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>
                  {taskLabel(t.name)}
                </div>
                <div style={{ color: 'var(--text-dim)', fontFamily: 'monospace', fontSize: 9, marginTop: 1 }} title={t.id}>
                  {t.id.slice(0, 8)}…
                </div>
              </td>
              <td style={{ padding: '6px 10px', color: 'var(--text-dim)', fontSize: 11 }}>
                {taskDetail(t, versionMap)}
              </td>
              <td style={{ padding: '6px 10px', color: 'var(--text-dim)', fontFamily: 'monospace', fontSize: 10 }}>
                {t.worker === 'queue' ? '—' : t.worker.replace(/^celery@/, '')}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                {t.state === 'active'
                  ? <span style={{ color: '#58a6ff', fontSize: 11 }}>⟳ running</span>
                  : t.state === 'reserved'
                  ? <span style={{ color: '#d29922', fontSize: 11 }}>⏳ next</span>
                  : <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>· queued</span>
                }
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                {t.time_start ? fmtDuration(new Date(t.time_start * 1000).toISOString(), null) : '—'}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <button
                  onClick={() => handleRevoke(t)}
                  disabled={revoking.has(t.id)}
                  style={{
                    background: 'rgba(248,81,73,0.1)', border: '1px solid rgba(248,81,73,0.3)',
                    borderRadius: 4, color: '#f85149', fontSize: 10, padding: '2px 8px',
                    cursor: revoking.has(t.id) ? 'default' : 'pointer',
                    opacity: revoking.has(t.id) ? 0.5 : 1,
                  }}
                >
                  {revoking.has(t.id) ? '…' : 'Cancel'}
                </button>
              </td>
            </tr>
          ))}
          {tasks.length === 0 && (
            <tr>
              <td colSpan={6} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                {isFetching ? 'Checking workers…' : 'No active or queued tasks'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading, dataUpdatedAt } = useAdminOverview()
  const [secondsAgo, setSecondsAgo] = useState(0)
  const [updateStates, setUpdateStates] = useState<Record<string, UpdateState>>({})
  const [reindexStates, setReindexStates] = useState<Record<string, UpdateState>>({})
  const [reindexAllState, setReindexAllState] = useState<'idle' | 'queued' | 'error'>('idle')

  async function handleUpdate(ontologyId: string) {
    setUpdateStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try {
      await api.admin.queueIngest(ontologyId)
    } catch {
      setUpdateStates(s => ({ ...s, [ontologyId]: 'error' }))
    }
  }

  async function handleReindex(ontologyId: string) {
    setReindexStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try {
      await api.admin.queueIndex(ontologyId)
    } catch {
      setReindexStates(s => ({ ...s, [ontologyId]: 'error' }))
    }
  }

  async function handleReindexAll() {
    setReindexAllState('queued')
    try {
      await api.admin.reindexAll()
    } catch {
      setReindexAllState('error')
    }
  }

  // Redirect non-admins after auth resolves
  useEffect(() => {
    if (!authLoading && user && !user.is_admin) {
      navigate('/')
    }
  }, [authLoading, user, navigate])

  // "Last updated Ns ago" counter
  useEffect(() => {
    if (!dataUpdatedAt) return
    const tick = () => setSecondsAgo(Math.floor((Date.now() - dataUpdatedAt) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [dataUpdatedAt])

  if (authLoading || isLoading) {
    return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Loading…</div>
  }
  if (!user?.is_admin) return null

  const s = data!.services

  // version_id → display name for worker task labels
  const versionMap: Record<string, string> = {}
  for (const o of data!.ontologies) {
    const name = o.shortname || o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '') || o.iri
    versionMap[o.version_id] = name
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem 2rem' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <span style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)' }}>System Admin</span>
        <span style={{
          color: '#3fb950', fontSize: 11,
          background: 'rgba(63,185,80,.1)', border: '1px solid rgba(63,185,80,.25)',
          padding: '1px 8px', borderRadius: 10,
        }}>
          ● live · refreshes every 10s
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          Last updated {secondsAgo}s ago
        </span>
      </div>

      {/* Service health */}
      <SectionLabel>Service Health</SectionLabel>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
        <ServiceCard name="Postgres" status={s.postgres} />
        <ServiceCard name="Redis" status={s.redis} />
        <ServiceCard name="MinIO" status={s.minio} />
        <ServiceCard name="ELK" status={s.elk} />
        <ServiceCard name="Queue" status={s.celery_queue_depth} />
      </div>

      {/* Ontology pipeline */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <SectionLabel style={{ margin: 0 }}>Ontology Pipeline ({data!.ontologies.length})</SectionLabel>
        <div style={{ flex: 1 }} />
        <button
          onClick={handleReindexAll}
          disabled={reindexAllState === 'queued'}
          title="Queue index_ontology for every ingested version (rebuilds search index and deprecated-term filter)"
          style={{
            background: reindexAllState === 'error' ? 'rgba(248,81,73,0.1)' : 'none',
            border: `1px solid ${reindexAllState === 'error' ? 'rgba(248,81,73,0.3)' : 'var(--border)'}`,
            borderRadius: 4, cursor: reindexAllState === 'queued' ? 'default' : 'pointer',
            color: reindexAllState === 'error' ? '#f85149' : reindexAllState === 'queued' ? '#ffa657' : 'var(--text-dim)',
            fontSize: 11, padding: '4px 12px',
            opacity: reindexAllState === 'queued' ? 0.7 : 1,
          }}
        >
          {reindexAllState === 'queued' ? '↑ queuing…' : reindexAllState === 'error' ? '✕ retry re-index all' : '↺ Re-index all'}
        </button>
      </div>
      <div style={{ marginBottom: 24 }}>
        <OntologyTable
          rows={data!.ontologies}
          updateStates={updateStates}
          onUpdate={handleUpdate}
          reindexStates={reindexStates}
          onReindex={handleReindex}
        />
      </div>

      {/* Workers */}
      <SectionLabel>Workers</SectionLabel>
      <div style={{ marginBottom: 24 }}>
        <WorkersPanel versionMap={versionMap} />
      </div>

      {/* Recent jobs */}
      <SectionLabel>Recent Jobs</SectionLabel>
      <JobsTable jobs={data!.jobs} />

    </div>
  )
}
