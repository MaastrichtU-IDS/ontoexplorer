import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ApiKey } from '../lib/api'

export default function ApiKeys() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [copied, setCopied] = useState(false)
  // Scopes are enforced from 0.3.92: a read key genuinely cannot modify
  // anything. Read stays the default, so a key is only as powerful as asked for.
  const [canWrite, setCanWrite] = useState(false)

  function copyKey() {
    if (!newKey) return
    navigator.clipboard.writeText(newKey).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }).catch(() => {})   // clipboard blocked (insecure origin / denied permission)
  }

  const { data, isLoading } = useQuery({ queryKey: ['api-keys'], queryFn: () => api.apiKeys.list() })

  const create = useMutation({
    mutationFn: () => api.apiKeys.create(name, canWrite ? ['read', 'write'] : ['read']),
    onSuccess: (key: ApiKey) => {
      setNewKey(key.key ?? null)
      setName('')
      setCanWrite(false)
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
            color: showForm ? 'var(--text-muted)' : 'var(--bg)',
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
          <form onSubmit={e => { e.preventDefault(); create.mutate() }} style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Key name (e.g. my-script)"
              required
              style={{ flex: 1, minWidth: '14rem' }}
            />
            <label style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)', cursor: 'pointer',
            }}>
              <input
                type="checkbox"
                checked={canWrite}
                onChange={e => setCanWrite(e.target.checked)}
              />
              Allow this key to make changes
            </label>
            <button
              type="submit"
              disabled={create.isPending}
              style={{
                padding: '0.4rem 0.9rem',
                background: 'var(--accent)',
                color: 'var(--bg)',
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
              <p style={{ fontWeight: 600, color: 'var(--accent)', marginBottom: '0.5rem', fontSize: 'var(--font-size-sm)' }}>
                Copy this key now — it won't be shown again.
              </p>
              {/* The key and its copy control sit in their own box, so the
                  warning above reads as prose rather than as part of the value. */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.5rem 0.6rem',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
              }}>
                <code style={{ flex: 1, wordBreak: 'break-all', fontSize: 'var(--font-size-sm)', color: 'var(--text)' }}>{newKey}</code>
                <button
                  onClick={copyKey}
                  aria-label="Copy API key to clipboard"
                  title={copied ? 'Copied' : 'Copy to clipboard'}
                  style={{
                    flexShrink: 0,
                    fontSize: 14,
                    padding: '2px 8px',
                    background: 'none',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)',
                    color: copied ? 'var(--accent)' : 'var(--text-dim)',
                    cursor: 'pointer',
                    transition: 'color 0.15s, border-color 0.15s',
                  }}
                  onMouseEnter={e => { if (!copied) e.currentTarget.style.borderColor = 'var(--text-muted)' }}
                  onMouseLeave={e => { if (!copied) e.currentTarget.style.borderColor = 'var(--border)' }}
                >
                  {copied ? '✓' : '⎘'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
        <table style={{ minWidth: 480, width: '100%', borderCollapse: 'collapse', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
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
                    style={{ fontSize: 'var(--font-size-sm)', color: 'var(--red-soft)' }}
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
        </div>
      )}
    </div>
  )
}
