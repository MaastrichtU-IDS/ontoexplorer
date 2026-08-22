import { useCallback, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'oe_lang_override'

function readSessionLang(): string | null {
  try { return localStorage.getItem(STORAGE_KEY) } catch { return null }
}

function writeSessionLang(lang: string | null): void {
  try {
    if (lang) localStorage.setItem(STORAGE_KEY, lang)
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* ignore */ }
}

// One value shared by every useLang() caller.
//
// This used to be per-component useState seeded from localStorage. The picker
// lives in the navbar while the tree and term panel read the language on the
// ontology page, so changing language updated only the picker's own copy:
// everything else kept its stale value, refetched with it, and nothing
// appeared to happen.
let current: string | null = readSessionLang()
const listeners = new Set<() => void>()

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

function getSnapshot(): string | null {
  return current
}

function publish(lang: string | null): void {
  current = lang
  writeSessionLang(lang)
  listeners.forEach(fn => fn())
}

export interface UseLangResult {
  effectiveLang: string | null
  sessionLang: string | null
  setSessionLang: (lang: string | null) => void
}

export function useLang(): UseLangResult {
  const sessionLang = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const setSessionLang = useCallback((lang: string | null) => {
    publish(lang)
  }, [])

  // Session choice, else let the server apply the signed-in user's preference.
  // There is no per-ontology default: the display language belongs to the
  // reader, not to the ontology.
  const effectiveLang = sessionLang ?? null

  return { effectiveLang, sessionLang, setSessionLang }
}
