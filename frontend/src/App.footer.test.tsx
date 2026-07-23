import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { Footer } from './App'

afterEach(() => vi.restoreAllMocks())

function mockVersion(body: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, json: () => Promise.resolve(body),
  }))
}

describe('Footer version', () => {
  it('shows the git ref and short sha when injected', async () => {
    mockVersion({ version: '0.3.9', git_ref: '0.3.9', git_sha: '6eb51d9abcd0' })
    render(<MemoryRouter><Footer /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText(/0\.3\.9 · 6eb51d9abcd0/)).toBeInTheDocument())
  })

  it('falls back to v<version> when no git ref (dev build)', async () => {
    mockVersion({ version: '0.3.9', git_ref: null, git_sha: null })
    render(<MemoryRouter><Footer /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('v0.3.9')).toBeInTheDocument())
  })

  it('renders without a version when the endpoint fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve(null) }))
    render(<MemoryRouter><Footer /></MemoryRouter>)
    // The API links still render; no crash.
    expect(screen.getByText('REST API')).toBeInTheDocument()
  })
})
