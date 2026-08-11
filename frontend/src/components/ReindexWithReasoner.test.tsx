import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReindexWithReasoner from './ReindexWithReasoner'

const { mockReason, mockReasoners } = vi.hoisted(() => ({
  mockReason: vi.fn().mockResolvedValue({ status: 'queued', reasoner: 'rustdl', version_id: 'v1' }),
  mockReasoners: vi.fn().mockResolvedValue([
    { name: 'whelk', profile: 'EL', capabilities: ['classify', 'consistency'], available: true },
    { name: 'rustdl', profile: 'DL', capabilities: ['classify', 'justify'], available: true },
    { name: 'rdflib', profile: 'RDFS', capabilities: [], available: true },        // no classify → excluded
    { name: 'downservice', profile: 'DL', capabilities: ['classify'], available: false }, // down → excluded
  ]),
}))

vi.mock('../lib/api', () => ({
  api: { reasoners: { list: mockReasoners }, ontologies: { reason: mockReason } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ReindexWithReasoner', () => {
  it('defaults to the previous reasoner, lists only classify-capable available ones, and re-indexes', async () => {
    wrap(<ReindexWithReasoner ontologyId="o1" versionId="v1" currentReasoner="rustdl" />)

    const select = await screen.findByRole('combobox') as HTMLSelectElement
    // Default = previously-selected reasoner.
    expect(select.value).toBe('rustdl')
    // Only available + classify-capable reasoners are offered.
    await waitFor(() => expect(screen.getByRole('option', { name: 'whelk' })).toBeInTheDocument())
    expect(screen.getByRole('option', { name: 'rustdl' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'rdflib' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'downservice' })).not.toBeInTheDocument()

    // Button re-indexes with the current selection.
    fireEvent.click(screen.getByRole('button', { name: /Re-index with reasoner/i }))
    await waitFor(() => expect(mockReason).toHaveBeenCalledWith('o1', 'v1', 'rustdl'))
    expect(await screen.findByText('queued')).toBeInTheDocument()
  })

  it('re-indexes with a newly chosen reasoner', async () => {
    mockReason.mockClear()
    wrap(<ReindexWithReasoner ontologyId="o2" versionId="v9" currentReasoner="rustdl" />)
    const select = await screen.findByRole('combobox')
    await screen.findByRole('option', { name: 'whelk' })  // wait for reasoners to load
    fireEvent.change(select, { target: { value: 'whelk' } })
    fireEvent.click(screen.getByRole('button', { name: /Re-index with reasoner/i }))
    await waitFor(() => expect(mockReason).toHaveBeenCalledWith('o2', 'v9', 'whelk'))
  })
})
