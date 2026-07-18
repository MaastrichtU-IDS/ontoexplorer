import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, slugFromIri, type Ontology, type OntologyVersion, type ReasonerInfo } from '../lib/api'
import { useAuth } from '../hooks/useAuth'

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

// ── Group constants ───────────────────────────────────────────────────────────

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

const ALL_GROUPS = Object.keys(GROUP_LABELS)

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
    mutationFn: (name: string) => api.ontologies.patch(ontology.id, { shortname: name || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontologies'] }); setEditing(false); setError(null) },
    onError: (err: unknown) => { setError(err instanceof Error ? err.message : 'Failed to save') },
  })

  // Effective value shown on the public list page
  const effective = ontology.shortname ?? displayName(ontology)
  const isManual = !!ontology.shortname

  function open() { setValue(ontology.shortname ?? ''); setError(null); setEditing(true) }
  function commit() { save.mutate(value.trim()) }

  if (!editing) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
        <span style={{ fontSize: 'var(--font-size-sm)', color: isManual ? 'var(--text)' : 'var(--text-dim)', fontStyle: isManual ? 'normal' : 'italic' }}>
          {effective}
        </span>
        {!isManual && <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>(auto)</span>}
        <button onClick={open} title="Edit shortname" style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1 }}>✎</button>
      </span>
    )
  }

  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
      <span style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
        <input autoFocus value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          placeholder="my-ontology"
          style={{ fontSize: 'var(--font-size-sm)', padding: '0.15rem 0.4rem', width: '12rem' }} />
        <button onClick={commit} disabled={save.isPending} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent)' }}>
          {save.isPending ? '…' : 'save'}
        </button>
        <button onClick={() => setEditing(false)} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>cancel</button>
      </span>
      {error && <span style={{ fontSize: 'var(--font-size-sm)', color: '#f87171' }}>{error}</span>}
    </span>
  )
}

function TitleEditor({ ontology }: { ontology: Ontology }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(ontology.title ?? ontology.label ?? '')
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: (t: string) => api.ontologies.patch(ontology.id, { title: t || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontologies'] }); setEditing(false); setError(null) },
    onError: (err: unknown) => { setError(err instanceof Error ? err.message : 'Failed to save') },
  })

  // Effective value shown on the public list page
  const effective = ontology.label || null
  const isManual = !!ontology.title

  function open() { setValue(ontology.title ?? ontology.label ?? ''); setError(null); setEditing(true) }
  function commit() { save.mutate(value.trim()) }

  if (!editing) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 'var(--font-size-sm)', color: effective ? (isManual ? 'var(--text)' : 'var(--text-dim)') : 'var(--text-dim)', fontStyle: effective && !isManual ? 'italic' : 'normal' }}>
          {effective ?? '—'}
        </span>
        {effective && !isManual && <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>(auto)</span>}
        <button onClick={open} title="Edit title" style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1 }}>✎</button>
      </span>
    )
  }

  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
      <span style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
        <input autoFocus value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          placeholder="My Ontology"
          style={{ fontSize: 'var(--font-size-sm)', padding: '0.15rem 0.4rem', width: '18rem' }} />
        <button onClick={commit} disabled={save.isPending} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent)' }}>
          {save.isPending ? '…' : 'save'}
        </button>
        <button onClick={() => setEditing(false)} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>cancel</button>
      </span>
      {error && <span style={{ fontSize: 'var(--font-size-sm)', color: '#f87171' }}>{error}</span>}
    </span>
  )
}

