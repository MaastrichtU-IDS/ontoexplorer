import { loginWithProvider } from '../lib/auth'

// The platform `ontoexplorer` realm is the only sign-in path (#368): it owns
// registration + email verification and brokers ORCID/GitHub, so one
// account covers everyone regardless of the identity they bring. We route
// solely through it because the realm guarantees a verified email on every
// login (needed for held-version/nudge/maintainer notifications); the old
// direct ORCID/GitHub buttons created separate, often email-less accounts.
const primaryProvider = {
  id: 'keycloak' as const,
  label: 'Sign in with your platform account',
  color: 'var(--accent)',
}

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
      <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: '1.5rem', maxWidth: 320, textAlign: 'center' }}>
        Your platform account signs you in with ORCID, GitHub, or email.
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
    </div>
  )
}
