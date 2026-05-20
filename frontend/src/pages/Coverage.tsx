import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, slugFromIri, CoverageFleet, CoverageFleetEntry, CoverageEntityType } from '../lib/api'

type SortKey =
  | 'name' | 'class_total' | 'class_label' | 'class_def' | 'class_multi'
  | 'props_label' | 'props_def' | 'ind_label'

function pct(num: number, denom: number): string {
  if (denom <= 0) return '—'
  return `${Math.round((num / denom) * 100)}%`
}

function pctValue(num: number, denom: number): number {
  if (denom <= 0) return -1  // sorts zero-total rows to the bottom of ascending order
  return num / denom
}

function propsAgg(entry: CoverageFleetEntry, field: 'total' | 'with_label' | 'with_definition'): number {
  const types: CoverageEntityType[] = ['object_property', 'data_property', 'annotation_property']
  return types.reduce((acc, t) => acc + (entry.by_type[t]?.[field] ?? 0), 0)
}

export default function Coverage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['coverage', 'fleet'],
    queryFn: () => api.coverage.fleet(),
  })
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const rows = useMemo(() => {
    if (!data) return []
    return [...(data as CoverageFleet).by_ontology].sort((a, b) => {
      const valA = sortValue(a, sortKey)
      const valB = sortValue(b, sortKey)
      if (valA < valB) return sortDir === 'asc' ? -1 : 1
      if (valA > valB) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [data, sortKey, sortDir])

  if (isLoading) return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
  if (error || !data) return <p style={{ color: 'var(--text-dim)' }}>Failed to load coverage.</p>

  const fleet = data as CoverageFleet

  function toggleSort(key: SortKey) {
    if (key === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('asc') }
  }

  const classTotals = fleet.totals.class

  return (
    <div>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1rem' }}>Coverage</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem', marginBottom: '1.25rem' }}>
        <SummaryCard label="Class label coverage"      pct={pct(classTotals.with_label, classTotals.total)} />
        <SummaryCard label="Class definition coverage" pct={pct(classTotals.with_definition, classTotals.total)} />
        <SummaryCard label="Class multilingual"        pct={pct(classTotals.multilingual, classTotals.total)} />
      </div>

      <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', minWidth: 720, borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <Th onClick={() => toggleSort('name')}        active={sortKey === 'name'}        dir={sortDir}>Ontology</Th>
            <Th onClick={() => toggleSort('class_total')} active={sortKey === 'class_total'} dir={sortDir}>Classes</Th>
            <Th onClick={() => toggleSort('class_label')} active={sortKey === 'class_label'} dir={sortDir}>Class label %</Th>
            <Th onClick={() => toggleSort('class_def')}   active={sortKey === 'class_def'}   dir={sortDir}>Class def %</Th>
            <Th onClick={() => toggleSort('class_multi')} active={sortKey === 'class_multi'} dir={sortDir}>Class multilingual %</Th>
            <Th onClick={() => toggleSort('props_label')} active={sortKey === 'props_label'} dir={sortDir}>Props label %</Th>
            <Th onClick={() => toggleSort('props_def')}   active={sortKey === 'props_def'}   dir={sortDir}>Props def %</Th>
            <Th onClick={() => toggleSort('ind_label')}   active={sortKey === 'ind_label'}   dir={sortDir}>Indivs label %</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(entry => (
            <CoverageRow key={entry.version_id} entry={entry} />
          ))}
        </tbody>
      </table>
      </div>
    </div>
  )
}

function sortValue(entry: CoverageFleetEntry, key: SortKey): number | string {
  const cls = entry.by_type.class
  const ind = entry.by_type.individual
  switch (key) {
    case 'name':        return (entry.shortname || entry.ontology_id).toLowerCase()
    case 'class_total': return cls.total
    case 'class_label': return pctValue(cls.with_label, cls.total)
    case 'class_def':   return pctValue(cls.with_definition, cls.total)
    case 'class_multi': return pctValue(cls.multilingual, cls.total)
    case 'props_label': return pctValue(propsAgg(entry, 'with_label'), propsAgg(entry, 'total'))
    case 'props_def':   return pctValue(propsAgg(entry, 'with_definition'), propsAgg(entry, 'total'))
    case 'ind_label':   return pctValue(ind.with_label, ind.total)
  }
}

function CoverageRow({ entry }: { entry: CoverageFleetEntry }) {
  const cls = entry.by_type.class
  const ind = entry.by_type.individual
  const slug = entry.shortname || slugFromIri(entry.ontology_id)
  const propsTotal = propsAgg(entry, 'total')
  const propsLabel = propsAgg(entry, 'with_label')
  const propsDef = propsAgg(entry, 'with_definition')

  return (
    <tr data-testid="coverage-row" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
      <td style={{ padding: '5px 8px' }}>
        <OntologyLink slug={slug} hash="coverage" />
      </td>
      <td style={{ padding: '5px 8px' }}>{cls.total.toLocaleString()}</td>
      <td style={{ padding: '5px 8px' }}>{pct(cls.with_label, cls.total)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(cls.with_definition, cls.total)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(cls.multilingual, cls.total)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(propsLabel, propsTotal)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(propsDef, propsTotal)}</td>
      <td style={{ padding: '5px 8px' }} data-testid="individuals-label-pct">{pct(ind.with_label, ind.total)}</td>
    </tr>
  )
}

function Th({ children, onClick, active, dir }: {
  children: React.ReactNode; onClick: () => void; active: boolean; dir: 'asc' | 'desc'
}) {
  return (
    <th style={{ padding: '4px 8px', textAlign: 'left' }}>
      <button onClick={onClick} style={{
        background: 'none', border: 'none', color: active ? 'var(--text)' : 'var(--text-dim)',
        fontSize: 10, textTransform: 'uppercase', fontWeight: 500, cursor: 'pointer', padding: 0,
      }}>
        {children}{active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  )
}

function OntologyLink({ slug, hash }: { slug: string; hash: string }) {
  const [hover, setHover] = useState(false)
  return (
    <Link
      to={`/ontologies/${slug}#${hash}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        color: 'var(--accent-blue)',
        textDecoration: 'underline',
        textDecorationColor: hover ? 'var(--accent-blue)' : 'rgba(97,175,239,0.4)',
        textUnderlineOffset: 3,
        fontWeight: 600,
        fontFamily: 'var(--font-mono, monospace)',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
      }}
    >
      <span data-testid="ontology-name">{slug}</span>
      <span style={{ fontSize: 10, opacity: hover ? 1 : 0.6 }}>→</span>
    </Link>
  )
}

function SummaryCard({ label, pct }: { label: string; pct: string }) {
  return (
    <div style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '1rem',
    }}>
      <p style={{
        fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '0.25rem',
        textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600,
      }}>{label}</p>
      <p style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text)' }}>{pct}</p>
    </div>
  )
}