function GroupsEditor({ ontology }: { ontology: Ontology }) {
  const [editing, setEditing] = useState(false)
  const [selected, setSelected] = useState<string[]>(ontology.groups ?? [])
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: (groups: string[]) => api.ontologies.patch(ontology.id, { groups }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontologies'] }); setEditing(false) },
  })

  function open() { setSelected(ontology.groups ?? []); setEditing(true) }

  const current = (ontology.groups ?? []).filter(g => g in GROUP_LABELS)

  if (!editing) {
    return (
      <span style={{ display: 'inline-flex', gap: '0.2rem', flexWrap: 'wrap', alignItems: 'center' }}>
        {current.length === 0
          ? <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>—</span>
          : current.map(g => {
              const c = GROUP_COLORS[g]
              return (
                <span key={g} style={{
                  fontSize: 9, padding: '1px 6px', borderRadius: 10,
                  background: c.bg, border: `1px solid ${c.border}`,
                  color: c.color, fontWeight: 600, letterSpacing: 0.3,
                }}>
                  {GROUP_LABELS[g]}
                </span>
              )
            })
        }
        <button onClick={open} title="Edit groups" style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1 }}>✎</button>
      </span>
    )
  }

  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <span style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', alignItems: 'center' }}>
        {ALL_GROUPS.map(g => {
          const on = selected.includes(g)
          const c = GROUP_COLORS[g]
          return (
            <button
              key={g}
              onClick={() => setSelected(s => on ? s.filter(x => x !== g) : [...s, g])}
              style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 10, cursor: 'pointer',
                background: on ? c.bg : 'transparent',
                border: `1px solid ${on ? c.border : 'var(--border)'}`,
                color: on ? c.color : 'var(--text-dim)',
                fontWeight: on ? 600 : 400, letterSpacing: 0.3,
              }}
            >
              {GROUP_LABELS[g]}
            </button>
          )
        })}
        <button onClick={() => save.mutate(selected)} disabled={save.isPending}
          style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent)' }}>
          {save.isPending ? '…' : 'save'}
        </button>
        <button onClick={() => setEditing(false)} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
          cancel
        </button>
      </span>
    </span>
  )
}

const FIELD_LABEL: React.CSSProperties = {
  fontSize: 'var(--font-size-sm)',
  color: 'var(--text-dim)',
  whiteSpace: 'nowrap',
  paddingTop: '0.05rem',
}

type CheckState = 'idle' | 'checking' | 'up_to_date' | 'update_queued' | 'no_source_url' | 'error'

