import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
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

  it('auto-expands when a held version arrives AFTER mount (async versions query)', async () => {
    // Regression: the open state used a one-shot useState initializer that ran while
    // `versions` was still [] (query pending) and never re-opened once data loaded,
    // leaving the held version buried behind the collapsed "▸ N versions" toggle.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const ui = (versions: OntologyVersion[]) => (
      <QueryClientProvider client={qc}>
        <VersionManager ontology={ontology} versions={versions} />
      </QueryClientProvider>
    )
    const { rerender } = render(ui([]))
    expect(screen.queryByText(/set aside after inactivity/)).toBeNull()

    // Versions resolve with a held draft → must auto-expand on its own.
    await act(async () => { rerender(ui([retired()])) })
    expect(await screen.findByText(/set aside after inactivity/)).toBeInTheDocument()
  })

  it('surfaces the OWL 2 profile cause when a version could not be profiled', async () => {
    wrap([
      retired(),  // auto-expands the version list
      retired({ id: 'v2', status: 'ready', auto_retired_held: false,
                profile_unavailable: true,
                profile_error_detail: 'http://ex/o is typed voaf:Vocabulary, which the strict OWL reader rejects as an annotation.' }),
    ])
    await screen.findByText(/set aside after inactivity/)   // list is expanded
    const line = await screen.findByTestId('profile-uncomputable')
    expect(line.textContent).toMatch(/OWL.{0,3}2 profile not computed/)
    expect(line.textContent).toMatch(/voaf:Vocabulary/)
    // the version without profile_unavailable shows no such line (only one on the page)
    expect(screen.getAllByTestId('profile-uncomputable')).toHaveLength(1)
  })

  it('shows a collapsed "needs your attention" hint after the user collapses the list', async () => {
    wrap([retired()])
    // Auto-expanded; collapsing should still flag that attention is needed.
    await screen.findByText(/set aside after inactivity/)
    fireEvent.click(screen.getByRole('button', { name: /version/ }))
    expect(screen.getByText(/needs your attention/)).toBeInTheDocument()
    expect(screen.queryByText(/set aside after inactivity/)).toBeNull()
  })
})
