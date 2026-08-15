import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReasonerProfilesPanel } from './ReasonerProfilesPanel'

const { mockProfiles, mockReasoners, mockCreate } = vi.hoisted(() => ({
  mockProfiles: vi.fn().mockResolvedValue({ profiles: [
    { id: 'p1', name: 'rustdl (default)', reasoner: 'rustdl', params: {}, dashboard_selectable: true, is_default: true, archived: false, description: null },
  ] }),
  mockReasoners: vi.fn().mockResolvedValue([
    { name: 'rustdl', profile: 'DL', capabilities: ['classify'], available: true, param_schema: [
      { key: 'saturation_only', type: 'bool', default: false, label: 'EL saturation only' },
      { key: 'per_pair_timeout_ms', type: 'int', default: 200, min: 0, label: 'Per-pair timeout (ms)' },
    ] },
    { name: 'km', profile: 'EL++', capabilities: ['classify'], available: true, param_schema: [] },
  ]),
  mockCreate: vi.fn().mockResolvedValue({ id: 'p2' }),
}))

vi.mock('../../lib/api', () => ({
  api: {
    admin: { reasonerProfiles: mockProfiles, createReasonerProfile: mockCreate, updateReasonerProfile: vi.fn(), archiveReasonerProfile: vi.fn() },
    reasoners: { list: mockReasoners },
  },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ReasonerProfilesPanel', () => {
  it('lists profiles and creates a new one with schema-driven params', async () => {
    wrap(<ReasonerProfilesPanel />)

    // existing profile shown
    expect(await screen.findByText('rustdl (default)')).toBeInTheDocument()

    // open the create form
    fireEvent.click(screen.getByRole('button', { name: '+ New profile' }))

    // typed fields from the selected reasoner's schema render
    expect(await screen.findByText('EL saturation only')).toBeInTheDocument()
    expect(screen.getByText('Per-pair timeout (ms)')).toBeInTheDocument()

    // fill name + submit
    fireEvent.change(screen.getByPlaceholderText(/rustdl EL/i), { target: { value: 'my profile' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalled())
    const body = mockCreate.mock.calls[0][0]
    expect(body.name).toBe('my profile')
    expect(body.reasoner).toBe('rustdl')
    expect(body.params).toEqual({ saturation_only: false, per_pair_timeout_ms: 200 })
  })
})
