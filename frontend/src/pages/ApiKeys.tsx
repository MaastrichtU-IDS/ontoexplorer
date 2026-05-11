import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ApiKey } from '../lib/api'

export default function ApiKeys() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)

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
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '1.5rem' }}>API Keys</h1>

      <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '1.25rem', marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.75rem' }}>Create new key</h2>
        <form onSubmit={e => { e.preventDefault(); create.mutate() }} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Key name (e.g. my-script)"
            required
            style={{ flex: 1, padding: '0.5rem 0.75rem', border: '1px solid #e2e8f0', borderRadius: 6 }}
          />
          <button
            type="submit"
            disabled={create.isPending}
            style={{ padding: '0.5rem 1rem', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, fontWeight: 600 }}
          >
            Create
          </button>
        </form>

        {newKey && (
          <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6 }}>
            <p style={{ fontWeight: 600, color: '#15803d', marginBottom: '0.25rem' }}>Your key (copy it now — shown once):</p>
            <code style={{ wordBreak: 'break-all', fontSize: '0.875rem' }}>{newKey}</code>
          </div>
        )}
      </div>

      {isLoading ? <p style={{ color: '#64748b' }}>Loading…</p> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
          <thead style={{ background: '#f8fafc' }}>
            <tr>
              {['Name', 'Scopes', 'Created', 'Last used', ''].map(h => (
                <th key={h} style={{ padding: '0.75rem 1rem', textAlign: 'left', fontSize: '0.8rem', fontWeight: 600, color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.api_keys ?? []).map(k => (
              <tr key={k.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '0.75rem 1rem', fontSize: '0.875rem', fontWeight: 500 }}>{k.name}</td>
                <td style={{ padding: '0.75rem 1rem', fontSize: '0.875rem', color: '#64748b' }}>{k.scopes.join(', ')}</td>
                <td style={{ padding: '0.75rem 1rem', fontSize: '0.875rem', color: '#64748b' }}>{new Date(k.created_at).toLocaleDateString()}</td>
                <td style={{ padding: '0.75rem 1rem', fontSize: '0.875rem', color: '#64748b' }}>{k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : '—'}</td>
                <td style={{ padding: '0.75rem 1rem' }}>
                  <button
                    onClick={() => revoke.mutate(k.id)}
                    style={{ fontSize: '0.8rem', color: '#dc2626', background: 'none', border: '1px solid #fca5a5', borderRadius: 4, padding: '0.25rem 0.5rem' }}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
            {!data?.api_keys.length && (
              <tr><td colSpan={5} style={{ padding: '1.5rem', textAlign: 'center', color: '#94a3b8' }}>No API keys yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
