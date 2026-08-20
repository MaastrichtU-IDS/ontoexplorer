import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

import { api } from '../lib/api'
const mockSubmitByIri = api.ontologies.submitByIri as ReturnType<typeof vi.fn>
const mockJobGet = api.jobs.get as ReturnType<typeof vi.fn>
const mockSubmitByContent = api.ontologies.submitByContent as ReturnType<typeof vi.fn>
const mockSubmitFile = api.ontologies.submitFile as ReturnType<typeof vi.fn>
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
  expect(screen.getByLabelText(/ontology iri or url/i)).toBeInTheDocument()
})

test('hides add form when cancel is clicked', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('× Cancel'))
  expect(screen.queryByLabelText(/ontology iri or url/i)).not.toBeInTheDocument()
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
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
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

  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() =>
    expect(mockSubmitByIri).toHaveBeenCalledWith('https://purl.obolibrary.org/obo/go.owl', 'p2')
  )
})

test('does not duplicate the views/downloads section — it lives on the Stats page', async () => {
  wrap()
  await waitFor(() => expect(screen.getAllByText('go').length).toBeGreaterThan(0))
  expect(screen.queryByText(/Views & Downloads/)).not.toBeInTheDocument()
})

// A submission that fails before any version exists (unreachable IRI, source over
// the download cap, unparseable file) used to leave the UI showing only
// "Queued — task ID: …" forever; the error reached the worker log and nowhere
// else. The submit response's task_id is the ingestion job id, so the form
// polls GET /jobs/{id} and reports the outcome.
test('reports an ingestion failure returned by the job poll', async () => {
  mockJobGet.mockResolvedValue({
    id: 'task-1', version_id: null, type: 'ingestion', status: 'failed',
    started_at: null, finished_at: null,
    error: 'Response exceeds size limit (706398355 bytes, limit 536870912 bytes)',
    created_at: '2026-08-20T00:00:00Z',
  })

  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'http://purl.obolibrary.org/obo/dron.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() => expect(mockJobGet).toHaveBeenCalledWith('task-1'))
  expect(await screen.findByText(/exceeds size limit/)).toBeInTheDocument()
  expect(await screen.findByText(/Failed/)).toBeInTheDocument()
})

test('closes the add form once the job poll reports the ingestion is done', async () => {
  mockJobGet.mockResolvedValue({
    id: 'task-1', version_id: 'ver-1', type: 'ingestion', status: 'done',
    started_at: null, finished_at: null, error: null,
    created_at: '2026-08-20T00:00:00Z',
  })

  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() => expect(mockJobGet).toHaveBeenCalledWith('task-1'))
  // onSuccess refreshes the list and closes the form.
  await waitFor(() =>
    expect(screen.queryByLabelText(/ontology iri or url/i)).not.toBeInTheDocument()
  )
})

test('keeps polling while the job is still running, then reports the failure', async () => {
  // The common path: ingestion takes a while, so the first polls come back
  // "running" and only a later one carries the verdict.
  mockJobGet
    .mockResolvedValueOnce({
      id: 'task-1', version_id: null, type: 'ingestion', status: 'running',
      started_at: null, finished_at: null, error: null, created_at: '2026-08-20T00:00:00Z',
    })
    .mockResolvedValue({
      id: 'task-1', version_id: null, type: 'ingestion', status: 'failed',
      started_at: null, finished_at: null,
      error: 'Downloaded content exceeds size limit (2147483648 bytes)',
      created_at: '2026-08-20T00:00:00Z',
    })

  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'http://purl.obolibrary.org/obo/dron.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  expect(await screen.findByText(/Ingesting…/)).toBeInTheDocument()
  expect(await screen.findByText(/exceeds size limit/, {}, { timeout: 5000 })).toBeInTheDocument()
  expect(mockJobGet.mock.calls.length).toBeGreaterThan(1)
}, 10000)

test('renders an ingestion failure in red and progress in the normal colour', async () => {
  mockJobGet.mockResolvedValue({
    id: 'task-1', version_id: null, type: 'ingestion', status: 'failed',
    started_at: null, finished_at: null,
    error: 'Response exceeds size limit (706398355 bytes, limit 536870912 bytes)',
    created_at: '2026-08-20T00:00:00Z',
  })

  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'http://purl.obolibrary.org/obo/dron.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  const failed = await screen.findByText(/exceeds size limit/)
  expect(failed.style.color).toBe('var(--red-soft)')
})

