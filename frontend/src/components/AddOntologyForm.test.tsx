import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AddOntologyForm from './AddOntologyForm'

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      submitByIri: vi.fn().mockResolvedValue({ task_id: 'task-1', status: 'queued' }),
      submitByContent: vi.fn().mockResolvedValue({ task_id: 'task-3', status: 'queued' }),
      submitFile: vi.fn().mockResolvedValue({ task_id: 'task-4', status: 'queued' }),
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
    reasoners: { list: vi.fn().mockResolvedValue([]) },
  },
}))

import { api } from '../lib/api'
const mockSubmitByIri = api.ontologies.submitByIri as ReturnType<typeof vi.fn>
const mockJobGet = api.jobs.get as ReturnType<typeof vi.fn>
const mockSubmitByContent = api.ontologies.submitByContent as ReturnType<typeof vi.fn>
const mockSubmitFile = api.ontologies.submitFile as ReturnType<typeof vi.fn>
const mockProfilesList = api.reasonerProfiles.list as ReturnType<typeof vi.fn>

// Reset call history before each test so cross-test order can't contaminate
// assertions like not.toHaveBeenCalled(). clearAllMocks resets calls/results only;
// the mockResolvedValue defaults set in the factory survive.
beforeEach(() => vi.clearAllMocks())

function wrap(props: Partial<React.ComponentProps<typeof AddOntologyForm>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AddOntologyForm onSuccess={props.onSuccess} onQueued={props.onQueued} />
    </QueryClientProvider>
  )
}

// ── Tabs & fields ───────────────────────────────────────────────────────────────

test('offers a single combined IRI/URL tab', () => {
  wrap()
  expect(screen.getByText('By IRI or URL')).toBeInTheDocument()
  expect(screen.queryByText('By URL')).not.toBeInTheDocument()
})

test('Advanced disclosure is collapsed by default and hides the reasoner select', () => {
  wrap()
  expect(screen.getByText(/Advanced/)).toBeInTheDocument()
  expect(screen.queryByLabelText(/reasoner/i)).not.toBeInTheDocument()
})

test('expanding Advanced reveals a reasoner-profile select populated from reasonerProfiles.list', async () => {
  wrap()
  fireEvent.click(screen.getByText(/Advanced/))
  await waitFor(() => expect(mockProfilesList).toHaveBeenCalled())
  const select = await screen.findByLabelText(/reasoner profile/i) as HTMLSelectElement
  const opts = within(select)
  expect(opts.getByRole('option', { name: '(default)' })).toBeInTheDocument()
  expect(await opts.findByRole('option', { name: /rustdl \(default\).*rustdl/ })).toBeInTheDocument()
  expect(opts.getByRole('option', { name: /konclude.*konclude/ })).toBeInTheDocument()
})

test('submitting with Advanced left collapsed calls submitByIri with no reasoner', async () => {
  wrap()
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
  fireEvent.click(screen.getByText(/Advanced/))
  const select = await screen.findByLabelText(/reasoner profile/i) as HTMLSelectElement
  await waitFor(() => expect(within(select).getByRole('option', { name: /konclude/ })).toBeInTheDocument())
  fireEvent.change(select, { target: { value: 'p2' } })
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() =>
    expect(mockSubmitByIri).toHaveBeenCalledWith('https://purl.obolibrary.org/obo/go.owl', 'p2')
  )
})

test('the combined tab submits a plain URL through the content-negotiating path', async () => {
  wrap()
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://raw.githubusercontent.com/org/repo/main/o.ttl' },
  })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() =>
    expect(mockSubmitByIri).toHaveBeenCalledWith(
      'https://raw.githubusercontent.com/org/repo/main/o.ttl', undefined)
  )
})

// ── Paste / upload format selector ────────────────────────────────────────────────

test('paste format defaults to auto-detect and offers Manchester and Functional', () => {
  wrap()
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
  fireEvent.click(screen.getByText('Paste RDF'))
  fireEvent.change(screen.getByPlaceholderText(/Paste your/), { target: { value: 'Class: :Person' } })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() =>
    expect(mockSubmitByContent).toHaveBeenCalledWith('Class: :Person', '', undefined)
  )
})

test('choosing Manchester sends the omn format key', async () => {
  wrap()
  fireEvent.click(screen.getByText('Paste RDF'))
  fireEvent.change(screen.getByLabelText(/format/i), { target: { value: 'omn' } })
  fireEvent.change(screen.getByPlaceholderText(/Paste your/), { target: { value: 'Class: :Person' } })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() =>
    expect(mockSubmitByContent).toHaveBeenCalledWith('Class: :Person', 'omn', undefined)
  )
})

test('the upload tab offers the same auto-detect format override', () => {
  wrap()
  fireEvent.click(screen.getByText('Upload file'))
  const select = screen.getByLabelText(/format/i) as HTMLSelectElement
  expect(select.value).toBe('')
  const opts = within(select)
  expect(opts.getByRole('option', { name: /Auto-detect/ })).toBeInTheDocument()
  expect(opts.getByRole('option', { name: /Manchester/ })).toBeInTheDocument()
})

test('an upload sends the chosen format to the API', async () => {
  wrap()
  fireEvent.click(screen.getByText('Upload file'))
  fireEvent.change(screen.getByLabelText(/format/i), { target: { value: 'omn' } })
  const user = userEvent.setup()
  const file = new File(['Class: :Person'], 'ontology.owl', { type: '' })
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  await user.upload(input, file)
  fireEvent.submit(input.closest('form')!)
  await waitFor(() => expect(mockSubmitFile).toHaveBeenCalledWith(file, undefined, 'omn'))
})

// ── Inline tracking (no onQueued) ────────────────────────────────────────────────
// Without onQueued the form polls GET /jobs/{id} and reports the outcome inline;
// the /dashboard/add page passes onQueued instead and hands off to the submission
// record. A submission that fails before any version exists used to show only
// "Queued — task ID: …" forever.

test('reports an ingestion failure returned by the job poll', async () => {
  mockJobGet.mockResolvedValue({
    id: 'task-1', version_id: null, type: 'ingestion', status: 'failed',
    started_at: null, finished_at: null,
    error: 'Response exceeds size limit (706398355 bytes, limit 536870912 bytes)',
    created_at: '2026-08-20T00:00:00Z',
  })
  wrap()
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'http://purl.obolibrary.org/obo/dron.owl' },
  })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() => expect(mockJobGet).toHaveBeenCalledWith('task-1'))
  expect(await screen.findByText(/exceeds size limit/)).toBeInTheDocument()
  expect(await screen.findByText(/Failed/)).toBeInTheDocument()
})

test('calls onSuccess once the job poll reports the ingestion is done', async () => {
  mockJobGet.mockResolvedValue({
    id: 'task-1', version_id: 'ver-1', type: 'ingestion', status: 'done',
    started_at: null, finished_at: null, error: null, created_at: '2026-08-20T00:00:00Z',
  })
  const onSuccess = vi.fn()
  wrap({ onSuccess })
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() => expect(mockJobGet).toHaveBeenCalledWith('task-1'))
  await waitFor(() => expect(onSuccess).toHaveBeenCalled())
})

test('hands off to onQueued (no inline poll) when provided', async () => {
  const onQueued = vi.fn()
  wrap({ onQueued })
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))
  await waitFor(() => expect(onQueued).toHaveBeenCalledWith('task-1'))
  expect(mockJobGet).not.toHaveBeenCalled()
})

test('keeps polling while the job is still running, then reports the failure', async () => {
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
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))
  const progress = await screen.findByText(/Ingesting…/)
  expect(progress.style.color).toBe('var(--accent)')
})
