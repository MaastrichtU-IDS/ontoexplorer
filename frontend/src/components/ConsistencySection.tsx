import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ClassExprNode, ConsistencyReport, ConsistencyScopeName, JustificationAxiom, JustificationResult, ScopeResult } from '../lib/api'


const OWL_NOTHING = 'http://www.w3.org/2002/07/owl#Nothing'


function exprLabel(n: ClassExprNode | undefined): string {
  if (!n) return '?'
  if (n.type === 'named') return n.label ?? n.iri ?? '?'
  // Fall back to a compact bracketed form for complex expressions (restrictions, intersections, etc.)
  return `(${n.type})`
}


/** Renders the inferred-axiom statement + its justification for a single
 *  unsatisfiable class, lazily fetched from the existing /justification endpoint
 *  which is backed by ELK + the hitting-set algorithm in the elk-service. */
function UnsatJustification({
  ontologyId, versionId, classIri, classLabel,
}: {
  ontologyId: string; versionId: string; classIri: string; classLabel: string | null
}) {
  const display = classLabel || classIri.split(/[#/]/).pop() || classIri
  const { data, isLoading, error } = useQuery<JustificationResult>({
    queryKey: ['unsat-justification', versionId, classIri],
    queryFn: () => api.ontologies.justification(ontologyId, versionId, classIri, OWL_NOTHING, 3),
    retry: false,
    staleTime: 5 * 60_000,  // 5 min — justifications are immutable per version
  })

  // The inferred axiom statement is always present (the class IS unsat per Konclude)
  const inferenceLine = (
    <div style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text)', marginTop: 2 }}>
      <span style={{ color: 'var(--accent-blue)' }}>{display}</span>
      <span style={{ color: 'var(--text-dim)', margin: '0 4px' }}>⊑</span>
      <span style={{ color: '#e06c75' }}>owl:Nothing</span>
      <span style={{ color: 'var(--text-dim)', marginLeft: 6, fontSize: 9 }}>(inferred)</span>
    </div>
  )

  let body: React.ReactNode = null
  if (isLoading) {
    body = <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 2 }}>fetching justification…</div>
  } else if (error || data?.timed_out) {
    body = <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 2, fontStyle: 'italic' }}>
      Justification fetch failed or timed out.
    </div>
  } else if (!data || data.justifications.length === 0) {
    body = <div style={{ color: 'var(--text-dim)', fontSize: 10, marginTop: 2, fontStyle: 'italic' }}>
      No justification available (ELK couldn't classify this class — likely requires a DL reasoner).
    </div>
  } else {
    // Render each justification as a "because:" block of axioms
    body = (
      <div style={{ marginTop: 4 }}>
        <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>because:</div>
        {data.justifications.map((just: JustificationAxiom[], i: number) => (
          <ul key={i} style={{ margin: '2px 0 0', paddingLeft: '1rem', listStyle: 'none' }}>
            {just.map((ax: JustificationAxiom, j: number) => (
              <li key={j} style={{ fontFamily: 'monospace', fontSize: 10, lineHeight: 1.5 }}>
                <span style={{ color: 'var(--text-dim)', marginRight: 4 }}>•</span>
                <span style={{ color: 'var(--accent-blue)' }}>{exprLabel(ax.sub)}</span>
                <span style={{ color: 'var(--text-dim)', margin: '0 4px' }}>
                  {ax.rel === 'subClassOf' ? '⊑'
                    : ax.rel === 'disjointWith' ? 'disjointWith'
                    : '≡'}
                </span>
                <span style={{ color: 'var(--text)' }}>{exprLabel(ax.sup)}</span>
              </li>
            ))}
            {i < data.justifications.length - 1 && (
              <li style={{ fontSize: 9, color: 'var(--text-dim)', marginTop: 4 }}>— or —</li>
            )}
          </ul>
        ))}
      </div>
    )
  }

  return (
    <div style={{ marginTop: 4, paddingLeft: 8, borderLeft: '2px solid var(--border)' }}>
      {inferenceLine}
      {body}
    </div>
  )
}


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

function ScopeCard({
  ontologyId, versionId, scope, result,
}: {
  ontologyId: string; versionId: string; scope: ConsistencyScopeName; result: ScopeResult
}) {
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

      {/* Special case: globally inconsistent (Konclude said inconsistent AND no unsat list
          — which means the consistency check itself failed, so classification was skipped). */}
      {result.status === 'inconsistent' && result.unsatisfiable_classes.length === 0 && (
        <div style={{ marginTop: 6, padding: '6px 8px', background: 'rgba(224,108,117,0.08)',
                      border: '1px solid rgba(224,108,117,0.3)', borderRadius: 'var(--radius-sm)',
                      fontSize: 11, color: '#e06c75' }}>
          <strong>Globally inconsistent.</strong> No model exists for this scope — every entailment is provable,
          including <code style={{ fontFamily: 'monospace' }}>owl:Thing ⊑ owl:Nothing</code>. Common causes: an
          individual asserted to be in disjoint classes, or a contradiction in property assertions. Check
          the asserted axioms for an individual that violates a disjointness or functional-property axiom.
        </div>
      )}

      {top10.length > 0 && (
        <button onClick={() => setExpanded(!expanded)} style={{
          background: 'none', border: 'none', color: 'var(--accent-blue)',
          cursor: 'pointer', padding: '4px 0', fontSize: 11,
        }}>
          {expanded ? '▲ Hide' : '▼ Show'} inferred axioms + justifications
        </button>
      )}
      {expanded && (
        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11, listStyle: 'none' }}>
          {top10.map(uc => (
            <li key={uc.iri} style={{ marginBottom: 8 }}>
              <UnsatJustification
                ontologyId={ontologyId}
                versionId={versionId}
                classIri={uc.iri}
                classLabel={uc.label}
              />
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
        return (
          <ScopeCard
            key={s}
            ontologyId={ontologyId}
            versionId={versionId}
            scope={s}
            result={sr}
          />
        )
      })}
    </div>
  )
}
