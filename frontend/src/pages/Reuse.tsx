import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, ReuseFleet, ReuseFleetEntry } from '../lib/api'


type SortKey = 'name' | 'imports' | 'mireot' | 'reused' | 'mappings'


function sortValue(e: ReuseFleetEntry, key: SortKey): string | number {
  switch (key) {
    case 'name':    return (e.shortname || e.id).toLowerCase()
    case 'imports': return e.imports_count
    case 'mireot':  return e.mireot_terms_count
    case 'reused':  return e.term_iri_reused_count
    case 'mappings':return e.mappings_count
  }
}


function Th({
  children, onClick, active, dir, testId,
}: {
  children: React.ReactNode
  onClick: () => void
  active: boolean
  dir: 'asc' | 'desc'
  testId?: string
}) {
  return (
    <th style={{ padding: '4px 8px', textAlign: 'left' }}>
      <button
        data-testid={testId}
        onClick={onClick}
        style={{
          background: 'none', border: 'none',
          color: active ? 'var(--text)' : 'var(--text-dim)',
          fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
          cursor: 'pointer', padding: 0,
        }}
      >
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
                  margin: '4px 0 0' }}>
        {value.toLocaleString()}
      </p>
    </div>
  )
}


export function Reuse() {
  const { data, isLoading, error } = useQuery<ReuseFleet>({
    queryKey: ['reuse-fleet'],
    queryFn: () => api.reuse.fleet(),
  })
  const [sortKey, setSortKey] = useState<SortKey>('reused')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function clickHeader(k: SortKey) {
    if (k === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!data) return []
    const arr = [...data.ontologies]
    arr.sort((a, b) => {
      const va = sortValue(a, sortKey)
      const vb = sortValue(b, sortKey)
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return arr
  }, [data, sortKey, sortDir])

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div>Failed to load fleet reuse data.</div>

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <div style={{ display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: '0.5rem' }}>
        <SummaryCard label="Ontologies" value={data.totals.fleet_size} testId="reuse-fleet-size" />
        <SummaryCard label="Import edges" value={data.totals.total_import_edges} testId="reuse-import-edges" />
        <SummaryCard label="MIREOT terms" value={data.totals.total_mireot_terms} testId="reuse-mireot-total" />
        <SummaryCard label="With MIREOT" value={data.totals.ontologies_with_mireot} testId="reuse-mireot-onts" />
      </div>

      {data.top_reused_sources.length > 0 && (
        <div style={{ background: 'var(--bg-secondary)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)', padding: '0.75rem' }}>
          <h4 style={{ fontSize: 'var(--font-size-sm)', margin: '0 0 8px' }}>
            Top reused sources
          </h4>
          <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
            {data.top_reused_sources.map(s => (
              <li key={s.prefix}>
                <Link to={`/ontologies?reuses=${s.prefix}`}
                      style={{ color: 'var(--accent-blue)' }}>
                  <code>{s.prefix}</code>
                </Link>
                {' — '}
                <span style={{ color: 'var(--text-dim)' }}>
                  {s.reusers_count} ontolog{s.reusers_count === 1 ? 'y' : 'ies'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            <Th onClick={() => clickHeader('name')}
                active={sortKey === 'name'} dir={sortDir}
                testId="reuse-th-name">Ontology</Th>
            <Th onClick={() => clickHeader('imports')}
                active={sortKey === 'imports'} dir={sortDir}
                testId="reuse-th-imports">Imports</Th>
            <Th onClick={() => clickHeader('mireot')}
                active={sortKey === 'mireot'} dir={sortDir}
                testId="reuse-th-mireot">MIREOT</Th>
            <Th onClick={() => clickHeader('reused')}
                active={sortKey === 'reused'} dir={sortDir}
                testId="reuse-th-reused">Reused terms</Th>
            <Th onClick={() => clickHeader('mappings')}
                active={sortKey === 'mappings'} dir={sortDir}
                testId="reuse-th-mappings">Mappings</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(e => (
            <tr key={e.id} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 8px' }}>
                <Link to={`/ontologies/${e.shortname || e.id}`}
                      style={{ color: 'var(--accent-blue)' }}>
                  {e.shortname || e.id}
                </Link>
              </td>
              <td style={{ padding: '4px 8px' }}>{e.imports_count}</td>
              <td style={{ padding: '4px 8px' }}>{e.mireot_terms_count}</td>
              <td style={{ padding: '4px 8px' }}>{e.term_iri_reused_count}</td>
              <td style={{ padding: '4px 8px' }}>{e.mappings_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
