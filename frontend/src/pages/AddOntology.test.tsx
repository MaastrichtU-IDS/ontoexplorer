import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AddOntology from './AddOntology'

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      submitByIri: vi.fn().mockResolvedValue({ task_id: 'task-xyz', status: 'queued' }),
      submitByContent: vi.fn(),
      submitFile: vi.fn(),
    },
    jobs: { get: vi.fn() },
    reasonerProfiles: { list: vi.fn().mockResolvedValue({ profiles: [] }) },
    reasoners: { list: vi.fn().mockResolvedValue([]) },
  },
}))

function SubmissionStub() {
  const { taskId } = useParams()
  return <div>submission page for {taskId}</div>
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard/add']}>
        <Routes>
          <Route path="/dashboard/add" element={<AddOntology />} />
          <Route path="/dashboard/submissions/:taskId" element={<SubmissionStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('on submit, navigates to the durable submission record for the task', async () => {
  wrap()
  fireEvent.change(screen.getByLabelText(/ontology iri or url/i), {
    target: { value: 'https://purl.obolibrary.org/obo/go.owl' },
  })
  fireEvent.click(screen.getByText('Add'))
  expect(await screen.findByText('submission page for task-xyz')).toBeInTheDocument()
})
