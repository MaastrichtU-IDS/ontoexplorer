import { useMemo, useState } from 'react'
import { useOntologies } from '../../hooks/useOntologies'
import {
  ReasoningMode,
  formatScopeAsFromClauses,
  selectedGraphIris,
} from './scopeUrls'

export interface ScopeToolbarProps {
  onScopeChange: (endpoint: string) => void
  onCopy: (fromBlock: string) => void
}

export function ScopeToolbar({
  onScopeChange: _onScopeChange,
  onCopy,
}: ScopeToolbarProps) {
  const { ontologies } = useOntologies()
  const [selected, _setSelected] = useState<Set<string>>(new Set())
  const [mode, setMode] = useState<ReasoningMode>('asserted')

  const graphIris = useMemo(
    () => selectedGraphIris(selected, mode, ontologies),
    [selected, mode, ontologies],
  )
  const hasSelection = selected.size > 0

  function handleCopy() {
    onCopy(formatScopeAsFromClauses(graphIris))
  }

  const summary = hasSelection
    ? `${selected.size} ontolog${selected.size === 1 ? 'y' : 'ies'} · ${mode} · ${graphIris.length} graph${graphIris.length === 1 ? '' : 's'} scoped`
    : 'No scope selected · whole store queryable'

  return (
    <div
      style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>Scope:</span>
      <button
        style={{
          fontSize: 11, padding: '2px 8px', border: '1px dashed var(--border)',
          borderRadius: 12, background: 'transparent', color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
      >
        + add ontology…
      </button>
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
