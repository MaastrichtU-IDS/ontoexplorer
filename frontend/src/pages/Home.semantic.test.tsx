import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../hooks/useSearch', () => ({
  useGlobalSearch: () => ({
    data: {
      results: [],
      semantic_results: [
        {
          iri: 'http://example.org/Heart',
          label: 'heart',
          short: 'Heart',
          type: 'class',
          match_type: 'semantic',
          score: 0.92,
        },
      ],
    },
  }),
  useAutocomplete: () => ({ data: null }),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: [] }),
}))

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      stats: { public: () => Promise.resolve({ total_ontologies: 0, total_classes: 0, total_properties: 0, total_individuals: 0 }) },
      ontologies: {
        ...actual.api.ontologies,
        search: () => Promise.resolve({ results: [], count: 0, truncated: false }),
      },
    },
  }
})

import Home from './Home'

describe('Home semantic results', () => {
  it('shows "Semantically similar" section when semantic_results is non-empty', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><Home /></MemoryRouter>
      </QueryClientProvider>
    )
    expect(screen.queryByText('Semantically similar')).not.toBeNull()
  })
})
