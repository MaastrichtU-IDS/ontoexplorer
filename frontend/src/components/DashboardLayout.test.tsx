import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DashboardLayout from './DashboardLayout'

function wrap(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route path="/dashboard" element={<div>Ontologies page</div>} />
            <Route path="/dashboard/keys" element={<div>Keys page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders sidebar nav links', () => {
  wrap('/dashboard')
  expect(screen.getByText('Ontologies')).toBeInTheDocument()
  expect(screen.getByText('API Keys')).toBeInTheDocument()
  expect(screen.getByText('Webhooks')).toBeInTheDocument()
  expect(screen.getByText('Stats')).toBeInTheDocument()
})

test('renders child route via Outlet', () => {
  wrap('/dashboard')
  expect(screen.getByText('Ontologies page')).toBeInTheDocument()
})

test('renders correct child on /dashboard/keys', () => {
  wrap('/dashboard/keys')
  expect(screen.getByText('Keys page')).toBeInTheDocument()
})
