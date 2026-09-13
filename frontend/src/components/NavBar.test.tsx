import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NavBar from './NavBar'

// Mutable so individual tests can flip auth state (vi.mock is hoisted once).
let authState: { user: unknown; isAuthenticated: boolean; isLoading: boolean } = {
  user: null, isAuthenticated: false, isLoading: false,
}
vi.mock('../hooks/useAuth', () => ({ useAuth: () => authState }))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

const DESKTOP = 1200
const MOBILE = 375
function setWidth(w: number) {
  Object.defineProperty(window, 'innerWidth', { value: w, configurable: true, writable: true })
}

beforeEach(() => {
  authState = { user: null, isAuthenticated: false, isLoading: false }
  setWidth(DESKTOP)
})

test('renders logo and nav links', () => {
  wrap(<NavBar />)
  expect(screen.getByText('OntoExplorer')).toBeInTheDocument()
  expect(screen.getByText('Ontologies')).toBeInTheDocument()
})

test('shows Sign in when unauthenticated', () => {
  wrap(<NavBar />)
  expect(screen.getByText('Sign in')).toBeInTheDocument()
})

test('on mobile the nav collapses behind a menu button', () => {
  setWidth(MOBILE)
  authState = { user: { is_admin: true }, isAuthenticated: true, isLoading: false }
  wrap(<NavBar />)
  // Collapsed: the menu toggle is present, the admin/dashboard controls are not yet.
  expect(screen.getByLabelText('Menu')).toBeInTheDocument()
  expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  expect(screen.queryByText('Dashboard')).not.toBeInTheDocument()
})

test('opening the mobile menu reveals Admin and Dashboard (the reported blocker)', () => {
  setWidth(MOBILE)
  authState = { user: { is_admin: true }, isAuthenticated: true, isLoading: false }
  wrap(<NavBar />)
  fireEvent.click(screen.getByLabelText('Menu'))
  expect(screen.getByText('Admin')).toBeInTheDocument()
  expect(screen.getByText('Dashboard')).toBeInTheDocument()
  expect(screen.getByText('Sign out')).toBeInTheDocument()
})

test('non-admin mobile user sees Dashboard but not Admin', () => {
  setWidth(MOBILE)
  authState = { user: { is_admin: false }, isAuthenticated: true, isLoading: false }
  wrap(<NavBar />)
  fireEvent.click(screen.getByLabelText('Menu'))
  expect(screen.getByText('Dashboard')).toBeInTheDocument()
  expect(screen.queryByText('Admin')).not.toBeInTheDocument()
})
