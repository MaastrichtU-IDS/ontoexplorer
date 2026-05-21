import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import QuerySidebar from './QuerySidebar'

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: null }) }))

vi.mock('../lib/api', () => ({
  api: {
    savedQueries: {
      list: vi.fn().mockResolvedValue({ queries: [] }),
      listStarters: vi.fn().mockResolvedValue({
        starters: [
          { id: 's1', name: 'All classes', description: 'desc 1', category: 'Exploration',
            tags: [], query_text: 'SELECT * WHERE { ?s ?p ?o }',
            is_starter: true, is_public: true, created_at: null, updated_at: null },
          { id: 's2', name: 'Subclasses', description: 'desc 2', category: 'Term lookup',
            tags: [], query_text: 'SELECT ?sub WHERE {}',
            is_starter: true, is_public: true, created_at: null, updated_at: null },
        ],
      }),
    },
    ontologies: { list: vi.fn().mockResolvedValue({ ontologies: [] }) },
  },
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('QuerySidebar — Starters', () => {
  it('shows starters for anonymous users', async () => {
    const yasgui = { getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }) } as any
    render(wrap(<QuerySidebar yasguiRef={{ current: yasgui }} />))
    await waitFor(() => {
      expect(screen.getByText('All classes')).toBeInTheDocument()
      expect(screen.getByText('Subclasses')).toBeInTheDocument()
    })
  })

  it('clicking a starter calls setValue with its query_text', async () => {
    const setValueMock = vi.fn()
    const yasgui = { getTab: () => ({ getYasqe: () => ({ setValue: setValueMock }) }) } as any
    render(wrap(<QuerySidebar yasguiRef={{ current: yasgui }} />))
    await waitFor(() => screen.getByText('All classes'))
    fireEvent.click(screen.getByText('All classes'))
    expect(setValueMock).toHaveBeenCalledWith('SELECT * WHERE { ?s ?p ?o }')
  })

  it('groups starters by category', async () => {
    const yasgui = { getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }) } as any
    render(wrap(<QuerySidebar yasguiRef={{ current: yasgui }} />))
    await waitFor(() => screen.getByText('All classes'))
    expect(screen.getByText('Exploration')).toBeInTheDocument()
    expect(screen.getByText('Term lookup')).toBeInTheDocument()
  })
})
