import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Webhook } from '../lib/api'

const ALL_EVENTS = [
  'ontology.ingested',
  'version.deprecated',
  'reasoning.completed',
  'reasoning.failed',
  'indexing.completed',
]

export default function Webhooks() {
  const qc = useQueryClient()
  const [url, setUrl] = useState('')
  const [secret, setSecret] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>(['ontology.ingested'])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

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
      setShowForm(false)
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
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Webhooks</h1>
        <button
          onClick={() => setShowForm(v => !v)}
          style={{
            padding: '0.35rem 0.8rem',
            background: showForm ? 'var(--bg-secondary)' : 'var(--accent)',
            color: showForm ? 'var(--text-muted)' : 'var(--bg)',
            border: showForm ? '1px solid var(--border)' : 'none',
            borderRadius: 'var(--radius-sm)',
            fontWeight: 600,
            fontSize: 'var(--font-size-sm)',
          }}
        >
          {showForm ? '× Cancel' : '+ Register Webhook'}
        </button>
      </div>

      {/* Register form */}
      {showForm && (
        <div style={{
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: '1rem',
          marginBottom: '1.25rem',
        }}>
          <form onSubmit={e => { e.preventDefault(); create.mutate() }}>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
              <input
                value={url}
                onChange={e => setUrl(e.target.value)}
                placeholder="https://example.com/webhook"
                required
                style={{ flex: 2 }}
              />
              <input
                value={secret}
                onChange={e => setSecret(e.target.value)}
                placeholder="Optional signing secret"
                style={{ flex: 1 }}
              />
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
              {ALL_EVENTS.map(ev => (
                <label key={ev} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: 'var(--font-size-sm)', cursor: 'pointer', color: 'var(--text-muted)' }}>
                  <input type="checkbox" checked={selectedEvents.includes(ev)} onChange={() => toggleEvent(ev)} />
                  <code style={{ color: 'var(--text-muted)' }}>{ev}</code>
                </label>
              ))}
            </div>
            <button
              type="submit"
              disabled={create.isPending || selectedEvents.length === 0}
              style={{
                padding: '0.4rem 0.9rem',
                background: 'var(--accent)',
                color: 'var(--bg)',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 700,
                fontSize: 'var(--font-size-sm)',
              }}
            >
              {create.isPending ? 'Registering…' : 'Register'}
            </button>
            {create.isError && (
              <span style={{ marginLeft: '0.75rem', color: 'var(--red-soft)', fontSize: 'var(--font-size-sm)' }}>
                {(create.error as Error).message}
              </span>
            )}
          </form>
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {(data?.webhooks ?? []).map((wh: Webhook) => (
            <div key={wh.id} style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
              <div style={{ padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <code style={{ fontSize: 'var(--font-size-base)', color: 'var(--text)' }}>{wh.url}</code>
                  <div style={{ marginTop: '0.25rem', display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                    {wh.events.map(ev => (
                      <span key={ev} style={{
                        fontSize: '0.7rem',
                        padding: '0.1rem 0.4rem',
                        background: 'rgba(99, 179, 237, 0.1)',
                        color: 'var(--accent-blue)',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid rgba(99, 179, 237, 0.2)',
                      }}>
                        {ev}
                      </span>
                    ))}
                  </div>
                </div>
                <span style={{
                  fontSize: 'var(--font-size-sm)',
                  color: wh.active ? 'var(--accent)' : 'var(--text-dim)',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                }}>
                  {wh.active ? 'active' : 'inactive'}
                </span>
                <button
                  onClick={() => test.mutate(wh.id)}
                  disabled={test.isPending}
                  style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}
                >
                  test
                </button>
                <button
                  onClick={() => setExpandedId(expandedId === wh.id ? null : wh.id)}
                  style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}
                >
                  {expandedId === wh.id ? 'hide' : 'history'}
                </button>
                <button
                  onClick={() => remove.mutate(wh.id)}
                  style={{ fontSize: 'var(--font-size-sm)', color: 'var(--red-soft)' }}
                >
                  delete
                </button>
              </div>

              {expandedId === wh.id && (
                <div style={{ borderTop: '1px solid var(--border)', padding: '0.75rem 1rem' }}>
                  <p style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-dim)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Delivery history
                  </p>
                  {!deliveries?.deliveries.length ? (
                    <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>No deliveries yet.</p>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
                      <thead>
                        <tr>
                          {['Event', 'Status', 'HTTP', 'Attempts', 'Last attempt'].map(h => (
                            <th key={h} style={{ textAlign: 'left', padding: '0.25rem 0.5rem', color: 'var(--text-dim)', fontWeight: 600 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {deliveries.deliveries.map((d: any) => (
                          <tr key={d.id} style={{ borderTop: '1px solid var(--border)' }}>
                            <td style={{ padding: '0.25rem 0.5rem' }}><code style={{ color: 'var(--text-muted)' }}>{d.event}</code></td>
                            <td style={{ padding: '0.25rem 0.5rem', color: d.status === 'delivered' ? 'var(--accent)' : 'var(--red-soft)' }}>{d.status}</td>
                            <td style={{ padding: '0.25rem 0.5rem', color: 'var(--text-muted)' }}>{d.response_status ?? '—'}</td>
                            <td style={{ padding: '0.25rem 0.5rem', color: 'var(--text-muted)' }}>{d.attempts}</td>
                            <td style={{ padding: '0.25rem 0.5rem', color: 'var(--text-dim)' }}>
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
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
              No webhooks registered. Use "+ Register Webhook" above to add one.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
