import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import IncrementalReasoningPanel from './IncrementalReasoningPanel'

const { mockStart, mockSubsumed, mockAssert, mockAssertAxioms, mockRetract, mockClose } = vi.hoisted(() => ({
  mockStart: vi.fn().mockResolvedValue({ session_id: 's1', revision: 0, inconsistent: false, total_clauses: 3, clause_ids: [1, 2, 3] }),
  mockSubsumed: vi.fn()
    .mockResolvedValueOnce({ sub: 'A', sup: 'B', entailed: false, revision: 0 })
    .mockResolvedValue({ sub: 'A', sup: 'B', entailed: true, revision: 1 }),
  mockAssert: vi.fn().mockResolvedValue({ revision: 1, inconsistent: false, clause_ids: [42] }),
  mockAssertAxioms: vi.fn().mockResolvedValue({ revision: 2, inconsistent: false, clause_ids: [7, 8] }),
  mockRetract: vi.fn().mockResolvedValue({ revision: 3, inconsistent: false }),
  mockClose: vi.fn().mockResolvedValue({ closed: true }),
}))

vi.mock('../lib/api', () => ({
  api: { ontologies: { incremental: { start: mockStart, subsumed: mockSubsumed, assert: mockAssert, assertAxioms: mockAssertAxioms, retract: mockRetract, close: mockClose } } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('IncrementalReasoningPanel', () => {
  it('starts a session, queries subsumption, and flips after asserting an axiom', async () => {
    wrap(<IncrementalReasoningPanel ontologyId="o1" versionId="v1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Start session' }))
    await waitFor(() => expect(mockStart).toHaveBeenCalledWith('o1', 'v1'))
    expect(await screen.findByText(/session live/)).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('sub class (name or IRI)'), { target: { value: 'A' } })
    fireEvent.change(screen.getByPlaceholderText('super class (name or IRI)'), { target: { value: 'B' } })

    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(mockSubsumed).toHaveBeenCalledWith('o1', 'v1', 's1', 'A', 'B'))
    expect(await screen.findByText('not entailed')).toBeInTheDocument()

    // Assert the axiom → it re-queries → now entailed.
    fireEvent.click(screen.getByRole('button', { name: '+ Assert ⊑' }))
    await waitFor(() => expect(mockAssert).toHaveBeenCalledWith('o1', 'v1', 's1', 'A', 'B'))
    expect(await screen.findByText('entailed')).toBeInTheDocument()

    // The asserted axiom is tracked and can be retracted by its clause ids.
    const retractBtn = await screen.findByRole('button', { name: /retract/ })
    fireEvent.click(retractBtn)
    await waitFor(() => expect(mockRetract).toHaveBeenCalledWith('o1', 'v1', 's1', [42]))
  })

  it('asserts arbitrary OWL functional-syntax axioms and tracks them for retraction', async () => {
    wrap(<IncrementalReasoningPanel ontologyId="o1" versionId="v1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start session' }))
    expect(await screen.findByText(/session live/)).toBeInTheDocument()

    const ofn = 'EquivalentClasses(<http://x/D> <http://x/A>)'
    fireEvent.change(screen.getByPlaceholderText(/SubClassOf/), { target: { value: ofn } })
    fireEvent.click(screen.getByRole('button', { name: '+ Assert axioms' }))

    await waitFor(() => expect(mockAssertAxioms).toHaveBeenCalledWith('o1', 'v1', 's1', ofn))
    // Tracked in the asserted list (by its returned clause ids) and retractable.
    const retractBtn = await screen.findByRole('button', { name: /retract/ })
    fireEvent.click(retractBtn)
    await waitFor(() => expect(mockRetract).toHaveBeenCalledWith('o1', 'v1', 's1', [7, 8]))
  })
})
