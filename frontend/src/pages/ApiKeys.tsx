import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ApiKey } from '../lib/api'

export default function ApiKeys() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  const { data, isLoading } = useQuery({ queryKey: ['api-keys'], queryFn: () => api.apiKeys.list() })

  const create = useMutation({
    mutationFn: () => api.apiKeys.create(name, ['read']),
    onSuccess: (key: ApiKey) => {
      setNewKey(key.key ?? null)
      setName('')
      qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api.apiKeys.revoke(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>API Keys</h1>
        <button
          onClick={() => { setShowForm(v => !v); setNewKey(null) }}
          style={{
            padding: '0.35rem 0.8rem',
            background: showForm ? 'var(--bg-secondary)' : 'var(--accent)',
            color: showForm ? 'var(--text-muted)' : '#0f172a',
            border: showForm ? '1px solid var(--border)' : 'none',
            borderRadius: 'var(--radius-sm)',
            fontWeight: 600,
            fontSize: 'var(--font-size-sm)',
          }}
        >
          {showForm ? '× Cancel' : '+ New Key'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div style={{
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: '1rem',
          marginBottom: '1.25rem',
        }}>
          <form onSubmit={e => { e.preventDefault(); create.mutate() }} style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Key name (e.g. my-script)"
              required
              style={{ flex: 1 }}
            />
            <button
              type="submit"
              disabled={create.isPending}
              style={{
                padding: '0.4rem 0.9rem',
                background: 'var(--accent)',
                color: '#0f172a',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 700,
                fontSize: 'var(--font-size-sm)',
              }}
            >
              {create.isPending ? 'Creating…' : 'Create'}
            </button>
          </form>

          {newKey && (
            <div style={{
              marginTop: '0.75rem',
              padding: '0.75rem',
              background: 'rgba(16, 185, 129, 0.08)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
              borderRadius: 'var(--radius-sm)',
            }}>
              <p style={{ fontWeight: 600, color: 'var(--accent)', marginBottom: '0.25rem', fontSize: 'var(--font-size-sm)' }}>
                Copy this key now — it won't be shown again:
              </p>
              <code style={{ wordBreak: 'break-all', fontSize: 'var(--font-size-sm)', color: 'var(--text)' }}>{newKey}</code>
            </div>
          )}
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <thead>
            <tr style={{ background: 'var(--bg-secondary)' }}>
              {['Name', 'Scopes', 'Created', 'Last used', ''].map(h => (
                <th key={h} style={{
                  padding: '0.5rem 1rem',
                  textAlign: 'left',
                  fontSize: 'var(--font-size-sm)',
                  fontWeight: 600,
                  color: 'var(--text-dim)',
                  borderBottom: '1px solid var(--border)',
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.api_keys ?? []).map(k => (
              <tr key={k.id} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '0.6rem 1rem', fontSize: 'var(--font-size-base)', fontWeight: 500 }}>{k.name}</td>
                <td style={{ padding: '0.6rem 1rem', fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}>{k.scopes.join(', ')}</td>
                <td style={{ padding: '0.6rem 1rem', fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{new Date(k.created_at).toLocaleDateString()}</td>
                <td style={{ padding: '0.6rem 1rem', fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : '—'}</td>
                <td style={{ padding: '0.6rem 1rem', whiteSpace: 'nowrap' }}>
                  <button
                    onClick={() => revoke.mutate(k.id)}
                    style={{ fontSize: 'var(--font-size-sm)', color: '#f87171' }}
                  >
                    revoke
                  </button>
                </td>
              </tr>
            ))}
            {!data?.api_keys.length && (
              <tr>
                <td colSpan={5} style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
                  No API keys yet. Use "+ New Key" above to create one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
