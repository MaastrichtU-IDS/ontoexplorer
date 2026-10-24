import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SubmissionDetail from './SubmissionDetail'
import { ApiError, api } from '../lib/api'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual('../lib/api')
  return {
    ...actual,
    api: { ...(actual as any).api, ontologies: { submission: vi.fn() } },
  }
})

const mockSub = api.ontologies.submission as ReturnType<typeof vi.fn>

function wrap(taskId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/dashboard/submissions/${taskId}`]}>
        <Routes>
          <Route path="/dashboard/submissions/:taskId" element={<SubmissionDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SubmissionDetail', () => {
  it('offers a dashboard fix link for a held submission', async () => {
    mockSub.mockResolvedValue({
      task_id: 't2', job_status: 'done', created_at: '2026-10-24T11:00:00Z', finished_at: null,
      error: null, ontology: { id: 'o2', shortname: 'bad', title: 'Held One' },
      version: { id: 'v2', status: 'needs_review' },
    })
    wrap('t2')
    expect(await screen.findByText('Needs your attention')).toBeInTheDocument()
    expect(screen.getByText('Fix it on the dashboard →')).toBeInTheDocument()
  })

  it('treats a 404 (worker row not written yet) as still processing, not an error', async () => {
    mockSub.mockRejectedValue(new ApiError('Submission not found', 404, null))
    wrap('t-new')
    expect(await screen.findByText('Processing')).toBeInTheDocument()
    // The 404 must not surface as an error message.
    await waitFor(() => expect(mockSub).toHaveBeenCalled())
    expect(screen.queryByText('Submission not found')).toBeNull()
  })

  it('surfaces a non-404 error instead of masking it as processing', async () => {
    mockSub.mockRejectedValue(new ApiError('Internal error', 500, null))
    wrap('t-err')
    expect(await screen.findByText('Internal error')).toBeInTheDocument()
    expect(screen.queryByText('Processing')).toBeNull()
  })

  it('links to the published ontology when ready', async () => {
    mockSub.mockResolvedValue({
      task_id: 't1', job_status: 'done', created_at: '2026-10-24T10:00:00Z', finished_at: '2026-10-24T10:05:00Z',
      error: null, ontology: { id: 'o1', shortname: 'go', title: 'Gene Ontology' },
      version: { id: 'v1', status: 'ready' },
    })
    wrap('t1')
    expect(await screen.findByText('View published ontology →')).toBeInTheDocument()
  })
})
