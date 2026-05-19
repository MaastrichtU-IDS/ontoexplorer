import { describe, expect, test, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TablePager } from './TablePager'

function Setup(props: Partial<React.ComponentProps<typeof TablePager>> = {}) {
  const defaults: React.ComponentProps<typeof TablePager> = {
    total: 47, page: 0, pageSize: 10,
    onPage: () => {}, onPageSize: () => {},
  }
  return <TablePager {...defaults} {...props} />
}

describe('TablePager', () => {
  test('renders "Rows", current input, and range', () => {
    render(<Setup />)
    expect(screen.getByLabelText(/rows/i)).toHaveValue(10)
    expect(screen.getByText(/1\D+10\D+of\D+47/)).toBeInTheDocument()
  })

  test('Prev is disabled on page 0; Next enabled', () => {
    render(<Setup page={0} />)
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /next/i })).not.toBeDisabled()
  })

  test('Next is disabled on last page', () => {
    render(<Setup page={4} />)  // 47 / 10 → pages 0..4
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })

  test('clicking Next calls onPage(page+1)', () => {
    const onPage = vi.fn()
    render(<Setup page={1} onPage={onPage} />)
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(onPage).toHaveBeenCalledWith(2)
  })

  test('changing rows input and blurring calls onPageSize with the number', () => {
    const onPageSize = vi.fn()
    render(<Setup onPageSize={onPageSize} />)
    const input = screen.getByLabelText(/rows/i)
    fireEvent.change(input, { target: { value: '25' } })
    fireEvent.blur(input)
    expect(onPageSize).toHaveBeenCalledWith(25)
  })

  test('pressing Enter commits the rows value', () => {
    const onPageSize = vi.fn()
    render(<Setup onPageSize={onPageSize} />)
    const input = screen.getByLabelText(/rows/i)
    fireEvent.change(input, { target: { value: '5' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPageSize).toHaveBeenCalledWith(5)
  })

  test('blank input on commit falls back to default 10', () => {
    const onPageSize = vi.fn()
    render(<Setup onPageSize={onPageSize} />)
    const input = screen.getByLabelText(/rows/i)
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(onPageSize).toHaveBeenCalledWith(10)
  })
})
