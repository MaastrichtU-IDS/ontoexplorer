import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'
import { loginWithProvider } from '../lib/auth'

vi.mock('../lib/auth', () => ({
  loginWithProvider: vi.fn(),
}))

test('offers only the platform-account sign-in', () => {
  render(<MemoryRouter><Login /></MemoryRouter>)
  // The platform (Keycloak) account is the sole sign-in path (#368): it brokers
  // ORCID/GitHub/Google and guarantees a verified email on every login, so the
  // direct provider buttons were removed.
  const button = screen.getByText(/sign in with your platform account/i)
  expect(button).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /sign in with orcid/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /sign in with github/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /sign in with google/i })).not.toBeInTheDocument()

  fireEvent.click(button)
  expect(loginWithProvider).toHaveBeenCalledWith('keycloak')
})
