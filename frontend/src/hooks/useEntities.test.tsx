import { describe, it, expect, afterEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useEntities } from './useEntities'
import { useRelated } from './useRelated'
import { useFacets } from './useFacets'

vi.mock('../lib/auth', () => ({
  getAccessToken: () => 'tok',
  refreshAccessToken: async () => 'tok',
  clearAccessToken: () => {},
}))

const row = {
  iri: 'http://x/A', primary_label: 'A', short: 'A', type: 'class',
  ontology_id: 'o1', ontology_title: 'Onto', version_id: 'v1', source: 's', definition: '',
}

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

function mockFetch(body: unknown) {
  const f = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body })
  vi.stubGlobal('fetch', f)
  return f
}

afterEach(() => vi.unstubAllGlobals())

describe('entity hooks', () => {
  it('useEntities hits /entities with params and returns rows', async () => {
    const f = mockFetch({ entities: [row], next: null, approx_total: 1, limit: 25 })
    const { result } = renderHook(
      () => useEntities({ type: 'class', q: 'gene', ontology: ['o1', 'o2'], limit: 25 }),
      { wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.entities).toHaveLength(1))
    const url = f.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/entities?')
    expect(url).toContain('type=class')
    expect(url).toContain('q=gene')
    expect(url).toContain('ontology=o1&ontology=o2')
    expect(url).toContain('limit=25')
    expect(result.current.entities[0].iri).toBe('http://x/A')
  })

  it('useRelated does not fetch when q is empty', async () => {
    const f = mockFetch({ entities: [], unavailable: false })
    renderHook(() => useRelated({ type: 'class', q: '' }), { wrapper: wrapper() })
    await new Promise(r => setTimeout(r, 50))
    expect(f).not.toHaveBeenCalled()
  })

  it('useRelated fetches when q is set', async () => {
    const f = mockFetch({ entities: [{ ...row, score: 0.9 }], unavailable: false })
    const { result } = renderHook(() => useRelated({ type: 'class', q: 'gene', k: 5 }), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.entities).toHaveLength(1))
    expect(f.mock.calls[0][0]).toContain('/api/v1/entities/related?')
  })

  it('useFacets unwraps the ontologies envelope', async () => {
    mockFetch({ ontologies: [{ ontology_id: 'o1', short: 'O', title: 'Onto', count: 3 }] })
    const { result } = renderHook(() => useFacets('class'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.facets).toHaveLength(1))
    expect(result.current.facets[0].count).toBe(3)
  })
})
