import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

/**
 * Reasoner-profile dropdown + a re-reason icon button for a single ontology
 * version. Picks a reasoner PROFILE (reasoner + params) and re-classifies with it.
 * On the owner Dashboard it offers dashboard-selectable profiles; on the Admin
 * dashboard (admin) it offers all non-archived profiles.
 */
export default function ReindexWithReasoner({
  ontologyId, versionId, currentProfileId, admin = false, onQueued,
}: {
  ontologyId: string
  versionId: string
  currentProfileId?: string | null
  admin?: boolean
  onQueued?: () => void
}) {
  const { data } = useQuery({
    queryKey: admin ? ['admin', 'reasoner-profiles'] : ['reasoner-profiles'],
    queryFn: () => (admin ? api.admin.reasonerProfiles() : api.reasonerProfiles.list()),
    staleTime: 60_000,
  })
  const profiles = (data?.profiles ?? []).filter(p => !p.archived)

  const [picked, setPicked] = useState('')
  // Effective choice: explicit pick → the version's bound profile → default → first.
  const chosen = picked
    || (currentProfileId && profiles.some(p => p.id === currentProfileId) ? currentProfileId : '')
    || profiles.find(p => p.is_default)?.id
    || profiles[0]?.id
    || ''

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
        disabled={mutation.isPending || profiles.length === 0}
        title="Reasoner profile"
        style={{
          fontSize: 11, padding: '2px 4px', borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
          maxWidth: 150,
        }}
      >
        {profiles.length === 0 && <option value="">—</option>}
        {profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !chosen}
        title={chosen ? 'Re-index with this profile' : 'No reasoner profile available'}
        style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 24, height: 22, cursor: mutation.isPending || !chosen ? 'default' : 'pointer',
          borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
          background: 'var(--bg-secondary)', color: 'var(--accent-blue)', fontSize: 12,
        }}
        aria-label="Re-index with reasoner profile"
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
