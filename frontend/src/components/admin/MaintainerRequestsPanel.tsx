import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, MaintainerRequest } from '../../lib/api'

const STATUS_COLOR: Record<string, string> = {
  pending: '#f0883e',
  approved: '#3fb950',
  denied: 'var(--error, #e06c75)',
}

function requestTarget(r: MaintainerRequest): string {
  if (r.request_type === 'uploader') return 'Add new ontologies (upload access)'
  return `Maintain ontology: ${r.ontology_shortname || r.ontology_iri || r.ontology_id}`
}

export function MaintainerRequestsPanel() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<'pending' | 'approved' | 'denied' | 'all'>('pending')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'maintainer-requests', statusFilter],
    queryFn: () => api.admin.maintainerRequests(statusFilter === 'all' ? undefined : statusFilter),
  })

  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'deny' }) =>
      action === 'approve'
        ? api.admin.approveMaintainerRequest(id, notes[id])
        : api.admin.denyMaintainerRequest(id, notes[id]),
    onSuccess: () => {
      setErr(null)
      qc.invalidateQueries({ queryKey: ['admin', 'maintainer-requests'] })
    },
    onError: (e) => setErr((e as Error)?.message || 'Action failed'),
  })

  const requests = data?.requests ?? []

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: '1rem' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text)', margin: 0 }}>
          Maintainer requests
        </h2>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value as typeof statusFilter)}
          style={{
            background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)',
            borderRadius: 'var(--radius-sm)', padding: '4px 8px', fontSize: 'var(--font-size-sm)',
          }}
        >
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="denied">Denied</option>
          <option value="all">All</option>
        </select>
      </div>

      {err && <p style={{ color: 'var(--error, #e06c75)', fontSize: 'var(--font-size-sm)' }}>{err}</p>}
      {isLoading && <p style={{ color: 'var(--text-dim)' }}>Loading…</p>}
      {!isLoading && requests.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No {statusFilter === 'all' ? '' : statusFilter} requests.</p>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {requests.map(r => (
          <div key={r.id} style={{
            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            background: 'var(--bg-secondary)', padding: '0.9rem 1.1rem',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, color: 'var(--text)', fontSize: 'var(--font-size-sm)' }}>
                {requestTarget(r)}
              </span>
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: STATUS_COLOR[r.status], textTransform: 'uppercase' }}>
                {r.status}
              </span>
            </div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginTop: 4 }}>
              {r.user_display_name || r.user_email || r.user_id}
              {r.user_email && r.user_display_name ? ` · ${r.user_email}` : ''}
              {' · '}{new Date(r.created_at).toLocaleString()}
            </div>
            {r.note && (
              <div style={{ marginTop: 8, fontSize: 'var(--font-size-sm)', color: 'var(--text)', whiteSpace: 'pre-wrap' }}>
                <span style={{ color: 'var(--text-dim)' }}>Rationale: </span>{r.note}
              </div>
            )}

            {r.status === 'pending' ? (
              <div style={{ marginTop: 10 }}>
                <textarea
                  placeholder="Optional decision note (shown to the requester)"
                  value={notes[r.id] ?? ''}
                  onChange={e => setNotes(n => ({ ...n, [r.id]: e.target.value }))}
                  rows={2}
                  style={{
                    width: '100%', boxSizing: 'border-box', background: 'var(--bg)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                    color: 'var(--text)', fontSize: 'var(--font-size-sm)', padding: '6px 8px', resize: 'vertical',
                  }}
                />
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button
                    onClick={() => decide.mutate({ id: r.id, action: 'approve' })}
                    disabled={decide.isPending}
                    style={{
                      padding: '5px 14px', borderRadius: 'var(--radius-sm)', border: 'none',
                      background: '#3fb950', color: '#0a0f1a', fontWeight: 600,
                      fontSize: 'var(--font-size-sm)', cursor: 'pointer',
                    }}
                  >Approve</button>
                  <button
                    onClick={() => decide.mutate({ id: r.id, action: 'deny' })}
                    disabled={decide.isPending}
                    style={{
                      padding: '5px 14px', borderRadius: 'var(--radius-sm)',
                      background: 'transparent', border: '1px solid var(--border)',
                      color: 'var(--error, #e06c75)', fontSize: 'var(--font-size-sm)', cursor: 'pointer',
                    }}
                  >Deny</button>
                </div>
              </div>
            ) : (
              r.decision_note && (
                <div style={{ marginTop: 8, fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', whiteSpace: 'pre-wrap' }}>
                  Decision note: {r.decision_note}
                </div>
              )
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
