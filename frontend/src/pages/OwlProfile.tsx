import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, slugFromIri, OwlProfileFleet, OwlProfileFleetEntry } from '../lib/api'

type FilterPill = 'all' | 'el' | 'rl' | 'ql' | 'dl'
type SortKey = 'name' | 'el' | 'rl' | 'ql' | 'dl'

function profileInKey(profile: Exclude<FilterPill, 'all'>): keyof OwlProfileFleetEntry {
  return `in_${profile}` as keyof OwlProfileFleetEntry
}

function sortValue(entry: OwlProfileFleetEntry, key: SortKey): string | number {
  switch (key) {
    case 'name': return (entry.shortname || entry.id).toLowerCase()
    case 'el':   return entry.in_el ? 1 : 0
    case 'rl':   return entry.in_rl ? 1 : 0
    case 'ql':   return entry.in_ql ? 1 : 0
    case 'dl':   return entry.in_dl ? 1 : 0
  }
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

function ProfileBadge({ inProfile, violations }: { inProfile: boolean; violations: number }) {
  if (inProfile) {
    return (
      <span style={{ color: 'var(--green)', fontWeight: 700 }}>✓</span>
    )
  }
  return (
    <span style={{ color: 'var(--error)' }}>
      ✗ <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>({violations.toLocaleString()})</span>
    </span>
  )
}

function Th({
  children,
  onClick,
  active,
  dir,
  testId,
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
          background: 'none',
          border: 'none',
          color: active ? 'var(--text)' : 'var(--text-dim)',
          fontSize: 10,
          textTransform: 'uppercase',
          fontWeight: 500,
          cursor: 'pointer',
          padding: 0,
        }}
      >
        {children}
        {active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  )
}

function SummaryCard({
  label,
  count,
  total,
  testId,
}: {
  label: string
  count: number
  total: number
  testId: string
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div
      data-testid={testId}
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '1rem',
      }}
    >
      <p
        style={{
          fontSize: 'var(--font-size-sm)',
          color: 'var(--text-dim)',
          marginBottom: '0.25rem',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          fontWeight: 600,
        }}
      >
        {label}
      </p>
      <p
        style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text)', margin: 0 }}
      >
        {count} / {total}
      </p>
      <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
        {pct}% conformant
      </p>
    </div>
  )
}

