import { describe, expect, test, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePagedTable } from './usePagedTable'

beforeEach(() => {
  localStorage.clear()
})

const ROWS = Array.from({ length: 27 }, (_, i) => i)

describe('usePagedTable', () => {
  test('defaults pageSize to 10 and slices accordingly', () => {
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-a'))
    expect(result.current.pageSize).toBe(10)
    expect(result.current.paged).toHaveLength(10)
    expect(result.current.paged[0]).toBe(0)
    expect(result.current.totalPages).toBe(3)
  })

  test('setPage advances slicing', () => {
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-b'))
    act(() => result.current.setPage(1))
    expect(result.current.paged[0]).toBe(10)
    expect(result.current.paged).toHaveLength(10)
    act(() => result.current.setPage(2))
    expect(result.current.paged).toHaveLength(7)
  })

  test('setPageSize resets page to 0 and re-slices', () => {
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-c'))
    act(() => result.current.setPage(2))
    expect(result.current.page).toBe(2)
    act(() => result.current.setPageSize(20))
    expect(result.current.page).toBe(0)
    expect(result.current.paged).toHaveLength(20)
  })

  test('pageSize persists to localStorage and reads back', () => {
    const { result, unmount } = renderHook(() => usePagedTable(ROWS, 'test-d'))
    act(() => result.current.setPageSize(15))
    unmount()
    const { result: result2 } = renderHook(() => usePagedTable(ROWS, 'test-d'))
    expect(result2.current.pageSize).toBe(15)
  })

  test('invalid stored value falls back to default 10', () => {
    localStorage.setItem('admin.rowsPerPage.test-e', 'not-a-number')
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-e'))
    expect(result.current.pageSize).toBe(10)
  })

  test('out-of-range stored value falls back to default 10', () => {
    localStorage.setItem('admin.rowsPerPage.test-f', '99999')
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-f'))
    expect(result.current.pageSize).toBe(10)
  })

  test('page snaps to last when input list shrinks below current offset', () => {
    let rows = ROWS
    const { result, rerender } = renderHook(({ r }) => usePagedTable(r, 'test-g'), {
      initialProps: { r: rows },
    })
    act(() => result.current.setPage(2))
    expect(result.current.page).toBe(2)
    rows = ROWS.slice(0, 5)
    rerender({ r: rows })
    expect(result.current.page).toBe(0)
    expect(result.current.paged).toHaveLength(5)
  })
})
