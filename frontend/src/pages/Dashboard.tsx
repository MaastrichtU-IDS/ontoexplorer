import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, slugFromIri, type Ontology, type OntologyVersion, type OntologyDocumentMetadata } from '../lib/api'

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

// ── Display name (strip file extension) ──────────────────────────────────────

function displayName(ontology: Ontology): string {
  if (ontology.shortname) return ontology.shortname
  const last = ontology.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? ontology.iri
  return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
}

// ── Extract title from ontology document metadata ─────────────────────────────

const TITLE_PREDICATES = [
  'http://purl.org/dc/terms/title',
  'http://purl.org/dc/elements/1.1/title',
  'http://www.w3.org/2000/01/rdf-schema#label',
]

function extractTitle(metadata: OntologyDocumentMetadata | undefined): string | null {
  if (!metadata) return null
  for (const p of TITLE_PREDICATES) {
    const vals = metadata.predicates[p]
    if (vals && vals.length > 0) {
      const en = vals.find(v => v.language === 'en' || v.language === null)
      return (en ?? vals[0]).value
    }
  }
  return null
}

// ── Copyable IRI chip ─────────────────────────────────────────────────────────

function IriChip({ iri }: { iri: string }) {
  const [copied, setCopied] = useState(false)
  function copy(e: React.MouseEvent) {
    e.preventDefault()
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

// ── Single ontology row ───────────────────────────────────────────────────────

function ShortnameEditor({ ontology }: { ontology: Ontology }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(ontology.shortname ?? '')
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: (name: string) => api.ontologies.patch(ontology.id, name || null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ontologies'] })
      setEditing(false)
      setError(null)
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Failed to save')
    },
  })

  function commit() {
    const trimmed = value.trim()
    save.mutate(trimmed)
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setValue(ontology.shortname ?? ''); setError(null); setEditing(true) }}
        title="Edit shortname"
        style={{
          fontSize: 'var(--font-size-sm)',
          color: ontology.shortname ? 'var(--accent-blue)' : 'var(--text-dim)',
        }}
      >
        {ontology.shortname ?? '+ shortname'}
      </button>
    )
  }

  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
      <span style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
        <input
          autoFocus
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          placeholder="my-ontology"
          style={{ fontSize: 'var(--font-size-sm)', padding: '0.15rem 0.4rem', width: '12rem' }}
        />
        <button
          onClick={commit}
          disabled={save.isPending}
          style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent)' }}
        >
          {save.isPending ? '…' : 'save'}
        </button>
        <button
          onClick={() => setEditing(false)}
          style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}
        >
          cancel
        </button>
      </span>
      {error && <span style={{ fontSize: 'var(--font-size-sm)', color: '#f87171' }}>{error}</span>}
    </span>
  )
}

function OntologyRow({ ontology }: { ontology: Ontology }) {
  const [confirming, setConfirming] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const qc = useQueryClient()

  const { data: versionsData } = useQuery({
    queryKey: ['versions', ontology.id],
    queryFn: () => api.ontologies.versions(ontology.id),
  })

  const latest: OntologyVersion | undefined = versionsData?.versions[0]

  const { data: statsData } = useQuery({
    queryKey: ['version-stats', ontology.id, latest?.id],
    queryFn: () => api.ontologies.stats(ontology.id, latest!.id),
    enabled: !!latest,
    staleTime: 120_000,
  })

  const { data: metaData } = useQuery({
    queryKey: ['onto-doc-meta', ontology.id, latest?.id],
    queryFn: () => api.ontologies.ontologyMetadata(ontology.id, latest!.id),
    enabled: !!latest,
    staleTime: 300_000,
  })

  const del = useMutation({
    mutationFn: () => api.ontologies.delete(ontology.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ontologies'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err: unknown) => {
      setConfirming(false)
      setDeleteError(err instanceof Error ? err.message : 'Delete failed')
    },
  })

  const name = displayName(ontology)
  const title = extractTitle(metaData)
  const showTitle = title && title.toLowerCase() !== name.toLowerCase()

  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      {/* Name + title + IRI + shortname + stats */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top' }}>
        <Link
          to={`/ontologies/${ontology.shortname ?? slugFromIri(ontology.iri)}`}
          style={{ color: 'var(--accent-blue)', fontSize: 'var(--font-size-base)', display: 'block', fontWeight: 500 }}
        >
          {name}
        </Link>
        {showTitle && (
          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', display: 'block' }}>
            {title}
          </span>
        )}
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.2rem', flexWrap: 'wrap' }}>
          <IriChip iri={ontology.iri} />
          <ShortnameEditor ontology={ontology} />
        </span>
        <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', display: 'block', marginTop: '0.2rem' }}>
          added {new Date(ontology.created_at).toLocaleDateString()}
          {statsData?.class_count != null && ` · ${fmtCount(statsData.class_count)} classes`}
          {statsData?.property_count != null && ` · ${fmtCount(statsData.property_count)} props`}
          {statsData?.triple_count != null && ` · ${fmtCount(statsData.triple_count)} axioms`}
        </span>
      </td>

      {/* Status */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        {latest ? <StatusDot status={latest.status} /> : <span style={{ color: 'var(--text-dim)' }}>—</span>}
      </td>

      {/* Actions */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        <Link
          to={`/ontologies/${ontology.shortname ?? slugFromIri(ontology.iri)}`}
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
              {del.isPending ? '…' : 'yes'}
            </button>
            <button
              onClick={() => setConfirming(false)}
              disabled={del.isPending}
              style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
            >
              no
            </button>
          </span>
        ) : (
          <button
            onClick={() => { setDeleteError(null); setConfirming(true) }}
            style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            delete
          </button>
        )}
        {deleteError && (
          <span style={{ display: 'block', color: '#f87171', fontSize: 'var(--font-size-sm)', marginTop: '0.25rem' }}>
            {deleteError}
          </span>
        )}
      </td>
    </tr>
  )
}

