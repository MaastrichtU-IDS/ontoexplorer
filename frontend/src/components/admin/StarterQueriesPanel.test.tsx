import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi } from 'vitest'
import { StarterQueriesPanel } from './StarterQueriesPanel'

vi.mock('../../lib/api', () => ({
  api: {
    admin: { importStarters: vi.fn() },
  },
}))
import { api } from '../../lib/api'
const mockImport = api.admin.importStarters as ReturnType<typeof vi.fn>

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('StarterQueriesPanel', () => {
  it('renders three input zones', () => {
    render(wrap(<StarterQueriesPanel />))
    expect(screen.getByLabelText(/paste/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/upload/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/url/i)).toBeInTheDocument()
  })

  it('paste import calls api with the typed text', async () => {
    mockImport.mockResolvedValue({ created: 2, skipped: 0, errors: [] })
    render(wrap(<StarterQueriesPanel />))
    fireEvent.change(screen.getByLabelText(/paste/i), { target: { value: '{"starters":[]}' } })
    fireEvent.click(screen.getByRole('button', { name: /import paste/i }))
    await waitFor(() => expect(mockImport).toHaveBeenCalledWith({ text: '{"starters":[]}' }))
    expect(screen.getByText(/imported 2/i)).toBeInTheDocument()
  })

  it('url import calls api with the typed URL', async () => {
    mockImport.mockResolvedValue({ created: 1, skipped: 0, errors: [] })
    render(wrap(<StarterQueriesPanel />))
    fireEvent.change(screen.getByLabelText(/url/i), { target: { value: 'https://example.com/lib.json' } })
    fireEvent.click(screen.getByRole('button', { name: /import url/i }))
    await waitFor(() => expect(mockImport).toHaveBeenCalledWith({ source_url: 'https://example.com/lib.json' }))
  })

  it('shows error count when import returns errors', async () => {
    mockImport.mockResolvedValue({ created: 0, skipped: 1, errors: [{ index: 0, reason: 'duplicate name' }] })
    render(wrap(<StarterQueriesPanel />))
    fireEvent.change(screen.getByLabelText(/paste/i), { target: { value: '{"starters":[{"name":"x","query_text":"y"}]}' } })
    fireEvent.click(screen.getByRole('button', { name: /import paste/i }))
    await waitFor(() => expect(screen.getByText(/1 error/i)).toBeInTheDocument())
  })
})
