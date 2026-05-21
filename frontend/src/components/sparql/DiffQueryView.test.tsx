import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { DiffQueryView } from './DiffQueryView'
import type { BindingRow } from './diffBindings'

const uri = (v: string) => ({ type: 'uri' as const, value: v })

describe('DiffQueryView', () => {
  it('renders status badges for onlyFrom / onlyTo / both', () => {
    const from: BindingRow[] = [{ x: uri('http://a') }, { x: uri('http://b') }]
    const to:   BindingRow[] = [{ x: uri('http://b') }, { x: uri('http://c') }]
    render(<DiffQueryView from={from} to={to} fromError={null} toError={null} />)
    expect(screen.getByText('Only From')).toBeInTheDocument()
    expect(screen.getByText('Only To')).toBeInTheDocument()
    expect(screen.getByText('Both')).toBeInTheDocument()
  })

  it('filter pills show counts', () => {
    const from: BindingRow[] = [{ x: uri('a') }, { x: uri('b') }, { x: uri('c') }]
    const to:   BindingRow[] = [{ x: uri('b') }, { x: uri('c') }, { x: uri('d') }]
    render(<DiffQueryView from={from} to={to} fromError={null} toError={null} />)
    expect(screen.getByText(/All \(4\)/)).toBeInTheDocument()
    expect(screen.getByText(/Only From \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Only To \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Both \(2\)/)).toBeInTheDocument()
  })

  it('filter pill narrows to one bucket', () => {
    const from: BindingRow[] = [{ x: uri('http://a') }]
    const to:   BindingRow[] = [{ x: uri('http://b') }]
    render(<DiffQueryView from={from} to={to} fromError={null} toError={null} />)
    fireEvent.click(screen.getByRole('button', { name: /Only From \(1\)/ }))
    expect(screen.queryByText('http://b')).not.toBeInTheDocument()
    expect(screen.getByText('http://a')).toBeInTheDocument()
  })

  it('shows banner when one side errored', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    render(<DiffQueryView from={from} to={[]} fromError={null} toError="boom" />)
    expect(screen.getByText(/To side failed/i)).toBeInTheDocument()
  })

  it('shows empty-results message when both sides empty and no errors', () => {
    render(<DiffQueryView from={[]} to={[]} fromError={null} toError={null} />)
    expect(screen.getByText(/no results on either side/i)).toBeInTheDocument()
  })

  it('renders IRI cells as a.iri so the page-level click handler can intercept', () => {
    const from: BindingRow[] = [{ x: uri('http://example.org/X') }]
    const { container } = render(<DiffQueryView from={from} to={[]} fromError={null} toError={null} />)
    const anchor = container.querySelector('a.iri')
    expect(anchor).not.toBeNull()
    expect(anchor?.getAttribute('href')).toBe('http://example.org/X')
  })
})
