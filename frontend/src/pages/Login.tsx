import { loginWithProvider } from '../lib/auth'

// Keycloak (the platform ids3 realm) is the preferred path (#368): it owns
// registration + email verification and brokers ORCID/GitHub/Google, so it
// covers users who have no academic email or ORCID iD. The direct ORCID/GitHub
// buttons remain during the migration for existing accounts.
const primaryProvider = {
  id: 'keycloak' as const,
  label: 'Sign in with your platform account',
  color: 'var(--accent)',
}
const providers = [
  { id: 'orcid' as const, label: 'Sign in with ORCID', color: '#a6ce39' },
  { id: 'github' as const, label: 'Sign in with GitHub', color: 'var(--gray)' },
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
      <button
        key={primaryProvider.id}
        onClick={() => loginWithProvider(primaryProvider.id)}
        style={{
          background: 'var(--accent)', border: `1px solid ${primaryProvider.color}`,
          color: 'var(--accent-contrast, #fff)', borderRadius: 'var(--radius)',
          padding: '10px 24px', width: 260, fontSize: 'var(--font-size-base)',
          fontWeight: 600, display: 'flex', alignItems: 'center',
          justifyContent: 'center', gap: 10, cursor: 'pointer',
        }}
      >
        {primaryProvider.label}
      </button>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, width: 260,
        color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', margin: '0.25rem 0',
      }}>
        <span style={{ flex: 1, height: 1, background: 'var(--border)' }} />
        or
        <span style={{ flex: 1, height: 1, background: 'var(--border)' }} />
      </div>
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
