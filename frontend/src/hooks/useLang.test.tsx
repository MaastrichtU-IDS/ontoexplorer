import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useLang } from './useLang'

describe('useLang', () => {
  beforeEach(() => localStorage.clear())
  // The store is a module-level singleton, so a language set by one test would
  // otherwise leak into the next.
  afterEach(() => {
    const { result } = renderHook(() => useLang())
    act(() => result.current.setSessionLang(null))
  })

  it('shares the session language across every component that uses it', () => {
    // The picker lives in the navbar while the tree and term panel read the
    // language on the ontology page. With per-component useState the picker
    // updated only its own copy, so changing language refetched everything
    // with the old value and nothing appeared to happen.
    const picker = renderHook(() => useLang())
    const page = renderHook(() => useLang())

    act(() => picker.result.current.setSessionLang('fr'))

    expect(picker.result.current.sessionLang).toBe('fr')
    expect(page.result.current.sessionLang).toBe('fr')
    expect(page.result.current.effectiveLang).toBe('fr')
  })

  it('propagates a reset back to all consumers', () => {
    const picker = renderHook(() => useLang())
    const page = renderHook(() => useLang())

    act(() => picker.result.current.setSessionLang('de'))
    act(() => picker.result.current.setSessionLang(null))

    expect(page.result.current.sessionLang).toBeNull()
  })

  it('still lets the ontology default apply when no session language is set', () => {
    const page = renderHook(() => useLang({ ontologyPreferredLang: 'nl' }))
    expect(page.result.current.effectiveLang).toBe('nl')
  })

  it('prefers the session language over the ontology default', () => {
    const picker = renderHook(() => useLang())
    const page = renderHook(() => useLang({ ontologyPreferredLang: 'nl' }))

    act(() => picker.result.current.setSessionLang('ja'))
    expect(page.result.current.effectiveLang).toBe('ja')
  })

  it('starts from whatever was persisted', async () => {
    // Initialisation happens once at module load, so this needs a fresh copy
    // of the module rather than a re-render.
    localStorage.setItem('oe_lang_override', 'es')
    vi.resetModules()
    const { useLang: freshUseLang } = await import('./useLang')

    const { result } = renderHook(() => freshUseLang())
    expect(result.current.sessionLang).toBe('es')
  })
})
