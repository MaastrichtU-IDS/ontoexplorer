import { useEffect, useMemo, useState } from 'react'

const DEFAULT_PAGE_SIZE = 10
const MIN_PAGE_SIZE = 1
const MAX_PAGE_SIZE = 500
const LS_PREFIX = 'admin.rowsPerPage.'

function readStoredPageSize(scopeKey: string): number {
  try {
    const raw = localStorage.getItem(LS_PREFIX + scopeKey)
    if (raw == null) return DEFAULT_PAGE_SIZE
    const n = Number(raw)
    if (!Number.isFinite(n) || n < MIN_PAGE_SIZE || n > MAX_PAGE_SIZE) {
      return DEFAULT_PAGE_SIZE
    }
    return Math.floor(n)
  } catch {
    return DEFAULT_PAGE_SIZE
  }
}

export interface UsePagedTableResult<T> {
  paged: T[]
  page: number
  setPage: (p: number) => void
  pageSize: number
  setPageSize: (n: number) => void
  totalPages: number
  total: number
}

export function usePagedTable<T>(rows: T[], scopeKey: string): UsePagedTableResult<T> {
  const [pageSize, setPageSizeRaw] = useState<number>(() => readStoredPageSize(scopeKey))
  const [page, setPage] = useState(0)

  function setPageSize(n: number) {
    const valid = Number.isFinite(n) && n >= MIN_PAGE_SIZE && n <= MAX_PAGE_SIZE
    const next = valid ? Math.floor(n) : DEFAULT_PAGE_SIZE
    setPageSizeRaw(next)
    setPage(0)
    if (valid) {
      try {
        localStorage.setItem(LS_PREFIX + scopeKey, String(next))
      } catch {
        // Ignore quota / privacy-mode errors.
      }
    }
  }

  const total = rows.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // If the input list shrinks past the current page, snap to page 0.
  useEffect(() => {
    if (page * pageSize >= total && page !== 0) {
      setPage(0)
    }
  }, [total, page, pageSize])

  const paged = useMemo(
    () => rows.slice(page * pageSize, (page + 1) * pageSize),
    [rows, page, pageSize],
  )

  return { paged, page, setPage, pageSize, setPageSize, totalPages, total }
}
