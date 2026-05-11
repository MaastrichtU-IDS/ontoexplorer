import { useState, useRef } from 'react'
import { useAutocomplete } from '../hooks/useSearch'

interface Props {
  ontologyId: string | null
  versionId: string | null
  onSearch: (query: string) => void
  placeholder?: string
  initialValue?: string
}

export default function SearchBar({ ontologyId, versionId, onSearch, placeholder, initialValue }: Props) {
  const [value, setValue] = useState(initialValue ?? '')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)

  const autocompleteEnabled = showSuggestions && value.length >= 1
  const { data: acData } = useAutocomplete(ontologyId, versionId, value, cursor, autocompleteEnabled)
  const completions = acData?.completions ?? []
  const replaceFrom = acData?.replace_from ?? value.length
  const replaceTo   = acData?.replace_to   ?? value.length

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      setShowSuggestions(false)
      onSearch(value.trim())
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setValue(e.target.value)
    setCursor(e.target.selectionStart ?? -1)
    setShowSuggestions(true)
  }

  function applyCompletion(insert: string) {
    const newValue = value.slice(0, replaceFrom) + insert + value.slice(replaceTo)
    const newCursor = replaceFrom + insert.length
    setValue(newValue)
    setCursor(newCursor)
    setShowSuggestions(true)
    requestAnimationFrame(() => {
      if (inputRef.current) {
        inputRef.current.focus()
        inputRef.current.setSelectionRange(newCursor, newCursor)
      }
    })
  }

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '8px 12px',
      }}>
        <span style={{ color: 'var(--text-dim)' }}>⌕</span>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={() => setShowSuggestions(false)}
          onFocus={() => setShowSuggestions(true)}
          placeholder={placeholder ?? 'Search terms, ontologies, CURIEs, or MOS expressions…'}
          style={{
            flex: 1, background: 'none', border: 'none',
            color: 'var(--text)', fontSize: 'var(--font-size-base)',
            outline: 'none',
          }}
        />
      </div>

      {showSuggestions && completions.length > 0 && (
        <ul style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 200,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', listStyle: 'none',
          marginTop: 4, maxHeight: 240, overflowY: 'auto',
        }}>
          {completions.map((c, i) => (
            <li
              key={i}
              onMouseDown={() => applyCompletion(c.insert)}
              style={{
                padding: '6px 12px', cursor: 'pointer',
                display: 'flex', gap: 8, alignItems: 'center',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              <span style={{
                fontSize: 10, background: 'var(--bg)',
                color: c.type === 'class' ? 'var(--accent-purple)' : 'var(--text-dim)',
                borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
              }}>
                {c.type}
              </span>
              <span style={{ color: 'var(--text)' }}>{c.text}</span>
              {c.short && (
                <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 'auto' }}>
                  {c.short}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
