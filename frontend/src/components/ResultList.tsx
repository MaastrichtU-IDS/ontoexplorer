import { Link } from 'react-router-dom'
import type { SearchResult } from '../lib/api'
import SourceBadge from './SourceBadge'

const TYPE_BADGE: Record<string, string> = {
  class: 'CLASS',
  object_property: 'OP',
  data_property: 'DP',
  annotation_property: 'AP',
  individual: 'IND',
  concept: 'SKOS',
}

export function TypeBadge({ type }: { type?: string }) {
  if (!type) return null
  const label = TYPE_BADGE[type]
  if (!label) return null
  return (
    <span style={{
      fontSize: 9, padding: '1px 5px', borderRadius: 3,
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      color: 'var(--text-dim)', flexShrink: 0, fontWeight: 600, letterSpacing: 0.3,
    }}>{label}</span>
  )
}

export function ResultList({ results, pathFor, ontologyNameFor }: {
  results: SearchResult[]
  pathFor: (r: SearchResult) => string | null
  ontologyNameFor?: (r: SearchResult) => string | null
}) {
  if (results.length === 0) return null
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {results.map(r => {
        const path = pathFor(r)
        const ontName = ontologyNameFor?.(r) ?? null
        const inner = (
          <>
            <TypeBadge type={r.type} />
            <span style={{ color: 'var(--accent)', fontWeight: 500, flexShrink: 0 }}>{r.label}</span>
            {r.source && <SourceBadge source={r.source} />}
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
            {ontName && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0, fontWeight: 500,
              }}>{ontName}</span>
            )}
          </>
        )
        const sharedStyle: React.CSSProperties = {
          padding: '8px 10px', borderRadius: 'var(--radius-sm)',
          display: 'flex', gap: 10, alignItems: 'baseline',
          borderBottom: '1px solid var(--border)',
          textDecoration: 'none',
        }
        return path ? (
          <li key={r.iri}>
            <Link
              to={path}
              style={sharedStyle}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              {inner}
            </Link>
          </li>
        ) : (
          <li key={r.iri} style={{ ...sharedStyle, color: 'var(--text-dim)' }}>
            {inner}
          </li>
        )
      })}
    </ul>
  )
}
