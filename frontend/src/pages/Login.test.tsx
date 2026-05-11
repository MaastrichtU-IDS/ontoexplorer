import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'

vi.mock('../lib/auth', () => ({
  loginWithProvider: vi.fn(),
}))

test('renders three OAuth provider buttons', () => {
  render(<MemoryRouter><Login /></MemoryRouter>)
  expect(screen.getByText(/sign in with orcid/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with github/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with google/i)).toBeInTheDocument()
})
