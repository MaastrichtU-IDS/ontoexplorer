import { useAuth } from '../hooks/useAuth'

const PROVIDER_LABELS: Record<string, string> = {
  github: 'GitHub',
  google: 'Google',
  orcid: 'ORCID',
}

export default function Profile() {
  const { user } = useAuth()

  if (!user) return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>

  const memberSince = new Date(user.created_at).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
  })

  return (
    <div style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1.5rem' }}>Profile</h1>

      <div style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{
            width: 48, height: 48, borderRadius: '50%',
            background: 'var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.25rem', fontWeight: 700, color: '#0a0f1a',
            flexShrink: 0,
          }}>
            {(user.display_name || user.email || '?')[0].toUpperCase()}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, fontSize: '1rem', color: 'var(--text)' }}>
                {user.display_name || '(no name)'}
              </span>
              {user.is_admin && (
                <span style={{
                  fontSize: '0.7rem', fontWeight: 700,
                  background: '#f0883e22', color: '#f0883e',
                  border: '1px solid #f0883e66',
                  borderRadius: 3, padding: '1px 6px',
                  letterSpacing: '0.05em', textTransform: 'uppercase',
                }}>
                  Admin
                </span>
              )}
            </div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginTop: 2 }}>
              {user.email || '—'}
            </div>
          </div>
        </div>

        <div style={{ padding: '1rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <Row label="Member since" value={memberSince} />
          <Row
            label="Connected accounts"
            value={
              user.connected_providers && user.connected_providers.length > 0
                ? user.connected_providers.map(p => PROVIDER_LABELS[p] || p).join(', ')
                : '—'
            }
          />
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
      <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text)', textAlign: 'right' }}>{value}</span>
    </div>
  )
}
