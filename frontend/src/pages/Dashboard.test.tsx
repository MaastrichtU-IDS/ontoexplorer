import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from './Dashboard'

vi.mock('../lib/api', () => ({
  slugFromIri: (iri: string) => {
    const last = iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? iri
    return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '').toLowerCase()
  },
  api: {
    auth: {
      me: vi.fn().mockResolvedValue({
        id: 'user-1',
        email: 'test@example.com',
        display_name: 'Test User',
        created_at: '2026-05-01T00:00:00Z',
        is_admin: false,
        connected_providers: [],
      }),
    },
    ontologies: {
      list: vi.fn().mockResolvedValue({
        ontologies: [
          { id: 'ont1', iri: 'http://example.org/go.owl', created_at: '2026-05-10T00:00:00Z' },
          { id: 'ont2', iri: 'http://example.org/chebi.owl', created_at: '2026-05-08T00:00:00Z' },
        ],
        offset: 0,
        limit: 50,
      }),
      versions: vi.fn().mockResolvedValue({
        versions: [
          {
            id: 'v1', ontology_id: 'ont1', version_iri: 'http://example.org/go/2024',
            format: 'owl', status: 'ready', sha256: 'abc', triple_count: 1200000,
            download_url: '/dl', created_at: '2026-05-10T00:00:00Z',
          },
        ],
      }),
      stats: vi.fn().mockResolvedValue({
        triple_count: 1200000, class_count: 50000,
        object_property_count: 100, datatype_property_count: 50,
      }),
      submitByIri: vi.fn().mockResolvedValue({ task_id: 'task-1', status: 'queued' }),
      submitByUrl: vi.fn().mockResolvedValue({ task_id: 'task-2', status: 'queued' }),
      submitByContent: vi.fn().mockResolvedValue({ task_id: 'task-3', status: 'queued' }),
      submitFile: vi.fn().mockResolvedValue({ task_id: 'task-4', status: 'queued' }),
      delete: vi.fn().mockResolvedValue(undefined),
      patch: vi.fn().mockResolvedValue(undefined),
    },
    stats: {
      usageMine: vi.fn().mockResolvedValue({
        granularity: 'month',
        totals: { views: { unique: 30, total: 75 }, downloads: { unique: 4, total: 9 } },
        per_ontology: [
          { ontology_id: 'ont1', shortname: 'go', title: 'Gene Ontology',
            view_unique: 30, view_total: 75, download_unique: 4, download_total: 9 },
        ],
        trend: [{ period: '2026-07', view_unique: 30, view_total: 75, download_unique: 4, download_total: 9 }],
      }),
    },
    admin: {
      checkUpdate: vi.fn().mockResolvedValue({ status: 'up_to_date' }),
    },
    jobs: {
      get: vi.fn().mockResolvedValue({
        id: 'task-1', version_id: null, type: 'ingestion', status: 'running',
        started_at: null, finished_at: null, error: null, created_at: '2026-08-20T00:00:00Z',
      }),
    },
    reasonerProfiles: {
      list: vi.fn().mockResolvedValue({ profiles: [
        { id: 'p1', name: 'rustdl (default)', reasoner: 'rustdl', params: {}, is_default: true, description: null },
        { id: 'p2', name: 'konclude', reasoner: 'konclude', params: {}, is_default: false, description: null },
      ] }),
    },
  },
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders heading', () => {
  wrap()
  expect(screen.getByText('My Ontologies')).toBeInTheDocument()
})

test('renders ontology rows', async () => {
  wrap()
  // Dashboard shows displayName (slug from IRI), not the full IRI as text.
  await waitFor(() => expect(screen.getAllByText('go').length).toBeGreaterThan(0))
  expect(screen.getAllByText('chebi').length).toBeGreaterThan(0)
})

test('shows confirm delete UI on delete button click', async () => {
  wrap()
  await waitFor(() => expect(screen.getAllByText('go').length).toBeGreaterThan(0))
  const deleteButtons = screen.getAllByText('Delete')
  fireEvent.click(deleteButtons[0])
  expect(screen.getByText('yes')).toBeInTheDocument()
  expect(screen.getByText('no')).toBeInTheDocument()
})

test('does not duplicate the views/downloads section — it lives on the Stats page', async () => {
  wrap()
  await waitFor(() => expect(screen.getAllByText('go').length).toBeGreaterThan(0))
  expect(screen.queryByText(/Views & Downloads/)).not.toBeInTheDocument()
})

// Adding moved to its own page (/dashboard/add); the header control is now a link
// there, not an inline toggle. The form itself is covered by AddOntologyForm.test.
test('the "+ Add Ontology" control links to the add page', () => {
  wrap()
  const link = screen.getByText('+ Add Ontology').closest('a')
  expect(link).toHaveAttribute('href', '/dashboard/add')
})
