import { useEffect, useState } from 'react'

export interface TablePagerProps {
  total: number
  page: number
  pageSize: number
  onPage: (page: number) => void
  onPageSize: (size: number) => void
}

const DEFAULT_PAGE_SIZE = 10

export function TablePager({ total, page, pageSize, onPage, onPageSize }: TablePagerProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const start = total === 0 ? 0 : page * pageSize + 1
  const end = Math.min((page + 1) * pageSize, total)

  // Mirror pageSize in a local string so the input is editable.
  const [draft, setDraft] = useState(String(pageSize))
  useEffect(() => {
    setDraft(String(pageSize))
  }, [pageSize])

  function commit() {
    const n = Number(draft)
    if (!Number.isFinite(n) || n < 1) {
      onPageSize(DEFAULT_PAGE_SIZE)
      setDraft(String(DEFAULT_PAGE_SIZE))
    } else {
      const v = Math.floor(n)
      onPageSize(v)
      setDraft(String(v))
    }
  }

  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: 4,
    color: disabled ? 'var(--text-dim)' : 'var(--text)',
    fontSize: 11,
    padding: '2px 10px',
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.4 : 1,
  })

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
        Rows:
        <input
          type="number"
          min={1}
          max={500}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') commit() }}
          style={{
            width: 56,
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            color: 'var(--text)',
            fontSize: 11,
            padding: '2px 6px',
            outline: 'none',
          }}
        />
      </label>
      <div style={{ flex: 1 }} />
      <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
        {start}–{end} of {total}
      </span>
      <button onClick={() => onPage(page - 1)} disabled={page === 0} style={btnStyle(page === 0)}>
        ‹ Prev
      </button>
      <button
        onClick={() => onPage(page + 1)}
        disabled={page >= totalPages - 1}
        style={btnStyle(page >= totalPages - 1)}
      >
        Next ›
      </button>
    </div>
  )
}
