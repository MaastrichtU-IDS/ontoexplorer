import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Submissions from './Submissions'
import { api } from '../lib/api'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual('../lib/api')
  return {
    ...actual,
    api: { ...(actual as any).api, ontologies: { submissions: vi.fn() } },
  }
})

const mockSubs = api.ontologies.submissions as ReturnType<typeof vi.fn>

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Submissions /></MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Submissions', () => {
  it('shows an outcome chip per submission, in contributor vocabulary', async () => {
    mockSubs.mockResolvedValue({ submissions: [
      { task_id: 't1', job_status: 'done', created_at: '2026-10-24T10:00:00Z', finished_at: null,
        error: null, ontology: { id: 'o1', shortname: 'go', title: 'Gene Ontology' },
        version: { id: 'v1', status: 'ready' } },
      { task_id: 't2', job_status: 'done', created_at: '2026-10-24T11:00:00Z', finished_at: null,
        error: null, ontology: { id: 'o2', shortname: 'bad', title: 'Held One' },
        version: { id: 'v2', status: 'needs_review' } },
      { task_id: 't3', job_status: 'failed', created_at: '2026-10-24T12:00:00Z', finished_at: null,
        error: 'boom', ontology: null, version: null },
    ] })
    wrap()
    expect(await screen.findByText('Published')).toBeInTheDocument()
    expect(screen.getByText('Needs your attention')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    // Never surfaces the raw gate status.
    expect(screen.queryByText('needs_review')).toBeNull()
  })

  it('shows an empty state when there are no submissions', async () => {
    mockSubs.mockResolvedValue({ submissions: [] })
    wrap()
    expect(await screen.findByText('No submissions yet.')).toBeInTheDocument()
  })
})
