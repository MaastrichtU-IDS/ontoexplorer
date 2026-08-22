import { useCallback, useSyncExternalStore } from 'react'
import { api } from '../lib/api'

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

interface UseLangOptions {
  ontologyId?: string
  ontologyPreferredLang?: string | null
}

export interface UseLangResult {
  effectiveLang: string | null
  sessionLang: string | null
  setSessionLang: (lang: string | null) => void
  setOntologyLang: (ontologyId: string, lang: string | null) => Promise<void>
}

export function useLang(opts: UseLangOptions = {}): UseLangResult {
  const sessionLang = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const setSessionLang = useCallback((lang: string | null) => {
    publish(lang)
  }, [])

  const setOntologyLang = useCallback(async (ontologyId: string, lang: string | null) => {
    await api.ontologies.patch(ontologyId, { preferred_lang: lang })
  }, [])

  // Three-tier resolution: session > ontology override > (user pref handled server-side)
  const effectiveLang = sessionLang ?? opts.ontologyPreferredLang ?? null

  return { effectiveLang, sessionLang, setSessionLang, setOntologyLang }
}
