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
      delete: vi.fn().mockResolvedValue(undefined),
      patch: vi.fn().mockResolvedValue(undefined),
    },
    admin: {
      checkUpdate: vi.fn().mockResolvedValue({ status: 'up_to_date' }),
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

test('shows add form when button is clicked', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  expect(screen.getByPlaceholderText(/purl.obolibrary/)).toBeInTheDocument()
})

test('hides add form when cancel is clicked', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('× Cancel'))
  expect(screen.queryByPlaceholderText(/purl.obolibrary/)).not.toBeInTheDocument()
})

test('renders ontology rows', async () => {
  wrap()
  // Dashboard shows displayName (slug from IRI), not the full IRI as text.
  // The slug appears in multiple places per row (name link + shortname/title), so use getAllByText.
  await waitFor(() => expect(screen.getAllByText('go').length).toBeGreaterThan(0))
  expect(screen.getAllByText('chebi').length).toBeGreaterThan(0)
})

test('shows confirm delete UI on delete button click', async () => {
  wrap()
  await waitFor(() => expect(screen.getAllByText('go').length).toBeGreaterThan(0))
  const deleteButtons = screen.getAllByText('Delete')
  fireEvent.click(deleteButtons[0])
  // After clicking Delete, confirmation shows yes/no buttons
  expect(screen.getByText('yes')).toBeInTheDocument()
  expect(screen.getByText('no')).toBeInTheDocument()
})
