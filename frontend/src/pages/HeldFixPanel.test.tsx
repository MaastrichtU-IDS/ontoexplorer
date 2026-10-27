import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HeldFixPanel } from './Dashboard'
import type { OntologyVersion } from '../lib/api'

const { mockCandidates, mockPatch, mockReeval, mockLicenses } = vi.hoisted(() => ({
  mockCandidates: vi.fn(),
  mockPatch: vi.fn().mockResolvedValue({}),
  mockReeval: vi.fn().mockResolvedValue({ status: 'ready', review_reasons: [], declared_license: null }),
  mockLicenses: vi.fn().mockResolvedValue({ licenses: [{ spdx: 'CC0-1.0', label: 'CC0 1.0' }] }),
}))

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      meta: { candidates: mockCandidates },
      patch: mockPatch,
      reevaluateVersion: mockReeval,
      compliantLicenses: mockLicenses,
    },
  },
  slugFromIri: (s: string) => s,
}))

function held(reasons: string[], extra: Partial<OntologyVersion> = {}): OntologyVersion {
  return { id: 'v1', status: 'needs_review', review_reasons: reasons, license_raw: null,
           license_compliant: null, ...extra } as unknown as OntologyVersion
}

function wrap(version: OntologyVersion, onDone = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <HeldFixPanel ontologyId="o1" version={version} onDone={onDone} />
    </QueryClientProvider>
  )
  return onDone
}

describe('HeldFixPanel title property-chooser', () => {
  beforeEach(() => vi.clearAllMocks())

  it('offers title values from the file and applies the pick before re-running the gate', async () => {
    mockCandidates.mockResolvedValue({
      version_id: 'v1',
      title: [{ iri: 'http://purl.org/dc/terms/title', values: ['Gene Ontology'], label: 'dcterms:title' }],
    })
    const onDone = wrap(held(['no title']))

    // The candidate value appears once the profile loads.
    const option = await screen.findByText(/Gene Ontology — dcterms:title/)
    const select = option.closest('select') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'Gene Ontology' } })

    fireEvent.click(screen.getByRole('button', { name: 'Publish' }))

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('o1', { title: 'Gene Ontology' }))
    expect(mockReeval).toHaveBeenCalledWith('o1', 'v1', undefined)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('falls back to the manual hint when the file has no title candidates', async () => {
    mockCandidates.mockResolvedValue({ version_id: 'v1', title: [] })
    wrap(held(['no title']))

    expect(await screen.findByText(/Set a title in the Title field above/)).toBeInTheDocument()
    expect(screen.queryByText(/Title from your file/)).toBeNull()
  })

  it('does not fetch candidates or set a title when only a license is missing', async () => {
    wrap(held(['license missing or not on the platform compliance allowlist']))

    // License select is shown; the title chooser is not; candidates are not fetched.
    expect(await screen.findByText('Choose a license…')).toBeInTheDocument()
    expect(mockCandidates).not.toHaveBeenCalled()
    // Wait for the async-loaded license option before selecting it.
    await screen.findByRole('option', { name: 'CC0 1.0' })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'CC0-1.0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(mockReeval).toHaveBeenCalledWith('o1', 'v1', 'CC0-1.0'))
    expect(mockPatch).not.toHaveBeenCalled()
  })
})
