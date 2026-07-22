import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'

vi.mock('../lib/auth', () => ({
  loginWithProvider: vi.fn(),
}))

test('renders the enabled OAuth provider buttons', () => {
  render(<MemoryRouter><Login /></MemoryRouter>)
  expect(screen.getByText(/sign in with orcid/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with github/i)).toBeInTheDocument()
  // Google is disabled for now (no Google OAuth app configured).
  expect(screen.queryByText(/sign in with google/i)).not.toBeInTheDocument()
})
