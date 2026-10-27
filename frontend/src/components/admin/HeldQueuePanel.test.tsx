import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HeldQueuePanel } from './HeldQueuePanel'

const { mockHeld, mockBulk } = vi.hoisted(() => ({
  mockHeld: vi.fn().mockResolvedValue({
    min_age_days: 0,
    total: 2,
    versions: [
      {
        version_id: 'v-old', ontology_id: 'o1', ontology_title: 'Old One',
        ontology_shortname: 'old', created_at: '2026-09-01T00:00:00Z', age_days: 40,
        triple_count: 3, license: null, license_raw: null, declared_license: null,
        review_reasons: ['no title', 'license missing or not on the platform compliance allowlist'],
      },
      {
        version_id: 'v-new', ontology_id: 'o2', ontology_title: 'New One',
        ontology_shortname: 'new', created_at: '2026-10-20T00:00:00Z', age_days: 5,
        triple_count: 100, license: null, license_raw: null, declared_license: 'CC0-1.0',
        review_reasons: ['no title'],
      },
    ],
  }),
  mockBulk: vi.fn().mockResolvedValue({
    requested: 2, published: 1,
    results: [
      { version_id: 'v-old', outcome: 'still_held', status: 'needs_review', review_reasons: ['no title'] },
      { version_id: 'v-new', outcome: 'published', status: 'ready', review_reasons: [] },
    ],
  }),
}))

vi.mock('../../lib/api', () => ({
  api: { admin: { heldVersions: mockHeld, bulkReevaluate: mockBulk } },
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HeldQueuePanel />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('HeldQueuePanel', () => {
  it('lists held versions with reasons and ages', async () => {
    wrap()
    expect(await screen.findByText('Old One')).toBeInTheDocument()
    expect(screen.getByText('New One')).toBeInTheDocument()
    expect(screen.getByText('40d')).toBeInTheDocument()
    // "no title" is a reason on both rows.
    expect(screen.getAllByText('no title').length).toBe(2)
    // Header count reflects the total.
    expect(screen.getByText(/Held for review \(2\)/)).toBeInTheDocument()
  })

  it('select-all then re-run gate calls bulkReevaluate and reports the outcome', async () => {
    wrap()
    await screen.findByText('Old One')

    fireEvent.click(screen.getByLabelText('Select all held versions'))
    fireEvent.click(screen.getByRole('button', { name: /Re-run gate \(2\)/ }))

    await waitFor(() => expect(mockBulk).toHaveBeenCalledWith(['v-old', 'v-new']))
    expect(await screen.findByText(/1 published/)).toBeInTheDocument()
    expect(screen.getByText(/1 still held/)).toBeInTheDocument()
  })

  it('disables the re-run button when nothing is selected', async () => {
    wrap()
    await screen.findByText('Old One')
    expect(screen.getByRole('button', { name: /Re-run gate \(0\)/ })).toBeDisabled()
  })
})
