import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ResolvableBadge from './ResolvableBadge'

describe('ResolvableBadge', () => {
  it('shows a resolvable badge when the IRI dereferences', () => {
    render(<ResolvableBadge resolvable={true} checkedAt="2026-10-09T00:00:00Z" />)
    expect(screen.getByText(/resolvable/i)).toBeInTheDocument()
  })
  it('renders nothing when not resolvable or unchecked', () => {
    const { container: a } = render(<ResolvableBadge resolvable={false} checkedAt={null} />)
    expect(a.textContent).toBe('')
    const { container: b } = render(<ResolvableBadge resolvable={null} checkedAt={null} />)
    expect(b.textContent).toBe('')
  })
})
