import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, slugFromIri, type Ontology, type OntologyVersion } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import ReindexWithReasoner from '../components/ReindexWithReasoner'

const INGEST_POLL_MS = 1500
const INGEST_TRACK_TIMEOUT_MS = 30 * 60_000

// ── Status dot ────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ready:      'var(--accent)',
  ingested:   'var(--text-muted)',
  reasoning:  'var(--accent-purple)',
  indexing:   'var(--accent-purple)',
  deprecated: 'var(--text-dim)',
  failed:     'var(--red-soft)',
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
  upper:       { bg: 'rgba(97,175,239,0.12)',  border: 'rgba(97,175,239,0.4)',  color: 'var(--od-blue)' },
  sulo_family: { bg: 'rgba(229,192,123,0.12)', border: 'rgba(229,192,123,0.4)', color: 'var(--od-yellow)' },
  metadata:    { bg: 'rgba(198,120,221,0.12)', border: 'rgba(198,120,221,0.4)', color: 'var(--od-purple)' },
  obo:         { bg: 'rgba(152,195,121,0.12)', border: 'rgba(152,195,121,0.4)', color: 'var(--od-green)' },
  biomedical:  { bg: 'rgba(224,108,117,0.12)', border: 'rgba(224,108,117,0.4)', color: 'var(--error)' },
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
      <span style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <input autoFocus value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          placeholder="my-ontology"
          style={{ fontSize: 'var(--font-size-sm)', padding: '0.15rem 0.4rem', width: '100%', maxWidth: '12rem' }} />
        <button onClick={commit} disabled={save.isPending} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent)' }}>
          {save.isPending ? '…' : 'save'}
        </button>
        <button onClick={() => setEditing(false)} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>cancel</button>
      </span>
      {error && <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--red-soft)' }}>{error}</span>}
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
      <span style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <input autoFocus value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          placeholder="My Ontology"
          style={{ fontSize: 'var(--font-size-sm)', padding: '0.15rem 0.4rem', width: '100%', maxWidth: '18rem' }} />
        <button onClick={commit} disabled={save.isPending} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--accent)' }}>
          {save.isPending ? '…' : 'save'}
        </button>
        <button onClick={() => setEditing(false)} style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>cancel</button>
      </span>
      {error && <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--red-soft)' }}>{error}</span>}
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

function versionLabel(v: OntologyVersion): string {
  const seg = v.version_iri ? (v.version_iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? v.version_iri) : ''
  // Prefer a clean version/date token (e.g. "0.2.14", "2024-05-01").
  const m = seg.match(/\d{4}-\d{2}-\d{2}/) ?? seg.match(/\d+(?:\.\d+)+/)
  return m ? m[0] : (seg || v.id.slice(0, 8))
}

// Pick which version is the ontology's default ("latest"). Empty = automatic
// (version-aware) selection; a specific version pins it. Reuses PATCH, so an
// ontology owner/maintainer can set it (no admin needed).
function DefaultVersionEditor({ ontology, versions }: { ontology: Ontology; versions: OntologyVersion[] }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const ready = versions.filter(v => !['pending', 'failed', 'deprecated'].includes(v.status))
  const mut = useMutation({
    mutationFn: (cvid: string | null) => api.ontologies.patch(ontology.id, { current_version_id: cvid }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ontologies'] }); setError(null) },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : 'Update failed'),
  })
  if (ready.length <= 1) {
    return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>—</span>
  }
  const value = ontology.current_version_id ?? ''
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <select
        value={value}
        onChange={e => mut.mutate(e.target.value || null)}
        disabled={mut.isPending}
        style={{ fontSize: 'var(--font-size-sm)', background: 'var(--bg-secondary)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px', maxWidth: '100%' }}
      >
        <option value="">Automatic (latest by version)</option>
        {ready.map(v => <option key={v.id} value={v.id}>{versionLabel(v)}</option>)}
      </select>
      {value === '' && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>auto</span>}
      {error && <span style={{ color: 'var(--error)', fontSize: 11 }}>{error}</span>}
    </div>
  )
}

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
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>

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

              <span style={FIELD_LABEL}>default version</span>
              <DefaultVersionEditor ontology={ontology} versions={versionsData?.versions ?? []} />

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
            {latest && (
              <ReindexWithReasoner
                ontologyId={ontology.id}
                versionId={latest.id}
                currentProfileId={latest.reasoner_profile_id}
                onQueued={() => {
                  qc.invalidateQueries({ queryKey: ['versions', ontology.id] })
                  qc.invalidateQueries({ queryKey: ['version-stats', ontology.id, latest.id] })
                }}
              />
            )}
            {user?.is_admin && (
              checkState === 'idle' || checkState === 'error' ? (
                <button
                  onClick={handleCheckUpdate}
                  style={{
                    color: checkState === 'error' ? 'var(--red-soft)' : 'var(--text-dim)',
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
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--green)' }}>● up to date</span>
              ) : checkState === 'update_queued' ? (
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--orange)' }}>↑ update queued</span>
              ) : checkState === 'no_source_url' ? (
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>no source URL</span>
              ) : null
            )}
            {deleteError && (
              <span style={{ color: 'var(--red-soft)', fontSize: 'var(--font-size-sm)', textAlign: 'right' }}>
                {deleteError}
              </span>
            )}
            {confirming ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontSize: 'var(--font-size-sm)' }}>
                <button onClick={() => del.mutate()} disabled={del.isPending}
                  style={{ color: '#fff', background: 'var(--red)', border: 'none', borderRadius: 20, padding: '1px 10px', fontSize: 'var(--font-size-sm)', fontWeight: 600, cursor: 'pointer' }}>
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
                  color: 'var(--red)', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
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

function AddOntologyForm({ onSuccess }: { onSuccess: () => void }) {
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
    if (taskId) await trackIngestion(taskId)
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
                    <option key={p.id} value={p.id}>{p.name}</option>
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
  // After an upload, ingestion runs asynchronously in a worker and creates the
  // ontology row ~10-30s later. Poll the list until this timestamp so the new
  // ontology appears without a manual refresh.
  const [pollUntil, setPollUntil] = useState(0)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['ontologies', 'mine'],
    // "My Ontologies" = owned or maintained (distinct from the global catalog
    // cache under ['ontologies'] used by search/OntologyPage).
    queryFn: () => api.ontologies.list(0, 200, undefined, undefined, undefined, undefined, true),
    refetchInterval: () => (Date.now() < pollUntil ? 4000 : false),
  })

  function handleAdded() {
    // Ingestion is async — keep refetching for ~90s so the new ontology shows
    // up on its own once the worker finishes (covers all but very large loads).
    setPollUntil(Date.now() + 90_000)
    qc.invalidateQueries({ queryKey: ['ontologies', 'mine'] })
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
            color: showForm ? 'var(--text-muted)' : 'var(--bg)',
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
