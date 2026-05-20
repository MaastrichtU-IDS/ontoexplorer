import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ReuseReport } from '../lib/api'


function Card({
  title,
  count,
  testId,
  children,
}: {
  title: string
  count: number
  testId: string
  children: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div
      data-testid={testId}
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '0.75rem',
      }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text)',
          fontWeight: 600,
          fontSize: 'var(--font-size-sm)',
          cursor: 'pointer',
          padding: 0,
          width: '100%',
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <span>{title}</span>
        <span style={{ color: 'var(--text-dim)' }}>
          {count.toLocaleString()} {expanded ? '▲' : '▼'}
        </span>
      </button>
      {expanded && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  )
}


export function ReuseSection({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data, isLoading, error } = useQuery<ReuseReport>({
    queryKey: ['reuse', ontologyId, versionId],
    queryFn: () => api.ontologies.reuse(ontologyId, versionId),
    retry: false,
  })

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading reuse…</div>
  if (error) return <div style={{ color: 'var(--text-dim)' }}>No reuse report yet (reindex pending)</div>
  if (!data) return null

  const termIRIPairs = Object.entries(data.term_iri_reuse).sort(
    (a, b) => (b[1].class_count + b[1].property_count) - (a[1].class_count + a[1].property_count)
  )

  return (
    <div style={{ display: 'grid', gap: '0.5rem', padding: '0.75rem' }}>
      <Card title="owl:imports" count={data.imports.length} testId="reuse-card-imports">
        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
          {data.imports.map((edge, i) => (
            <li key={i}>
              <code style={{ color: 'var(--accent-blue)' }}>{edge.target_prefix ?? '(unresolved)'}</code>
              {' — '}
              <span style={{ color: 'var(--text-dim)', wordBreak: 'break-all' }}>
                {edge.target_iri}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card
        title="Term-IRI reuse"
        count={termIRIPairs.reduce((acc, [, v]) => acc + v.class_count + v.property_count, 0)}
        testId="reuse-card-term-iri"
      >
        <table style={{ width: '100%', fontSize: 11 }}>
          <thead>
            <tr style={{ color: 'var(--text-dim)' }}>
              <th style={{ textAlign: 'left' }}>Source</th>
              <th style={{ textAlign: 'right' }}>Classes</th>
              <th style={{ textAlign: 'right' }}>Properties</th>
            </tr>
          </thead>
          <tbody>
            {termIRIPairs.map(([prefix, entry]) => (
              <tr key={prefix}>
                <td>
                  <code style={{ color: 'var(--accent-blue)' }}>{prefix}</code>
                </td>
                <td style={{ textAlign: 'right' }}>{entry.class_count}</td>
                <td style={{ textAlign: 'right' }}>{entry.property_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="MIREOT-style terms"
        count={data.mireot_terms.length}
        testId="reuse-card-mireot"
      >
        {data.mireot_terms.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            No MIREOT-pattern terms detected.
          </div>
        ) : (
          <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
            {data.mireot_terms.slice(0, 20).map((term, i) => (
              <li key={i}>
                <code style={{ color: 'var(--accent-blue)' }}>{term.source_prefix}</code>
                {' '}
                <span style={{ color: 'var(--text-dim)', wordBreak: 'break-all' }}>
                  {term.iri}
                </span>
                {term.has_imported_from && (
                  <span style={{ color: '#3fb950', marginLeft: 4 }}>★</span>
                )}
              </li>
            ))}
            {data.mireot_terms.length > 20 && (
              <li style={{ color: 'var(--text-dim)' }}>
                … {data.mireot_terms.length - 20} more
              </li>
            )}
          </ul>
        )}
      </Card>

      <Card
        title="Cross-ontology mappings"
        count={Object.values(data.mappings).reduce(
          (acc, entries) => acc + entries.reduce((a, e) => a + e.count, 0), 0,
        )}
        testId="reuse-card-mappings"
      >
        {Object.entries(data.mappings).map(([predicate, entries]) => (
          <div key={predicate} style={{ marginBottom: 4 }}>
            <strong style={{ fontSize: 11 }}>{predicate}</strong>
            <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
              {entries.map((e, i) => (
                <li key={i}>
                  <code style={{ color: 'var(--accent-blue)' }}>
                    {e.target_prefix ?? '(unresolved)'}
                  </code>
                  : {e.count}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Card>
    </div>
  )
}
