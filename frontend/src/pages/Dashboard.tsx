import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, slugFromIri, type Ontology, type OntologyVersion } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import ReindexWithReasoner from '../components/ReindexWithReasoner'
import ResolvableBadge from '../components/ResolvableBadge'
import { useIsMobile } from '../hooks/useIsMobile'
import { useOntologiesInfinite } from '../hooks/useOntologiesInfinite'
import { versionLabel, compareVersionsDesc } from '../lib/versions'

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
  obo:         'OBO Foundry',
  bioportal:   'BioPortal',
  lov:         'LOV',
}

const GROUP_COLORS: Record<string, { bg: string; border: string; color: string }> = {
  upper:       { bg: 'rgba(97,175,239,0.12)',  border: 'rgba(97,175,239,0.4)',  color: 'var(--od-blue)' },
  sulo_family: { bg: 'rgba(229,192,123,0.12)', border: 'rgba(229,192,123,0.4)', color: 'var(--od-yellow)' },
  obo:         { bg: 'rgba(152,195,121,0.12)', border: 'rgba(152,195,121,0.4)', color: 'var(--od-green)' },
  bioportal:   { bg: 'rgba(86,182,194,0.12)',  border: 'rgba(86,182,194,0.4)',  color: 'var(--od-cyan)' },
  lov:         { bg: 'rgba(240,136,62,0.12)',  border: 'rgba(240,136,62,0.4)',  color: 'var(--orange)' },
}

// Derived chip styling for content-property chips (SKOS), computed from the live
// stats rather than an editable group tag — so they never drift.
const SKOS_CHIP = { bg: 'rgba(198,120,221,0.12)', border: 'rgba(198,120,221,0.4)', color: 'var(--od-purple)' }

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
        {current.map(g => {
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
        })}
        {/* Derived content-property chips — computed from live stats, NOT editable
            group tags, so they never drift. SKOS = has skos:Concept terms
            (concept_count > 0); Resolvable = the live resolvable column. */}
        {(ontology.concept_count ?? 0) > 0 && (
          <span style={{
            fontSize: 9, padding: '1px 6px', borderRadius: 10,
            background: SKOS_CHIP.bg, border: `1px solid ${SKOS_CHIP.border}`,
            color: SKOS_CHIP.color, fontWeight: 600, letterSpacing: 0.3,
          }}>SKOS</span>
        )}
        <ResolvableBadge resolvable={ontology.resolvable} checkedAt={ontology.resolve_checked_at} />
        {current.length === 0 && ontology.resolvable !== true && (ontology.concept_count ?? 0) === 0 && (
          <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>—</span>
        )}
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

// `versionLabel` now lives in ../lib/versions (shared with the admin table and
// cross-compare pickers) so a versionless IRI like `…/sio-release.owl` no longer
// renders as the uninformative "sio-release.owl".

// A clean version/date token from a versionIRI string (for the update badge).
function shortVersion(versionIri?: string | null): string {
  if (!versionIri) return ''
  const seg = versionIri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? versionIri
  const m = seg.match(/\d{4}-\d{2}-\d{2}/) ?? seg.match(/\d+(?:\.\d+)+/)
  return m ? m[0] : seg
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
        {ready.map(v => (
          <option key={v.id} value={v.id}>
            {versionLabel(v, { isDefault: v.id === ontology.current_version_id })}
          </option>
        ))}
      </select>
      {value === '' && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>auto</span>}
      {error && <span style={{ color: 'var(--error)', fontSize: 11 }}>{error}</span>}
    </div>
  )
}

