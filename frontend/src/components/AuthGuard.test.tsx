import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AuthGuard from './AuthGuard'

let mockAuth = { user: null as null, isAuthenticated: false, isLoading: false }

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => mockAuth,
}))

function wrap(isAuthenticated: boolean, isLoading: boolean) {
  mockAuth = { user: null, isAuthenticated, isLoading }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route element={<AuthGuard />}>
            <Route path="/dashboard" element={<div>Protected</div>} />
          </Route>
          <Route path="/login" element={<div>Login page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows protected content when authenticated', () => {
  wrap(true, false)
  expect(screen.getByText('Protected')).toBeInTheDocument()
})

test('redirects to /login when not authenticated', () => {
  wrap(false, false)
  expect(screen.getByText('Login page')).toBeInTheDocument()
})
