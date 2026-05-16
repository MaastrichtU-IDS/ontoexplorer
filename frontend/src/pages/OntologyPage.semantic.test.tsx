import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual('../lib/api')
  return {
    ...actual,
    api: {
      ...(actual as any).api,
      ontologies: {
        ...(actual as any).api?.ontologies,
        search: vi.fn().mockResolvedValue({
          mode: 'entity',
          results: [{ iri: 'http://ex.org/Heart', label: 'heart', short: 'Heart', match_type: 'entity' }],
          semantic_results: [{ iri: 'http://ex.org/Cardiac', label: 'cardiac', short: 'Cardiac', match_type: 'semantic', score: 0.88 }],
          count: 1, truncated: false,
        }),
      },
    },
  }
})

describe('OntologySearchBar semantic', () => {
  it('shows semantic results section when present', async () => {
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <div id="test-host" />
        </MemoryRouter>
      </QueryClientProvider>
    )
    const { api } = await import('../lib/api')
    const result = await api.ontologies.search('go', 'v1', 'heart', 'auto', undefined, true)
    expect(result.semantic_results).toHaveLength(1)
    expect(result.semantic_results![0].score).toBe(0.88)
  })
})
