import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
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
    reasonerProfiles: {
      list: vi.fn().mockResolvedValue({ profiles: [
        { id: 'p1', name: 'rustdl (default)', reasoner: 'rustdl', params: {}, is_default: true, description: null },
        { id: 'p2', name: 'konclude', reasoner: 'konclude', params: {}, is_default: false, description: null },
      ] }),
    },
  },
}))

import { api } from '../lib/api'
const mockSubmitByIri = api.ontologies.submitByIri as ReturnType<typeof vi.fn>
const mockProfilesList = api.reasonerProfiles.list as ReturnType<typeof vi.fn>

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

test('Advanced disclosure is collapsed by default and hides the reasoner select', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  expect(screen.getByText(/Advanced/)).toBeInTheDocument()
  expect(screen.queryByLabelText(/reasoner/i)).not.toBeInTheDocument()
})

test('expanding Advanced reveals a reasoner-profile select populated from reasonerProfiles.list', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText(/Advanced/))

  await waitFor(() => expect(mockProfilesList).toHaveBeenCalled())
  const select = await screen.findByLabelText(/reasoner profile/i) as HTMLSelectElement
  expect(select).toBeInTheDocument()

  // Scope option assertions to the add-form select (ontology-card reindex
  // controls also render profile dropdowns on this page).
  const opts = within(select)
  expect(opts.getByRole('option', { name: '(default)' })).toBeInTheDocument()
  expect(await opts.findByRole('option', { name: 'rustdl (default)' })).toBeInTheDocument()
  expect(opts.getByRole('option', { name: 'konclude' })).toBeInTheDocument()
})

test('submitting with Advanced left collapsed calls submitByIri with no reasoner', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByPlaceholderText(/purl.obolibrary/), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() =>
    expect(mockSubmitByIri).toHaveBeenCalledWith('https://purl.obolibrary.org/obo/go.owl', undefined)
  )
})

test('choosing a reasoner profile under Advanced threads it into the submit call', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText(/Advanced/))

  const select = await screen.findByLabelText(/reasoner profile/i)
  await waitFor(() => expect(screen.getByRole('option', { name: 'konclude' })).toBeInTheDocument())
  fireEvent.change(select, { target: { value: 'p2' } })

  fireEvent.change(screen.getByPlaceholderText(/purl.obolibrary/), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() =>
    expect(mockSubmitByIri).toHaveBeenCalledWith('https://purl.obolibrary.org/obo/go.owl', 'p2')
  )
})

test('shows the "my ontologies" usage section with per-ontology views/downloads', async () => {
  wrap()
  expect(await screen.findByText(/Views & Downloads — my ontologies/)).toBeInTheDocument()
  // Per-ontology row (title links to the ontology) with its counts.
  expect(await screen.findByText('Gene Ontology')).toBeInTheDocument()
  expect(screen.getByText('30 / 75')).toBeInTheDocument()   // views unique / total
  expect(screen.getByText('4 / 9')).toBeInTheDocument()     // downloads unique / total
})
