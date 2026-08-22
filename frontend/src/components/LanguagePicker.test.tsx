import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import LanguagePicker from './LanguagePicker'
import { useLang } from '../hooks/useLang'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const LANGS = [{ lang: 'en' }, { lang: 'fr' }, { lang: 'ja' }]

describe('LanguagePicker', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => {
    const { result } = renderHook(() => useLang())
    act(() => result.current.setSessionLang(null))
  })

  it('offers only the languages it is given', () => {
    // On an ontology page this is that ontology's languages, not the whole
    // repository's — offering one it has no labels in is a choice that
    // visibly does nothing.
    wrap(<LanguagePicker languages={[{ lang: 'fr' }]} />)
    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText('français')).toBeInTheDocument()
    expect(screen.queryByText('日本語')).not.toBeInTheDocument()
  })

  it('sets the shared session language, so other consumers follow', () => {
    const elsewhere = renderHook(() => useLang())
    wrap(<LanguagePicker languages={LANGS} />)

    fireEvent.click(screen.getByRole('button', { name: /All/ }))
    fireEvent.click(screen.getByText('français'))

    expect(elsewhere.result.current.effectiveLang).toBe('fr')
  })

  it('shows the current language on the trigger', () => {
    const other = renderHook(() => useLang())
    act(() => other.result.current.setSessionLang('ja'))

    wrap(<LanguagePicker languages={LANGS} />)
    expect(screen.getByRole('button', { name: /ja/ })).toBeInTheDocument()
  })

  it('offers a way back to all languages', () => {
    const elsewhere = renderHook(() => useLang())
    act(() => elsewhere.result.current.setSessionLang('fr'))

    wrap(<LanguagePicker languages={LANGS} />)
    fireEvent.click(screen.getByRole('button', { name: /fr/ }))
    fireEvent.click(screen.getByText('All languages'))

    expect(elsewhere.result.current.effectiveLang).toBeNull()
  })

  it('filters by code, endonym or English name', () => {
    wrap(<LanguagePicker languages={LANGS} />)
    fireEvent.click(screen.getByRole('button'))
    const search = screen.getByPlaceholderText('Search…')

    fireEvent.change(search, { target: { value: 'japanese' } })
    expect(screen.getByText('日本語')).toBeInTheDocument()
    expect(screen.queryByText('français')).not.toBeInTheDocument()

    fireEvent.change(search, { target: { value: '日本' } })
    expect(screen.getByText('日本語')).toBeInTheDocument()
  })

  it('says so when nothing matches', () => {
    wrap(<LanguagePicker languages={LANGS} />)
    fireEvent.click(screen.getByRole('button'))
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'zzz' } })
    expect(screen.getByText('No match')).toBeInTheDocument()
  })
})