function OntologyRow({ ontology }: { ontology: Ontology }) {
  const [confirming, setConfirming] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [checkState, setCheckState] = useState<CheckState>('idle')
  const { user } = useAuth()
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

  async function handleCheckUpdate() {
    setCheckState('checking')
    try {
      const result = await api.admin.checkUpdate(ontology.id)
      setCheckState(result.status as CheckState)
    } catch {
      setCheckState('error')
    }
  }

  const name = displayName(ontology)
  const s = statsData

  const statParts: string[] = []
  if (s?.triple_count != null)             statParts.push(`${fmtCount(s.triple_count)} axioms`)
  if (s?.class_count != null)              statParts.push(`${fmtCount(s.class_count)} classes`)
  if (s?.object_property_count != null)    statParts.push(`${fmtCount(s.object_property_count)} obj props`)
  if (s?.datatype_property_count != null)  statParts.push(`${fmtCount(s.datatype_property_count)} data props`)
  if (s?.annotation_property_count != null) statParts.push(`${fmtCount(s.annotation_property_count)} ann props`)
  if (s?.individual_count != null)         statParts.push(`${fmtCount(s.individual_count)} individuals`)

  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>

        {/* Two-column layout: content (left) · status + delete (right) */}
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>

          {/* Left: name, fields, date, stats, download */}
          <div style={{ flex: 1, minWidth: 0 }}>

            {/* Name + IRI chip */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
              <Link
                to={`/ontologies/${ontology.shortname ?? slugFromIri(ontology.iri)}`}
                style={{ color: 'var(--accent-blue)', fontSize: 'var(--font-size-base)', fontWeight: 600 }}
              >
                {name}
              </Link>
              <IriChip iri={ontology.iri} />
            </div>

            {/* Editable fields grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: '0.75rem', rowGap: '0.25rem', alignItems: 'start', marginBottom: '0.5rem' }}>
              <span style={FIELD_LABEL}>shortname</span>
              <ShortnameEditor ontology={ontology} />

              <span style={FIELD_LABEL}>title</span>
              <TitleEditor ontology={ontology} />

              <span style={FIELD_LABEL}>groups</span>
              <GroupsEditor ontology={ontology} />

              <span style={FIELD_LABEL}>version IRI</span>
              {latest?.version_iri ? (
                /^https?:\/\//.test(latest.version_iri) ? (
                  <a
                    href={latest.version_iri}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: 'var(--accent-blue)',
                      fontFamily: 'monospace',
                      fontSize: 'var(--font-size-sm)',
                      wordBreak: 'break-all',
                      textDecoration: 'none',
                    }}
                  >
                    {latest.version_iri}
                  </a>
                ) : (
                  <span style={{ fontFamily: 'monospace', fontSize: 'var(--font-size-sm)', color: 'var(--text)', wordBreak: 'break-all' }}>
                    {latest.version_iri}
                  </span>
                )
              ) : (
                <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>—</span>
              )}
            </div>

            {/* Date */}
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '0.2rem' }}>
              added {new Date(ontology.created_at).toLocaleDateString()}
            </div>

            {/* Stats */}
            {statParts.length > 0 && (
              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '0.5rem' }}>
                {statParts.join(' · ')}
              </div>
            )}

          </div>

          {/* Right: status + download + check update + delete */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.5rem', flexShrink: 0 }}>
            {latest && <StatusDot status={latest.status} />}
            {latest && (
              <a
                href={latest.download_url}
                download
                style={{
                  color: 'var(--accent-blue)', background: 'rgba(97,175,239,0.08)',
                  border: '1px solid rgba(97,175,239,0.3)',
                  borderRadius: 20, padding: '1px 10px',
                  fontSize: 'var(--font-size-sm)', fontWeight: 600, textDecoration: 'none',
                }}
              >
                ↓ {latest.format}
              </a>
            )}
            {user?.is_admin && (
              checkState === 'idle' || checkState === 'error' ? (
                <button
                  onClick={handleCheckUpdate}
                  style={{
                    color: checkState === 'error' ? '#f87171' : 'var(--text-dim)',
                    background: 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: 20, padding: '1px 10px',
                    fontSize: 'var(--font-size-sm)', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {checkState === 'error' ? '✕ retry check' : '↻ Check update'}
                </button>
              ) : checkState === 'checking' ? (
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>checking…</span>
              ) : checkState === 'up_to_date' ? (
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent-green, #3fb950)' }}>● up to date</span>
              ) : checkState === 'update_queued' ? (
                <span style={{ fontSize: 'var(--font-size-sm)', color: '#ffa657' }}>↑ update queued</span>
              ) : checkState === 'no_source_url' ? (
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>no source URL</span>
              ) : null
            )}
            {deleteError && (
              <span style={{ color: '#f87171', fontSize: 'var(--font-size-sm)', textAlign: 'right' }}>
                {deleteError}
              </span>
            )}
            {confirming ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontSize: 'var(--font-size-sm)' }}>
                <button onClick={() => del.mutate()} disabled={del.isPending}
                  style={{ color: '#fff', background: '#ef4444', border: 'none', borderRadius: 20, padding: '1px 10px', fontSize: 'var(--font-size-sm)', fontWeight: 600, cursor: 'pointer' }}>
                  {del.isPending ? '…' : 'yes'}
                </button>
                <button onClick={() => setConfirming(false)} disabled={del.isPending}
                  style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
                  no
                </button>
              </span>
            ) : (
              <button
                onClick={() => { setDeleteError(null); setConfirming(true) }}
                style={{
                  color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
                  borderRadius: 20, padding: '1px 10px', fontSize: 'var(--font-size-sm)', fontWeight: 600, cursor: 'pointer',
                }}
              >
                Delete
              </button>
            )}
          </div>

        </div>
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
]

