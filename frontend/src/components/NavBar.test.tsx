import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NavBar from './NavBar'

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, isLoading: false }),
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders logo and nav links', () => {
  wrap(<NavBar />)
  expect(screen.getByText('OntoExplorer')).toBeInTheDocument()
  expect(screen.getByText('Ontologies')).toBeInTheDocument()
})

test('shows Sign in when unauthenticated', () => {
  wrap(<NavBar />)
  expect(screen.getByText('Sign in')).toBeInTheDocument()
})
