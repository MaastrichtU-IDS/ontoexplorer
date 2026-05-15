import { useState, useCallback } from 'react'
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
  const [sessionLang, setSessionLangState] = useState<string | null>(readSessionLang)

  const setSessionLang = useCallback((lang: string | null) => {
    writeSessionLang(lang)
    setSessionLangState(lang)
  }, [])

  const setOntologyLang = useCallback(async (ontologyId: string, lang: string | null) => {
    await api.ontologies.patch(ontologyId, { preferred_lang: lang })
  }, [])

  // Three-tier resolution: session > ontology override > (user pref handled server-side)
  const effectiveLang = sessionLang ?? opts.ontologyPreferredLang ?? null

  return { effectiveLang, sessionLang, setSessionLang, setOntologyLang }
}
