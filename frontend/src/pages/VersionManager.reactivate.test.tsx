import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { VersionManager } from './Dashboard'
import type { Ontology, OntologyVersion } from '../lib/api'

const { mockReactivate, mockDeprecate, mockDelete } = vi.hoisted(() => ({
  mockReactivate: vi.fn().mockResolvedValue({ status: 'needs_review' }),
  mockDeprecate: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      reactivateVersion: mockReactivate,
      deprecateVersion: mockDeprecate,
      deleteVersion: mockDelete,
      compliantLicenses: vi.fn().mockResolvedValue({ licenses: [] }),
      meta: { candidates: vi.fn().mockResolvedValue({ version_id: 'v1', title: [] }) },
    },
  },
  slugFromIri: (s: string) => s,
}))

const ontology = { id: 'o1', iri: 'http://ex/o', title: 'My Ontology' } as unknown as Ontology

function retired(extra: Partial<OntologyVersion> = {}): OntologyVersion {
  return { id: 'v1', status: 'deprecated', auto_retired_held: true, is_default: false,
           created_at: '2026-08-01T00:00:00Z', ...extra } as unknown as OntologyVersion
}

function wrap(versions: OntologyVersion[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <VersionManager ontology={ontology} versions={versions} />
    </QueryClientProvider>
  )
}

describe('VersionManager reactivate', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows a reactivate control for a set-aside held draft and calls the endpoint', async () => {
    wrap([retired()])
    // Auto-expands because an auto-retired draft is present.
    expect(screen.getByText(/set aside after inactivity/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'reactivate' }))
    await waitFor(() => expect(mockReactivate).toHaveBeenCalledWith('o1', 'v1'))
  })

  it('offers no reactivate control for an ordinary deprecated version', () => {
    wrap([retired({ auto_retired_held: false }), retired({ id: 'v2', status: 'ready', auto_retired_held: false })])
    expect(screen.queryByRole('button', { name: 'reactivate' })).toBeNull()
  })
})
