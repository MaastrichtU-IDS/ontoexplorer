import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'

vi.mock('../lib/auth', () => ({
  loginWithProvider: vi.fn(),
}))

test('renders the enabled OAuth provider buttons', () => {
  render(<MemoryRouter><Login /></MemoryRouter>)
  // Keycloak (platform SSO) is the primary option (#368).
  expect(screen.getByText(/sign in with your platform account/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with orcid/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with github/i)).toBeInTheDocument()
  // Google is disabled for now (no Google OAuth app configured).
  expect(screen.queryByText(/sign in with google/i)).not.toBeInTheDocument()
})
