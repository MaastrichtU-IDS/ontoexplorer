import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import IriAutocomplete from './IriAutocomplete'

/**
 * Incremental EL++ reasoning workbench (km) for one ontology version. Start a
 * live session, ask "is A ⊑ B?" on demand, and assert a hypothetical axiom to
 * watch the entailment flip — all without re-classifying. EL++ only.
 */
export default function IncrementalReasoningPanel({ ontologyId, versionId }: {
  ontologyId: string
  versionId: string
}) {
  const [session, setSession] = useState<{ id: string; revision: number; inconsistent: boolean; total: number } | null>(null)
  const [sub, setSub] = useState('')
  const [sup, setSup] = useState('')
  const [result, setResult] = useState<{ sub: string; sup: string; entailed: boolean | null } | null>(null)
  const [asserted, setAsserted] = useState<{ label: string; clauseIds: number[] }[]>([])
  const [axiomText, setAxiomText] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Close the session when the panel unmounts.
  useEffect(() => () => {
    if (session) api.ontologies.incremental.close(ontologyId, versionId, session.id).catch(() => {})
  }, [session, ontologyId, versionId])

  const start = useMutation({
    mutationFn: () => api.ontologies.incremental.start(ontologyId, versionId),
    onSuccess: r => { setError(null); setSession({ id: r.session_id, revision: r.revision, inconsistent: r.inconsistent, total: r.total_clauses }) },
    onError: (e: unknown) => setError((e as Error)?.message ?? 'Could not start a session (is this ontology EL++?)'),
  })

  const ask = useMutation({
    mutationFn: () => api.ontologies.incremental.subsumed(ontologyId, versionId, session!.id, sub.trim(), sup.trim()),
    onSuccess: r => { setError(null); setResult({ sub: r.sub, sup: r.sup, entailed: r.entailed }) },
    onError: (e: unknown) => setError((e as Error)?.message ?? 'Query failed'),
  })

  const assertAxiom = useMutation({
    mutationFn: () => api.ontologies.incremental.assert(ontologyId, versionId, session!.id, sub.trim(), sup.trim()),
    onSuccess: (r, _v, ctx) => {
      setError(null)
      setSession(s => s ? { ...s, revision: r.revision, inconsistent: r.inconsistent } : s)
      const a = ctx as { sub: string; sup: string }
      if (r.clause_ids?.length) {
        setAsserted(list => [...list, { label: `${a.sub} ⊑ ${a.sup}`, clauseIds: r.clause_ids }])
      }
      ask.mutate()   // re-run the query so the flip is visible
    },
    onMutate: () => ({ sub: sub.trim(), sup: sup.trim() }),
    onError: (e: unknown) => setError((e as Error)?.message ?? 'Assert failed'),
  })

  const assertAxioms = useMutation({
    mutationFn: () => api.ontologies.incremental.assertAxioms(ontologyId, versionId, session!.id, axiomText.trim()),
    onSuccess: (r, _v, ctx) => {
      setError(null)
      setSession(s => s ? { ...s, revision: r.revision, inconsistent: r.inconsistent } : s)
      const text = ctx as string
      if (r.clause_ids?.length) {
        setAsserted(list => [...list, { label: text.replace(/\s+/g, ' ').slice(0, 120), clauseIds: r.clause_ids }])
      }
      setAxiomText('')
      if (canQuery) ask.mutate()   // refresh the current query if one is set
    },
    onMutate: () => axiomText.trim(),
    onError: (e: unknown) => setError((e as Error)?.message ?? 'Assert failed (is it valid EL++ functional syntax?)'),
  })

  const retract = useMutation({
    mutationFn: (clauseIds: number[]) =>
      api.ontologies.incremental.retract(ontologyId, versionId, session!.id, clauseIds),
    onSuccess: (r, clauseIds) => {
      setError(null)
      setSession(s => s ? { ...s, revision: r.revision, inconsistent: r.inconsistent } : s)
      setAsserted(list => list.filter(a => a.clauseIds !== clauseIds))
      ask.mutate()   // re-run the query so the flip back is visible
    },
    onError: (e: unknown) => setError((e as Error)?.message ?? 'Retract failed'),
  })

  const canQuery = !!session && !!sub.trim() && !!sup.trim()
  const input: React.CSSProperties = {
    fontSize: 13, padding: '5px 8px', borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', flex: 1, minWidth: 0,
  }
  const btn: React.CSSProperties = {
    fontSize: 13, padding: '5px 12px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
    border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text)', whiteSpace: 'nowrap',
  }

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 14 }}>Incremental reasoning <span style={{ fontSize: 11, color: 'var(--text-dim)', fontWeight: 400 }}>· km EL++ · experimental</span></strong>
        {session ? (
          <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            session live · rev {session.revision} · {session.total} clauses
            {session.inconsistent && <span style={{ color: 'var(--red)' }}> · inconsistent</span>}
          </span>
        ) : (
          <button type="button" style={{ ...btn, background: 'var(--accent-blue)', color: '#fff', border: 'none' }}
                  onClick={() => start.mutate()} disabled={start.isPending}>
            {start.isPending ? 'Starting…' : 'Start session'}
          </button>
        )}
      </div>

      <p style={{ fontSize: 12, color: 'var(--text-dim)', margin: 0 }}>
        Ask whether one class is inferred to be a subclass of another, then assert a hypothetical
        axiom and watch the answer change — the reasoner updates without reclassifying.
      </p>

      {session && (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <IriAutocomplete ontologyId={ontologyId} versionId={versionId}
              value={sub} onChange={setSub} placeholder="sub class (name or IRI)" style={input} />
            <span style={{ color: 'var(--text-dim)' }}>⊑</span>
            <IriAutocomplete ontologyId={ontologyId} versionId={versionId}
              value={sup} onChange={setSup} placeholder="super class (name or IRI)" style={input} />
            <button type="button" style={btn} onClick={() => ask.mutate()} disabled={!canQuery || ask.isPending}>
              {ask.isPending ? '…' : 'Ask'}
            </button>
            <button type="button" style={btn} onClick={() => assertAxiom.mutate()} disabled={!canQuery || assertAxiom.isPending}
                    title="Add this subclass axiom to the live session (hypothetical)">
              {assertAxiom.isPending ? '…' : '+ Assert ⊑'}
            </button>
          </div>

          {result && (
            <div style={{ fontSize: 14 }}>
              <code style={{ fontSize: 12 }}>{result.sub}</code> ⊑ <code style={{ fontSize: 12 }}>{result.sup}</code>{' '}
              →{' '}
              <strong style={{ color: result.entailed ? 'var(--green)' : (result.entailed === false ? 'var(--red)' : 'var(--text-dim)') }}>
                {result.entailed === null ? 'unknown class' : result.entailed ? 'entailed' : 'not entailed'}
              </strong>
            </div>
          )}

          {asserted.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Asserted this session
              </span>
              {asserted.map((a, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <code style={{ fontSize: 11, wordBreak: 'break-all' }}>{a.label}</code>
                  <button type="button"
                          onClick={() => retract.mutate(a.clauseIds)}
                          disabled={retract.isPending}
                          title="Retract this hypothetical axiom"
                          style={{ ...btn, fontSize: 11, padding: '1px 6px', color: 'var(--red)', flexShrink: 0 }}>
                    ✕ retract
                  </button>
                </div>
              ))}
            </div>
          )}

          <details style={{ fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-dim)' }}>
              Advanced: assert arbitrary axioms (OWL functional syntax)
            </summary>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
              <textarea
                value={axiomText}
                onChange={e => setAxiomText(e.target.value)}
                placeholder={'SubClassOf(<http://…/A> ObjectSomeValuesFrom(<http://…/r> <http://…/B>))\nDisjointClasses(<http://…/A> <http://…/C>)'}
                rows={3}
                style={{ ...input, fontFamily: 'var(--font-mono, monospace)', resize: 'vertical' }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button type="button" style={btn}
                        onClick={() => assertAxioms.mutate()}
                        disabled={!session || !axiomText.trim() || assertAxioms.isPending}
                        title="Normalize and add these axioms to the live session (must be EL++)">
                  {assertAxioms.isPending ? '…' : '+ Assert axioms'}
                </button>
                <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  one or more axioms, full IRIs; EL++ only
                </span>
              </div>
            </div>
          </details>
        </>
      )}

      {error && <span style={{ color: 'var(--red)', fontSize: 12 }}>{error}</span>}
    </div>
  )
}
