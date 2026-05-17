import { useState } from 'react'

export interface Candidate {
  iri: string
  label: string
  count?: number
}

function shortLabel(iri: string): string {
  return iri.split(/[/#]/).pop() ?? iri
}

function PropChip({ iri, label, count, onRemove }: {
  iri: string; label: string; count?: number; onRemove: () => void
}) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: 'var(--bg)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '2px 6px', fontSize: 11, color: 'var(--text)',
    }}>
      <span title={iri}>{label}</span>
      {count !== undefined && (
        <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>({count.toLocaleString()})</span>
      )}
      <button
        onClick={onRemove}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', fontSize: 11, padding: 0 }}
      >
        ×
      </button>
    </span>
  )
}

export function SearchableRoleSection({
  sectionLabel, currentProps, candidates, onRemove, onAdd,
}: {
  sectionLabel: string
  currentProps: string[]
  candidates: Candidate[]
  onRemove: (iri: string) => void
  onAdd: (iri: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [query, setQuery] = useState('')

  const candidateMap = Object.fromEntries(candidates.map(c => [c.iri, c]))
  const available = candidates.filter(c => !currentProps.includes(c.iri))
  const q = query.toLowerCase()
  const filtered = q
    ? available.filter(c => c.label.toLowerCase().includes(q) || c.iri.toLowerCase().includes(q))
    : available
  const isCustom = query.trim() !== '' && !candidates.some(c => c.iri === query.trim())

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 5 }}>
        {sectionLabel}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 3 }}>
        {currentProps.length === 0 && (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>(none)</span>
        )}
        {currentProps.map(iri => {
          const c = candidateMap[iri]
          return (
            <PropChip
              key={iri}
              iri={iri}
              label={c?.label ?? shortLabel(iri)}
              count={c?.count}
              onRemove={() => onRemove(iri)}
            />
          )
        })}
        <button
          onClick={() => { setAdding(a => !a); setQuery('') }}
          style={{
            fontSize: 10, padding: '2px 6px', borderRadius: 4,
            border: '1px dashed var(--border)', background: 'none',
            color: 'var(--accent)', cursor: 'pointer',
          }}
        >
          + Add
        </button>
      </div>
      {adding && (
        <div style={{ paddingLeft: 4 }}>
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search properties…"
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 4,
              border: '1px solid var(--border)', background: 'var(--bg)',
              color: 'var(--text)', width: 220, marginBottom: 6, display: 'block',
            }}
          />
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {filtered.map(c => (
              <button
                key={c.iri}
                title={c.iri}
                onClick={() => { onAdd(c.iri); setAdding(false); setQuery('') }}
                style={{
                  fontSize: 10, padding: '2px 6px', borderRadius: 4,
                  border: '1px solid var(--border)', background: 'var(--bg-secondary)',
                  color: 'var(--text-muted)', cursor: 'pointer',
                }}
              >
                {c.label}{c.count !== undefined ? ` (${c.count.toLocaleString()})` : ''}
              </button>
            ))}
            {isCustom && (
              <button
                onClick={() => { onAdd(query.trim()); setAdding(false); setQuery('') }}
                style={{
                  fontSize: 10, padding: '2px 6px', borderRadius: 4,
                  border: '1px dashed var(--border)', background: 'none',
                  color: 'var(--accent)', cursor: 'pointer',
                }}
              >
                Add &ldquo;{query.trim()}&rdquo;
              </button>
            )}
            {filtered.length === 0 && !isCustom && (
              <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                {query ? 'No matches' : 'No candidates available'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
