import { useState, useRef, useEffect } from 'react'
import { useAutocomplete, useGlobalAutocomplete } from '../hooks/useSearch'

interface Props {
  ontologyId: string | null
  versionId: string | null
  onSearch: (query: string) => void
  placeholder?: string
  initialValue?: string
  /** When provided, use global cross-ontology autocomplete scoped to these IDs (empty = all ontologies) */
  scopeOntologyIds?: string[]
}

export default function SearchBar({ ontologyId, versionId, onSearch, placeholder, initialValue, scopeOntologyIds }: Props) {
  const [value, setValue] = useState(initialValue ?? '')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const [activeIdx, setActiveIdx] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const autocompleteEnabled = showSuggestions && value.length >= 1
  const globalMode = scopeOntologyIds !== undefined
  const { data: acData } = useAutocomplete(ontologyId, versionId, value, cursor, autocompleteEnabled && !globalMode)
  const { data: globalAcData } = useGlobalAutocomplete(value, cursor, autocompleteEnabled && globalMode, scopeOntologyIds ?? [])
  const activeAcData = globalMode ? globalAcData : acData
  const completions = activeAcData?.completions ?? []
  const replaceFrom = activeAcData?.replace_from ?? value.length
  const replaceTo   = activeAcData?.replace_to   ?? value.length

  // Reset the highlighted suggestion whenever the suggestion set changes.
  useEffect(() => { setActiveIdx(-1) }, [activeAcData])

  // Keep the highlighted item scrolled into view during arrow navigation.
  useEffect(() => {
    if (activeIdx < 0 || !listRef.current) return
    const el = listRef.current.children[activeIdx] as HTMLElement | undefined
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIdx])

  const suggestionsOpen = showSuggestions && completions.length > 0

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (suggestionsOpen && e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, completions.length - 1))
    } else if (suggestionsOpen && e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Tab' && completions.length > 0) {
      // Tab accepts the highlighted suggestion (or the top one if none highlighted).
      e.preventDefault()
      applyCompletion(completions[activeIdx >= 0 ? activeIdx : 0].insert)
    } else if (e.key === 'Enter') {
      if (suggestionsOpen && activeIdx >= 0) {
        // A suggestion is highlighted — accept it and keep building, don't submit.
        e.preventDefault()
        applyCompletion(completions[activeIdx].insert)
      } else {
        setShowSuggestions(false)
        onSearch(value.trim())
      }
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setValue(e.target.value)
    setCursor(e.target.selectionStart ?? -1)
    setShowSuggestions(true)
    setActiveIdx(-1)
  }

  function applyCompletion(insert: string) {
    const newValue = value.slice(0, replaceFrom) + insert + value.slice(replaceTo)
    const newCursor = replaceFrom + insert.length
    setValue(newValue)
    setCursor(newCursor)
    setShowSuggestions(true)
    setActiveIdx(-1)
    // Restore cursor position in the input after React re-renders
    setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.setSelectionRange(newCursor, newCursor)
      }
    }, 0)
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

      {suggestionsOpen && (
        <ul ref={listRef} style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 200,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', listStyle: 'none',
          marginTop: 4, maxHeight: 240, overflowY: 'auto',
        }}>
          {completions.map((c, i) => (
            <li
              key={i}
              onMouseDown={(e) => { e.preventDefault(); applyCompletion(c.insert) }}
              onMouseEnter={() => setActiveIdx(i)}
              style={{
                padding: '6px 12px', cursor: 'pointer',
                display: 'flex', gap: 8, alignItems: 'center',
                background: i === activeIdx ? 'var(--bg-hover)' : 'transparent',
              }}
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
                <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                  {c.short}
                </span>
              )}
              {c.ontology_shortname && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 3,
                  background: 'var(--bg)', border: '1px solid var(--border)',
                  color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0,
                }}>
                  {c.ontology_shortname}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
