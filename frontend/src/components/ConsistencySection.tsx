import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ConsistencyReport, ConsistencyScopeName, ScopeResult } from '../lib/api'


const SCOPE_LABELS: Record<ConsistencyScopeName, string> = {
  host_only: 'Host only',
  host_plus_imports: 'Host + imports',
  host_plus_imports_plus_mireot: 'Host + imports + MIREOT sources',
}

const STATUS_COLOR: Record<string, string> = {
  consistent: '#3fb950',
  inconsistent: '#e06c75',
  partial: '#e5c07b',
  timeout: '#c678dd',
  error: '#e06c75',
}

function StatusBadge({ status }: { status: string }) {
  const symbol =
    status === 'consistent' ? '✓' :
    status === 'inconsistent' ? '✗' :
    status === 'partial' ? '⚠' :
    status === 'timeout' ? '⏱' : '!'
  return (
    <span style={{ color: STATUS_COLOR[status] ?? 'var(--text)', fontWeight: 700 }}>
      {symbol} {status}
    </span>
  )
}

function ScopeCard({ scope, result }: { scope: ConsistencyScopeName; result: ScopeResult }) {
  const [expanded, setExpanded] = useState(false)
  const top10 = result.unsatisfiable_classes.slice(0, 10)
  return (
    <div data-testid={`consistency-card-${scope}`} style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '0.75rem',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: 'var(--font-size-sm)' }}>{SCOPE_LABELS[scope]}</strong>
        <StatusBadge status={result.status} />
      </div>
      <p style={{ fontSize: 10, color: 'var(--text-dim)', margin: '4px 0 0' }}>
        {result.unsatisfiable_classes.length} unsat
        {result.mireot_sources_skipped.length > 0 && (
          <> · {result.mireot_sources_skipped.length} MIREOT sources skipped</>
        )}
        {result.error_message && <> · {result.error_message}</>}
      </p>
      {top10.length > 0 && (
        <button onClick={() => setExpanded(!expanded)} style={{
          background: 'none', border: 'none', color: 'var(--accent-blue)',
          cursor: 'pointer', padding: '4px 0', fontSize: 11,
        }}>
          {expanded ? '▲ Hide' : '▼ Show'} justifications
        </button>
      )}
      {expanded && (
        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
          {top10.map(uc => (
            <li key={uc.iri} style={{ marginBottom: 6 }}>
              <code style={{ color: 'var(--accent-blue)' }}>{uc.label || uc.iri}</code>
              {uc.justification.length > 0 && (
                <ul style={{ margin: '2px 0 0', paddingLeft: '1rem' }}>
                  {uc.justification.map((ax, i) => (
                    <li key={i} style={{ fontFamily: 'monospace', fontSize: 10 }}>
                      {ax.manchester.map((tok, j) =>
                        tok.t === 'iri'
                          ? <span key={j} style={{ color: 'var(--accent-blue)' }}>
                              {tok.label ?? tok.iri}
                            </span>
                          : <span key={j}>{tok.v}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}


export function ConsistencySection({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data, isLoading, error } = useQuery<ConsistencyReport>({
    queryKey: ['consistency', ontologyId, versionId],
    queryFn: () => api.ontologies.consistency(ontologyId, versionId),
    retry: false,
    // Poll while pending/running
    refetchInterval: (q) => {
      const s = (q.state.data as ConsistencyReport | undefined)?.job_status
      return s === 'pending' || s === 'running' ? 5000 : false
    },
  })

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading consistency…</div>
  if (error) return <div style={{ color: 'var(--text-dim)' }}>No consistency report yet (reindex pending)</div>
  if (!data) return null

  if (data.job_status === 'pending' || data.job_status === 'running') {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>
        <p>⏳ Consistency analysis running…</p>
        <p style={{ fontSize: 11 }}>
          Three reasoning scopes (host-only, host+imports, host+imports+MIREOT sources).
          This can take a few minutes for large ontologies. The page updates automatically.
        </p>
      </div>
    )
  }

  if (data.job_status === 'failed') {
    return <div style={{ padding: '1rem', color: '#e06c75' }}>
      ✗ Analysis failed. Click refresh in admin to re-enqueue.
    </div>
  }

  return (
    <div style={{ display: 'grid', gap: '0.5rem', padding: '0.75rem' }}>
      {(['host_only', 'host_plus_imports', 'host_plus_imports_plus_mireot'] as const).map(s => {
        const sr = data.scopes[s]
        if (!sr) return null
        return <ScopeCard key={s} scope={s} result={sr} />
      })}
    </div>
  )
}