// ── Add-ontology inline form ──────────────────────────────────────────────────

type AddTab = 'iri' | 'url' | 'upload' | 'paste'

const FORMATS = [
  { value: 'turtle',      label: 'Turtle (.ttl)' },
  { value: 'rdf',         label: 'RDF/XML (.rdf, .owl)' },
  { value: 'n-triples',   label: 'N-Triples (.nt)' },
  { value: 'json-ld',     label: 'JSON-LD (.jsonld)' },
  { value: 'obo',         label: 'OBO (.obo)' },
  { value: 'manchester',  label: 'Manchester (.omn)' },
]

function AddOntologyForm({ onSuccess }: { onSuccess: () => void }) {
  const [tab, setTab] = useState<AddTab>('iri')
  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [pasteContent, setPasteContent] = useState('')
  const [pasteFormat, setPasteFormat] = useState('turtle')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      let result: { task_id: string }
      if (tab === 'iri') {
        result = await api.ontologies.submitByIri(value)
      } else if (tab === 'url') {
        result = await api.ontologies.submitByUrl(value)
      } else if (tab === 'upload') {
        if (!file) return
        result = await api.ontologies.submitFile(file)
      } else {
        result = await api.ontologies.submitByContent(pasteContent, pasteFormat)
      }
      setMessage(`Queued — task ID: ${result.task_id}`)
      setValue('')
      setFile(null)
      setPasteContent('')
      setTimeout(onSuccess, 2000)
    } catch (err: unknown) {
      setMessage(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const tabs: { key: AddTab; label: string }[] = [
    { key: 'iri',    label: 'By IRI' },
    { key: 'url',    label: 'By URL' },
    { key: 'upload', label: 'Upload file' },
    { key: 'paste',  label: 'Paste RDF' },
  ]

  const submitDisabled = submitting
    || (tab === 'upload' && !file)
    || (tab === 'paste' && !pasteContent.trim())

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
            onClick={() => { setTab(key); setMessage(null) }}
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

      <form onSubmit={handleSubmit}>
        {(tab === 'iri' || tab === 'url') && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder={tab === 'iri' ? 'https://purl.obolibrary.org/obo/go.owl' : 'https://example.com/ontology.ttl'}
              style={{ flex: 1 }}
              required
            />
          </div>
        )}

        {tab === 'upload' && (
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <input
              type="file"
              accept=".owl,.ttl,.rdf,.nt,.obo,.jsonld,.omn,.xml"
              onChange={e => setFile(e.target.files?.[0] ?? null)}
              style={{ flex: 1, fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}
              required
            />
          </div>
        )}

        {tab === 'paste' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>Format:</span>
              <select
                value={pasteFormat}
                onChange={e => setPasteFormat(e.target.value)}
                style={{ fontSize: 'var(--font-size-sm)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '0.2rem 0.4rem', color: 'var(--text)' }}
              >
                {FORMATS.map(f => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>
            <textarea
              value={pasteContent}
              onChange={e => setPasteContent(e.target.value)}
              placeholder={`Paste your RDF content here…`}
              rows={6}
              style={{ resize: 'vertical', fontSize: 'var(--font-size-sm)', fontFamily: 'monospace', color: 'var(--text)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '0.5rem', width: '100%', boxSizing: 'border-box' }}
              required
            />
          </div>
        )}

        <div style={{ marginTop: '0.5rem' }}>
          <button
            type="submit"
            disabled={submitDisabled}
            style={{
              padding: '0.4rem 0.9rem',
              background: 'var(--accent)',
              color: '#0f172a',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 700,
              fontSize: 'var(--font-size-sm)',
              opacity: submitDisabled ? 0.5 : 1,
            }}
          >
            {submitting ? 'Adding…' : 'Add'}
          </button>
        </div>
      </form>

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
    qc.invalidateQueries({ queryKey: ['stats'] })
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
              {['Ontology', 'Status', ''].map(h => (
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
                  colSpan={3}
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
