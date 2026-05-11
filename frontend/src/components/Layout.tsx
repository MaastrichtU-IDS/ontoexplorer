import { Link, NavLink, Outlet } from 'react-router-dom'
import { logout } from '../lib/auth'

const nav = [
  { to: '/app/dashboard', label: 'My Ontologies' },
  { to: '/app/dashboard/keys', label: 'API Keys' },
  { to: '/app/dashboard/webhooks', label: 'Webhooks' },
  { to: '/app/dashboard/stats', label: 'Usage Stats' },
]

export default function Layout() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <aside style={{
        width: 220, background: '#1e293b', color: '#94a3b8', padding: '1.5rem 1rem',
        display: 'flex', flexDirection: 'column', gap: '0.5rem',
      }}>
        <Link to="/" style={{ color: '#f1f5f9', fontWeight: 700, fontSize: '1.1rem', marginBottom: '1.5rem', display: 'block' }}>
          OntoExplorer
        </Link>
        {nav.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              color: isActive ? '#f1f5f9' : '#94a3b8',
              background: isActive ? '#334155' : 'transparent',
              padding: '0.5rem 0.75rem',
              borderRadius: 6,
              display: 'block',
            })}
          >
            {label}
          </NavLink>
        ))}
        <div style={{ marginTop: 'auto' }}>
          <button
            onClick={() => logout()}
            style={{ background: 'none', border: 'none', color: '#94a3b8', padding: '0.5rem 0.75rem', width: '100%', textAlign: 'left' }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main style={{ flex: 1, padding: '2rem' }}>
        <Outlet />
      </main>
    </div>
  )
}