function AddOntologyForm({ onSuccess }: { onSuccess: () => void }) {
  const [tab, setTab] = useState<AddTab>('iri')
  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [pasteContent, setPasteContent] = useState('')
  const [pasteFormat, setPasteFormat] = useState('turtle')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [reasoner, setReasoner] = useState<string | undefined>(undefined)

  const { data: reasonersData } = useQuery({
    queryKey: ['reasoners'],
    queryFn: () => api.reasoners.list(),
    enabled: showAdvanced,
    staleTime: 300_000,
  })
  const availableReasoners: ReasonerInfo[] = (reasonersData ?? []).filter(r => r.available)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      let result: { task_id: string }
      if (tab === 'iri') {
        result = await api.ontologies.submitByIri(value, reasoner)
      } else if (tab === 'url') {
        result = await api.ontologies.submitByUrl(value, reasoner)
      } else if (tab === 'upload') {
        if (!file) return
        result = await api.ontologies.submitFile(file, reasoner)
      } else {
        result = await api.ontologies.submitByContent(pasteContent, pasteFormat, reasoner)
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
              accept=".owl,.ttl,.rdf,.nt,.obo,.jsonld,.xml"
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
                Reasoner
                <select
                  value={reasoner ?? ''}
                  onChange={e => setReasoner(e.target.value || undefined)}
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
                  {availableReasoners.map(r => (
                    <option key={r.name} value={r.name}>{r.name}</option>
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

type SortCol = 'name' | 'date' | 'status'
type SortDir = 'asc' | 'desc'

const STATUS_RANK: Record<string, number> = { ready: 0, ingested: 1, indexing: 2, reasoning: 2, failed: 3 }

function sortOntologies(list: Ontology[], col: SortCol, dir: SortDir): Ontology[] {
  const sorted = [...list].sort((a, b) => {
    let cmp = 0
    if (col === 'name') {
      cmp = displayName(a).localeCompare(displayName(b))
    } else if (col === 'date') {
      cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    } else {
      const ra = STATUS_RANK[a.latest_version?.status ?? ''] ?? 4
      const rb = STATUS_RANK[b.latest_version?.status ?? ''] ?? 4
      cmp = ra - rb || displayName(a).localeCompare(displayName(b))
    }
    return dir === 'asc' ? cmp : -cmp
  })
  return sorted
}

export default function Dashboard() {
  const [showForm, setShowForm] = useState(false)
  const [search, setSearch] = useState('')
  const [sortCol, setSortCol] = useState<SortCol>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
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

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const all = data?.ontologies ?? []
  const q = search.trim().toLowerCase()
  const filtered = q
    ? all.filter(o =>
        (o.shortname ?? '').toLowerCase().includes(q) ||
        o.iri.toLowerCase().includes(q) ||
        (o.title ?? '').toLowerCase().includes(q) ||
        (o.label ?? '').toLowerCase().includes(q)
      )
    : all
  const ontologies = sortOntologies(filtered, sortCol, sortDir)

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
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

      {/* Search bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', padding: '6px 10px', marginBottom: '1rem',
      }}>
        <span style={{ color: 'var(--text-dim)' }}>⌕</span>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter by name, IRI, or title…"
          style={{ flex: 1, background: 'none', border: 'none', color: 'var(--text)', fontSize: 'var(--font-size-sm)', outline: 'none' }}
        />
        {search && (
          <button onClick={() => setSearch('')} style={{ color: 'var(--text-dim)', fontSize: 11, padding: '2px 4px' }}>✕</button>
        )}
      </div>

      {/* Sort bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginRight: '0.25rem' }}>Sort:</span>
        {(['name', 'date'] as SortCol[]).map(col => {
          const active = sortCol === col
          const arrow = active ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''
          return (
            <button
              key={col}
              onClick={() => handleSort(col)}
              style={{
                fontSize: 'var(--font-size-sm)',
                padding: '2px 8px', borderRadius: 4,
                border: '1px solid',
                borderColor: active ? 'var(--accent)' : 'var(--border)',
                color: active ? 'var(--accent)' : 'var(--text-dim)',
                background: active ? 'rgba(var(--accent-rgb, 97,175,239),0.08)' : 'transparent',
                cursor: 'pointer',
                fontWeight: active ? 600 : 400,
              }}
            >
              {col.charAt(0).toUpperCase() + col.slice(1)}{arrow}
            </button>
          )
        })}
      </div>

      {/* Inline add form */}
      {showForm && <AddOntologyForm onSuccess={handleAdded} />}

      {/* Table */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <tbody>
            {ontologies.map(o => (
              <OntologyRow key={o.id} ontology={o} />
            ))}
            {ontologies.length === 0 && (
              <tr>
                <td
                  colSpan={1}
                  style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
                >
                  {q ? 'No ontologies match your filter.' : 'No ontologies yet. Use "+ Add Ontology" above to get started.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
