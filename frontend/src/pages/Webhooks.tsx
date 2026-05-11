import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Webhook } from '../lib/api'

export default function Webhooks() {
  const qc = useQueryClient()
  const [url, setUrl] = useState('')
  const [secret, setSecret] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>(['ontology.ingested'])
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const ALL_EVENTS = [
    'ontology.ingested',
    'version.deprecated',
    'reasoning.completed',
    'reasoning.failed',
    'indexing.completed',
  ]

  const { data, isLoading } = useQuery({ queryKey: ['webhooks'], queryFn: () => api.webhooks.list() })

  const { data: deliveries } = useQuery({
    queryKey: ['webhook-deliveries', expandedId],
    queryFn: () => api.webhooks.deliveries(expandedId!),
    enabled: !!expandedId,
  })

  const create = useMutation({
    mutationFn: () => api.webhooks.create(url, selectedEvents, secret || undefined),
    onSuccess: () => {
      setUrl('')
      setSecret('')
      setSelectedEvents(['ontology.ingested'])
      qc.invalidateQueries({ queryKey: ['webhooks'] })
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.webhooks.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks'] }),
  })

  const test = useMutation({
    mutationFn: (id: string) => api.webhooks.test(id),
    onSuccess: (_, id) => qc.invalidateQueries({ queryKey: ['webhook-deliveries', id] }),
  })

  function toggleEvent(event: string) {
    setSelectedEvents(prev =>
      prev.includes(event) ? prev.filter(e => e !== event) : [...prev, event]
    )
  }

  return (
    <div>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '1.5rem' }}>Webhooks</h1>

      <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '1.25rem', marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.75rem' }}>Register webhook</h2>
        <form onSubmit={e => { e.preventDefault(); create.mutate() }}>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
            <input
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://example.com/webhook"
              required
              style={{ flex: 1, padding: '0.5rem 0.75rem', border: '1px solid #e2e8f0', borderRadius: 6 }}
            />
            <input
              value={secret}
              onChange={e => setSecret(e.target.value)}
              placeholder="Optional signing secret"
              style={{ flex: 1, padding: '0.5rem 0.75rem', border: '1px solid #e2e8f0', borderRadius: 6 }}
            />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
            {ALL_EVENTS.map(ev => (
              <label key={ev} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem', cursor: 'pointer' }}>
                <input type="checkbox" checked={selectedEvents.includes(ev)} onChange={() => toggleEvent(ev)} />
                <code>{ev}</code>
              </label>
            ))}
          </div>
          <button
            type="submit"
            disabled={create.isPending || selectedEvents.length === 0}
            style={{ padding: '0.5rem 1rem', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, fontWeight: 600 }}
          >
            {create.isPending ? 'Registering…' : 'Register'}
          </button>
          {create.isError && (
            <p style={{ marginTop: '0.5rem', color: '#dc2626', fontSize: '0.875rem' }}>
              {(create.error as Error).message}
            </p>
          )}
        </form>
      </div>

      {isLoading ? <p style={{ color: '#64748b' }}>Loading…</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {(data?.webhooks ?? []).map((wh: Webhook) => (
            <div key={wh.id} style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
              <div style={{ padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div style={{ flex: 1 }}>
                  <code style={{ fontSize: '0.875rem', fontWeight: 500 }}>{wh.url}</code>
                  <div style={{ marginTop: '0.25rem', display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                    {wh.events.map(ev => (
                      <span key={ev} style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', background: '#eff6ff', color: '#2563eb', borderRadius: 4 }}>{ev}</span>
                    ))}
                  </div>
                </div>
                <span style={{ fontSize: '0.75rem', color: wh.active ? '#16a34a' : '#94a3b8', fontWeight: 600 }}>
                  {wh.active ? 'Active' : 'Inactive'}
                </span>
                <button
                  onClick={() => test.mutate(wh.id)}
                  disabled={test.isPending}
                  style={{ fontSize: '0.8rem', padding: '0.25rem 0.5rem', border: '1px solid #e2e8f0', borderRadius: 4, background: '#fff' }}
                >
                  Test
                </button>
                <button
                  onClick={() => setExpandedId(expandedId === wh.id ? null : wh.id)}
                  style={{ fontSize: '0.8rem', padding: '0.25rem 0.5rem', border: '1px solid #e2e8f0', borderRadius: 4, background: '#fff' }}
                >
                  {expandedId === wh.id ? 'Hide' : 'History'}
                </button>
                <button
                  onClick={() => remove.mutate(wh.id)}
                  style={{ fontSize: '0.8rem', color: '#dc2626', background: 'none', border: '1px solid #fca5a5', borderRadius: 4, padding: '0.25rem 0.5rem' }}
                >
                  Delete
                </button>
              </div>

              {expandedId === wh.id && (
                <div style={{ borderTop: '1px solid #f1f5f9', padding: '0.75rem 1rem' }}>
                  <p style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', marginBottom: '0.5rem' }}>Delivery history</p>
                  {!deliveries?.deliveries.length ? (
                    <p style={{ fontSize: '0.8rem', color: '#94a3b8' }}>No deliveries yet.</p>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                      <thead>
                        <tr>
                          {['Event', 'Status', 'HTTP', 'Attempts', 'Last attempt'].map(h => (
                            <th key={h} style={{ textAlign: 'left', padding: '0.25rem 0.5rem', color: '#64748b', fontWeight: 600 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {deliveries.deliveries.map((d: any) => (
                          <tr key={d.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                            <td style={{ padding: '0.25rem 0.5rem' }}><code>{d.event}</code></td>
                            <td style={{ padding: '0.25rem 0.5rem', color: d.status === 'delivered' ? '#16a34a' : '#dc2626' }}>{d.status}</td>
                            <td style={{ padding: '0.25rem 0.5rem' }}>{d.response_status ?? '—'}</td>
                            <td style={{ padding: '0.25rem 0.5rem' }}>{d.attempts}</td>
                            <td style={{ padding: '0.25rem 0.5rem', color: '#64748b' }}>
                              {d.last_attempt_at ? new Date(d.last_attempt_at).toLocaleString() : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
          {!data?.webhooks.length && (
            <p style={{ textAlign: 'center', color: '#94a3b8', padding: '1.5rem' }}>No webhooks registered.</p>
          )}
        </div>
      )}
    </div>
  )
}
