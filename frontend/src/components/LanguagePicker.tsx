import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLang } from '../hooks/useLang'

export interface PickerLanguage {
  lang: string
  label_count?: number
}

// Render a BCP-47 tag in its own language ("el" → "Ελληνικά", "ja" → "日本語").
function endonym(tag: string): string {
  if (!tag) return 'untagged'
  try {
    return new Intl.DisplayNames([tag], { type: 'language', fallback: 'code' }).of(tag) || tag
  } catch {
    return tag
  }
}

// English name, used for search-matching only ("el" → "greek", so the picker
// can still be filtered by typing a familiar Latin-script name).
function englishName(tag: string): string {
  if (!tag) return ''
  try {
    return new Intl.DisplayNames(['en'], { type: 'language', fallback: 'code' }).of(tag) || ''
  } catch {
    return ''
  }
}

/**
 * The language picker, used in the navigation bar over every language in the
 * repository and on an ontology page over just that ontology's languages.
 *
 * One component rather than two look-alikes: both set the same session
 * language, which is a shared store, so whichever you use the other updates
 * with it. Only the list of offered languages differs — on an ontology page,
 * offering languages that ontology does not have would be a menu of choices
 * that visibly do nothing.
 */
export default function LanguagePicker({ languages, align = 'right', title }: {
  languages: PickerLanguage[]
  align?: 'left' | 'right'
  title?: string
}) {
  const { sessionLang, setSessionLang } = useLang()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')

  // The backend returns languages sorted by code already.
  const q = filter.trim().toLowerCase()
  const visible = q
    ? languages.filter(({ lang }) =>
        lang.toLowerCase().includes(q)
        || endonym(lang).toLowerCase().includes(q)
        || englishName(lang).toLowerCase().includes(q)
      )
    : languages

  function pick(lang: string | null) {
    setSessionLang(lang)
    setOpen(false)
    setFilter('')
    // Refetch anything whose result depends on the active language, without a
    // full page reload — reloading wipes the in-memory access token and forces
    // a refresh-token round-trip that can fail and log the user out.
    queryClient.invalidateQueries()
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        title={title ?? 'Your display language — applies to everything you view, and only to you'}
        onClick={() => setOpen(v => !v)}
        style={{
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', padding: '4px 10px',
          color: 'var(--text-dim)', fontSize: 12, cursor: 'pointer',
        }}
      >
        {'🌐'} {sessionLang ?? 'All'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', [align]: 0, top: '110%', zIndex: 100,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', minWidth: 190, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
            <input
              autoFocus
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Search…"
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '4px 7px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)', color: 'var(--text)', outline: 'none',
              }}
            />
          </div>
          <div style={{ maxHeight: 280, overflowY: 'auto' }}>
            {!q && (
              <button
                onClick={() => pick(null)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '6px 12px', background: 'none', border: 'none',
                  color: sessionLang === null ? 'var(--accent)' : 'var(--text)',
                  fontSize: 12, cursor: 'pointer',
                }}
              >
                All languages
              </button>
            )}
            {visible.map(({ lang }) => (
              <button
                key={lang}
                onClick={() => pick(lang || null)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  width: '100%', textAlign: 'left',
                  padding: '6px 12px', background: 'none', border: 'none',
                  color: sessionLang === (lang ? lang : null) ? 'var(--accent)' : 'var(--text)',
                  fontSize: 12, cursor: 'pointer', gap: 8,
                }}
              >
                <span>{endonym(lang)}</span>
                <span style={{ fontSize: 10, color: 'var(--text-dim)', flexShrink: 0 }}>{lang || '—'}</span>
              </button>
            ))}
            {visible.length === 0 && (
              <div style={{ padding: '6px 12px', fontSize: 12, color: 'var(--text-dim)' }}>No match</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
