import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, ConsistencyFleet, ConsistencyFleetEntry, ConsistencyScopeStatus } from '../lib/api'


type SortKey = 'name' | 'host_only' | 'host_plus_imports' | 'host_plus_imports_plus_mireot' | 'total_unsat'


function rank(status: ConsistencyScopeStatus | null | undefined): number {
  switch (status) {
    case 'consistent':   return 0
    case 'partial':      return 1
    case 'timeout':      return 2
    case 'error':        return 3
    case 'inconsistent': return 4
    default:             return -1
  }
}

function StatusCell({ status }: { status: ConsistencyScopeStatus | null }) {
  if (!status) return <span style={{ color: 'var(--text-dim)' }}>—</span>
  const color =
    status === 'consistent' ? '#3fb950' :
    status === 'inconsistent' ? '#e06c75' :
    status === 'partial' ? '#e5c07b' :
    status === 'timeout' ? '#c678dd' : '#e06c75'
  const symbol =
    status === 'consistent' ? '✓' :
    status === 'inconsistent' ? '✗' :
    status === 'partial' ? '⚠' :
    status === 'timeout' ? '⏱' : '!'
  return <span style={{ color, fontWeight: 700 }}>{symbol}</span>
}

function Th({
  children, onClick, active, dir,
}: {
  children: React.ReactNode
  onClick: () => void
  active: boolean
  dir: 'asc' | 'desc'
}) {
  return (
    <th style={{ padding: '4px 8px', textAlign: 'left' }}>
      <button onClick={onClick} style={{
        background: 'none', border: 'none',
        color: active ? 'var(--text)' : 'var(--text-dim)',
        fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
        cursor: 'pointer', padding: 0,
      }}>
        {children}{active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  )
}

function SummaryCard({ label, value, testId }: { label: string; value: number; testId: string }) {
  return (
    <div data-testid={testId} style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '0.75rem',
    }}>
      <p style={{ fontSize: 10, color: 'var(--text-dim)', margin: 0,
                  textTransform: 'uppercase' }}>{label}</p>
      <p style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)',
                  margin: '4px 0 0' }}>{value.toLocaleString()}</p>
    </div>
  )
}


export function Consistency() {
  const { data, isLoading, error } = useQuery<ConsistencyFleet>({
    queryKey: ['consistency-fleet'],
    queryFn: () => api.consistency.fleet(),
    refetchInterval: 10000,  // auto-refresh while jobs are pending
  })
  const [sortKey, setSortKey] = useState<SortKey>('total_unsat')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function click(k: SortKey) {
    if (k === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!data) return []
    const arr = [...data.ontologies]
    arr.sort((a, b) => {
      let va: string | number
      let vb: string | number
      if (sortKey === 'name') {
        va = (a.shortname || a.id).toLowerCase()
        vb = (b.shortname || b.id).toLowerCase()
      } else if (sortKey === 'total_unsat') {
        va = a.total_unsat ?? 0
        vb = b.total_unsat ?? 0
      } else {
        va = rank(a[sortKey] as ConsistencyScopeStatus | null)
        vb = rank(b[sortKey] as ConsistencyScopeStatus | null)
      }
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return arr
  }, [data, sortKey, sortDir])

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div>Failed to load fleet consistency data.</div>

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <div style={{ display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: '0.5rem' }}>
        <SummaryCard label="Ontologies" value={data.totals.fleet_size} testId="consistency-fleet-size" />
        <SummaryCard label="Consistent (all scopes)" value={data.totals.consistent_all_scopes} testId="consistency-all-ok" />
        <SummaryCard label="Inconsistent (any scope)" value={data.totals.inconsistent_any_scope} testId="consistency-inconsistent" />
        <SummaryCard label="Pending / Running" value={data.totals.pending_or_running} testId="consistency-pending" />
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            <Th onClick={() => click('name')} active={sortKey === 'name'} dir={sortDir}>Ontology</Th>
            <Th onClick={() => click('host_only')} active={sortKey === 'host_only'} dir={sortDir}>Host</Th>
            <Th onClick={() => click('host_plus_imports')} active={sortKey === 'host_plus_imports'} dir={sortDir}>Host + imports</Th>
            <Th onClick={() => click('host_plus_imports_plus_mireot')} active={sortKey === 'host_plus_imports_plus_mireot'} dir={sortDir}>+ MIREOT sources</Th>
            <Th onClick={() => click('total_unsat')} active={sortKey === 'total_unsat'} dir={sortDir}>Total unsat</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((e: ConsistencyFleetEntry) => (
            <tr key={e.id} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 8px' }}>
                <Link to={`/ontologies/${e.shortname || e.id}#consistency`}
                      style={{ color: 'var(--accent-blue)' }}>
                  {e.shortname || e.id}
                </Link>
              </td>
              <td style={{ padding: '4px 8px' }}><StatusCell status={e.host_only} /></td>
              <td style={{ padding: '4px 8px' }}><StatusCell status={e.host_plus_imports} /></td>
              <td style={{ padding: '4px 8px' }}><StatusCell status={e.host_plus_imports_plus_mireot} /></td>
              <td style={{ padding: '4px 8px' }}>{e.total_unsat ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