test('renders a queued/progress message in the accent colour, not red', async () => {
  mockJobGet.mockResolvedValue({
    id: 'task-1', version_id: null, type: 'ingestion', status: 'running',
    started_at: null, finished_at: null, error: null, created_at: '2026-08-20T00:00:00Z',
  })

  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))

  const progress = await screen.findByText(/Ingesting…/)
  expect(progress.style.color).toBe('var(--accent)')
})

// ── Merged IRI/URL tab ────────────────────────────────────────────────────────
// "By IRI" and "By URL" differed only in whether the fetch sent an RDF Accept
// header. One tab that always content-negotiates covers both: static file
// servers ignore Accept, so a direct URL still resolves.
test('offers a single combined IRI/URL tab', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  expect(screen.getByText('By IRI or URL')).toBeInTheDocument()
  expect(screen.queryByText('By URL')).not.toBeInTheDocument()
})

test('the combined tab submits a plain URL through the content-negotiating path', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://raw.githubusercontent.com/org/repo/main/o.ttl' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() =>
    expect(mockSubmitByIri).toHaveBeenCalledWith(
      'https://raw.githubusercontent.com/org/repo/main/o.ttl', undefined,
    )
  )
})

// ── Paste format selector ─────────────────────────────────────────────────────
test('paste format defaults to auto-detect and offers Manchester and Functional', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('Paste RDF'))

  const select = screen.getByLabelText(/format/i) as HTMLSelectElement
  expect(select.value).toBe('')
  const opts = within(select)
  expect(opts.getByRole('option', { name: /Auto-detect/ })).toBeInTheDocument()
  expect(opts.getByRole('option', { name: /Manchester/ })).toBeInTheDocument()
  expect(opts.getByRole('option', { name: /Functional/ })).toBeInTheDocument()
})

test('pasting with auto-detect sends no explicit format', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('Paste RDF'))
  fireEvent.change(screen.getByPlaceholderText(/Paste your/), {
    target: { value: 'Class: :Person' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() =>
    expect(mockSubmitByContent).toHaveBeenCalledWith('Class: :Person', '', undefined)
  )
})

test('choosing Manchester sends the omn format key', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('Paste RDF'))
  fireEvent.change(screen.getByLabelText(/format/i), { target: { value: 'omn' } })
  fireEvent.change(screen.getByPlaceholderText(/Paste your/), {
    target: { value: 'Class: :Person' },
  })
  fireEvent.click(screen.getByText('Add'))

  await waitFor(() =>
    expect(mockSubmitByContent).toHaveBeenCalledWith('Class: :Person', 'omn', undefined)
  )
})

test('the upload tab offers the same auto-detect format override', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('Upload file'))

  const select = screen.getByLabelText(/format/i) as HTMLSelectElement
  expect(select.value).toBe('')
  const opts = within(select)
  expect(opts.getByRole('option', { name: /Auto-detect/ })).toBeInTheDocument()
  expect(opts.getByRole('option', { name: /Manchester/ })).toBeInTheDocument()
})

test('an upload sends the chosen format to the API', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('Upload file'))
  fireEvent.change(screen.getByLabelText(/format/i), { target: { value: 'omn' } })

  // A file whose extension lies about its contents — the case the override
  // exists for, since detection would otherwise trust ".owl".
  // jsdom makes input.files read-only, so drive the picker through user-event
  // (v14 needs an explicit setup() session, and filters against `accept`).
  const user = userEvent.setup()
  const file = new File(['Class: :Person'], 'ontology.owl', { type: '' })
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  await user.upload(input, file)
  // Submit the form directly: jsdom's click-to-submit path runs constraint
  // validation against the `required` file input and swallows the submit even
  // once a file is attached. The click path is covered by the other tests.
  fireEvent.submit(input.closest('form')!)

  await waitFor(() =>
    expect(mockSubmitFile).toHaveBeenCalledWith(file, undefined, 'omn')
  )
})