export default function OwlProfile() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['owl-profile', 'fleet'],
    queryFn: () => api.owl_profile.fleet(),
  })

  const [filter, setFilter] = useState<FilterPill>('all')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const rows = useMemo(() => {
    if (!data) return []
    const fleet = data as OwlProfileFleet
    const filtered = filter === 'all'
      ? fleet.ontologies
      : fleet.ontologies.filter(e => e[profileInKey(filter)])
    return [...filtered].sort((a, b) => {
      const va = sortValue(a, sortKey)
      const vb = sortValue(b, sortKey)
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [data, filter, sortKey, sortDir])

  if (isLoading) {
    return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
  }
  if (error || !data) {
    return <p style={{ color: 'var(--text-dim)' }}>Failed to load OWL profile data.</p>
  }

  const fleet = data as OwlProfileFleet
  const { totals } = fleet

  function toggleSort(key: SortKey) {
    if (key === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const pills: FilterPill[] = ['all', 'dl', 'el', 'ql', 'rl']

  return (
    <div>
      <h1
        style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.5rem' }}
      >
        OWL 2 Profile Conformance
      </h1>
      <p
        style={{
          color: 'var(--text-dim)',
          fontSize: 'var(--font-size-sm)',
          marginBottom: '1.25rem',
          maxWidth: 640,
        }}
      >
        W3C OWL 2 defines four tractable profiles — DL, EL, QL, and RL — each
        with different expressivity/reasoning trade-offs. This page shows which
        profiles each ontology version conforms to. The language tier below is a
        coarser axis: whether a vocabulary is plain RDFS, lightweight RDFS-Plus,
        or full OWL.
      </p>

      {/* Language / expressivity tiers */}
      <h2 style={{ fontSize: '0.9rem', fontWeight: 600, margin: '0 0 0.5rem' }}>
        Language / expressivity
      </h2>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '0.75rem',
          marginBottom: '1.25rem',
        }}
      >
        <SummaryCard label="OWL" count={totals.tier_owl_count ?? 0} total={totals.fleet_size} testId="summary-tier-owl" />
        <SummaryCard label="RDFS-Plus" count={totals.tier_rdfs_plus_count ?? 0} total={totals.fleet_size} testId="summary-tier-rdfs-plus" />
        <SummaryCard label="RDFS" count={totals.tier_rdfs_count ?? 0} total={totals.fleet_size} testId="summary-tier-rdfs" />
        <SummaryCard label="RDF" count={totals.tier_rdf_count ?? 0} total={totals.fleet_size} testId="summary-tier-rdf" />
      </div>

      {/* Summary cards */}
      <h2 style={{ fontSize: '0.9rem', fontWeight: 600, margin: '0 0 0.5rem' }}>
        OWL 2 profiles
      </h2>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '0.75rem',
          marginBottom: '1.25rem',
        }}
      >
        <SummaryCard
          label="OWL 2 DL"
          count={totals.dl_count}
          total={totals.fleet_size}
          testId="summary-dl"
        />
        <SummaryCard
          label="OWL 2 EL"
          count={totals.el_count}
          total={totals.fleet_size}
          testId="summary-el"
        />
        <SummaryCard
          label="OWL 2 QL"
          count={totals.ql_count}
          total={totals.fleet_size}
          testId="summary-ql"
        />
        <SummaryCard
          label="OWL 2 RL"
          count={totals.rl_count}
          total={totals.fleet_size}
          testId="summary-rl"
        />
      </div>

      {/* Filter pills */}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          marginBottom: '1rem',
          flexWrap: 'wrap',
        }}
      >
        {pills.map(p => (
          <button
            key={p}
            data-testid={`filter-${p}`}
            onClick={() => setFilter(p)}
            style={{
              padding: '4px 14px',
              borderRadius: 20,
              border: '1px solid',
              borderColor: filter === p ? 'var(--accent)' : 'var(--border)',
              background: filter === p ? 'rgba(88,166,255,0.1)' : 'none',
              color: filter === p ? 'var(--accent)' : 'var(--text-dim)',
              fontSize: 12,
              cursor: 'pointer',
              fontWeight: filter === p ? 600 : 400,
              textTransform: p === 'all' ? 'capitalize' : 'uppercase',
            }}
          >
            {p === 'all' ? 'All' : p.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          minWidth: 560,
          borderCollapse: 'collapse',
          fontSize: 'var(--font-size-sm)',
        }}
      >
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <Th
              onClick={() => toggleSort('name')}
              active={sortKey === 'name'}
              dir={sortDir}
              testId="sort-name"
            >
              Ontology
            </Th>
            <Th
              onClick={() => toggleSort('dl')}
              active={sortKey === 'dl'}
              dir={sortDir}
            >
              DL
            </Th>
            <Th
              onClick={() => toggleSort('el')}
              active={sortKey === 'el'}
              dir={sortDir}
            >
              EL
            </Th>
            <Th
              onClick={() => toggleSort('ql')}
              active={sortKey === 'ql'}
              dir={sortDir}
            >
              QL
            </Th>
            <Th
              onClick={() => toggleSort('rl')}
              active={sortKey === 'rl'}
              dir={sortDir}
            >
              RL
            </Th>
            <th
              style={{
                padding: '4px 8px',
                textAlign: 'left',
                fontSize: 10,
                textTransform: 'uppercase',
                fontWeight: 500,
                color: 'var(--text-dim)',
              }}
            >
              Violations summary
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(entry => {
            const slug = entry.shortname || slugFromIri(entry.id)

            const violationParts: string[] = []
            if (!entry.in_dl && entry.dl_violations > 0)
              violationParts.push(`DL: ${entry.dl_violations.toLocaleString()}`)
            if (!entry.in_el && entry.el_violations > 0)
              violationParts.push(`EL: ${entry.el_violations.toLocaleString()}`)
            if (!entry.in_ql && entry.ql_violations > 0)
              violationParts.push(`QL: ${entry.ql_violations.toLocaleString()}`)
            if (!entry.in_rl && entry.rl_violations > 0)
              violationParts.push(`RL: ${entry.rl_violations.toLocaleString()}`)

            return (
              <tr
                key={entry.version_id}
                data-testid="owl-profile-row"
                style={{
                  borderBottom: '1px solid var(--overlay)',
                }}
              >
                <td style={{ padding: '5px 8px' }}>
                  <OntologyLink slug={slug} hash="owl-profile" />
                </td>
                <td style={{ padding: '5px 8px' }}>
                  <ProfileBadge
                    inProfile={entry.in_dl}
                    violations={entry.dl_violations}
                  />
                </td>
                <td style={{ padding: '5px 8px' }}>
                  <ProfileBadge
                    inProfile={entry.in_el}
                    violations={entry.el_violations}
                  />
                </td>
                <td style={{ padding: '5px 8px' }}>
                  <ProfileBadge
                    inProfile={entry.in_ql}
                    violations={entry.ql_violations}
                  />
                </td>
                <td style={{ padding: '5px 8px' }}>
                  <ProfileBadge
                    inProfile={entry.in_rl}
                    violations={entry.rl_violations}
                  />
                </td>
                <td
                  style={{
                    padding: '5px 8px',
                    color: 'var(--text-dim)',
                    fontSize: 11,
                  }}
                >
                  {violationParts.length > 0
                    ? violationParts.join(', ')
                    : <span style={{ color: 'var(--green)' }}>All conformant</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>

      {rows.length === 0 && (
        <p
          style={{
            color: 'var(--text-dim)',
            fontSize: 'var(--font-size-sm)',
            marginTop: '1rem',
          }}
        >
          No ontologies match the selected filter.
        </p>
      )}
    </div>
  )
}
