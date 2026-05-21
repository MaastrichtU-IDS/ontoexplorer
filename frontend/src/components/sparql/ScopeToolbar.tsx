import { useEffect, useMemo, useRef, useState } from 'react'
import { useOntologies } from '../../hooks/useOntologies'
import {
  ReasoningMode,
  buildScopedEndpoint,
  endpointForVersion,
  formatScopeAsFromClauses,
  selectedGraphIris,
} from './scopeUrls'
import type { Ontology, OntologyVersion } from '../../lib/api'
import { api } from '../../lib/api'

const BASE_ENDPOINT = '/api/v1/sparql/content'

export interface DiffScope {
  from: { version: OntologyVersion; mode: ReasoningMode }
  to:   { version: OntologyVersion; mode: ReasoningMode }
}

export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
  onOntologyAdded?: (ontologyId: string) => void
  onSelectionChange?: (ontologyIds: string[]) => void
  onLabelsToggle?: (enabled: boolean) => void
  onDiffScopeChange?: (scope: DiffScope | null) => void
  /** Called whenever the scope's graph IRI list changes in Single mode. The
   *  page uses this to keep the editor's managed FROM/FROM NAMED clauses in
   *  sync with the chip selection. In Diff mode the toolbar emits [] (Diff
   *  uses URL params, not editor-injected FROM clauses). */
  onScopeGraphsChange?: (graphIris: string[]) => void
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

