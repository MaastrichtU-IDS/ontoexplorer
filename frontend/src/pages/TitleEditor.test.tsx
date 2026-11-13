import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TitleEditor } from './Dashboard'
import type { Ontology } from '../lib/api'

const { mockPatch } = vi.hoisted(() => ({ mockPatch: vi.fn().mockResolvedValue({}) }))

vi.mock('../lib/api', () => ({
  api: { ontologies: { patch: mockPatch } },
  slugFromIri: (s: string) => s,
}))

function ont(extra: Partial<Ontology> = {}): Ontology {
  return {
    id: 'o1', iri: 'http://ex/pro', shortname: 'pro', title: null,
    created_at: '2026-01-01T00:00:00Z', label: 'Protein Ontology', ...extra,
  } as unknown as Ontology
}

function wrap(o: Ontology) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <TitleEditor ontology={o} />
    </QueryClientProvider>
  )
}

describe('TitleEditor blank-means-auto', () => {
  beforeEach(() => vi.clearAllMocks())

  it('opens EMPTY (not pre-filled with the auto label) when there is no manual title', () => {
    // The bug: the editor seeded the input with the auto-resolved `label`, so
    // clearing it and saving made the identical auto name reappear — reading as
    // "it reverted to the original title". The input must open blank instead.
    wrap(ont({ title: null, label: 'Protein Ontology' }))
    fireEvent.click(screen.getByTitle('Edit title'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    expect(input.value).toBe('')
    // the auto name is offered as ghost text + an explanatory hint, not as a value
    expect(input.placeholder).toBe('Protein Ontology')
    expect(screen.getByText(/Leave blank to use the auto-resolved name/)).toBeInTheDocument()
    expect(screen.getByText(/Protein Ontology/)).toBeInTheDocument()
  })

  it('seeds the input with the MANUAL title when one is set', () => {
    wrap(ont({ title: 'My Custom Name', label: 'Protein Ontology' }))
    fireEvent.click(screen.getByTitle('Edit title'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    expect(input.value).toBe('My Custom Name')
  })

  it('clearing a manual title and saving sends { title: null }, not the auto label', async () => {
    wrap(ont({ title: 'My Custom Name', label: 'Protein Ontology' }))
    fireEvent.click(screen.getByTitle('Edit title'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(screen.getByText('save'))
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('o1', { title: null }))
  })

  it('saves a trimmed manual title', async () => {
    wrap(ont({ title: null, label: 'Protein Ontology' }))
    fireEvent.click(screen.getByTitle('Edit title'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  Protein Ontology (curated)  ' } })
    fireEvent.click(screen.getByText('save'))
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('o1', { title: 'Protein Ontology (curated)' }))
  })
})
