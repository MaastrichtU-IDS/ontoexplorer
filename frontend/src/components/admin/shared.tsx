import React, { useState } from 'react'
import { AdminOntologyEntry, AdminVersionEntry } from '../../lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

export type UpdateState = 'idle' | 'queued' | 'error'

// ── Formatters ────────────────────────────────────────────────────────────────

export function fmtTriples(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

export function fmtAge(iso: string | null): string {
  if (!iso) return '—'
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

export function fmtDuration(started: string | null, finished: string | null): string {
  if (!started) return '—'
  const end = finished ? new Date(finished).getTime() : Date.now()
  const secs = Math.floor((end - new Date(started).getTime()) / 1000)
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

export function ontologyDisplayName(row: AdminOntologyEntry): string {
  return row.shortname
    || row.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
    || row.iri
}

// ── Shared colors ─────────────────────────────────────────────────────────────

export const JOB_TYPE_COLOR: Record<string, string> = {
  ingest: '#d2a8ff',
  ingestion: '#d2a8ff',
  index: '#79c0ff',
  indexing: '#79c0ff',
  reason: '#56d364',
  reasoning: '#56d364',
  embedding: '#ffa657',
}

// ── Status badges ─────────────────────────────────────────────────────────────

export function StatusDot({ status, label }: { status: string; label?: string }) {
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

export function DiffStatusBadge({ status }: { status: AdminVersionEntry['diff_vs_prev']['status'] }) {
  const text = status === 'missing' ? 'none' : status
  if (status === 'ready')   return <span style={{ color: 'var(--accent-green, #3fb950)', fontSize: 11 }}>● {text}</span>
  if (status === 'running' || status === 'pending') return <span style={{ color: '#58a6ff', fontSize: 11 }}>⟳ {text}</span>
  if (status === 'failed')  return <span style={{ color: '#f85149', fontSize: 11 }}>✕ {text}</span>
  if (status === 'stale')   return <span style={{ color: '#d29922', fontSize: 11 }}>↻ {text}</span>
  return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>— {text}</span>
}

export function diffActionLabelFor(status: AdminVersionEntry['diff_vs_prev']['status']): string {
  if (status === 'failed') return '✕ retry'
  if (status === 'stale')  return '↻ refresh'
  return '⚖ diff'
}

// ── Page layout primitives ────────────────────────────────────────────────────

export function SectionLabel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase',
      letterSpacing: '.8px', marginBottom: 6, ...style,
    }}>
      {children}
    </div>
  )
}

export function ServiceCard({
  name,
  status,
  description,
}: {
  name: string
  status: string | number
  description?: string
}) {
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
      <div
        title={description}
        style={{
          color: 'var(--text-dim)', fontSize: 10,
          textTransform: 'uppercase', letterSpacing: .5,
          cursor: description ? 'help' : undefined,
        }}
      >
        {name}
      </div>
    </div>
  )
}

// ── Action button ─────────────────────────────────────────────────────────────

export function ActionButton({
  label,
  title,
  state,
  onClick,
}: {
  label: string
  title: string
  state: UpdateState
  onClick: () => void
}) {
  if (state === 'queued') {
    return <span style={{ color: '#ffa657', fontSize: 10 }}>↑ queued</span>
  }
  const isError = state === 'error'
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: isError ? 'rgba(248,81,73,0.1)' : 'none',
        border: `1px solid ${isError ? 'rgba(248,81,73,0.3)' : 'var(--border)'}`,
        borderRadius: 4, cursor: 'pointer',
        color: isError ? '#f85149' : 'var(--text-dim)',
        fontSize: 10, padding: '2px 6px', marginTop: 3,
      }}
    >
      {isError ? '✕ retry' : label}
    </button>
  )
}

// ── Copyable IRI chip ─────────────────────────────────────────────────────────

/**
 * Compact chip that shows a short label, reveals the full IRI on mouseover,
 * and copies the IRI to the clipboard on click.
 */
export function CopyableIri({ iri, label }: { iri: string; label: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(iri)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      // clipboard blocked — leave state alone
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={iri}
      style={{
        background: 'none',
        border: '1px solid var(--border)',
        borderRadius: 3,
        padding: '0 5px',
        cursor: 'pointer',
        color: copied ? 'var(--accent-green, #3fb950)' : 'var(--text-dim)',
        fontSize: 10,
        fontFamily: 'monospace',
        lineHeight: '14px',
        whiteSpace: 'nowrap',
      }}
    >
      {label} {copied ? '✓' : '⎘'}
    </button>
  )
}