export function ScopeToolbar({ onScopeChange, onCopy, onOntologyAdded, onSelectionChange, onLabelsToggle, onDiffScopeChange, onScopeGraphsChange }: ScopeToolbarProps) {
  const { ontologies } = useOntologies()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mode, setMode] = useState<ReasoningMode>('asserted')
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [labelsOn, setLabelsOn] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  type ToolbarMode = 'single' | 'diff'
  const [toolbarMode, setToolbarMode] = useState<ToolbarMode>('single')

  const [fromOntologyId, setFromOntologyId] = useState<string>('')
  const [fromVersionId, setFromVersionId] = useState<string>('')
  const [fromMode, setFromMode] = useState<ReasoningMode>('asserted')
  const [toOntologyId, setToOntologyId] = useState<string>('')
  const [toVersionId, setToVersionId] = useState<string>('')
  const [toMode, setToMode] = useState<ReasoningMode>('asserted')

  const [fromVersions, setFromVersions] = useState<OntologyVersion[]>([])
  const [toVersions, setToVersions] = useState<OntologyVersion[]>([])

  const selectableOntologies = useMemo(() => ontologies.filter(isSelectable), [ontologies])

  const graphIris = useMemo(
    () => selectedGraphIris(selected, mode, selectableOntologies),
    [selected, mode, selectableOntologies],
  )
  const hasSelection = selected.size > 0
  const endpoint = useMemo(() => buildScopedEndpoint(BASE_ENDPOINT, graphIris), [graphIris])

  // Notify the parent on any change to the computed endpoint. In Diff mode,
  // emit the From-side endpoint so Yasr's bound native fetch renders the From-
  // side response (used by the page's spec-compliant non-SELECT fallback). If
  // the From side isn't complete yet, fall back to the bare base endpoint.
  useEffect(() => {
    if (toolbarMode === 'diff') {
      const fromV = fromVersions.find(v => v.id === fromVersionId)
      onScopeChange(fromV ? endpointForVersion(fromV, fromMode) : BASE_ENDPOINT)
      return
    }
    onScopeChange(endpoint)
  }, [toolbarMode, endpoint, onScopeChange, fromVersions, fromVersionId, fromMode])

  // Notify the parent whenever the selection set changes.
  useEffect(() => {
    onSelectionChange?.(Array.from(selected))
  }, [selected, onSelectionChange])

  // Notify the parent whenever the scope's graph IRI list changes (Single mode
  // only; Diff mode uses URL params, not editor-injected FROM clauses). The
  // page uses this to keep the editor's managed FROM/FROM NAMED list in sync
  // with chip selection.
  useEffect(() => {
    if (toolbarMode === 'diff') {
      onScopeGraphsChange?.([])
      return
    }
    onScopeGraphsChange?.(graphIris)
  }, [toolbarMode, graphIris, onScopeGraphsChange])

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

  // Populate default ontology selection when entering Diff mode.
  useEffect(() => {
    if (toolbarMode !== 'diff') return
    const first = Array.from(selected)[0] ?? selectableOntologies[0]?.id
    if (first && !fromOntologyId && !toOntologyId) {
      setFromOntologyId(first)
      setToOntologyId(first)
    }
  }, [toolbarMode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch versions for the From side.
  useEffect(() => {
    if (!fromOntologyId) { setFromVersions([]); return }
    api.ontologies.versions(fromOntologyId)
      .then(r => {
        const sorted = [...r.versions].sort((a, b) =>
          (b.created_at ?? '').localeCompare(a.created_at ?? '')
        )
        setFromVersions(sorted)
        if (sorted.length > 0 && !fromVersionId) {
          setFromVersionId(sorted[1]?.id ?? sorted[0].id)
        }
      })
      .catch(() => setFromVersions([]))
  }, [fromOntologyId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch versions for the To side.
  useEffect(() => {
    if (!toOntologyId) { setToVersions([]); return }
    api.ontologies.versions(toOntologyId)
      .then(r => {
        const sorted = [...r.versions].sort((a, b) =>
          (b.created_at ?? '').localeCompare(a.created_at ?? '')
        )
        setToVersions(sorted)
        if (sorted.length > 0 && !toVersionId) {
          setToVersionId(sorted[0].id)
        }
      })
      .catch(() => setToVersions([]))
  }, [toOntologyId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Emit onDiffScopeChange whenever diff selection changes or mode exits.
  useEffect(() => {
    if (toolbarMode !== 'diff') {
      onDiffScopeChange?.(null)
      return
    }
    const fromV = fromVersions.find(v => v.id === fromVersionId)
    const toV = toVersions.find(v => v.id === toVersionId)
    if (fromV && toV) {
      onDiffScopeChange?.({
        from: { version: fromV, mode: fromMode },
        to:   { version: toV,   mode: toMode },
      })
    } else {
      onDiffScopeChange?.(null)
    }
  }, [toolbarMode, fromVersions, fromVersionId, fromMode, toVersions, toVersionId, toMode, onDiffScopeChange])

  function toggleOntology(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
        onOntologyAdded?.(id)
      }
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
      {/* Mode toggle: Single ↔ Diff */}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginRight: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Mode:</span>
        {(['single', 'diff'] as const).map(m => {
          const active = toolbarMode === m
          return (
            <button
              key={m}
              onClick={() => setToolbarMode(m)}
              style={{
                fontSize: 11, padding: '2px 10px', borderRadius: 12,
                border: '1px solid',
                borderColor: active ? 'var(--accent)' : 'var(--border)',
                background: active ? 'rgba(88,166,255,0.10)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--text-dim)',
                cursor: 'pointer', textTransform: 'capitalize',
              }}
            >
              {m === 'single' ? 'Single' : 'Diff'}
            </button>
          )
        })}
      </div>

      {toolbarMode === 'single' && (<>
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
      </>)}

      {toolbarMode === 'diff' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {(['from', 'to'] as const).map(side => {
            const ontId = side === 'from' ? fromOntologyId : toOntologyId
            const setOntId = side === 'from' ? setFromOntologyId : setToOntologyId
            const versions = side === 'from' ? fromVersions : toVersions
            const vid = side === 'from' ? fromVersionId : toVersionId
            const setVid = side === 'from' ? setFromVersionId : setToVersionId
            const sideMode = side === 'from' ? fromMode : toMode
            const setSideMode = side === 'from' ? setFromMode : setToMode

            return (
              <div key={side} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-dim)', minWidth: 36 }}>
                  {side === 'from' ? 'From:' : 'To:'}
                </span>
                <select
                  value={ontId}
                  onChange={e => { setOntId(e.target.value); setVid('') }}
                  style={{ fontSize: 11, padding: '2px 6px', background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }}
                >
                  <option value="">Pick ontology…</option>
                  {selectableOntologies.map(o => (
                    <option key={o.id} value={o.id}>{ontologyLabel(o)}</option>
                  ))}
                </select>
                <select
                  value={vid}
                  onChange={e => setVid(e.target.value)}
                  disabled={!versions.length}
                  style={{ fontSize: 11, padding: '2px 6px', background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }}
                >
                  <option value="">Pick version…</option>
                  {versions.map(v => (
                    <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
                  ))}
                </select>
                <div style={{ display: 'flex', gap: 2 }}>
                  {(['asserted', 'inferred', 'both'] as ReasoningMode[]).map(m => {
                    const active = sideMode === m
                    return (
                      <button
                        key={m}
                        onClick={() => setSideMode(m)}
                        style={{
                          fontSize: 10, padding: '1px 8px', borderRadius: 10,
                          border: '1px solid',
                          borderColor: active ? 'var(--accent)' : 'var(--border)',
                          background: active ? 'rgba(88,166,255,0.10)' : 'transparent',
                          color: active ? 'var(--accent)' : 'var(--text-dim)',
                          cursor: 'pointer', textTransform: 'capitalize',
                        }}
                      >{m}</button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <button
        onClick={() => {
          const next = !labelsOn
          setLabelsOn(next)
          onLabelsToggle?.(next)
        }}
        aria-label="Toggle result labels"
        title="Append rdfs:label to IRI cells in result table"
        style={{
          fontSize: 14, padding: '2px 8px',
          border: `1px solid ${labelsOn ? 'var(--accent)' : 'var(--border)'}`,
          borderRadius: 4, background: labelsOn ? 'rgba(88,166,255,0.1)' : 'transparent',
          color: labelsOn ? 'var(--accent)' : 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        📑
      </button>

      <button
        onClick={handleCopy}
        aria-label="Copy query with scope"
        title="Copy the editor query to clipboard"
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
