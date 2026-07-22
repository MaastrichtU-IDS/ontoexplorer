import { loginWithProvider } from '../lib/auth'

const providers = [
  { id: 'orcid' as const, label: 'Sign in with ORCID', color: '#a6ce39' },
  { id: 'github' as const, label: 'Sign in with GitHub', color: '#6e7681' },
  // Google sign-in disabled for now — re-add when a Google OAuth app is configured.
  // { id: 'google' as const, label: 'Sign in with Google', color: '#4285f4' },
]

export default function Login() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', minHeight: 'calc(100vh - var(--nav-height))',
      gap: '1rem',
    }}>
      <h1 style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, marginBottom: '0.5rem' }}>
        Sign in to OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: '1.5rem' }}>
        Choose a provider to continue
      </p>
      {providers.map(({ id, label, color }) => (
        <button
          key={id}
          onClick={() => loginWithProvider(id)}
          style={{
            background: 'var(--bg-secondary)', border: `1px solid ${color}`,
            color: 'var(--text)', borderRadius: 'var(--radius)',
            padding: '10px 24px', width: 260, fontSize: 'var(--font-size-base)',
            display: 'flex', alignItems: 'center', gap: 10,
            cursor: 'pointer',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--bg-secondary)')}
        >
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
          {label}
        </button>
      ))}
    </div>
  )
}