// Collapsible per-version management: deprecate (soft, reversible) or delete
// (hard, irreversible) each version. Gated server-side by ontology-edit rights
// (owner/maintainer/admin). Delete is blocked for the only version — delete the
// ontology instead.
function VersionManager({ ontology, versions }: { ontology: Ontology; versions: OntologyVersion[] }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['versions', ontology.id] })
    qc.invalidateQueries({ queryKey: ['ontologies'] })
  }
  const deprecate = useMutation({
    mutationFn: (vid: string) => api.ontologies.deprecateVersion(ontology.id, vid),
    onSuccess: () => { invalidate(); setError(null) },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : 'Deprecate failed'),
  })
  const del = useMutation({
    mutationFn: (vid: string) => api.ontologies.deleteVersion(ontology.id, vid),
    onSuccess: () => { invalidate(); setConfirmId(null); setError(null) },
    onError: (e: unknown) => { setConfirmId(null); setError(e instanceof Error ? e.message : 'Delete failed') },
  })

  if (versions.length === 0) {
    return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>—</span>
  }
  const onlyOne = versions.length <= 1
  const sorted = [...versions].sort(compareVersionsDesc)
  const linkBtn: React.CSSProperties = {
    background: 'transparent', border: 'none', color: 'var(--text-dim)',
    fontSize: 'var(--font-size-sm)', cursor: 'pointer', padding: 0, textAlign: 'left',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', minWidth: 0 }}>
      <button onClick={() => setOpen(o => !o)} style={linkBtn}>
        {open ? '▾' : '▸'} {versions.length} version{versions.length === 1 ? '' : 's'}
      </button>
      {error && <span style={{ color: 'var(--red-soft)', fontSize: 11 }}>{error}</span>}
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
          {sorted.map(v => (
            <div key={v.id} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap', fontSize: 'var(--font-size-sm)' }}>
              <StatusDot status={v.status} />
              <span style={{ color: 'var(--text)' }}>{versionLabel(v, { isDefault: v.is_default })}</span>
              {v.status !== 'deprecated' && (
                <button
                  onClick={() => deprecate.mutate(v.id)}
                  disabled={deprecate.isPending}
                  title="Hide this version from default selection and diffs (reversible)"
                  style={{ ...linkBtn, color: 'var(--orange)' }}
                >
                  deprecate
                </button>
              )}
              {confirmId === v.id ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                  <button onClick={() => del.mutate(v.id)} disabled={del.isPending}
                    style={{ color: '#fff', background: 'var(--red)', border: 'none', borderRadius: 20, padding: '1px 10px', fontSize: 'var(--font-size-sm)', fontWeight: 600, cursor: 'pointer' }}>
                    {del.isPending ? '…' : 'delete permanently'}
                  </button>
                  <button onClick={() => setConfirmId(null)} disabled={del.isPending} style={linkBtn}>no</button>
                </span>
              ) : (
                <button
                  onClick={() => { setError(null); setConfirmId(v.id) }}
                  disabled={onlyOne}
                  title={onlyOne ? 'This is the only version — delete the ontology instead' : 'Permanently delete this version and all its data (irreversible)'}
                  style={{
                    color: 'var(--red)', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
                    borderRadius: 20, padding: '0 8px', fontSize: 'var(--font-size-sm)', fontWeight: 600,
                    cursor: onlyOne ? 'not-allowed' : 'pointer', opacity: onlyOne ? 0.5 : 1,
                  }}
                >
                  delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function OntologyRow({ ontology }: { ontology: Ontology }) {
  const isMobile = useIsMobile()
  const [confirming, setConfirming] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [checkState, setCheckState] = useState<CheckState>('idle')
  const { user } = useAuth()
  const qc = useQueryClient()

  const { data: versionsData } = useQuery({
    queryKey: ['versions', ontology.id],
    queryFn: () => api.ontologies.versions(ontology.id),
  })

  // Show the version-aware DEFAULT version (highest version_iri / pinned), not the
  // newest-ingested row — a later ingest of an older snapshot must not appear as
  // "current". The backend marks it with is_default; fall back to [0] if absent.
  const versions = versionsData?.versions
  const latest: OntologyVersion | undefined =
    versions?.find(v => v.is_default) ?? versions?.[0]

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
  if (s?.concept_count != null)            statParts.push(`${fmtCount(s.concept_count)} concepts`)

  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>

        {/* Two-column layout: content (left) · status + delete (right) */}
        <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? '0.6rem' : '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>

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

              <span style={FIELD_LABEL}>versions</span>
              <VersionManager ontology={ontology} versions={versionsData?.versions ?? []} />

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

              {ontology.update_available && (
                <>
                  <span style={FIELD_LABEL}>update</span>
                  <span
                    title="A newer release is available at the ontology's IRI. Use Check update to ingest it (or enable auto-sync)."
                    style={{
                      display: 'inline-block', padding: '0.05rem 0.4rem', borderRadius: 4,
                      background: 'rgba(230,160,30,0.14)', color: 'var(--text)',
                      fontSize: 'var(--font-size-sm)', fontFamily: 'monospace', width: 'fit-content',
                    }}
                  >
                    {'update available'}
                    {shortVersion(ontology.update_detail?.detected_version) &&
                      ` → ${shortVersion(ontology.update_detail?.detected_version)}`}
                  </span>
                </>
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
          <div style={{ display: 'flex', flexDirection: isMobile ? 'row' : 'column', flexWrap: 'wrap', alignItems: 'center', justifyContent: isMobile ? 'flex-start' : undefined, gap: '0.5rem', flexShrink: 0, alignSelf: isMobile ? 'stretch' : undefined }}>
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

// ── Dashboard page ────────────────────────────────────────────────────────────

type SortCol = 'name' | 'date'
type SortDir = 'asc' | 'desc'

export default function Dashboard() {
  const [search, setSearch] = useState('')
  const [sortCol, setSortCol] = useState<SortCol>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  // Server-authoritative list, scoped to the caller's owned/maintained set and
  // paginated on scroll — a prolific owner can have thousands of ontologies, so a
  // single capped fetch both truncated browse and hid matches past the cap. The
  // server owns the filter (`q`, relevance-ranked) and the name/date sort, so
  // there is no client-side re-sort to desync. Adding now happens on /dashboard/add
  // and lands on the submission record, so the list just refetches on return.
  const { ontologies, total, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useOntologiesInfinite({
      query: search,
      sort: sortCol,
      dir: sortDir,
      langs: [],
      mine: true,
    })

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const q = search.trim()

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>My Ontologies</h1>
        <Link
          to="/dashboard/add"
          style={{
            padding: '0.35rem 0.8rem',
            background: 'var(--accent)',
            color: 'var(--bg)',
            border: 'none',
            borderRadius: 'var(--radius-sm)',
            fontWeight: 600,
            fontSize: 'var(--font-size-sm)',
            textDecoration: 'none',
          }}
        >
          + Add Ontology
        </Link>
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
                  {q ? 'No ontologies match your filter.' : 'No ontologies yet. Use "+ Add Ontology" to get started.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {/* Pagination: load the next server page on demand. A prolific owner's full
          set is reachable here instead of being capped at the first page. */}
      {!isLoading && ontologies.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginTop: '0.75rem' }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            Showing {ontologies.length}{typeof total === 'number' ? ` of ${total.toLocaleString()}` : ''}
          </span>
          {hasNextPage && (
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              style={{
                padding: '0.3rem 0.9rem', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)', color: 'var(--text)', cursor: isFetchingNextPage ? 'default' : 'pointer',
                fontSize: 'var(--font-size-sm)',
              }}
            >
              {isFetchingNextPage ? 'Loading…' : 'Load more'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
