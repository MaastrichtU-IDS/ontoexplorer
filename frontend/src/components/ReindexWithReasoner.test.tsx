import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReindexWithReasoner from './ReindexWithReasoner'

const { mockReason, mockUserProfiles, mockAdminProfiles } = vi.hoisted(() => ({
  mockReason: vi.fn().mockResolvedValue({ status: 'queued', reasoner: 'rustdl', profile_id: 'p1', version_id: 'v1' }),
  mockUserProfiles: vi.fn().mockResolvedValue({ profiles: [
    { id: 'p1', name: 'rustdl (default)', reasoner: 'rustdl', params: {}, is_default: true, archived: false, description: null, dashboard_selectable: true },
    { id: 'p2', name: 'rustdl full DL', reasoner: 'rustdl', params: {}, is_default: false, archived: false, description: null, dashboard_selectable: true },
  ] }),
  mockAdminProfiles: vi.fn().mockResolvedValue({ profiles: [
    { id: 'p1', name: 'rustdl (default)', reasoner: 'rustdl', params: {}, is_default: true, archived: false, description: null, dashboard_selectable: true },
    { id: 'pk', name: 'konclude', reasoner: 'konclude', params: {}, is_default: false, archived: false, description: null, dashboard_selectable: false },
  ] }),
}))

vi.mock('../lib/api', () => ({
  api: {
    ontologies: { reason: mockReason },
    reasonerProfiles: { list: mockUserProfiles },
    admin: { reasonerProfiles: mockAdminProfiles },
  },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ReindexWithReasoner (profiles)', () => {
  it('offers dashboard-selectable profiles, defaults to the version profile, and re-indexes', async () => {
    wrap(<ReindexWithReasoner ontologyId="o1" versionId="v1" currentProfileId="p2" />)

    const select = await screen.findByRole('combobox') as HTMLSelectElement
    await waitFor(() => expect(screen.getByRole('option', { name: 'rustdl full DL' })).toBeInTheDocument())
    expect(select.value).toBe('p2')  // preselects the version's bound profile

    fireEvent.click(screen.getByRole('button', { name: /Re-index with reasoner profile/i }))
    await waitFor(() => expect(mockReason).toHaveBeenCalledWith('o1', 'v1', 'p2'))
    expect(await screen.findByText('queued')).toBeInTheDocument()
  })

  it('admin mode uses the admin profile list (incl. non-dashboard profiles)', async () => {
    mockReason.mockClear()
    wrap(<ReindexWithReasoner ontologyId="o2" versionId="v9" admin />)
    await screen.findByRole('option', { name: 'konclude' })  // admin-only profile visible
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'pk' } })
    fireEvent.click(screen.getByRole('button', { name: /Re-index with reasoner profile/i }))
    await waitFor(() => expect(mockReason).toHaveBeenCalledWith('o2', 'v9', 'pk'))
  })
})
