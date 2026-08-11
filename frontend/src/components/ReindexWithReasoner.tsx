import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

/**
 * Reasoner dropdown + an index/re-reason icon button for a single ontology
 * version. Defaults the dropdown to the version's previously-selected reasoner.
 * Used on both the owner Dashboard and the Admin dashboard — both hit the same
 * owner-scoped endpoint (can_edit gates it; admins pass).
 */
export default function ReindexWithReasoner({
  ontologyId, versionId, currentReasoner, onQueued,
}: {
  ontologyId: string
  versionId: string
  currentReasoner?: string | null
  onQueued?: () => void
}) {
  const { data } = useQuery({
    queryKey: ['reasoners'],
    queryFn: () => api.reasoners.list(),
    staleTime: 300_000,
  })
  // Only reasoners that are up and can classify are usable for (re)reasoning.
  const usable = (data ?? []).filter(r => r.available && r.capabilities.includes('classify'))

  const [picked, setPicked] = useState('')
  // Effective choice: explicit pick → the version's previous reasoner → first usable.
  const chosen = picked || currentReasoner || usable[0]?.name || ''
  // Keep the current reasoner selectable even if the service didn't list it.
  const names = usable.map(r => r.name)
  const options = chosen && !names.includes(chosen) ? [chosen, ...names] : names

  const mutation = useMutation({
    mutationFn: () => api.ontologies.reason(ontologyId, versionId, chosen || undefined),
    onSuccess: () => onQueued?.(),
  })

  // The 'queued'/'failed' badge is transient click-feedback, not a live status —
  // the reasoning StatusDot (which polls) reflects the real state. Clear it after
  // a few seconds so it doesn't linger as a stale "queued" long after the job ran.
  const settled = mutation.isSuccess || mutation.isError
  useEffect(() => {
    if (!settled) return
    const t = setTimeout(() => mutation.reset(), 4000)
    return () => clearTimeout(t)
  }, [settled, mutation])

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <select
        value={chosen}
        onChange={e => setPicked(e.target.value)}
        disabled={mutation.isPending || options.length === 0}
        title="Reasoner"
        style={{
          fontSize: 11, padding: '2px 4px', borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
          maxWidth: 120,
        }}
      >
        {options.length === 0 && <option value="">—</option>}
        {options.map(n => <option key={n} value={n}>{n}</option>)}
      </select>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !chosen}
        title={chosen ? `Re-index with ${chosen}` : 'No reasoner available'}
        style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 24, height: 22, cursor: mutation.isPending || !chosen ? 'default' : 'pointer',
          borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
          background: 'var(--bg-secondary)', color: 'var(--accent-blue)', fontSize: 12,
        }}
        aria-label="Re-index with reasoner"
      >
        {mutation.isPending ? '…' : '⟳'}
      </button>
      {mutation.isSuccess && (
        <span style={{ fontSize: 10, color: 'var(--accent-blue)' }}>queued</span>
      )}
      {mutation.isError && (
        <span style={{ fontSize: 10, color: 'var(--red)' }} title={(mutation.error as Error)?.message}>
          failed
        </span>
      )}
    </span>
  )
}
