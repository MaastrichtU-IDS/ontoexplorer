import { useMemo, useState } from 'react'
import { BindingRow, BindingValue, diffBindings } from './diffBindings'

type Status = 'onlyFrom' | 'onlyTo' | 'both'
type Filter = 'all' | Status
type SortKey = 'status' | string  // 'status' or a variable name
type SortDir = 'asc' | 'desc'

interface Props {
  from: BindingRow[]
  to: BindingRow[]
  fromError: string | null
  toError: string | null
}

const STATUS_LABEL: Record<Status, string> = {
  onlyFrom: 'Only From',
  onlyTo: 'Only To',
  both: 'Both',
}

const STATUS_COLOR: Record<Status, { bg: string; border: string; color: string }> = {
  onlyFrom: { bg: 'rgba(248,81,73,0.10)',  border: 'rgba(248,81,73,0.35)',  color: '#f85149' },
  onlyTo:   { bg: 'rgba(63,185,80,0.10)',  border: 'rgba(63,185,80,0.35)',  color: '#3fb950' },
  both:     { bg: 'rgba(125,133,144,0.10)', border: 'rgba(125,133,144,0.35)', color: 'var(--text-dim)' },
}

// Order onlyFrom/onlyTo before both, so 'status asc' surfaces changes first.
const STATUS_ORDER: Record<Status, number> = { onlyFrom: 0, onlyTo: 1, both: 2 }

function compareValues(a: BindingValue | undefined, b: BindingValue | undefined): number {
  if (!a && !b) return 0
  if (!a) return -1
  if (!b) return 1
  return a.value.localeCompare(b.value)
}

function renderValue(v: BindingValue) {
  if (v.type === 'uri') {
    return <a className="iri" href={v.value}>{v.value}</a>
  }
  if (v.type === 'bnode') {
    return <span style={{ fontFamily: 'monospace', color: 'var(--text-dim)' }}>_:{v.value}</span>
  }
  const lang = v['xml:lang']
  return (
    <span>
      <span>{v.value}</span>
      {lang && <span style={{ color: 'var(--text-dim)', fontSize: 10, marginLeft: 4 }}>@{lang}</span>}
    </span>
  )
}

export function DiffQueryView({ from, to, fromError, toError }: Props) {
  const { onlyFrom, onlyTo, both, vars } = useMemo(() => diffBindings(from, to), [from, to])
  const [filter, setFilter] = useState<Filter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('status')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const allRows: Array<{ status: Status; row: BindingRow }> = useMemo(() => {
    return [
      ...onlyFrom.map(row => ({ status: 'onlyFrom' as const, row })),
      ...onlyTo.map(row => ({ status: 'onlyTo' as const, row })),
      ...both.map(row => ({ status: 'both' as const, row })),
    ]
  }, [onlyFrom, onlyTo, both])

  const visible = useMemo(() => {
    const filtered = filter === 'all' ? allRows : allRows.filter(r => r.status === filter)
    const sorted = [...filtered].sort((a, b) => {
      let cmp: number
      if (sortKey === 'status') {
        cmp = STATUS_ORDER[a.status] - STATUS_ORDER[b.status]
      } else {
        cmp = compareValues(a.row[sortKey], b.row[sortKey])
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [allRows, filter, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  function sortArrow(key: SortKey): string {
    if (sortKey !== key) return ''
    return sortDir === 'asc' ? ' ▲' : ' ▼'
  }

  const totalCount = allRows.length
  const empty = totalCount === 0 && !fromError && !toError

  const banner = (() => {
    if (fromError && toError) {
      return `Both sides failed: From — ${fromError} · To — ${toError}`
    }
    if (fromError) return `From side failed: ${fromError}`
    if (toError) return `To side failed: ${toError}`
    return null
  })()

  return (
    <div style={{ padding: '1rem', overflowY: 'auto', height: '100%', boxSizing: 'border-box' }}>
      {banner && (
        <div style={{
          background: 'rgba(248,81,73,0.10)', border: '1px solid rgba(248,81,73,0.35)',
          color: '#f85149', borderRadius: 4, padding: '6px 10px', fontSize: 12, marginBottom: 8,
        }}>
          {banner}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {[
          { k: 'all'      as const, n: totalCount },
          { k: 'onlyFrom' as const, n: onlyFrom.length },
          { k: 'onlyTo'   as const, n: onlyTo.length },
          { k: 'both'     as const, n: both.length },
        ].map(({ k, n }) => {
          const active = filter === k
          const label = k === 'all' ? 'All' : STATUS_LABEL[k as Status]
          return (
            <button
              key={k}
              onClick={() => setFilter(k)}
              style={{
                fontSize: 11, padding: '3px 10px', borderRadius: 12,
                border: '1px solid', borderColor: active ? 'var(--accent)' : 'var(--border)',
                background: active ? 'rgba(88,166,255,0.10)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >{label} ({n})</button>
          )
        })}
      </div>

      {empty && (
        <div style={{ color: 'var(--text-dim)', fontSize: 12, padding: 12 }}>
          No results on either side.
        </div>
      )}

      {!empty && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th
                  onClick={() => toggleSort('status')}
                  style={{
                    textAlign: 'left', padding: '4px 8px',
                    color: sortKey === 'status' ? 'var(--text)' : 'var(--text-dim)',
                    fontSize: 10, textTransform: 'uppercase', fontWeight: sortKey === 'status' ? 700 : 500,
                    cursor: 'pointer', userSelect: 'none',
                  }}
                >
                  Status{sortArrow('status')}
                </th>
                {vars.map(v => (
                  <th
                    key={v}
                    onClick={() => toggleSort(v)}
                    style={{
                      textAlign: 'left', padding: '4px 8px',
                      color: sortKey === v ? 'var(--text)' : 'var(--text-dim)',
                      fontSize: 10, textTransform: 'uppercase', fontWeight: sortKey === v ? 700 : 500,
                      cursor: 'pointer', userSelect: 'none',
                    }}
                  >
                    {v}{sortArrow(v)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map(({ status, row }, i) => {
                const c = STATUS_COLOR[status]
                return (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <td style={{ padding: '4px 8px' }}>
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 10,
                        background: c.bg, border: `1px solid ${c.border}`,
                        color: c.color, fontWeight: 600, letterSpacing: 0.3, whiteSpace: 'nowrap',
                      }}>
                        {STATUS_LABEL[status]}
                      </span>
                    </td>
                    {vars.map(v => (
                      <td key={v} style={{ padding: '4px 8px', verticalAlign: 'top' }}>
                        {row[v] ? renderValue(row[v]) : <span style={{ color: 'var(--text-dim)' }}>—</span>}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
