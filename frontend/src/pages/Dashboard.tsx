import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Ontology, type OntologyVersion } from '../lib/api'

// ── Status dot ────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ready:      'var(--accent)',
  ingested:   'var(--text-muted)',
  reasoning:  'var(--accent-purple)',
  indexing:   'var(--accent-purple)',
  deprecated: 'var(--text-dim)',
  failed:     '#f87171',
}

function StatusDot({ status }: { status: string }) {
  return (
    <span style={{ color: STATUS_COLOR[status] ?? 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
      ● {status}
    </span>
  )
}

// ── Format triple count ───────────────────────────────────────────────────────

function fmtCount(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

// ── Single ontology row ───────────────────────────────────────────────────────

function OntologyRow({ ontology }: { ontology: Ontology }) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()

  const { data: versionsData } = useQuery({
    queryKey: ['versions', ontology.id],
    queryFn: () => api.ontologies.versions(ontology.id),
  })

  const latest: OntologyVersion | undefined = versionsData?.versions[0]

  const del = useMutation({
    mutationFn: () => api.ontologies.delete(ontology.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ontologies'] })
    },
  })

  const shortVersion = latest?.version_iri
    ? latest.version_iri.replace(/.*[/#]/, '')
    : '—'

  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      {/* IRI + date + triple count */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top' }}>
        <Link
          to={`/ontologies/${ontology.id}`}
          style={{ color: 'var(--accent-blue)', fontSize: 'var(--font-size-base)', display: 'block' }}
        >
          {ontology.iri}
        </Link>
        <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          added {new Date(ontology.created_at).toLocaleDateString()}
          {latest?.triple_count != null && ` · ${fmtCount(latest.triple_count)} triples`}
        </span>
      </td>

      {/* Version */}
      <td style={{ padding: '0.6rem 1rem', color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        {shortVersion}
      </td>

      {/* Status */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        {latest ? <StatusDot status={latest.status} /> : <span style={{ color: 'var(--text-dim)' }}>—</span>}
      </td>

      {/* Actions */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        <Link
          to={`/ontologies/${ontology.id}`}
          style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginRight: '0.75rem' }}
        >
          view
        </Link>
        {confirming ? (
          <span style={{ fontSize: 'var(--font-size-sm)' }}>
            <span style={{ color: 'var(--text-muted)', marginRight: '0.25rem' }}>confirm?</span>
            <button
              onClick={() => del.mutate()}
              disabled={del.isPending}
              style={{ color: '#f87171', marginRight: '0.35rem', fontSize: 'var(--font-size-sm)' }}
            >
              yes
            </button>
            <button
              onClick={() => setConfirming(false)}
              style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
            >
              no
            </button>
          </span>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            delete
          </button>
        )}
      </td>
    </tr>
  )
}

// ── Add-ontology inline form ──────────────────────────────────────────────────

type AddTab = 'iri' | 'url' | 'paste'

function AddOntologyForm({ onSuccess }: { onSuccess: () => void }) {
  const [tab, setTab] = useState<AddTab>('iri')
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      const result = tab === 'iri'
        ? await api.ontologies.submitByIri(value)
        : await api.ontologies.submitByUrl(value)
      setMessage(`Queued — task ID: ${result.task_id}`)
      setValue('')
      setTimeout(onSuccess, 2000)
    } catch (err: unknown) {
      setMessage(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const tabs: { key: AddTab; label: string }[] = [
    { key: 'iri', label: 'By IRI' },
    { key: 'url', label: 'By URL' },
    { key: 'paste', label: 'Upload / Paste' },
  ]

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '1rem',
      marginBottom: '1.25rem',
    }}>
      <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.75rem' }}>
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              padding: '0.25rem 0.6rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)',
              background: tab === key ? 'var(--accent)' : 'transparent',
              color: tab === key ? '#0f172a' : 'var(--text-muted)',
              fontWeight: tab === key ? 700 : 400,
              fontSize: 'var(--font-size-sm)',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'paste' ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          File upload is available via the REST API: <code>POST /api/v1/ontologies</code> with multipart form data.
        </p>
      ) : (
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={tab === 'iri' ? 'https://purl.obolibrary.org/obo/go.owl' : 'https://example.com/ontology.ttl'}
            style={{ flex: 1 }}
            required
          />
          <button
            type="submit"
            disabled={submitting}
            style={{
              padding: '0.4rem 0.9rem',
              background: 'var(--accent)',
              color: '#0f172a',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 700,
              fontSize: 'var(--font-size-sm)',
            }}
          >
            {submitting ? 'Adding…' : 'Add'}
          </button>
        </form>
      )}

      {message && (
        <p style={{
          marginTop: '0.5rem',
          fontSize: 'var(--font-size-sm)',
          color: message.startsWith('Error') ? '#f87171' : 'var(--accent)',
        }}>
          {message}
        </p>
      )}
    </div>
  )
}

// ── Dashboard page ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [showForm, setShowForm] = useState(false)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.ontologies.list(),
  })

  function handleAdded() {
    qc.invalidateQueries({ queryKey: ['ontologies'] })
    setShowForm(false)
  }

  const ontologies = data?.ontologies ?? []

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>My Ontologies</h1>
        <button
          onClick={() => setShowForm(v => !v)}
          style={{
            padding: '0.35rem 0.8rem',
            background: showForm ? 'var(--bg-secondary)' : 'var(--accent)',
            color: showForm ? 'var(--text-muted)' : '#0f172a',
            border: showForm ? '1px solid var(--border)' : 'none',
            borderRadius: 'var(--radius-sm)',
            fontWeight: 600,
            fontSize: 'var(--font-size-sm)',
          }}
        >
          {showForm ? '× Cancel' : '+ Add Ontology'}
        </button>
      </div>

      {/* Inline add form */}
      {showForm && <AddOntologyForm onSuccess={handleAdded} />}

      {/* Table */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <thead>
            <tr style={{ background: 'var(--bg-secondary)' }}>
              {['Ontology', 'Version', 'Status', ''].map(h => (
                <th
                  key={h}
                  style={{
                    padding: '0.5rem 1rem',
                    textAlign: 'left',
                    fontSize: 'var(--font-size-sm)',
                    fontWeight: 600,
                    color: 'var(--text-dim)',
                    borderBottom: '1px solid var(--border)',
                    letterSpacing: '0.05em',
                    textTransform: 'uppercase',
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ontologies.map(o => (
              <OntologyRow key={o.id} ontology={o} />
            ))}
            {ontologies.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
                >
                  No ontologies yet. Use "+ Add Ontology" above to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
