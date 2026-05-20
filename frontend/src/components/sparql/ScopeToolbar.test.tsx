import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ScopeToolbar } from './ScopeToolbar'

vi.mock('../../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [],
    isLoading: false,
  }),
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('ScopeToolbar — empty state', () => {
  it('shows the "No scope" summary when nothing is selected', () => {
    render(wrap(
      <ScopeToolbar
        onScopeChange={vi.fn()}
        onCopy={vi.fn()}
      />
    ))
    expect(screen.getByText(/No scope selected/i)).toBeInTheDocument()
  })

  it('renders three reasoning options, all disabled', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    const asserted = screen.getByRole('button', { name: /asserted/i })
    const inferred = screen.getByRole('button', { name: /inferred/i })
    const both = screen.getByRole('button', { name: /both/i })
    expect(asserted).toBeDisabled()
    expect(inferred).toBeDisabled()
    expect(both).toBeDisabled()
  })

  it('renders an "add ontology" button', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    expect(screen.getByRole('button', { name: /add ontology/i })).toBeInTheDocument()
  })

  it('renders a copy button', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    expect(screen.getByRole('button', { name: /copy query with scope/i })).toBeInTheDocument()
  })
})
