import { useRef, useState } from 'react'
import { useOntologySearch } from '../hooks/useOntologySearch'
import type { Ontology } from '../lib/api'

interface Props {
  value: string[]
  onChange: (ids: string[]) => void
  placeholder?: string
}

function shortLabel(o: Ontology): string {
  // Prefer the last path segment of the IRI as a readable label
  return o.iri.split(/[/#]/).filter(Boolean).pop() ?? o.id
}

export default function OntologyPicker({ value, onChange, placeholder = 'Search ontologies…' }: Props) {
  const [inputValue, setInputValue] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const { data, isLoading } = useOntologySearch(inputValue)
  const results = data?.ontologies ?? []

  function select(id: string) {
    if (!value.includes(id)) onChange([...value, id])
    setInputValue('')
    inputRef.current?.focus()
  }

  function deselect(id: string) {
    onChange(value.filter(v => v !== id))
  }

  function handleBlur(e: React.FocusEvent) {
    if (!containerRef.current?.contains(e.relatedTarget as Node)) {
      setOpen(false)
    }
  }

  return (
    <div
      ref={containerRef}
      onBlur={handleBlur}
      style={{ position: 'relative', minWidth: 260 }}
    >
      {/* Input + chips */}
      <div
        onClick={() => { setOpen(true); inputRef.current?.focus() }}
        style={{
          display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center',
          minHeight: 34, padding: '4px 8px',
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', cursor: 'text',
        }}
      >
        {value.map(id => (
          <span
            key={id}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              background: 'var(--bg-hover)', color: 'var(--accent)',
              borderRadius: 3, padding: '1px 6px', fontSize: 'var(--font-size-sm)',
            }}
          >
            {id}
            <button
              onMouseDown={e => { e.preventDefault(); deselect(id) }}
              style={{ color: 'var(--text-dim)', fontSize: 12, lineHeight: 1, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={inputValue}
          onChange={e => { setInputValue(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          placeholder={value.length === 0 ? placeholder : ''}
          style={{
            flex: 1, minWidth: 100, background: 'none', border: 'none', outline: 'none',
            color: 'var(--text)', fontSize: 'var(--font-size-sm)',
          }}
        />
      </div>

      {/* Dropdown */}
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', marginTop: 2,
          maxHeight: 240, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        }}>
          {isLoading && (
            <div style={{ padding: '8px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
              Searching…
            </div>
          )}
          {!isLoading && results.length === 0 && (
            <div style={{ padding: '8px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
              No ontologies found
            </div>
          )}
          {results.map(o => {
            const selected = value.includes(o.id)
            return (
              <div
                key={o.id}
                onMouseDown={e => { e.preventDefault(); selected ? deselect(o.id) : select(o.id) }}
                style={{
                  padding: '6px 12px', cursor: 'pointer',
                  background: selected ? 'var(--bg-hover)' : 'transparent',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
                }}
                onMouseEnter={e => { if (!selected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
                onMouseLeave={e => { if (!selected) e.currentTarget.style.background = '' }}
              >
                <div>
                  <span style={{ color: selected ? 'var(--accent)' : 'var(--text)', fontSize: 'var(--font-size-sm)' }}>
                    {shortLabel(o)}
                  </span>
                  <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 1, wordBreak: 'break-all' }}>
                    {o.iri}
                  </div>
                </div>
                {selected && <span style={{ color: 'var(--accent)', fontSize: 14 }}>✓</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
