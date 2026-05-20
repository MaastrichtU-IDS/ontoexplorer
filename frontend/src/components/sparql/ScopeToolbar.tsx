import { useEffect, useMemo, useRef, useState } from 'react'
import { useOntologies } from '../../hooks/useOntologies'
import {
  ReasoningMode,
  buildScopedEndpoint,
  formatScopeAsFromClauses,
  selectedGraphIris,
} from './scopeUrls'
import type { Ontology } from '../../lib/api'

const BASE_ENDPOINT = '/api/v1/sparql/content'

export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
}

function ontologyLabel(o: Ontology): string {
  return (
    o.shortname
    || o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
    || o.iri
  )
}

function isSelectable(o: Ontology): boolean {
  if (!o.latest_version) return false
  return !['pending', 'failed', 'deprecated'].includes(o.latest_version.status)
}

export function ScopeToolbar({ onScopeChange, onCopy }: ScopeToolbarProps) {
  const { ontologies } = useOntologies()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mode, setMode] = useState<ReasoningMode>('asserted')
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)

  const selectableOntologies = useMemo(() => ontologies.filter(isSelectable), [ontologies])

  const graphIris = useMemo(
    () => selectedGraphIris(selected, mode, selectableOntologies),
    [selected, mode, selectableOntologies],
  )
  const hasSelection = selected.size > 0
  const endpoint = useMemo(() => buildScopedEndpoint(BASE_ENDPOINT, graphIris), [graphIris])

  // Notify the parent on any change to the computed endpoint.
  useEffect(() => {
    onScopeChange(endpoint)
  }, [endpoint, onScopeChange])

  // Close popover on outside click.
  useEffect(() => {
    if (!popoverOpen) return
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setPopoverOpen(false)
        setFilter('')
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [popoverOpen])

  function toggleOntology(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function removeChip(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  function handleCopy() {
    onCopy(formatScopeAsFromClauses(graphIris))
  }

  const q = filter.trim().toLowerCase()
  const popoverList = q
    ? selectableOntologies.filter(o => ontologyLabel(o).toLowerCase().includes(q))
    : selectableOntologies

  const summary = hasSelection
    ? `${selected.size} ontolog${selected.size === 1 ? 'y' : 'ies'} · ${mode} · ${graphIris.length} graph${graphIris.length === 1 ? '' : 's'} scoped`
    : 'No scope selected · whole store queryable'

  const selectedOntologies = selectableOntologies.filter(o => selected.has(o.id))

  return (
    <div
      ref={rootRef}
      style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        position: 'relative',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>Scope:</span>

      {selectedOntologies.map(o => (
        <button
          key={o.id}
          onClick={() => removeChip(o.id)}
          aria-label={`Remove ${ontologyLabel(o)}`}
          style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 12,
            border: '1px solid var(--accent)',
            background: 'rgba(88,166,255,0.1)', color: 'var(--accent)',
            cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4,
          }}
        >
          {ontologyLabel(o)} <span style={{ fontSize: 10 }}>✕</span>
        </button>
      ))}

      <button
        onClick={() => setPopoverOpen(v => !v)}
        style={{
          fontSize: 11, padding: '2px 8px', border: '1px dashed var(--border)',
          borderRadius: 12, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        + add ontology…
      </button>

      {popoverOpen && (
        <div
          style={{
            position: 'absolute', top: 'calc(100% + 2px)', left: '1.5rem',
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 4, zIndex: 50, minWidth: 220, maxHeight: 280, overflowY: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            display: 'flex', flexDirection: 'column',
          }}
        >
          <div style={{ padding: 6, borderBottom: '1px solid var(--border)' }}>
            <input
              autoFocus
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Filter ontologies…"
              aria-label="Filter ontologies"
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '4px 8px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 4, color: 'var(--text)', outline: 'none',
              }}
            />
          </div>
          <div>
            {popoverList.length === 0 ? (
              <div style={{ padding: 8, fontSize: 12, color: 'var(--text-dim)' }}>No matches</div>
            ) : (
              popoverList.map(o => {
                const isSelected = selected.has(o.id)
                return (
                  <button
                    key={o.id}
                    onClick={() => toggleOntology(o.id)}
                    style={{
                      display: 'block', width: '100%', textAlign: 'left',
                      padding: '6px 10px', background: 'none', border: 'none',
                      color: isSelected ? 'var(--accent)' : 'var(--text)',
                      fontSize: 12, cursor: 'pointer',
                    }}
                  >
                    {isSelected ? '✓ ' : '  '}{ontologyLabel(o)}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 4 }}>
        {(['asserted', 'inferred', 'both'] as ReasoningMode[]).map(m => (
          <button
            key={m}
            disabled={!hasSelection}
            onClick={() => setMode(m)}
            style={{
              fontSize: 11, padding: '2px 10px', borderRadius: 12,
              border: '1px solid',
              borderColor: mode === m && hasSelection ? 'var(--accent)' : 'var(--border)',
              background: mode === m && hasSelection ? 'rgba(88,166,255,0.1)' : 'transparent',
              color: !hasSelection ? 'var(--text-dim)' : mode === m ? 'var(--accent)' : 'var(--text)',
              opacity: hasSelection ? 1 : 0.45,
              cursor: hasSelection ? 'pointer' : 'not-allowed',
              textTransform: 'capitalize',
            }}
          >
            {m}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, minWidth: 80, fontSize: 11, color: 'var(--text-dim)' }}>
        {summary}
      </div>

      <button
        onClick={handleCopy}
        aria-label="Copy query with scope"
        title="Copy editor query with FROM/FROM NAMED clauses prepended"
        style={{
          fontSize: 14, padding: '2px 8px', border: '1px solid var(--border)',
          borderRadius: 4, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        📋
      </button>
    </div>
  )
}
