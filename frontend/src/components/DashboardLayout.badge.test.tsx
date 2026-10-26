import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DashboardLayout from './DashboardLayout'
import { api } from '../lib/api'

vi.mock('../lib/api', () => ({
  api: { ontologies: { attentionCount: vi.fn() } },
}))

const mockCount = api.ontologies.attentionCount as ReturnType<typeof vi.fn>

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route path="/dashboard" element={<div>page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows the attention badge when versions are held', async () => {
  mockCount.mockResolvedValue({ needs_review: 3 })
  wrap()
  expect(await screen.findByLabelText('3 versions need your attention')).toHaveTextContent('3')
})

test('hides the badge when nothing is held', async () => {
  mockCount.mockResolvedValue({ needs_review: 0 })
  wrap()
  await waitFor(() => expect(mockCount).toHaveBeenCalled())
  expect(screen.queryByLabelText(/need your attention/)).toBeNull()
})
