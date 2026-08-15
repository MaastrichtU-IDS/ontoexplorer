import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useDebounced } from '../hooks/useDebounced'

/**
 * Combobox for picking a class/entity within one ontology version. The box shows
 * a human **label** (or whatever you type); selecting a suggestion emits its full
 * **IRI** via `onChange` (what callers query with). Typing free text emits it
 * verbatim, so a raw IRI can still be pasted. `value` is the emitted IRI; the box
 * clears its display when the parent clears `value`.
 */
export default function IriAutocomplete({
  ontologyId, versionId, value, onChange, placeholder, style,
}: {
  ontologyId: string
  versionId: string
  value: string
  onChange: (iri: string) => void
  placeholder?: string
  style?: React.CSSProperties
}) {
  const [display, setDisplay] = useState('')
  const [open, setOpen] = useState(false)
  const q = useDebounced(display.trim(), 200)

  // Let the parent reset the box (e.g. after clearing the query).
  useEffect(() => { if (!value) setDisplay('') }, [value])

  const { data } = useQuery({
    queryKey: ['iri-autocomplete', ontologyId, versionId, q],
    queryFn: () => api.ontologies.autocomplete(ontologyId, versionId, q),
    enabled: open && q.length >= 2,
    staleTime: 30_000,
  })
  const options = (data?.completions ?? []).filter(c => c.iri).slice(0, 8)

  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
      <input
        style={{ ...style, width: '100%', boxSizing: 'border-box' }}
        placeholder={placeholder}
        value={display}
        onChange={e => { setDisplay(e.target.value); onChange(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && options.length > 0 && (
        <ul style={{
          position: 'absolute', zIndex: 20, top: 'calc(100% + 2px)', left: 0, right: 0,
          margin: 0, padding: 0, listStyle: 'none', maxHeight: 240, overflowY: 'auto',
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', boxShadow: '0 4px 12px rgba(0,0,0,0.18)',
        }}>
          {options.map((c, i) => (
            <li
              key={(c.iri ?? '') + i}
              onMouseDown={e => { e.preventDefault(); setDisplay(c.text); onChange(c.iri!); setOpen(false) }}
              style={{
                padding: '7px 9px', cursor: 'pointer', fontSize: 13,
                borderBottom: i < options.length - 1 ? '1px solid var(--border)' : 'none',
              }}
            >
              <div>
                <span style={{ color: 'var(--text)' }}>{c.text}</span>
                {c.short && <span style={{ color: 'var(--text-dim)', marginLeft: 6 }}>{c.short}</span>}
              </div>
              <div style={{
                color: 'var(--text-dim)', fontSize: 10,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{c.iri}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
