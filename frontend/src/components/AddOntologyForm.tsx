import { useQuery } from '@tanstack/react-query'
import React, { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

const INGEST_POLL_MS = 1500
const INGEST_TRACK_TIMEOUT_MS = 30 * 60_000

type AddTab = 'iri' | 'upload' | 'paste'

// Values are OntologyFormat keys, sent as `format` and resolved server-side by
// parse_format. '' means auto-detect, which handles almost everything — the
// explicit choices are the fallback for content the sniffer can't place.
const FORMATS = [
  { value: '',      label: 'Auto-detect' },
  { value: 'ttl',    label: 'Turtle (.ttl)' },
  { value: 'rdf',    label: 'RDF/XML (.rdf, .owl)' },
  { value: 'nt',     label: 'N-Triples (.nt)' },
  { value: 'nq',     label: 'N-Quads (.nq)' },
  { value: 'trig',   label: 'TriG (.trig)' },
  { value: 'jsonld', label: 'JSON-LD (.jsonld)' },
  { value: 'obo',    label: 'OBO (.obo)' },
  { value: 'omn',    label: 'Manchester (.omn)' },
  { value: 'ofn',    label: 'Functional (.ofn)' },
]

/**
 * The add-ontology form. `onSuccess` fires once ingestion completes (the inline
 * poll path). `onQueued` is optional: when provided, it fires the moment the
 * submission is accepted (with its task id), so a caller can hand off to the
 * durable submission record instead of polling inline — the dedicated /dashboard/add
 * page does this.
 */
export default function AddOntologyForm(
  { onSuccess, onQueued }: { onSuccess: () => void; onQueued?: (taskId: string) => void },
) {
  const [tab, setTab] = useState<AddTab>('iri')
  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [pasteContent, setPasteContent] = useState('')
  // Shared by the upload and paste tabs: '' = auto-detect, otherwise an
  // explicit OntologyFormat key that bypasses server-side detection.
  const [formatOverride, setFormatOverride] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  // Tone is set explicitly at each call site rather than sniffed from the text:
  // the failure message is the server's error verbatim, so its wording is not
  // ours to pattern-match on.
  const [messageTone, setMessageTone] = useState<'info' | 'error'>('info')
  const say = (text: string, tone: 'info' | 'error' = 'info') => {
    setMessage(text)
    setMessageTone(tone)
  }
  // Stops the ingestion poll from setting state after the form unmounts.
  const cancelled = useRef(false)
  useEffect(() => {
    cancelled.current = false
    return () => { cancelled.current = true }
  }, [])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [profileId, setProfileId] = useState<string | undefined>(undefined)

  const { data: profilesData } = useQuery({
    queryKey: ['reasoner-profiles'],
    queryFn: () => api.reasonerProfiles.list(),
    enabled: showAdvanced,
    staleTime: 300_000,
  })
  const profiles = profilesData?.profiles ?? []

  // Reasoner catalog carries backend version strings; map reasoner name -> version
  // so each profile option can show which reasoner build it runs on.
  const { data: reasonerCatalog } = useQuery({
    queryKey: ['reasoners'],
    queryFn: () => api.reasoners.list(),
    enabled: showAdvanced,
    staleTime: 300_000,
  })
  const reasonerVersion = (name: string) =>
    reasonerCatalog?.find(r => r.name === name)?.version || ''

  // Ingestion runs in a Celery worker, so POST /ontologies only queues it. The
  // returned task_id is also the ingestion job's id, so poll GET /jobs/{id} for
  // the outcome — a submission that fails before any version exists (unreachable
  // IRI, source over the download cap, unparseable file) otherwise reported
  // nothing but "queued" while the real error sat in the worker log.
  async function trackIngestion(taskId: string) {
    // Generous ceiling: ingesting a multi-hundred-MB ontology is slow, and
    // Celery retries a failed attempt three times a minute apart.
    const deadline = Date.now() + INGEST_TRACK_TIMEOUT_MS
    while (!cancelled.current && Date.now() < deadline) {
      try {
        const job = await api.jobs.get(taskId)
        if (job.status === 'failed') {
          say(`Failed: ${job.error ?? 'ingestion failed — see the jobs log'}`, 'error')
          return
        }
        if (job.status === 'done') {
          say('Ingested — refreshing…')
          onSuccess()
          return
        }
        say(`Ingesting… (task ${taskId})`)
      } catch {
        // 404 until the worker picks the task up and writes the row — keep waiting.
      }
      await new Promise((r) => setTimeout(r, INGEST_POLL_MS))
    }
    if (!cancelled.current) {
      say(`Still running — track task ${taskId} in the jobs log`)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    setMessageTone('info')
    let taskId: string | null = null
    try {
      let result: { task_id: string }
      if (tab === 'iri') {
        // One path for both: resolve_iri content-negotiates and follows
        // redirects, and a direct file URL resolves through it unchanged
        // because static servers ignore the Accept header.
        result = await api.ontologies.submitByIri(value, profileId)
      } else if (tab === 'upload') {
        if (!file) return
        result = await api.ontologies.submitFile(file, profileId, formatOverride)
      } else {
        result = await api.ontologies.submitByContent(pasteContent, formatOverride, profileId)
      }
      taskId = result.task_id
      say(`Queued — task ID: ${result.task_id}`)
      setValue('')
      setFile(null)
      setPasteContent('')
    } catch (err: unknown) {
      say(`Error: ${err instanceof Error ? err.message : String(err)}`, 'error')
    } finally {
      setSubmitting(false)
    }
    // Hand off to the durable submission record if the caller wants it; otherwise
    // fall back to the inline poll.
    if (taskId) {
      if (onQueued) onQueued(taskId)
      else await trackIngestion(taskId)
    }
  }

  const tabs: { key: AddTab; label: string }[] = [
    { key: 'iri',    label: 'By IRI or URL' },
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
              color: tab === key ? 'var(--bg)' : 'var(--text-muted)',
              fontWeight: tab === key ? 700 : 400,
              fontSize: 'var(--font-size-sm)',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit}>
        {tab === 'iri' && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              value={value}
              onChange={e => setValue(e.target.value)}
              aria-label="Ontology IRI or URL"
              style={{ flex: 1 }}
              required
            />
          </div>
        )}

        {tab === 'upload' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <input
                type="file"
                accept=".owl,.ttl,.turtle,.rdf,.xml,.nt,.nq,.trig,.jsonld,.json,.obo,.omn,.ofn"
                onChange={e => setFile(e.target.files?.[0] ?? null)}
                style={{ flex: 1, fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}
                required
              />
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              {/* Auto-detect reads the file extension first, so this is only
                  needed for a misnamed or extension-less file. */}
              <label htmlFor="upload-format" style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>Format:</label>
              <select
                id="upload-format"
                value={formatOverride}
                onChange={e => setFormatOverride(e.target.value)}
                style={{ fontSize: 'var(--font-size-sm)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '0.2rem 0.4rem', color: 'var(--text)' }}
              >
                {FORMATS.map(f => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {tab === 'paste' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <label htmlFor="paste-format" style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>Format:</label>
              <select
                id="paste-format"
                value={formatOverride}
                onChange={e => setFormatOverride(e.target.value)}
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
            type="button"
            onClick={() => setShowAdvanced(v => !v)}
            style={{
              fontSize: 'var(--font-size-sm)',
              color: 'var(--text-dim)',
              background: 'transparent',
              padding: 0,
            }}
          >
            {`${showAdvanced ? '▾' : '▸'} Advanced`}
          </button>

          {showAdvanced && (
            <div style={{ marginTop: '0.4rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
                Reasoner profile
                <select
                  value={profileId ?? ''}
                  onChange={e => setProfileId(e.target.value || undefined)}
                  style={{
                    fontSize: 'var(--font-size-sm)',
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '0.2rem 0.4rem',
                    color: 'var(--text)',
                  }}
                >
                  <option value="">(default)</option>
                  {profiles.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {` — ${p.reasoner}`}
                      {reasonerVersion(p.reasoner) ? ` ${reasonerVersion(p.reasoner)}` : ''}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </div>

        <div style={{ marginTop: '0.5rem' }}>
          <button
            type="submit"
            disabled={submitDisabled}
            style={{
              padding: '0.4rem 0.9rem',
              background: 'var(--accent)',
              color: 'var(--bg)',
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
          color: messageTone === 'error' ? 'var(--red-soft)' : 'var(--accent)',
        }}>
          {message}
        </p>
      )}
    </div>
  )
}
