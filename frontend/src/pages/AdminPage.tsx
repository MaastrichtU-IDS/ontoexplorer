import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useAdminOverview } from '../hooks/useAdminOverview'
import { AdminOntologyEntry, AdminJobEntry } from '../lib/api'

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
  if (status === 'not_started' || status === 'queued' || status === 'pending') {
    return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>— {text}</span>
  }
  if (status === 'failed' || status.startsWith('error')) {
    return <span style={{ color: '#f85149', fontSize: 11 }}>✕ {text}</span>
  }
  return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{text}</span>
}

// ── Section heading ───────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase',
      letterSpacing: '.8px', marginBottom: 6,
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

function OntologyTable({ rows }: { rows: AdminOntologyEntry[] }) {
  const sorted = [...rows].sort((a, b) =>
    (REASONING_ORDER[a.reasoning_status] ?? 0) - (REASONING_ORDER[b.reasoning_status] ?? 0)
  )
  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            {['Ontology', 'Triples', 'Ingestion', 'Indexed', 'Reasoning', 'Updated'].map(h => (
              <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Ontology' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(row => (
            <tr key={row.version_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                {row.shortname ?? row.iri.split(/[/#]/).pop()}
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
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <StatusDot status={row.reasoning_status} label={row.reasoning_status.replace('_', ' ')} />
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                {fmtAge(row.version_created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
                {job.ontology_shortname ?? '—'}
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading, dataUpdatedAt } = useAdminOverview()
  const [secondsAgo, setSecondsAgo] = useState(0)

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
      <SectionLabel>Ontology Pipeline ({data!.ontologies.length})</SectionLabel>
      <div style={{ marginBottom: 24 }}>
        <OntologyTable rows={data!.ontologies} />
      </div>

      {/* Recent jobs */}
      <SectionLabel>Recent Jobs</SectionLabel>
      <JobsTable jobs={data!.jobs} />

    </div>
  )
}
